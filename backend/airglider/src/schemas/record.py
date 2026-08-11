from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from typing import Any, Generic, ParamSpec, TypeVar
from .error_info import RuntimeErrorInfo
from .token_usage import TokenUsage
from ..utils import now_iso, remove_empty_values, uuid_8

OutputT = TypeVar("OutputT")
P = ParamSpec("P")


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
    """Outcome of a single named unit of work — one leaf, no subtree.

    The envelope every `@task` returns and the row every span list is made of.
    It is deliberately the *whole* record minus `steps`: a leaf carries an id,
    a parent, timing, input, output, details, usage and an error, which is
    everything a trace reader asks of one operation. Only something that runs
    other operations needs children, and that is `WorkFlowOperationResult`.

    Prefer this type in annotations and isinstance checks unless the code
    actually touches `steps`/`add_step`/`flatten` — a step is a step whether a
    `@task` or a `Workflow` produced it, and the narrower type is what says so.
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

    def add_details(self, *message):
        self.details.extend(message)

    def to_span(self) -> "OperationResult[Any]":
        """This envelope as one flat row — itself, for something with no subtree.

        The counterpart on `WorkFlowOperationResult` projects a tree node down
        to this class, which is what lets `flatten()` return a list whose
        entries genuinely carry no children. Polymorphic so the walk never has
        to ask which kind it is holding.
        """
        return self

    def to_summary(self) -> dict[str, Any]:
        """This envelope with the bulk taken out — one small dict, so a run
        reads top to bottom without unfolding payloads.

        Complements rather than replaces the full record: the DB row and the
        dev-log still carry `to_serializable(record)`. Only the shape the eye
        needs lives here.

        `details` is left out on purpose: nearly every `@task` leaf carries the
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
        # keeps a leaf to the three or four keys that actually say something;
        # `ok: False` and a genuine 0 survive this (see remove_empty_values)
        return remove_empty_values(summary)


class WorkFlowOperationResult(OperationResult):
    """An `OperationResult` that ran other operations — the same envelope plus
    the children it accumulated.

    The split is by shape, not by producer: `steps` is the only thing here, and
    everything that reads a record without walking into it should be typed on
    the base class. A `Workflow` owns one of these; a `@task` returns a plain
    `OperationResult`, and either can be attached as a step.
    """

    steps: list[Any] = Field(default_factory=list)

    def add_step(self, step: "OperationResult[Any]") -> None:
        """Attach a child envelope, stamp it as ours, and roll its token usage up.

        Lives here rather than on `Workflow` because `steps`/`token_usage` do:
        it is also how a non-Workflow caller (the Orchestrator) builds a root
        envelope over workflows that each own their own record.

        **This is the one place parentage is known**, which is why `parent_id`
        is set here and nowhere else. A child cannot know its own parent — a
        `@task` is a plain async function with no reference to its caller, and
        a `Workflow` is constructed before anyone decides where its record
        hangs. Both produce an orphan envelope, and whoever attaches it adopts
        it. Nothing has to be threaded into the decorator.

        Stamped at attach time rather than derived later (e.g. while
        flattening) so the link is part of the record itself: it survives the
        JSONB insert, and a reader that only ever sees the stored tree can
        still rebuild the nesting.
        """
        if not isinstance(step, OperationResult):
            raise ValueError(f"Step is of type {type(step)} not OperationResult")

        step.parent_id = self.id
        self.token_usage += step.token_usage
        self.steps.append(step)

    def to_span(self) -> OperationResult[Any]:
        """This node projected down to a childless `OperationResult`.

        `model_construct`, not a dump-and-revalidate: every value already came
        off a validated model, and re-validating would turn a live payload into
        the dict `model_dump` made of it. The sub-models (`timing`, `response`,
        `token_usage`) are shared with the tree node rather than copied — this
        is a view for reading, not an independent record.
        """
        return OperationResult.model_construct(
            **{name: getattr(self, name) for name in OperationResult.model_fields}
        )

    def to_summary(self) -> dict[str, Any]:
        """The base summary, plus each child's — nested exactly like `steps`.

        One recursive method rather than a summary + a separate steps summary:
        the tree has no fixed depth, so anything that doesn't recurse only ever
        shows the top two levels.
        """
        summary = super().to_summary()
        steps = [step.to_summary() for step in self.steps]
        if steps:
            summary["steps"] = steps
        return summary

    def flatten(self) -> list[OperationResult[Any]]:
        """This node and every descendant, depth-first, parent before child.

        The trace tree as a **span list** — one entry per operation, each
        carrying the `parent_id` `add_step` stamped on it, so the nesting
        survives the flattening and can be rebuilt from the list alone. With
        `timing.start_time` and `end_time` on every entry, that is the shape a
        timeline or a per-step cost table wants; `to_summary()` is the shape
        for reading a run top to bottom.

        Entries are `OperationResult`, never this class: a row that still
        dragged its own subtree would serialize the tree once per level, so
        every node goes through `to_span()` on the way in. A leaf step has no
        subtree to drop and comes back **by reference**.

        A record read back from JSON is the other case to know about —
        `steps: list[Any]` does not re-validate, so its children arrive as
        plain dicts. They are validated here as tree nodes (the wider of the
        two shapes: a leaf's dict simply has no `steps` key and defaults to
        none), which makes them copies.
        """
        flat: list[OperationResult[Any]] = [self.to_span()]
        for step in self.steps:
            if isinstance(step, dict):
                step = WorkFlowOperationResult.model_validate(step)

            if isinstance(step, WorkFlowOperationResult):
                flat.extend(step.flatten())
            elif isinstance(step, OperationResult):
                flat.append(step.to_span())
            # anything else came from a hand-built record — add_step rejects
            # it — and is skipped rather than allowed to break the walk
        return flat
