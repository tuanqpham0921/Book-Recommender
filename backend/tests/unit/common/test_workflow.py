import asyncio

import pytest
from common.workflow import Workflow, StepFailure
from common.operation import OperationResult, TokenUsage, task


def _make_flaky_task(fail_times: int):
    """Build a @task that raises on its first `fail_times` calls, then
    succeeds — for exercising crash-mid-step and retry behavior."""
    calls = {"count": 0}

    @task(log_info=False)
    async def flaky_step():
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise ValueError(f"attempt {calls['count']} failed")
        return f"succeeded on attempt {calls['count']}"

    return flaky_step


async def _as_coro(step: OperationResult) -> OperationResult:
    return step


class _SuccessWorkflow(Workflow):
    def __init__(self):
        # producing output requires declaring its type (check_output_type)
        super().__init__(output_type=str)

    async def run(self, *args, **kwargs):
        self.result.response.output = "done"
        # fail-closed contract: workflows must declare success explicitly
        self.result.ok = True


class _ExceptionWorkflow(Workflow):
    async def run(self, *args, **kwargs):
        raise RuntimeError("workflow exploded")


class _StepWorkflow(Workflow):
    def __init__(self, step: OperationResult, raise_on_failure: bool = True):
        super().__init__()
        self._step = step
        self._raise = raise_on_failure

    async def run(self, *args, **kwargs):
        step = await self.run_async_step(
            _as_coro(self._step), raise_on_failure=self._raise
        )
        # fail-closed contract: declare success only if the work succeeded
        if step.ok:
            self.result.ok = True


class _MultiStepWorkflow(Workflow):
    def __init__(self, steps: list[OperationResult], raise_on_failure: bool = True):
        super().__init__()
        self._steps = steps
        self._raise = raise_on_failure

    async def run(self, *args, **kwargs):
        for step in self._steps:
            await self.run_async_step(_as_coro(step), raise_on_failure=self._raise)


class TestWorkflowExecution:
    async def test_successful_run_sets_ok_true(self):
        result = await _SuccessWorkflow()()
        assert result.ok is True

    async def test_successful_run_records_duration(self):
        result = await _SuccessWorkflow()()
        assert result.timing.duration is not None
        assert result.timing.duration >= 0

    async def test_exception_in_run_sets_ok_false(self):
        result = await _ExceptionWorkflow()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert "workflow exploded" in result.runtime_error.message

    async def test_exception_in_run_still_records_duration(self):
        result = await _ExceptionWorkflow()()
        assert result.timing.duration is not None

    async def test_undeclared_output_fails_the_workflow(self):
        # producing output without declaring output_type is a contract
        # violation caught by check_output_type after run()
        class _UndeclaredOutput(Workflow):
            async def run(self, *args, **kwargs):
                self.result.response.output = "done"
                self.result.ok = True

        result = await _UndeclaredOutput()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "TypeError"



class TestRunAsyncStep:
    async def test_success_step_appended_to_steps(self):
        step = OperationResult(ok=True, name="my_step")
        result = await _StepWorkflow(step)()
        assert result.ok is True
        assert len(result.steps) == 1
        assert result.steps[0].name == "my_step"

    async def test_failed_step_sets_result_ok_false(self):
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, raise_on_failure=False)()
        assert result.ok is False

    async def test_failed_step_names_the_step_in_details(self):
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, raise_on_failure=False)()
        assert "FAILED STEP:bad_step" in result.details

    async def test_failed_step_with_raise_is_a_controlled_abort(self):
        # StepFailure is control flow, not a crash: the parent envelope must
        # NOT carry runtime_error — the step's own envelope has the details
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, raise_on_failure=True)()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "StepFailure"
        assert "bad_step" in result.runtime_error.message

    async def test_failed_step_without_raise_still_appended(self):
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, raise_on_failure=False)()
        assert len(result.steps) == 1

    async def test_multiple_steps_all_appended(self):
        steps = [
            OperationResult(ok=True, name="step_1"),
            OperationResult(ok=True, name="step_2"),
            OperationResult(ok=True, name="step_3"),
        ]
        result = await _MultiStepWorkflow(steps)()
        assert len(result.steps) == 3

    async def test_bad_step_does_not_stop_later_steps_without_raise(self):
        steps = [
            OperationResult(ok=True, name="step_1"),
            OperationResult(ok=False, name="bad_step"),
            OperationResult(ok=True, name="step_3"),
        ]
        result = await _MultiStepWorkflow(steps, raise_on_failure=False)()
        # raise_on_failure=False: every step still runs and is recorded
        assert len(result.steps) == 3
        assert [step.ok for step in result.steps] == [True, False, True]
        assert "FAILED STEP:bad_step" in result.details
        
    async def test_bad_step_stop_later_steps_with_raise(self):
        steps = [
            OperationResult(ok=True, name="step_1"),
            OperationResult(ok=False, name="bad_step"),
            OperationResult(ok=True, name="step_3"),
        ]
        result = await _MultiStepWorkflow(steps, raise_on_failure=True)()
        assert len(result.steps) == 2
        assert [step.ok for step in result.steps] == [True, False]
        assert "FAILED STEP:bad_step" in result.details

    async def test_later_success_does_not_clear_an_earlier_failure(self):
        steps = [
            OperationResult(ok=False, name="bad_step"),
            OperationResult(ok=True, name="step_2"),
        ]
        result = await _MultiStepWorkflow(steps)()
        # the parent stays failed unless the workflow explicitly declares
        # success after handling the failure (fail-closed contract)
        assert result.ok is False
        assert "FAILED STEP:bad_step" in result.details


