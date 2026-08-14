import asyncio

import pytest
from airglider import (
    OperationResult,
    Response,
    StepFailure,
    TokenUsage,
    Workflow,
    task,
)


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
        self.record.response.result = "done"
        # fail-closed contract: workflows must declare success explicitly
        self.record.ok = True


class _ExceptionWorkflow(Workflow):
    async def run(self, *args, **kwargs):
        raise RuntimeError("workflow exploded")


class _StepWorkflow(Workflow):
    """A hand-made envelope, attached explicitly.

    `_as_coro` is a plain coroutine, not a `@task`, so nothing published a scope
    for the step to adopt itself into — `add_step` is what that case always
    needed, and is all `run_async_step` ever added over a bare `await`.
    """

    def __init__(self, step: OperationResult, insist: bool = True):
        super().__init__()
        self._step = step
        self._insist = insist

    async def run(self, *args, **kwargs):
        step = await _as_coro(self._step)
        self.record.add_step(step)
        if self._insist:
            step.unwrap()
        # fail-closed contract: declare success only if the work succeeded
        if step.ok:
            self.record.ok = True


class _MultiStepWorkflow(Workflow):
    def __init__(self, steps: list[OperationResult], insist: bool = True):
        super().__init__()
        self._steps = steps
        self._insist = insist

    async def run(self, *args, **kwargs):
        for step in self._steps:
            attached = await _as_coro(step)
            self.record.add_step(attached)
            if self._insist:
                attached.unwrap()


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
                self.record.response.result = "done"
                self.record.ok = True

        result = await _UndeclaredOutput()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "TypeError"


class TestExplicitSteps:
    """Attaching an envelope produced outside any scope — the one thing
    `run_async_step` did that a bare `await` does not, now spelled `add_step`."""

    async def test_success_step_appended_to_steps(self):
        step = OperationResult(ok=True, name="my_step")
        result = await _StepWorkflow(step)()
        assert result.ok is True
        assert len(result.steps) == 1
        assert result.steps[0].name == "my_step"

    async def test_failed_step_leaves_the_workflow_not_ok(self):
        # nothing marks the parent: `ok` simply never gets declared, which is
        # the fail-closed default
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, insist=False)()
        assert result.ok is False

    async def test_insisting_names_the_step_in_details(self):
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, insist=True)()
        assert "FAILED STEP: bad_step" in result.details

    async def test_insisting_on_a_failed_step_is_a_controlled_abort(self):
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, insist=True)()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "StepFailure"
        assert "bad_step" in result.runtime_error.message

    async def test_failed_step_still_appended_when_not_insisting(self):
        step = OperationResult(ok=False, name="bad_step")
        result = await _StepWorkflow(step, insist=False)()
        assert len(result.steps) == 1

    async def test_multiple_steps_all_appended(self):
        steps = [
            OperationResult(ok=True, name="step_1"),
            OperationResult(ok=True, name="step_2"),
            OperationResult(ok=True, name="step_3"),
        ]
        result = await _MultiStepWorkflow(steps)()
        assert len(result.steps) == 3

    async def test_bad_step_does_not_stop_later_steps_when_not_insisting(self):
        steps = [
            OperationResult(ok=True, name="step_1"),
            OperationResult(ok=False, name="bad_step"),
            OperationResult(ok=True, name="step_3"),
        ]
        result = await _MultiStepWorkflow(steps, insist=False)()
        # a bare await says "I decide what a failure means": every step runs
        assert len(result.steps) == 3
        assert [step.ok for step in result.steps] == [True, False, True]

    async def test_bad_step_stops_later_steps_when_insisting(self):
        steps = [
            OperationResult(ok=True, name="step_1"),
            OperationResult(ok=False, name="bad_step"),
            OperationResult(ok=True, name="step_3"),
        ]
        result = await _MultiStepWorkflow(steps, insist=True)()
        assert len(result.steps) == 2
        assert [step.ok for step in result.steps] == [True, False]
        assert "FAILED STEP: bad_step" in result.details

    async def test_later_success_does_not_clear_an_earlier_failure(self):
        steps = [
            OperationResult(ok=False, name="bad_step"),
            OperationResult(ok=True, name="step_2"),
        ]
        result = await _MultiStepWorkflow(steps)()
        # the parent stays failed unless the workflow explicitly declares
        # success after handling the failure (fail-closed contract)
        assert result.ok is False
        assert "FAILED STEP: bad_step" in result.details


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
                await _explodes()

        result = await _BareCoroWorkflow()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "ValueError"
        assert result.steps == []

    async def test_unenveloped_coroutine_crash_still_have_previous_results(self):
        async def _explodes():
            raise ValueError("boom before any envelope")

        async def _okay_step(i):
            return OperationResult(ok=True, name=f"okay_step: {i}")

        class _BareCoroWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                for i in range(5):
                    if i == 3:
                        await _explodes()
                    self.record.add_step(await _okay_step(i))

        result = await _BareCoroWorkflow()()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "ValueError"
        assert len(result.steps) == 3

    async def test_enveloped_crash_continues_when_not_insisting(self):
        # @task turns the crash into a failed step envelope, and a bare await
        # lets the loop keep going
        @task(log_info=False)
        async def _explodes_enveloped():
            raise ValueError("boom")

        async def _okay_step(i):
            return OperationResult(ok=True, name=f"okay_step_{i}")

        class _EnvelopedCrashWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                for i in range(5):
                    if i == 3:
                        await _explodes_enveloped()
                    self.record.add_step(await _okay_step(i))

        result = await _EnvelopedCrashWorkflow()()
        # all 5 okay steps ran, plus the failed envelope in between
        assert len(result.steps) == 6
        failed = [step for step in result.steps if not step.ok]
        assert len(failed) == 1
        assert failed[0].runtime_error.type == "ValueError"
        # the workflow itself never crashed, and never declared success either
        assert result.ok is False
        assert result.runtime_error is None

    async def test_retry_loop_succeeds_on_third_attempt(self):
        # the case that motivated splitting awaiting from the failure policy:
        # the retry owner awaits bare and, on success, explicitly declares ok
        # (a later success never clears an earlier failure by itself)
        flaky_step = _make_flaky_task(fail_times=2)

        class _RetryWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                for _ in range(3):
                    step = await flaky_step()
                    if step.ok:
                        self.record.ok = True
                        return

        result = await _RetryWorkflow()()
        assert result.ok is True
        assert len(result.steps) == 3
        assert [step.ok for step in result.steps] == [False, False, True]
        assert result.steps[2].result == "succeeded on attempt 3"
        # the failed attempts remain in the trail for forensics
        assert result.steps[0].runtime_error.type == "ValueError"


