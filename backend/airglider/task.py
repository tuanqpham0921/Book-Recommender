import asyncio
import logging
import time
from typing import Callable
from functools import wraps
from typing import Any, Coroutine,  ParamSpec, TypeVar, overload

from .schemas.record import OperationResult, Response, TokenUsage, RuntimeErrorInfo


OutputT = TypeVar("OutputT")
P = ParamSpec("P")


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

                raw_output = await func(*args, **kwargs)

                # custom operation result retuned from the task
                # the task must validate ok itself
                if isinstance(raw_output, OperationResult):
                    if log_info and not raw_output.ok:
                        logger.warning(f"Task failed: {func_ref}")

                    raw_output.name = func_ref
                    raw_output.timing.duration = round(time.perf_counter() - time_start, 2)
                    return raw_output

                # task did not return an operation result, create a default one
                # no run time error is recorded, so the task is considered successful
                result = OperationResult(
                    name=func_ref,
                    response=Response(result=raw_output, output_type=type(raw_output).__name__),
                )
                result.timing.duration = round(time.perf_counter() - time_start, 2)
                result.ok = True
                result.add_details(
                    "output is not an operation result, creating a default one"
                )
                # token_usage defaults via Field(default_factory=TokenUsage) —
                # explicitly passing token_usage=None to the constructor above
                # would fail validation, so this stays a post-construction,
                # conditional assignment instead
                if hasattr(raw_output, "token_usage") and isinstance(
                    raw_output.token_usage, TokenUsage
                ):
                    result.token_usage = raw_output.token_usage.model_copy()
                    raw_output.token_usage = None
                    # this should work because @task decorator is one step only
                    # it might be an issue if you need to load it back exactly
                    result.add_details("promoted raw output token usage to wrapper")
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
                result.timing.duration = round(time.perf_counter() - time_start, 2)
                return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
