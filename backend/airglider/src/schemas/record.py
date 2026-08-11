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
        """Attach a child envelope and roll its token usage up into this one.

        Lives here rather than on `Workflow` because `steps`/`token_usage` do:
        it is also how a non-Workflow caller (the Orchestrator) builds a root
        envelope over workflows that each own their own record.
        """
        if not isinstance(step, OperationResult):
            raise ValueError(f"Step is of type {type(step)} not OperationResult")

        self.token_usage += step.token_usage
        self.steps.append(step)