class TestUnwrap:
    """`unwrap` is the payload-or-stop verb, usable from a `@task` as well as a
    `Workflow` — which is what moving the `StepFailure` branch into
    `record_span` bought."""

    def test_returns_the_payload_when_ok(self):
        step = OperationResult(ok=True, name="good", response=Response(result=42))
        assert step.unwrap() == 42

    def test_raises_step_failure_naming_the_step(self):
        step = OperationResult(ok=False, name="bad_step")
        with pytest.raises(StepFailure, match="bad_step"):
            step.unwrap()

    def test_names_the_anomaly_when_not_ok_without_a_crash(self):
        # ok means "ran to completion", so not-ok with no runtime_error is a bug
        # in the step — the message has to say so, or the caller stops with
        # nothing underneath it explaining why
        step = OperationResult(ok=False, name="bad_step")
        with pytest.raises(StepFailure, match="no runtime error recorded"):
            step.unwrap()

    async def test_stops_a_workflow_and_records_the_failed_step(self):
        flaky_step = _make_flaky_task(fail_times=99)

        class _UnwrapWorkflow(Workflow):
            def __init__(self):
                super().__init__()
                self.continued_past_step = False

            async def run(self, *args, **kwargs):
                (await flaky_step()).unwrap()
                self.continued_past_step = True

        wf = _UnwrapWorkflow()
        result = await wf()
        assert wf.continued_past_step is False
        assert result.ok is False
        assert result.runtime_error.type == "StepFailure"
        assert "flaky_step" in result.runtime_error.message
        # the caller says which step; the crash itself stays on that step
        assert "FAILED STEP: " in "".join(result.details)
        assert result.steps[0].runtime_error.type == "ValueError"

    async def test_stops_a_task_the_same_way_as_a_workflow(self):
        # the point of moving StepFailure into record_span: which decorator a
        # unit of work happens to use is not a fact about the failure
        flaky_step = _make_flaky_task(fail_times=99)

        @task(log_info=False)
        async def outer():
            (await flaky_step()).unwrap()
            return "never reached"

        result = await outer()
        assert result.ok is False
        assert result.result is None
        assert result.runtime_error.type == "StepFailure"
        assert "flaky_step" in result.runtime_error.message
        assert result.steps[0].runtime_error.type == "ValueError"

    async def test_propagates_up_a_chain_of_unwraps(self):
        # each level stops naming the level below; only the innermost carries
        # the original exception
        flaky_step = _make_flaky_task(fail_times=99)

        @task(log_info=False)
        async def middle():
            (await flaky_step()).unwrap()

        @task(log_info=False)
        async def outer():
            (await middle()).unwrap()

        result = await outer()
        assert result.runtime_error.type == "StepFailure"
        assert "middle" in result.runtime_error.message
        assert result.steps[0].runtime_error.type == "StepFailure"
        assert result.steps[0].steps[0].runtime_error.type == "ValueError"

    async def test_a_caller_may_still_inspect_instead_of_unwrapping(self):
        # plain await is the other verb — the envelope comes back and the
        # caller decides what a failure means
        flaky_step = _make_flaky_task(fail_times=99)

        class _InspectWorkflow(Workflow):
            async def run(self, *args, **kwargs):
                step = await flaky_step()
                if not step.ok:
                    self.add_details("handled it myself")
                self.record.ok = True

        result = await _InspectWorkflow()()
        assert result.ok is True
        assert result.runtime_error is None
        assert "handled it myself" in result.details
        assert result.steps[0].ok is False


class TestAddStep:
    # add_step lives on OperationResult, not Workflow — a workflow reaches it
    # through the envelope it owns (self.record), same as add_details
    def test_rejects_non_operation_result(self):
        wf = _SuccessWorkflow()
        with pytest.raises(ValueError):
            wf.record.add_step("not a result")

    def test_aggregates_token_usage_across_steps(self):
        wf = _SuccessWorkflow()
        wf.record.add_step(
            OperationResult(
                ok=True,
                token_usage=TokenUsage(total=10, prompt=8, completion=2, cached=8),
            )
        )
        wf.record.add_step(
            OperationResult(
                ok=True,
                token_usage=TokenUsage(total=20, prompt=12, completion=8, cached=2),
            )
        )

        usage = wf.record.token_usage
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
    """One instance = one execution: self.record accumulates for the life
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
        assert first_result.result == "done"

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
        assert wf.record.id in wf.workflow_name
