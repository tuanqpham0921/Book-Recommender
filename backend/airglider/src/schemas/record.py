import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from typing import Any, Generic, ParamSpec, TypeVar
from .error_info import RuntimeErrorInfo
from .token_usage import TokenUsage
from ..utils import now_iso, remove_empty_values, uuid_8

OutputT = TypeVar("OutputT")
P = ParamSpec("P")

logger = logging.getLogger(__name__)


class Time(BaseModel):
    start_time: str = Field(default_factory=now_iso)
    duration: float | None = None

    @property
    def end_time(self) -> str | None:
        """When this finished, ISO 8601 — or None while it is still running.

        **Derived, not observed**: `start_time + duration`. The two halves are
        measured differently on purpose — `start_time` is wall clock
        (`now_iso`), `duration` is `time.perf_counter`, which is monotonic — so
        this is "the wall-clock start, plus the time that actually elapsed".

        A second `now_iso()` at the end would read better but be worse: it
        inherits whatever the system clock did in between (an NTP correction, a
        laptop suspend), so `end_time - start_time` would stop agreeing with
        `duration` and a step could even appear to finish before it began.
        Deriving keeps the three values consistent by construction.

        Precision follows `duration`, which callers round to 2 decimals — so
        this is accurate to ±5ms and can sit just *after* the instant the call
        actually returned. Fine for reading a trace; don't difference two of
        these to measure something short.

        Not a field, and not a `computed_field`: it adds no information, so
        persisting it would be a third value that can disagree with the two it
        came from. `to_serializable` walks `model_fields` only, so neither form
        would reach the DB row anyway without changing that walk.
        """
        if self.duration is None:
            return None
        return (
            datetime.fromisoformat(self.start_time) + timedelta(seconds=self.duration)
        ).isoformat()


class Response(BaseModel, Generic[OutputT]):
    result: OutputT | None = None
    output_type: str | None = None