class TestCrashingSteps:
    """Steps whose coroutine raises mid-flight, before any OperationResult
    is produced."""

    async def test_unenveloped_coroutine_crash_is_a_workflow_crash(self):
        # a bare coroutine (no @task) has no envelope to absorb the crash:
        # the exception reaches __call__ and is recorded as the workflow's
        # own runtime failure, with no step in the trail
        async def _explodes():
            raise ValueError("boom before any envelope")

        class _BareCoroWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                await self.run_async_step(_explodes())

        result = await _BareCoroWorkflow()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "ValueError"
        assert result.steps == []
        
    async def test_unenveloped_coroutine_crash_still_have_previous_results(self):
        async def _explodes():
            raise ValueError("boom before any envelope")
        
        async def _okay_step(i):
            return OperationResult(ok=True, name = f"okay_step: {i}")

        class _BareCoroWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                for i in range(5):
                    if i == 3:
                        await self.run_async_step(_explodes())
                    await self.run_async_step(_okay_step(i))
                

        result = await _BareCoroWorkflow()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "ValueError"
        assert len(result.steps) == 3
        
    @pytest.mark.parametrize("raise_on_failure", [True, False])
    async def test_unenveloped_crash_ignores_raise_on_failure(self, raise_on_failure):
        # raise_on_failure only governs failed *envelopes*; the crash fires
        # at `await function`, before the flag is ever consulted — so a bare
        # coroutine crash aborts the workflow either way. To survive a
        # crashing step, envelope it with @task (see the next test).
        async def _explodes():
            raise ValueError("boom before any envelope")

        async def _okay_step(i):
            return OperationResult(ok=True, name=f"okay_step_{i}")

        class _BareCoroWorkflow(Workflow):
            def __init__(self, raise_on_failure):
                super().__init__()
                self._raise = raise_on_failure

            async def run(self, *args, **kwargs):
                for i in range(5):
                    if i == 3:
                        await self.run_async_step(
                            _explodes(), raise_on_failure=self._raise
                        )
                    await self.run_async_step(
                        _okay_step(i), raise_on_failure=self._raise
                    )

        result = await _BareCoroWorkflow(raise_on_failure)()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "ValueError"
        # steps 0-2 ran; the crash aborted before steps 3 and 4
        assert len(result.steps) == 3

    async def test_enveloped_crash_continues_without_raise(self):
        # the fourth quadrant: @task turns the crash into a failed step
        # envelope, and raise_on_failure=False lets the loop keep going
        @task(log_info=False)
        async def _explodes_enveloped():
            raise ValueError("boom")

        async def _okay_step(i):
            return OperationResult(ok=True, name=f"okay_step_{i}")

        class _EnvelopedCrashWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                for i in range(5):
                    if i == 3:
                        await self.run_async_step(
                            _explodes_enveloped(), raise_on_failure=False
                        )
                    await self.run_async_step(
                        _okay_step(i), raise_on_failure=False
                    )

        result = await _EnvelopedCrashWorkflow()()
        # all 5 okay steps ran, plus the failed envelope in between
        assert len(result.steps) == 6
        failed = [step for step in result.steps if not step.ok]
        assert len(failed) == 1
        assert failed[0].runtime_error.type == "ValueError"
        # the failure is recorded on the parent, but the workflow didn't crash
        assert result.ok is False
        assert result.runtime_error is None

    async def test_crashing_task_with_raise_stops_with_step_failure_message(self):
        # with @task the crash becomes a failed step envelope; the raise
        # then aborts the workflow as a controlled StepFailure — the parent
        # message says which step failed, runtime_error stays on the step
        flaky_step = _make_flaky_task(fail_times=99)

        class _CrashingStepWorkflow(Workflow):
            def __init__(self):
                super().__init__()
                self.continued_past_step = False

            async def run(self, *args, **kwargs):
                await self.run_async_step(flaky_step(), raise_on_failure=True)
                self.continued_past_step = True

        wf = _CrashingStepWorkflow()
        result = await wf()
        assert wf.continued_past_step is False
        assert result.ok is False
        assert result.runtime_error.type == "StepFailure"
        assert "Step failed" in result.runtime_error.message
        assert "flaky_step" in result.runtime_error.message
        # controlled abort: the crash details live on the step, not the parent
        assert result.runtime_error is not None
        assert result.steps[0].runtime_error.type == "ValueError"
        assert len(result.steps) == 1

    async def test_retry_loop_succeeds_on_third_attempt(self):
        # the retry owner runs attempts with raise_on_failure=False and,
        # on success, explicitly declares ok (a later success never clears
        # an earlier failure by itself — fail-closed contract)
        flaky_step = _make_flaky_task(fail_times=2)

        class _RetryWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                for _ in range(3):
                    step = await self.run_async_step(
                        flaky_step(), raise_on_failure=False
                    )
                    if step.ok:
                        self.result.ok = True
                        return

        result = await _RetryWorkflow()()
        assert result.ok is True
        assert len(result.steps) == 3
        assert [step.ok for step in result.steps] == [False, False, True]
        assert result.steps[2].response.output == "succeeded on attempt 3"
        # the failed attempts remain in the trail for forensics
        assert result.steps[0].runtime_error.type == "ValueError"


