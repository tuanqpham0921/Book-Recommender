"""Demo: why `except Exception` around a shielded cleanup can still miss a
cancellation — and why combining two shields into one fixes it.

Mirrors Orchestrator.run()'s finally block (app/orchestration/orchestrator.py)
and chat_message.py's generate_chat_response() cancel-then-gather dance. The
real second cancellation comes from EventSourceResponse's anyio cancel scope:
on client disconnect it calls task_group.cancel_scope.cancel(), which
(unlike a plain asyncio Task.cancel()) keeps re-injecting cancellation at
every checkpoint until the scope exits — including the
`await asyncio.gather(orchestrator_task, return_exceptions=True)` in
generate_chat_response's own finally block. asyncio.gather() responds to
being cancelled by cancelling everything it's gathering, so orchestrator_task
gets cancelled a second time, sometimes right in the middle of its own
shielded cleanup.

Run: poetry run python playground/scratch.py
"""

import asyncio


async def cleanup_step(name: str, delay: float) -> None:
    print(f"  [{name}] starting ({delay}s)...")
    await asyncio.sleep(delay)
    print(f"  [{name}] done")


# --- the bug: two separate shields, `except Exception` only ----------------
# CancelledError is a BaseException (since Python 3.8), not an Exception —
# `except Exception` never sees it, so a cancellation landing on the first
# shield blows straight past the second cleanup step entirely.

async def buggy_worker() -> None:
    try:
        print("worker: doing the main work...")
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("worker: cancelled mid-work")
        raise
    finally:
        try:
            await asyncio.shield(cleanup_step("record_chat_run", 0.3))
        except Exception:
            print("  [record_chat_run] except Exception (doesn't catch CancelledError!)")

        try:
            await asyncio.shield(cleanup_step("sse_stream.close", 0.1))
        except Exception:
            print("  [sse_stream.close] except Exception (doesn't catch CancelledError!)")


# --- the fix: one shield around the whole cleanup sequence ------------------
# A second cancellation now only interrupts the *await*, not the cleanup
# itself — _finalize() keeps running both steps to completion in the
# background regardless.

async def _finalize() -> None:
    try:
        await cleanup_step("record_chat_run", 0.3)
    except Exception:
        print("  [record_chat_run] failed, continuing")

    try:
        await cleanup_step("sse_stream.close", 0.1)
    except Exception:
        print("  [sse_stream.close] failed, continuing")


async def fixed_worker() -> None:
    try:
        print("worker: doing the main work...")
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("worker: cancelled mid-work")
        raise
    finally:
        try:
            await asyncio.shield(_finalize())
        except asyncio.CancelledError:
            print("worker: cleanup cancelled again — _finalize() keeps running in the background")


# --- the "generate_chat_response" side --------------------------------------

async def consumer(worker_factory) -> None:
    worker_task = asyncio.create_task(worker_factory())
    await asyncio.sleep(0.4)  # let the worker get partway into "main work"

    print(">>> simulating client disconnect: cancel #1 (worker)")
    worker_task.cancel()

    consumer_task = asyncio.current_task()

    async def deliver_second_cancel():
        await asyncio.sleep(0.15)  # land partway into worker's shielded cleanup
        print(">>> simulating anyio re-cancelling the consumer: cancel #2 (via gather)")
        consumer_task.cancel()

    asyncio.create_task(deliver_second_cancel())

    try:
        # mirrors generate_chat_response's `await asyncio.gather(orchestrator_task,
        # return_exceptions=True)` — gather cancels worker_task when THIS
        # await is cancelled
        await asyncio.gather(worker_task, return_exceptions=True)
    except asyncio.CancelledError:
        # mirrors the outer ASGI layer swallowing the re-cancellation
        pass

    # give any orphaned background cleanup a moment to actually finish, so
    # we can see whether it did
    await asyncio.sleep(0.5)


async def main() -> None:
    print("=== buggy: two separate shields ===")
    await consumer(buggy_worker)

    print("\n=== fixed: one shield around the whole cleanup ===")
    await consumer(fixed_worker)


if __name__ == "__main__":
    asyncio.run(main())
