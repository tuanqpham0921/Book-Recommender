import asyncio
import logging
import time
from typing import Callable
from functools import wraps
from typing import Any, Coroutine, ParamSpec, TypeVar, overload

from .context import parent_scope
from .schemas.record import (
    OperationResult,
    Response,
    TokenUsage,
    RuntimeErrorInfo,
)
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

    Computed before the call so the exception path records it too. Never
    raises: bookkeeping must not take down the task it describes.
    """
    try:
        arguments = bind_call_args(func, args, kwargs)
        return {
            name: to_record_input(value) for name, value in arguments.items()
        } or None
    except Exception:
        logger.warning(f"Could not record input for {func.__qualname__}", exc_info=True)
        return None


def task(
    func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    *,
    log_info: bool = True,
) -> Any:
    """Wrap an async function so it returns a record instead of a bare value.

    Reach for `Workflow` when you want a declared output type, SSE helpers,
    `run_async_step`'s failure policy, or somewhere to hang state — that is the
    whole difference. A task publishes its own envelope while it runs, so it may
    call other tasks and workflows freely.
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, Any]],
    ) -> Callable[P, Coroutine[Any, Any, OperationResult[Any]]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"
            call_input = record_input(func, args, kwargs, logger)

            # read as a pair — one wall clock, one monotonic — because
            # `end_time` is derived from both (see Time.end_time)
            started_at = now_iso()
            time_start = time.perf_counter()

            # Built before the call because `parent_scope` needs something to
            # publish, which also lets the error and cancel paths below report
            # without constructing a second envelope.
            result: OperationResult[Any] = OperationResult(
                name=func_ref, input=call_input
            )
            result.timing.start_time = started_at

            # Stamps `parent_id` on entry and attaches on exit — including
            # while a CancelledError is on its way out.
            with parent_scope(result):
                try:
                    if log_info:
                        logger.info(f"Running task: {func_ref}")

                    raw_output = await func(*args, **kwargs)

                    # The task validated `ok` itself. Its envelope becomes a
                    # step with its own id, input and timing — whether from
                    # `return await inner()` (already attached; `add_step`
                    # no-ops) or hand-built. This task reports it: `ok` and the
                    # payload are the child's. Storing the envelope in
                    # `response` instead would make `.result` hand back a record
                    # and serialize the subtree twice.
                    if isinstance(raw_output, OperationResult):
                        # `:` not `.` — readers shorten a name to its last
                        # dotted segment, and `.result` would shorten to
                        # "result" with no trace of which task it belongs to
                        if raw_output.name is None:
                            raw_output.name = f"{func_ref}:result"
                        result.add_step(raw_output)
                        result.add_details("nested envelope: response is the step")
                        result.ok = raw_output.ok
                        result.response = raw_output.response
                        if log_info and not result.ok:
                            logger.warning(f"Task failed: {func_ref}")
                    else:
                        # no envelope and no runtime error, so this succeeded
                        result.response = Response(
                            result=raw_output, output_type=type(raw_output).__name__
                        )
                        result.ok = True
                        result.add_details("wrapped a bare return value")
                        # `+=` not assignment, so usage rolled up from nested
                        # steps is not thrown away
                        if hasattr(raw_output, "token_usage") and isinstance(
                            raw_output.token_usage, TokenUsage
                        ):
                            result.token_usage += raw_output.token_usage
                            raw_output.token_usage = None
                            result.add_details("promoted output token usage")
                except asyncio.CancelledError as e:
                    # client disconnected mid-task. Returning a result would
                    # swallow the cancellation, so the envelope is stamped and
                    # propagates unreturned — the scope still attaches it.
                    result.ok = False
                    result.add_details("asyncio Cancelled")
                    result.runtime_error = RuntimeErrorInfo.from_exception(e)
                    logger.warning(f"Task cancelled: {func_ref}")
                    raise
                except Exception as e:
                    logger.exception(e)
                    result.ok = False
                    result.runtime_error = RuntimeErrorInfo.from_exception(e)
                finally:
                    # inside the scope, so `duration` and the rolled-up usage
                    # are final before the parent adopts and sums this
                    result.timing.duration = round(time.perf_counter() - time_start, 2)

            return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
