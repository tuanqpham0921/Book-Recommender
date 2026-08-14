import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from typing import Any, Generic, ParamSpec, TypeVar
from .error_info import RuntimeErrorInfo
from .token_usage import TokenUsage
from ..exception import StepFailure
from ..utils import now_iso, remove_empty_values, uuid_8

OutputT = TypeVar("OutputT")
P = ParamSpec("P")

logger = logging.getLogger(__name__)


class Time(BaseModel):
    start_time: str = Field(default_factory=now_iso)
    duration: float | None = None

    @property
    def end_time(self) -> str | None:
        """`start_time + duration`, or None while still running.

        Derived so it cannot disagree with `duration` if the clock jumps.
        Precision follows `duration` (2dp).
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
    span list is made of — one class for both, since any unit of work can run
    another.
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

    # `list[Any]` on purpose: pydantic would re-validate a child on assignment
    # and hand back a *copy*, so a step would stop being the same object its
    # producer is still writing to. Cost: children reloaded from JSON are plain
    # dicts, validated in `flatten`.
    steps: list[Any] = Field(default_factory=list)

    def check_output_type(self) -> None:
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

    def unwrap(self) -> OutputT:
        """The payload, or stop the caller.

        The verb for "I need what this step produced". `await` is the other one:
        it hands back this envelope and leaves the caller to decide what a
        failure means. Between them they replaced `run_async_step` and its
        `raise_on_failure` flag, splitting awaiting from the failure policy — so
        a caller can retry an envelope, or inspect it and *then* insist.

        A failed step notes itself on whatever envelope is currently being built
        and raises `StepFailure`, which `record_span` reports as a stop rather
        than a crash: the real traceback belongs to whichever step actually
        raised, one or more levels down.
        """
        if self.ok:
            return self.result

        # Local import: `context` imports this module to type CURRENT_PARENT, so
        # a module-level import here would be a cycle.
        from ..context import current_parent

        # the caller's own envelope — `parent_scope` published it before the
        # call, and the step's scope has already been reset by now
        if (parent := current_parent()) is not None:
            parent.add_details(f"FAILED STEP: {self.name}")

        if self.runtime_error is None:
            # Not ok, having not crashed. `ok` means "ran to completion", so
            # this is a bug in the step rather than a state to report — say so
            # in the message, or the caller stops with nothing underneath it
            # explaining why.
            raise StepFailure(f"Step failed: {self.name} (no runtime error recorded)")
        raise StepFailure(f"Step failed: {self.name}")

    @property
    def duration(self) -> float | None:
        return self.timing.duration

    @property
    def end_time(self) -> str | None:
        return self.timing.end_time

    def add_step(self, step: "OperationResult[Any]") -> None:
        """Attach a child, stamp it as ours, and roll its token usage up.

        On the envelope, not on `Workflow`, so a non-Workflow caller (the
        Orchestrator) can build a root over finished records.

        Idempotent — `parent_scope` attaches automatically, so a caller that
        also calls this would otherwise append twice; needed only for an
        envelope produced outside any scope. The guard is identity against
        `steps`, not
        `parent_id is None`, which the scope pre-stamps on entry. A step claimed
        by another parent is refused, not re-parented: it would be billed twice.
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
            self.add_details(f"step_id: {step.id} attempted to add twice")
            return

        step.parent_id = self.id
        self.token_usage += step.token_usage
        self.steps.append(step)

    def add_details(self, *message):
        self.details.extend(message)

    def to_span(self) -> "OperationResult[Any]":
        """This envelope as one flat row — the same record, minus its subtree.

        Keeps `flatten` from serializing the tree once per level. With children,
        a `model_construct` shallow copy (no dump-and-revalidate, so a live
        payload stays live); without, by reference.
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
        """One small dict per node, children nested beneath — a run read top to
        bottom without unfolding payloads. Complements the full record, never
        replaces it. `details` is omitted: it is mostly decorator bookkeeping.
        """
        payload = self.result
        summary = {
            "id": self.id,
            # leaf of the dotted ref only; the full path is in the whole tree
            "name": self.name.split(".")[-1] if self.name else None,
            "ok": self.ok,
            "duration": self.duration,
            # `or None` so a step that made no LLM call drops both keys
            "tokens": self.token_usage.total or None,
            "cost_usd": self.token_usage.cost_usd or None,
            # without this an unpriced model reads as free rather than unknown
            "unpriced_models": self.token_usage.unpriced_models,
            "error": self.runtime_error.type if self.runtime_error else None,
            "output": payload.to_summary() if hasattr(payload, "to_summary") else None,
        }
        # `ok: False` and a genuine 0 survive this (see remove_empty_values).
        # Steps are added after so the key is absent rather than empty.
        summary = remove_empty_values(summary)
        if self.steps:
            summary["steps"] = [step.to_summary() for step in self.steps]
        return summary

    def flatten(self) -> list["OperationResult[Any]"]:
        """This node and every descendant, depth-first, parent before child.

        Every entry carries its `parent_id`, so the nesting is rebuildable from
        the list alone. Children read back from JSON arrive as plain dicts (see
        `steps`) and are validated here.
        """
        flat: list[OperationResult[Any]] = [self.to_span()]
        for step in self.steps:
            if isinstance(step, dict):
                step = OperationResult.model_validate(step)

            if isinstance(step, OperationResult):
                flat.extend(step.flatten())
            # anything else came from a hand-built record and is skipped
        return flat
