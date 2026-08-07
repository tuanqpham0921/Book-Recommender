import asyncio
import logging
from pydantic import BaseModel, Field, model_validator
from typing import Any, Coroutine, Generic, ParamSpec, TypeVar, overload
import time
from typing import Callable
from functools import wraps
import traceback

from common.utils import now_iso, uuid_8
from config.pricing import UNKNOWN_MODEL, cost_of

OutputT = TypeVar("OutputT")
P = ParamSpec("P")


class ModelUsage(BaseModel):
    """Token counts attributable to a single model."""

    total: int = 0
    prompt: int = 0
    completion: int = 0

    # Subset of `prompt`; never additional tokens.
    cached: int = 0

    # Internal reasoning tokens used by the model. Subset of `completion`.
    reasoning_tokens: int = 0

    def __iadd__(self, other: "ModelUsage") -> "ModelUsage":
        self.total += other.total
        self.prompt += other.prompt
        self.completion += other.completion
        self.cached += other.cached
        self.reasoning_tokens += other.reasoning_tokens
        return self

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of prompt tokens served from the provider's cache.

        Lives here rather than on TokenUsage so each `by_model` bucket reports
        its own rate — the blended figure across models hides the differences
        that make it worth watching.
        """
        return self.cached / self.prompt if self.prompt else 0.0


class TokenUsage(ModelUsage):
    """Usage for one LLM call, or the roll-up of many.

    A *leaf* — what `OpenAIClient._extract_token_usage` builds — names its
    `model` and leaves `by_model` empty. Adding leaves together (see
    `Workflow.add_step`) produces an *aggregate*: the flat counts still sum
    across everything, and `by_model` keeps the per-model split that the flat
    counts alone can't express once more than one model is in play.

    `cost_usd` and `unpriced_models` are stored fields rather than properties
    on purpose — `common.utils.to_serializable` walks `model_fields` and would
    drop computed ones, so a property would never reach the chat_runs JSONB.
    Both are recomputed on construction and after every `+=`.
    """

    model: str = ''
    by_model: dict[str, ModelUsage] = Field(default_factory=dict)

    # USD, priced at PRICES_CHECKED_ON rates and frozen into the run record.
    cost_usd: float = 0.0

    # Models that contributed tokens but carry no rate, so their spend is
    # missing from cost_usd. Empty is the healthy state.
    unpriced_models: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _price_on_build(self) -> "TokenUsage":
        self._reprice()
        return self

    def contributions(self) -> dict[str, ModelUsage]:
        """The per-model rows this usage contributes to a parent — its own
        counts if it's a leaf, otherwise the buckets it already aggregated.
        Handling both is what lets roll-ups nest to any depth."""
        if self.by_model:
            return self.by_model

        if self.total or self.prompt or self.completion:
            return {
                self.model or UNKNOWN_MODEL: ModelUsage(
                    total=self.total,
                    prompt=self.prompt,
                    completion=self.completion,
                    cached=self.cached,
                    reasoning_tokens=self.reasoning_tokens,
                )
            }

        return {}

    def _reprice(self) -> None:
        total = 0.0
        unpriced = []
        for model, usage in self.contributions().items():
            cost = cost_of(model, usage.prompt, usage.cached, usage.completion)
            if cost is None:
                unpriced.append(model)
            else:
                total += cost

        self.cost_usd = round(total, 6)
        self.unpriced_models = sorted(unpriced)

    def __iadd__(self, other: "TokenUsage") -> "TokenUsage":
        super().__iadd__(other)

        for model, usage in other.contributions().items():
            bucket = self.by_model.setdefault(model, ModelUsage())
            bucket += usage

        self._reprice()
        return self


class RuntimeErrorInfo(BaseModel):
    """Serializable record of an unexpected exception — the error's type and
    message as first-class data for routing/aggregation, plus the formatted
    traceback for humans."""

    type: str
    message: str
    traceback: str

    @classmethod
    def from_exception(cls, e: BaseException) -> "RuntimeErrorInfo":
        return cls(
            type=type(e).__name__,
            message=str(e),
            traceback="".join(traceback.format_exception(e)),
        )
        
class Time(BaseModel):
    start_time: str = Field(default_factory=now_iso)
    duration: float | None = None

class Response(BaseModel, Generic[OutputT]):
    output: OutputT | None = None
    output_type: str | None = None

class OperationResult(BaseModel, Generic[OutputT]):
    """Outcome of a single named check or step."""

    id: str = Field(default_factory=lambda: f"op_{uuid_8()}")
    parent_id: str | None = None
    
    timing: Time = Field(default=Time())
    
    name: str | None = None
    
    # request: dict[str, any] | None = None

    ok: bool = False
    steps: list[Any] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)

    response: Response = Field(default_factory=Response(OutputT))

    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    runtime_error: RuntimeErrorInfo | None = None

    def check_output_type(self) -> None:
        # default there's no output
        if self.output is None:
            return

        if self.output_type is None:
            raise TypeError(
                f"Output of type {type(self.output).__name__} was produced "
                "without a declared output_type"
            )

        if type(self.output).__name__ != self.output_type:
            raise TypeError(
                f"Output {self.output} is of type {type(self.output).__name__} not of type {self.output_type}"
            )

    def add_details(self, *message):
        self.details.extend(message)


@overload
def task(
    func: Callable[P, Coroutine[Any, Any, Any]],
) -> Callable[P, Coroutine[Any, Any, OperationResult[Any]]]: ...


@overload
def task(
    func: None = None,
    *,
    log_info: bool = True,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, Any]]],
    Callable[P, Coroutine[Any, Any, OperationResult[Any]]],
]: ...


def task(
    func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    *,
    log_info: bool = True,
) -> Any:
    """For single-step operations (for multiple steps, use Workflow)."""

    def decorator(
        func: Callable[P, Coroutine[Any, Any, Any]],
    ) -> Callable[P, Coroutine[Any, Any, OperationResult[Any]]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"
            time_start = time.perf_counter()
            try:
                if log_info:
                    logger.info(f"Running task: {func_ref}")

                output = await func(*args, **kwargs)

                # custom operation result retuned from the task
                # the task must validate ok itself
                if isinstance(output, OperationResult):
                    if log_info and not output.ok:
                        logger.warning(f"Task failed: {func_ref}")

                    output.name = func_ref
                    output.duration = round(time.perf_counter() - time_start, 2)
                    return output

                # task did not return an operation result, create a default one
                # no run time error is recorded, so the task is considered successful
                result = OperationResult(
                    name=func_ref, output=output, output_type=type(output).__name__
                )
                result.duration = round(time.perf_counter() - time_start, 2)
                result.ok = True
                result.add_details(
                    "output is not an operation result, creating a default one"
                )
                if hasattr(output, "token_usage") and isinstance(
                    output.token_usage, TokenUsage
                ):
                    result.token_usage = output.token_usage
                return result
            except asyncio.CancelledError:
                # client disconnected (e.g. page refresh) mid-task. Unlike
                # Workflow.__call__, there's no persistent self.result to
                # stamp here — returning a result would swallow the
                # cancellation, so just log which task was in flight and
                # propagate; the enclosing Workflow.__call__ catches this
                # and records it on the workflow's own result.
                logger.warning(f"Task cancelled: {func_ref}")
                raise
            except Exception as e:
                # run time error is recorded, so the task is considered failed
                logger.exception(e)

                result = OperationResult(name=func_ref)
                result.ok = False
                result.runtime_error = RuntimeErrorInfo.from_exception(e)
                result.duration = round(time.perf_counter() - time_start, 2)
                return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
