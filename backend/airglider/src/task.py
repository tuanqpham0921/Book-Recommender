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

                # A body returning an envelope used to be the way to report `ok`
                # yourself or hand back what you called. Both have better
                # answers now — `ok` means "ran to completion" so nobody votes
                # on it, and anything awaited inside this body already attached
                # itself — which leaves only the ways it can go wrong: the
                # subtree serialized twice, or a failed step read as a success
                # with a None payload. Rejected rather than unwrapped silently,
                # because the two spellings below mean different things and
                # guessing is what produced the None.
                if isinstance(raw_output, OperationResult):
                    raise TypeError(
                        f"{func_ref} returned an OperationResult. A @task "
                        f"returns its payload — the envelope is the "
                        f"decorator's. Use `(await step).unwrap()` to hand back "
                        f"what a nested step produced (it has already attached "
                        f"itself to this task), or `await step` and return the "
                        f"part you want; `airglider.add_details` writes to this "
                        f"task's own record."
                    )

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
