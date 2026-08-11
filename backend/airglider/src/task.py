import asyncio
import logging
import time
from typing import Callable
from functools import wraps
from typing import Any, Coroutine,  ParamSpec, TypeVar, overload

from .schemas.record import OperationResult, Response, TokenUsage, RuntimeErrorInfo
from .utils import bind_call_args, now_iso, to_record_input


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


def record_input(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """What this call was made with, keyed by parameter name — or None.

    Computed *before* the call, so the exception path below records it too:
    a task that crashed is the one whose arguments are worth having.

    Never raises. `to_summary` is host code this library does not control, and
    bookkeeping that can take down the task it describes is worse than a
    missing field.
    """
    try:
        arguments = bind_call_args(func, args, kwargs)
        return {
            name: value for name, value in arguments.items()
        } or None
    except Exception:
        logger.warning(f"Could not record input for {func.__qualname__}", exc_info=True)
        return None


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
            call_input = record_input(func, args, kwargs, logger)

            # Read here, not left to `Time`'s default_factory: every envelope
            # below is constructed *after* the await, so the default would
            # stamp the moment the task finished as the moment it started —
            # putting `start_time` and the derived `end_time` a whole duration
            # too late. `perf_counter` alongside it is monotonic, and the pair
            # is what makes `end_time` consistent (see Time.end_time).
            started_at = now_iso()
            time_start = time.perf_counter()

            def stamp(result: OperationResult) -> OperationResult:
                """Timing is the wrapper's business, on every return path —
                including an envelope the task built for itself."""
                result.timing.start_time = started_at
                result.timing.duration = round(time.perf_counter() - time_start, 2)
                return result

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
                    # not overwritten: a task that built its own envelope may
                    # have recorded a more meaningful input than its raw
                    # arguments, and that is the one worth keeping
                    if raw_output.input is None:
                        raw_output.input = call_input
                    return stamp(raw_output)

                # task did not return an operation result, create a default one
                # no run time error is recorded, so the task is considered successful
                result = OperationResult(
                    name=func_ref,
                    input=call_input,
                    response=Response(result=raw_output, output_type=type(raw_output).__name__),
                )
                stamp(result)
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

                # the arguments matter most here: this envelope carries no
                # output to reason from, so what it was called with is the
                # only description of the failure beyond the traceback
                result = OperationResult(name=func_ref, input=call_input)
                result.ok = False
                result.runtime_error = RuntimeErrorInfo.from_exception(e)
                return stamp(result)

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
