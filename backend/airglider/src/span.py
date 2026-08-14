"""The recording body shared by `@task` and `Workflow.__call__`.

Both wrap their call in the same six things: a start timestamp paired with a
monotonic clock, `parent_scope`, a cancel path that stamps and re-raises, a stop
path for `StepFailure`, an error path that stamps and does not re-raise, and a
`finally` that closes `duration` inside the scope so the parent adopts a
finished record. Only the noun in the log lines differs, which is what `label`
is for.

Keeping it here rather than in two files is what makes the cancel contract
checkable by reading one function.
"""

import asyncio
import logging
import time
from contextlib import contextmanager
from typing import Iterator

from .context import parent_scope
from .exception import StepFailure
from .schemas.record import OperationResult, RuntimeErrorInfo
from .utils import now_iso


@contextmanager
def record_span(
    record: OperationResult,
    logger: logging.Logger,
    *,
    label: str,
    name: str | None = None,
    log_info: bool = True,
) -> Iterator[OperationResult]:
    """Time `record`, publish it as the current parent, and stamp what the body
    raises onto it.

    `Exception` is swallowed on purpose: the envelope's `ok`/`runtime_error`
    *is* the report, which is what keeps a failed unit of work from crashing the
    one above it. A caller wanting a different verdict for a particular
    exception type catches it inside the body, before it reaches here.

    `name` is the log-line display name, which is not always `record.name` — a
    workflow logs `Class:id` so concurrent runs stay tellable apart.
    """
    display_name = name or record.name

    # read as a pair — one wall clock, one monotonic — because `end_time` is
    # derived from both (see Time.end_time)
    record.timing.start_time = now_iso()
    time_start = time.perf_counter()

    # Publishes `record` for anything the body calls. Wrapping the whole
    # try/finally puts the attach after `duration` is stamped and every step has
    # rolled up — `add_step` reads usage once, at attach.
    with parent_scope(record):
        try:
            if log_info:
                logger.info(f"Running {label}: {display_name}")
            yield record
        except asyncio.CancelledError as e:
            # client disconnected mid-call. Stamp what we have, then re-raise —
            # swallowing this would stop the actual cancellation. The scope's
            # `finally` still attaches on the way out.
            record.ok = False
            record.add_details("asyncio Cancelled")
            record.runtime_error = RuntimeErrorInfo.from_exception(e)
            logger.warning(f"{label.capitalize()} cancelled: {display_name}")
            raise
        except StepFailure as e:
            # A step below returned not-ok and the body insisted on its payload
            # (`unwrap`). Stamped like any other failure — `ok` means "ran to
            # completion", so a stop is not a completion and must carry a reason
            # — but logged as a warning without a traceback: the step that
            # actually raised already logged the real one, and re-printing it at
            # every level above is how one cause becomes four tracebacks.
            #
            # Here rather than in `Workflow.__call__` so a `@task` that unwraps
            # reads the same as a workflow that does; which decorator a unit of
            # work happens to use is not a fact about the failure.
            record.ok = False
            record.runtime_error = RuntimeErrorInfo.from_exception(e)
            logger.warning(f"{label.capitalize()} stopped: {e}")
        except Exception as e:
            record.ok = False
            record.runtime_error = RuntimeErrorInfo.from_exception(e)
            logger.exception(f"{label.capitalize()} failed: {e}")
        finally:
            # inside the scope, so `duration` and the rolled-up usage are final
            # before the parent adopts and sums this
            record.timing.duration = round(time.perf_counter() - time_start, 2)
