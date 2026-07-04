import asyncio

import pytest
from common.workflow import Workflow, StepFailure
from common.operation import OperationResult


async def _as_coro(step: OperationResult) -> OperationResult:
    return step


class _SuccessWorkflow(Workflow):
    def __init__(self):
        # producing output requires declaring its type (check_output_type)
        super().__init__(output_type=str)

    async def run(self, *args, **kwargs):
        self.result.output = "done"
        self.result.message = "success"
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
    def __init__(self, steps: list[OperationResult]):
        super().__init__()
        self._steps = steps

    async def run(self, *args, **kwargs):
        for step in self._steps:
            await self.run_async_step(_as_coro(step), raise_on_failure=False)


class TestWorkflowExecution:
    async def test_successful_run_sets_ok_true(self):
        result = await _SuccessWorkflow()()
        assert result.ok is True

    async def test_successful_run_records_duration(self):
        result = await _SuccessWorkflow()()
        assert result.duration is not None
        assert result.duration >= 0

    async def test_exception_in_run_sets_ok_false(self):
        result = await _ExceptionWorkflow()()
        assert result.ok is False
        assert "workflow exploded" in result.message
        assert result.runtime_error is not None

    async def test_exception_in_run_still_records_duration(self):
        result = await _ExceptionWorkflow()()
        assert result.duration is not None

    async def test_undeclared_output_fails_the_workflow(self):
        # producing output without declaring output_type is a contract
        # violation caught by check_output_type after run()
        class _UndeclaredOutput(Workflow):
            async def run(self, *args, **kwargs):
                self.result.output = "done"
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
        step = OperationResult(ok=False, name="bad_step", message="bad")
        result = await _StepWorkflow(step, raise_on_failure=False)()
        assert result.ok is False

    async def test_failed_step_sets_informative_message(self):
        step = OperationResult(ok=False, name="bad_step", message="bad")
        result = await _StepWorkflow(step, raise_on_failure=False)()
        assert "bad_step" in result.message
        assert "bad" in result.message

    async def test_failed_step_with_raise_is_a_controlled_abort(self):
        # StepFailure is control flow, not a crash: the parent envelope must
        # NOT carry runtime_error — the step's own envelope has the details
        step = OperationResult(ok=False, name="bad_step", message="bad")
        result = await _StepWorkflow(step, raise_on_failure=True)()
        assert result.ok is False
        assert result.runtime_error is None
        assert "bad_step" in result.message

    async def test_failed_step_without_raise_still_appended(self):
        step = OperationResult(ok=False, name="bad_step", message="bad")
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


class TestAddStep:
    def test_rejects_non_operation_result(self):
        wf = _SuccessWorkflow()
        with pytest.raises(ValueError):
            wf.add_step("not a result")


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


class TestWorkflowProperties:
    def test_workflow_ref_includes_class_name(self):
        wf = _SuccessWorkflow()
        assert "_SuccessWorkflow" in wf.workflow_ref

    def test_workflow_name_includes_class_name_and_id(self):
        wf = _SuccessWorkflow()
        assert "_SuccessWorkflow" in wf.workflow_name
        assert wf.result.id in wf.workflow_name