class OperationResult(BaseModel, Generic[OutputT]):
    """Outcome of one named unit of work, and whatever work it ran in turn.

    The envelope every `@task` and every `Workflow` produces, and the row every
    span list is made of: an id, a parent, timing, input, output, details,
    usage, an error — and `steps`.

    **One class, not two.** There used to be a `WorkFlowOperationResult`
    subclass that added `steps`, on the reasoning that a leaf has no children
    and should not carry the field. Two things retired it. `steps` is not
    mandatory — an empty list costs nothing and `flatten` reads it the same
    either way — and, more decisively, once nesting became automatic
    (`parent_scope`, `src/context.py`) any unit of work can run another, so
    "which shape am I" stopped being answerable at decoration time. The split
    only ever showed up as the same relationship rebuilt from two angles: an
    isinstance ladder in `flatten`, a `getattr(x, "steps", [])` at every reader,
    and a rule about who was allowed to call whom.
    """

    id: str = Field(default_factory=lambda: f"op_{uuid_8()}")
    parent_id: str | None = None
    name: str | None = None

    ok: bool = False
    timing: Time = Field(default_factory=Time)

    input: dict[str, Any] | None = None
    response: Response[OutputT] = Field(default_factory=Response)
    details: list[str] = Field(default_factory=list)

    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    runtime_error: RuntimeErrorInfo | None = None

    # `list[Any]`, not `list[OperationResult]`, and deliberately so: pydantic
    # would re-validate a child on assignment and hand back a *copy*, which
    # breaks the one thing the tree depends on — a step being the same object
    # the workflow that produced it is still writing to. The cost is that a
    # record reloaded from JSON has plain-dict children; `flatten` validates
    # them on the way past.
    steps: list[Any] = Field(default_factory=list)

    def check_output_type(self) -> None:
        # default there's no output
        if self.result is None:
            return

        if self.response.output_type is None:
            raise TypeError(
                f"Output of type {type(self.result).__name__} was produced "
                "without a declared output_type"
            )

        if type(self.result).__name__ != self.response.output_type:
            raise TypeError(
                f"Output {self.result} is of type "
                f"{type(self.result).__name__} not of type "
                f"{self.response.output_type}"
            )

    @property
    def result(self):
        return self.response.result

    @property
    def duration(self) -> float | None:
        return self.timing.duration

    @property
    def end_time(self) -> str | None:
        return self.timing.end_time

    def add_step(self, step: "OperationResult[Any]") -> None:
        """Attach a child envelope, stamp it as ours, and roll its token usage up.

        Lives here rather than on `Workflow` because `steps`/`token_usage` do:
        it is also how a non-Workflow caller (the Orchestrator) builds a root
        envelope over workflows that each own their own record.

        `parent_scope` normally stamps `parent_id` on the way *in* — parentage
        is known when a call starts, and a record should carry it for the whole
        of its own run. This stamps it too, for the attach paths that never went
        through a scope: the `Orchestrator` builds a root envelope by hand and
        hangs two already-finished workflow records off it, and a `@task` may
        assemble a step list itself. Either way the child comes out an orphan
        and whoever attaches it adopts it — nothing has to be threaded into the
        decorator.

        Stamped on the record rather than derived later (e.g. while flattening)
        so the link survives the JSONB insert, and a reader that only ever sees
        the stored tree can still rebuild the nesting.

        **Attaching is idempotent**, and it has to be: `parent_scope` adopts a
        child automatically, so the explicit `add_step` that `run_async_step`
        still makes would otherwise append the same object twice and add its
        tokens twice, silently. The check is **identity against `steps`**, not
        `parent_id is None` — since the scope pre-stamps the id, that flag no
        longer distinguishes "knows its parent" from "has been attached". A step
        already claimed by a *different* parent is a genuine bug (the same
        envelope in two trees, its usage counted in both), so it is refused and
        logged rather than re-parented.
        """
        if not isinstance(step, OperationResult):
            raise ValueError(f"Step is of type {type(step)} not OperationResult")

        if step.parent_id is not None and step.parent_id != self.id:
            logger.warning(
                f"Step {step.name} ({step.id}) belongs to {step.parent_id}; "
                f"refusing to re-parent it under {self.id}"
            )
            return

        if any(attached is step for attached in self.steps):
            return

        step.parent_id = self.id
        self.token_usage += step.token_usage
        self.steps.append(step)

    def add_details(self, *message):
        self.details.extend(message)

    def to_span(self) -> "OperationResult[Any]":
        """This envelope as one flat row — the same record, minus its subtree.

        What `flatten()` puts in the list, and the reason no row re-encodes the
        tree once per level. A node **with** children comes back as a shallow
        copy carrying `steps=[]`; one **without** has nothing to drop and comes
        back by reference, which is what keeps flattening a mostly-free walk.

        `model_construct`, not a dump-and-revalidate: every value already came
        off a validated model, and re-validating would turn a live payload into
        the dict `model_dump` made of it. The sub-models (`timing`, `response`,
        `token_usage`) are shared with the tree node rather than copied — this
        is a view for reading, not an independent record.
        """
        if not self.steps:
            return self

        fields = {
            name: getattr(self, name)
            for name in OperationResult.model_fields
            if name != "steps"
        }
        return OperationResult.model_construct(**fields, steps=[])

    def to_summary(self) -> dict[str, Any]:
        """This envelope with the bulk taken out, and each child's beneath it —
        one small dict per node, so a run reads top to bottom without unfolding
        payloads.

        Recursive, because the tree has no fixed depth: anything that summarized
        only itself and its immediate children would stop at two levels.

        Complements rather than replaces the full record: the DB row and the
        dev-log still carry `to_serializable(record)`. Only the shape the eye
        needs lives here.

        `details` is left out on purpose: nearly every `@task` carries the
        decorator's own bookkeeping line, which would bury the shape. Read the
        full record when a failure needs explaining beyond `error`.
        """
        payload = self.result
        summary = {
            "id": self.id,
            # leaf of the dotted ref only — the full module path is in the
            # unabridged tree, and repeating it at every level is what made
            # the trace hard to scan. `name` is optional on the model, so an
            # unnamed envelope drops the key rather than raising here.
            "name": self.name.split(".")[-1] if self.name else None,
            "ok": self.ok,
            "duration": self.duration,
            # `or None` so a step that made no LLM call (a DB read, a
            # combine) drops both keys instead of repeating zeros down the
            # tree — same call strip_zero_token_usage makes for the dev log,
            # made here because a summary has no fidelity to protect
            "tokens": self.token_usage.total or None,
            "cost_usd": self.token_usage.cost_usd or None,
            # without this an unpriced model reads as free rather than
            # unknown — the one case where a missing cost_usd is not a zero
            "unpriced_models": self.token_usage.unpriced_models,
            "error": self.runtime_error.type if self.runtime_error else None,
            "output": payload.to_summary() if hasattr(payload, "to_summary") else None,
        }
        # keeps a childless node to the three or four keys that actually say
        # something; `ok: False` and a genuine 0 survive this (see
        # remove_empty_values). Steps are added after the strip so the key is
        # absent rather than empty when there are none.
        summary = remove_empty_values(summary)
        if self.steps:
            summary["steps"] = [step.to_summary() for step in self.steps]
        return summary

    def flatten(self) -> list["OperationResult[Any]"]:
        """This node and every descendant, depth-first, parent before child.

        The trace tree as a **span list** — one entry per operation, each
        carrying the `parent_id` `add_step` stamped on it, so the nesting
        survives the flattening and can be rebuilt from the list alone. With
        `timing.start_time` and `end_time` on every entry, that is the shape a
        timeline or a per-step cost table wants; `to_summary()` is the shape
        for reading a run top to bottom.

        No entry drags a subtree along — that would serialize the tree once per
        level — so every node goes through `to_span()` on the way in. A node
        with no children has nothing to drop and comes back by reference.

        A record read back from JSON is the other case to know about —
        `steps: list[Any]` does not re-validate, so its children arrive as
        plain dicts. They are validated here, which makes them copies.

        The walk is one branch now rather than an isinstance ladder: with a
        single envelope class, recursing is always the right move, and a
        childless node bottoms out on its own empty `steps`.
        """
        flat: list[OperationResult[Any]] = [self.to_span()]
        for step in self.steps:
            if isinstance(step, dict):
                step = OperationResult.model_validate(step)

            if isinstance(step, OperationResult):
                flat.extend(step.flatten())
            # anything else came from a hand-built record — add_step rejects
            # it — and is skipped rather than allowed to break the walk
        return flat

