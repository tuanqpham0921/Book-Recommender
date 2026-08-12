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

    Computed *before* the call, so the exception path below records it too:
    a task that crashed is the one whose arguments are worth having.

    Never raises. `to_summary` is host code this library does not control, and
    bookkeeping that can take down the task it describes is worse than a
    missing field.
    """
    try:
        arguments = bind_call_args(func, args, kwargs)
        return {name: value for name, value in arguments.items()} or None
    except Exception:
        logger.warning(f"Could not record input for {func.__qualname__}", exc_info=True)
        return None


def merge_returned_envelope(
    envelope: OperationResult, returned: OperationResult
) -> None:
    """Fold a task's self-built envelope into the one the decorator published.

    A task that wants to report `ok` itself — "the table does not exist" is an
    answer, not a crash — returns its own `OperationResult`. The decorator used
    to hand that object straight back, which is what made `@task` non-
    idempotent: the returned envelope's `id`, `name`, `input` and `timing` were
    overwritten in place, so three nested tasks collapsed into whichever one
    returned last, wearing the outermost one's name.

    It cannot be handed back at all any more. `parent_scope` published
    `envelope`, so that is the object this call's children attached themselves
    to; returning a different one would drop the whole subtree. The fields the
    task actually meant to set are copied across instead, and the throwaway
    envelope's identity — an id nobody held a reference to — is discarded.

    `steps` are re-attached rather than assigned so `add_step` can stamp and
    roll them up; ones that already auto-attached are skipped by its own
    idempotency guard, so a task that both nests calls and hand-builds a
    `steps=` list ends up with each child exactly once.
    """
    envelope.ok = returned.ok
    envelope.response = returned.response
    envelope.details.extend(returned.details)
    if returned.runtime_error is not None:
        envelope.runtime_error = returned.runtime_error
    if returned.input is not None:
        # a task that built its own envelope may have recorded a more
        # meaningful input than its raw arguments; that is the one worth keeping
        envelope.input = returned.input

    steps = getattr(returned, "steps", None) or []
    for step in steps:
        envelope.add_step(step)

    # only when it brought no children of its own: usage on a record that has
    # steps was rolled up from those steps, which we just re-attached, and
    # adding it again would count them twice
    if not steps:
        envelope.token_usage += returned.token_usage


def task(
    func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    *,
    log_info: bool = True,
) -> Any:
    """Wrap an async function so it returns a record instead of a bare value.

    Reach for `Workflow` when you want what a class gives you — a declared
    output type, SSE helpers, `run_async_step`'s failure policy, somewhere to
    hang state. That is now the whole difference: a task publishes its own
    envelope while it runs (`parent_scope`), so it may call other tasks and
    other workflows freely and they nest under it.
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, Any]],
    ) -> Callable[P, Coroutine[Any, Any, OperationResult[Any]]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"
            call_input = record_input(func, args, kwargs, logger)

            # Read here, not left to `Time`'s default_factory: the envelope is
            # built before the await, but `now_iso()` and `perf_counter()` have
            # to be read as a pair — one wall clock, one monotonic — because
            # `end_time` is derived from both (see Time.end_time).
            started_at = now_iso()
            time_start = time.perf_counter()

            # Built *before* the call because `parent_scope` needs something to
            # publish, which also means the error and cancellation paths below
            # no longer have to construct a second envelope to report on. It
            # can hold children because every envelope can — a task that runs
            # nothing else just carries an empty `steps`, and one that runs
            # another task adopts it without anything being threaded in.
            result: OperationResult[Any] = OperationResult(
                name=func_ref, input=call_input
            )
            result.timing.start_time = started_at

            # Exits by attaching `result` to whatever envelope was current when
            # this task was called — including while a CancelledError is on its
            # way out, so a cancelled task still lands in its caller's steps.
            with parent_scope(result):
                try:
                    if log_info:
                        logger.info(f"Running task: {func_ref}")

                    raw_output = await func(*args, **kwargs)

                    # custom operation result returned from the task: the task
                    # validated `ok` itself. Merged into the envelope we already
                    # published rather than returned in its place — see
                    # merge_returned_envelope for why handing it back is no
                    # longer possible.
                    if isinstance(raw_output, OperationResult):
                        merge_returned_envelope(result, raw_output)
                        if log_info and not result.ok:
                            logger.warning(f"Task failed: {func_ref}")
                    else:
                        # task did not return an operation result; no runtime
                        # error was recorded, so the task is considered successful
                        result.response = Response(
                            result=raw_output, output_type=type(raw_output).__name__
                        )
                        result.ok = True
                        result.add_details(
                            "output is not an operation result, creating a default one"
                        )
                        # token_usage defaults via Field(default_factory=TokenUsage);
                        # `+=` rather than assignment so usage rolled up from any
                        # nested steps this task ran is not thrown away
                        if hasattr(raw_output, "token_usage") and isinstance(
                            raw_output.token_usage, TokenUsage
                        ):
                            result.token_usage += raw_output.token_usage
                            raw_output.token_usage = None
                            result.add_details(
                                "promoted raw output token usage to wrapper"
                            )
                except asyncio.CancelledError as e:
                    # client disconnected (e.g. page refresh) mid-task.
                    # Returning a result would swallow the cancellation, so the
                    # envelope is stamped and propagates unreturned — the scope
                    # above still attaches it, so the caller's trace shows what
                    # was in flight.
                    result.ok = False
                    result.add_details("asyncio Cancelled")
                    result.runtime_error = RuntimeErrorInfo.from_exception(e)
                    logger.warning(f"Task cancelled: {func_ref}")
                    raise
                except Exception as e:
                    # run time error is recorded, so the task is considered failed
                    logger.exception(e)
                    # the arguments matter most here: this envelope carries no
                    # output to reason from, so what it was called with is the
                    # only description of the failure beyond the traceback
                    result.ok = False
                    result.runtime_error = RuntimeErrorInfo.from_exception(e)
                finally:
                    # inside the scope, so `duration` and the rolled-up
                    # `token_usage` are final before the parent adopts this and
                    # sums it — `add_step` reads usage once, at attach time
                    result.timing.duration = round(time.perf_counter() - time_start, 2)

            return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)
