import logging
from typing import Callable
from functools import wraps
from typing import Any, Coroutine, ParamSpec, TypeVar, overload

from .span import record_span
from .schemas.record import (
    OperationResult,
    Response,
    TokenUsage,
)
from .utils import record_call_input

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
    """Wrap an async function so it returns a record instead of a bare value.

    Reach for `Workflow` when you want a declared output type, SSE helpers, or
    somewhere to hang state — that is the whole difference. A task publishes its
    own envelope while it runs, so it may call other tasks and workflows freely,
    and `(await step).unwrap()` aborts it on a failed step exactly as it would a
    workflow.
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, Any]],
    ) -> Callable[P, Coroutine[Any, Any, OperationResult[Any]]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"

            # Built before the call because `record_span` needs something to
            # publish, which also lets its error and cancel paths report without
            # constructing a second envelope.
            result: OperationResult[Any] = OperationResult(
                name=func_ref, input=record_call_input(func, args, kwargs, logger)
            )

            # Timing, `parent_scope`, and the cancel/error paths — see span.py.
            with record_span(result, logger, label="task", log_info=log_info):
                raw_output = await func(*args, **kwargs)

                # The task validated `ok` itself. Its envelope becomes a step
                # with its own id, input and timing — whether from
                # `return await inner()` (already attached; `add_step` no-ops)
                # or hand-built. This task reports it: `ok` and the payload are
                # the child's. Storing the envelope in `response` instead would
                # make `.result` hand back a record and serialize the subtree
                # twice.
                if isinstance(raw_output, OperationResult):
                    # `:` not `.` — readers shorten a name to its last dotted
                    # segment, and `.result` would shorten to "result" with no
                    # trace of which task it belongs to
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
                    # `+=` not assignment, so usage rolled up from nested steps
                    # is not thrown away
                    if hasattr(raw_output, "token_usage") and isinstance(
                        raw_output.token_usage, TokenUsage
                    ):
                        result.token_usage += raw_output.token_usage
                        raw_output.token_usage = None
                        result.add_details("promoted output token usage")

            return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
