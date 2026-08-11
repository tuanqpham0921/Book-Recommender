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
    """Outcome of a single named check or step."""

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

    def add_details(self, *message):
        self.details.extend(message)

    @property
    def result(self):
        return self.response.result

    @property
    def duration(self) -> float | None:
        return self.timing.duration

    @property
    def end_time(self) -> str | None:
        return self.timing.end_time

    def to_summary(self) -> dict[str, Any]:
        """The trace tree with the bulk taken out — one small dict per
        envelope, nested exactly like `steps`, so a run reads top to bottom
        without unfolding payloads.

        Complements rather than replaces the full tree: the DB row and the
        dev-log still carry `to_serializable(record)`. Only the shape the eye
        needs lives here, which is why it stays one recursive method instead
        of a summary + a separate steps summary — the tree has no fixed depth,
        so anything that doesn't recurse only ever shows the top two levels.

        `details` is left out on purpose: nearly every `@task` leaf carries the
        decorator's own bookkeeping line, which would bury the shape. Read the
        full tree when a failure needs explaining beyond `error`.
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
            "steps": [step.to_summary() for step in self.steps],
        }
        # keeps a leaf to the three or four keys that actually say something;
        # `ok: False` and a genuine 0 survive this (see remove_empty_values)
        return remove_empty_values(summary)

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

    def flatten(self) -> list["OperationResult[Any]"]:
        """This envelope and every descendant, depth-first, parent before child.

        The trace tree as a **span list** — one entry per operation, each
        carrying the `parent_id` `add_step` stamped on it, so the nesting
        survives the flattening and can be rebuilt from the list alone. With
        `timing.start_time` and `end_time` on every entry, that is the shape a
        timeline or a per-step cost table wants; `to_summary()` is the shape
        for reading a run top to bottom.

        In-memory envelopes come back **by reference** — mutating one mutates
        the tree. A record read back from JSON is different: `steps: list[Any]`
        does not re-validate, so its children are plain dicts, and those are
        validated into envelopes here and are therefore copies.

        Each entry still carries its own `steps`, since these are the real
        envelopes rather than a projection. For a flat *table*, where a row
        dragging its whole subtree would blow the list up quadratically, drop
        them at the point of use:

            [op.model_copy(update={"steps": []}) for op in record.flatten()]
        """
        flat: list[OperationResult[Any]] = [self]
        for step in self.steps:
            # a reloaded record's steps are dicts (see above); an in-memory
            # one's are envelopes. add_step rejects anything else, so a value
            # that is neither came from a hand-built record and is skipped
            # rather than allowed to break the walk.
            if isinstance(step, dict):
                step = OperationResult.model_validate(step)
            if isinstance(step, OperationResult):
                flat.extend(step.flatten())
        return flat