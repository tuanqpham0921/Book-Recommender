import asyncio
import time

from app.common.sse_stream import SSEStream

_start = time.time()


def tprint(*args, **kwargs):
    print(f"[{time.time() - _start:6.3f}s]", *args, **kwargs)


# --- SSEStream (asyncio.Queue) producer/consumer demo -----------------------
#
# SSEStream wraps an asyncio.Queue: producer .put()s, consumer does
# `async for` (__anext__ = await self._queue.get()). The consumer just
# blocks on an empty queue — no polling — and resumes the instant an item
# lands, which is why send_chars() can "type" a message with a delay
# between each character and it still shows up live on the other side.

async def producer(stream: SSEStream):
    for word in ["Hello", "from", "the", "producer"]:
        tprint(f"producer: putting {word!r}")
        await stream.send(event_type="content.delta", data=word)
        await asyncio.sleep(1)  # simulate work between chunks (e.g. LLM tokens)
        await stream.send(event_type="content.delta", data="random stuff")
    await stream.close()
    tprint("producer: closed the stream")


async def consumer(stream: SSEStream):
    async for event in stream:
        tprint(f"consumer: got {event.data!r} (consumer was asleep until this arrived)")
        await asyncio.sleep(10)
    tprint("consumer: StopAsyncIteration — stream closed, loop exited")


async def demo_sse_queue():
    stream = SSEStream()
    # run both concurrently: consumer is idle (awaiting queue.get()) between
    # each item, waking up only when producer actually puts something
    await asyncio.gather(producer(stream), consumer(stream))


# --- mini chat_message.py / orchestrator.py style demo ---------------------
#
# fake_orchestrator_run   ~ Orchestrator.run(): the long-running step
# fake_generate_response  ~ generate_chat_response(): owns the task's lifecycle

async def fake_orchestrator_run():
    """Stand-in for Orchestrator.run(): a long step, cancel-aware cleanup."""
    try:
        tprint("fake_orchestrator: working (would take 60s)...")
        await asyncio.sleep(60)
        tprint("fake_orchestrator: finished normally (shouldn't happen here)")
    except asyncio.CancelledError:
        tprint("fake_orchestrator: cancelled mid-work")
        raise
    finally:
        # e.g. closing the SSE stream / recording the run — shielded so a
        # 2nd cancel (impatient caller) can't cut it off mid-cleanup
        await asyncio.shield(asyncio.sleep(0.3))
        tprint("fake_orchestrator: cleanup finished")


async def fake_event_stream():
    """Stand-in for request_context.sse_stream: a couple events, then a long
    wait for more — this is what generate_chat_response is actually
    suspended on, not the orchestrator task itself."""
    yield "event-1"
    await asyncio.sleep(100)
    yield "event-2"  # never reached in this demo


async def fake_generate_response():
    """Stand-in for generate_chat_response(): owns the task's lifecycle."""
    task = asyncio.create_task(fake_orchestrator_run())
    try:
        async for event in fake_event_stream():
            tprint(f"fake_generate_response: streaming {event!r} to the client...")
        await task
    finally:
        # mirrors chat_message.py: only cancel if it isn't already done,
        # then gather so we actually wait for cancellation to finish
        if not task.done():
            tprint("fake_generate_response: task still running, cancelling it")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        tprint(
            f"fake_generate_response: done={task.done()} cancelled={task.cancelled()}"
        )


async def main():
    tprint("--- fake_generate_response / fake_orchestrator_run ---")
    outer = asyncio.create_task(fake_generate_response())
    await asyncio.sleep(1)  # let it get partway into the "60s" step
    tprint("\n>>> simulating client disconnect: cancelling outer task <<<\n")
    outer.cancel()
    await asyncio.gather(outer, return_exceptions=True)


# --- catching timeouts -------------------------------------------------
#
# asyncio.TimeoutError IS asyncio.exceptions.TimeoutError, and since 3.11
# that's the same class as the builtin TimeoutError (OSError -> Exception ->
# BaseException). So unlike CancelledError, a plain `except Exception` (or
# `except TimeoutError`) catches it fine — no BaseException needed.

async def timeout_is_a_normal_exception():
    try:
        raise TimeoutError("boom")
    except Exception as e:
        tprint(f"except Exception DID catch it: {e!r}")


async def slow_step():
    try:
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        # wait_for()/asyncio.timeout() cancel us the instant the deadline
        # hits — this is where WE see it, not where TimeoutError is raised
        tprint("slow_step: cancelled by the timeout")
        raise


async def demo_wait_for_timeout():
    try:
        await asyncio.wait_for(slow_step(), timeout=0.5)
    except TimeoutError:
        # this is where the timeout itself surfaces — asyncio.wait_for
        # converts the cancellation into TimeoutError at the call site
        tprint("demo_wait_for_timeout: caught TimeoutError")


async def demo_timeout_context_manager():
    """asyncio.timeout() (3.11+) — same TimeoutError, no wait_for wrapper."""
    try:
        async with asyncio.timeout(0.5):
            await slow_step()
    except TimeoutError:
        tprint("demo_timeout_context_manager: caught TimeoutError")


async def demo_timeout_catching():
    await timeout_is_a_normal_exception()
    await demo_wait_for_timeout()
    await demo_timeout_context_manager()


if __name__ == "__main__":
    # asyncio.run(demo_sse_queue())
    # asyncio.run(main())
    asyncio.run(demo_timeout_catching())
