import asyncio
import logging
from pydantic import BaseModel, Field
from typing import Any, Coroutine, Generic, ParamSpec, TypeVar, overload
import time
from typing import Callable
from functools import wraps
import traceback

from common.utils import now_iso, uuid_8

OutputT = TypeVar("OutputT")
P = ParamSpec("P")


class TokenUsage(BaseModel):
    total: int = 0
    prompt: int = 0
    completion: int = 0

    def __iadd__(self, other: "TokenUsage") -> "TokenUsage":
        self.total += other.total
        self.prompt += other.prompt
        self.completion += other.completion
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


class OperationResult(BaseModel, Generic[OutputT]):
    """Outcome of a single named check or step."""

    id: str = Field(default_factory=lambda: f"op_{uuid_8()}")
    start_time: str = Field(default_factory=now_iso)
    name: str | None = None

    ok: bool = False
    message: str | None = None
    steps: list[Any] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)

    output: OutputT | None = None
    output_type: str | None = None

    duration: float | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    runtime_error: RuntimeErrorInfo | None = None
    # attempts consumed beyond the first (0 = succeeded/failed on attempt 1)
    retries: int = 0

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
    timeout: float | None = None,
    retries: int = 1,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, Any]]],
    Callable[P, Coroutine[Any, Any, OperationResult[Any]]],
]: ...


def task(
    func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    *,
    log_info: bool = True,
    timeout: float | None = None,
    retries: int = 1,
) -> Any:
    """For single-step operations (for multiple steps, use Workflow).

    retries: total attempts before giving up (default 1 = no retry, same
    behavior as before this option existed). timeout: per-attempt seconds
    passed to asyncio.wait_for (default None = no timeout).
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, Any]],
    ) -> Callable[P, Coroutine[Any, Any, OperationResult[Any]]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"
            attempts = max(retries, 1)

            for attempt in range(1, attempts + 1):
                time_start = time.perf_counter()
                try:
                    if log_info:
                        logger.info(f"Running task: {func_ref} (attempt {attempt}/{attempts})")

                    output = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)

                    # custom operation result retuned from the task
                    # the task must validate ok and message
                    if isinstance(output, OperationResult):
                        if log_info and not output.ok:
                            logger.warning(f"Task failed: {output.message}")

                        output.name = func_ref
                        output.duration = round(time.perf_counter() - time_start, 2)
                        output.retries = attempt - 1
                        return output

                    # task did not return an operation result, create a default one
                    # no run time error is recorded, so the task is considered successful
                    result = OperationResult(
                        name=func_ref, output=output, output_type=type(output).__name__
                    )
                    result.duration = round(time.perf_counter() - time_start, 2)
                    result.ok = True
                    result.message = f"Task {func_ref} completed successfully"
                    result.retries = attempt - 1
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
                    # and records it on the workflow's own result. Never
                    # retried — the caller is gone.
                    logger.warning(f"Task cancelled: {func_ref}")
                    raise
                except asyncio.TimeoutError:
                    message = f"Task timed out after {timeout}s: {func_ref}"
                    result = OperationResult(name=func_ref)
                    result.ok = False
                    result.message = message
                    result.runtime_error = RuntimeErrorInfo(
                        type="TimeoutError", message=message, traceback=""
                    )
                    result.duration = round(time.perf_counter() - time_start, 2)
                    result.retries = attempt - 1
                    if attempt >= attempts:
                        logger.error(message)
                        return result
                    logger.warning(f"{message} - retrying")
                except Exception as e:
                    # run time error is recorded, so the task is considered failed
                    result = OperationResult(name=func_ref)
                    result.ok = False
                    result.message = f"Task failed: {e}"
                    result.runtime_error = RuntimeErrorInfo.from_exception(e)
                    result.duration = round(time.perf_counter() - time_start, 2)
                    result.retries = attempt - 1
                    if attempt >= attempts:
                        logger.exception(e)
                        return result
                    logger.warning(f"Task attempt {attempt}/{attempts} failed: {e} - retrying")

            # unreachable — the loop above always returns on its last attempt
            return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