class TestAddStep:
    def test_rejects_non_operation_result(self):
        wf = _SuccessWorkflow()
        with pytest.raises(ValueError):
            wf.add_step("not a result")

    def test_aggregates_token_usage_across_steps(self):
        wf = _SuccessWorkflow()
        wf.add_step(
            OperationResult(
                ok=True,
                token_usage=TokenUsage(total=10, prompt=8, completion=2, cached=8),
            )
        )
        wf.add_step(
            OperationResult(
                ok=True,
                token_usage=TokenUsage(total=20, prompt=12, completion=8, cached=2),
            )
        )

        usage = wf.result.token_usage
        assert usage.total == 30
        assert usage.prompt == 20
        assert usage.completion == 10
        assert usage.cached == 10
        assert usage.cache_hit_rate == 0.5


class TestCancellation:
    async def test_cancellation_propagates_out_of_workflow(self):
        # a `return` inside __call__'s finally would swallow CancelledError
        # and let a dead request keep running — pin that it propagates
        class _SlowWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                await asyncio.sleep(30)

        task = asyncio.create_task(_SlowWorkflow()())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestSingleUseGuard:
    """One instance = one execution: self.result accumulates for the life
    of the instance, so a second __call__ would stack the new run's output
    onto the first's instead of replacing it. Guard against that mistake."""

    async def test_second_call_on_same_instance_raises(self):
        wf = _SuccessWorkflow()
        await wf()
        with pytest.raises(RuntimeError, match="single-use"):
            await wf()

    async def test_first_call_result_is_unaffected_by_the_rejected_second_call(self):
        wf = _SuccessWorkflow()
        first_result = await wf()
        with pytest.raises(RuntimeError):
            await wf()
        assert first_result.ok is True
        assert first_result.response.output == "done"

    async def test_guard_fires_even_after_a_failed_first_call(self):
        # a workflow that failed is still "used" — retries must construct a
        # new instance, not call the same one again
        wf = _ExceptionWorkflow()
        await wf()
        with pytest.raises(RuntimeError, match="single-use"):
            await wf()

    async def test_fresh_instance_is_unaffected(self):
        wf1 = _SuccessWorkflow()
        await wf1()
        wf2 = _SuccessWorkflow()
        result2 = await wf2()  # must not raise
        assert result2.ok is True


class TestWorkflowProperties:
    def test_workflow_ref_includes_class_name(self):
        wf = _SuccessWorkflow()
        assert "_SuccessWorkflow" in wf.workflow_ref

    def test_workflow_name_includes_class_name_and_id(self):
        wf = _SuccessWorkflow()
        assert "_SuccessWorkflow" in wf.workflow_name
        assert wf.result.id in wf.workflow_name
