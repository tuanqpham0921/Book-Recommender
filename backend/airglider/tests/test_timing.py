"""`Time.end_time` — derived from `start_time + duration`, never observed.

The derivation only means anything if `start_time` is the instant `duration`
is measured from. Both `Workflow.__call__` and `@task` have to stamp it
themselves to make that true, and for opposite reasons: a workflow's envelope
is built at *construction* (before the runner dispatches it), while a task's is
built *after* the await (so the default would record the finish as the start,
putting the whole interval a duration too late). Those two are the real tests
here — the property itself is arithmetic.
"""

import asyncio
from datetime import datetime

import pytest

from airglider import WorkFlowOperationResult, Workflow, task
from airglider.src.schemas import Time
from airglider.src.utils import now_iso

# `duration` is rounded to 2 decimals by both callers, so a derived end_time
# can sit up to half a centisecond past the instant the call really returned.
ROUNDING_TOLERANCE = 0.005


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


class TestDerivation:
    def test_end_time_is_start_plus_duration(self):
        timing = Time(start_time="2026-08-11T10:00:00+00:00", duration=1.5)

        assert timing.end_time == "2026-08-11T10:00:01.500000+00:00"

    def test_a_running_operation_has_no_end_time(self):
        """`duration` is only set when the call returns, so None here means
        'still running' rather than 'finished at an unknown time'."""
        assert Time(start_time=now_iso()).end_time is None

    def test_a_fresh_envelope_has_no_end_time(self):
        assert WorkFlowOperationResult().end_time is None

    def test_the_envelope_delegates_to_its_timing(self):
        record = WorkFlowOperationResult()
        record.timing.duration = 2.0

        assert record.end_time == record.timing.end_time

    def test_the_three_values_always_agree(self):
        """The reason this is derived rather than read from the clock a second
        time: a wall-clock end could disagree with `duration` after an NTP
        correction, and a step could even appear to finish before it began."""
        timing = Time(start_time="2026-08-11T10:00:00+00:00", duration=0.25)

        assert (
            _parse(timing.end_time) - _parse(timing.start_time)
        ).total_seconds() == timing.duration


class TestWorkflowStampsTheRunNotTheConstruction:
    async def test_start_time_is_when_the_run_began(self):
        """A node executor is constructed by the task runner and dispatched
        after — so an envelope keeping its construction time would report a
        start before the work, and an end_time to match."""

        class _Workflow(Workflow):
            async def run(self):
                self.record.ok = True

        workflow = _Workflow()
        constructed_at = _parse(workflow.record.timing.start_time)
        await asyncio.sleep(0.05)

        before_call = _parse(now_iso())
        await workflow()

        assert _parse(workflow.record.timing.start_time) >= before_call
        assert _parse(workflow.record.timing.start_time) > constructed_at

    async def test_end_time_falls_inside_the_call(self):
        """Within `duration`'s rounding — callers round to 2 decimals, so
        end_time can sit up to 5ms past the true return."""

        class _Workflow(Workflow):
            async def run(self):
                await asyncio.sleep(0.05)
                self.record.ok = True

        workflow = _Workflow()
        await workflow()
        after_call = _parse(now_iso())

        assert _parse(workflow.record.timing.start_time) < _parse(
            workflow.record.end_time
        )
        overshoot = (_parse(workflow.record.end_time) - after_call).total_seconds()
        assert overshoot <= ROUNDING_TOLERANCE


class TestTaskStampsBeforeTheAwait:
    async def test_start_time_precedes_the_work(self):
        """Every envelope in the decorator is constructed after the await, so
        the field's default_factory would stamp the finish as the start."""

        @task(log_info=False)
        async def _slow():
            await asyncio.sleep(0.05)
            return "done"

        before_call = _parse(now_iso())
        result = await _slow()

        assert _parse(result.timing.start_time) >= before_call
        overshoot = (_parse(result.end_time) - _parse(now_iso())).total_seconds()
        assert overshoot <= ROUNDING_TOLERANCE

    async def test_a_failing_task_brackets_its_own_run(self):
        @task(log_info=False)
        async def _explodes():
            await asyncio.sleep(0.05)
            raise ValueError("boom")

        before_call = _parse(now_iso())
        result = await _explodes()
        after_call = _parse(now_iso())

        assert not result.ok
        assert before_call <= _parse(result.timing.start_time)
        assert (
            _parse(result.end_time) - after_call
        ).total_seconds() <= ROUNDING_TOLERANCE

    async def test_a_task_owning_its_envelope_still_gets_wrapper_timing(self):
        """Timing is the wrapper's business on every return path — a task
        cannot know its own duration, and its envelope's construction time is
        as wrong as the default."""

        @task(log_info=False)
        async def _custom():
            await asyncio.sleep(0.05)
            return WorkFlowOperationResult(ok=True)

        before_call = _parse(now_iso())
        result = await _custom()

        assert result.duration is not None
        assert _parse(result.timing.start_time) >= before_call
