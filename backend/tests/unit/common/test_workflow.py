import pytest
from common.workflow import Workflow
from common.operation import OperationResult


class _SuccessWorkflow(Workflow):
    async def run(self, *args, **kwargs):
        self.result.output = "done"
        self.result.message = "success"


class _ExceptionWorkflow(Workflow):
    async def run(self, *args, **kwargs):
        raise RuntimeError("workflow exploded")


class _StepWorkflow(Workflow):
    def __init__(self, step: OperationResult, raise_on_failure: bool = True):
        super().__init__()
        self._step = step
        self._raise = raise_on_failure

    async def run(self, *args, **kwargs):
        self.add_step(self._step, raise_on_failure=self._raise)


class _MultiStepWorkflow(Workflow):
    def __init__(self, steps: list[OperationResult]):
        super().__init__()
        self._steps = steps

    async def run(self, *args, **kwargs):
        for step in self._steps:
            self.add_step(step, raise_on_failure=False)

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
        assert result.run_time_error is not None

    async def test_exception_in_run_still_records_duration(self):
        result = await _ExceptionWorkflow()()
        assert result.duration is not None


class TestAddStep:
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

    async def test_failed_step_with_raise_records_run_time_error(self):
        step = OperationResult(ok=False, name="bad_step", message="bad")
        result = await _StepWorkflow(step, raise_on_failure=True)()
        assert result.ok is False
        assert result.run_time_error is not None

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


class TestRunStep:
    async def test_success_step_appended_to_steps(self):
        step = OperationResult(ok=True, name="my_sync_step")
        result = await _RunStepWorkflow(step)()
        assert result.ok is True
        assert len(result.steps) == 1
        assert result.steps[0].name == "my_sync_step"

    async def test_failed_step_sets_result_ok_false(self):
        step = OperationResult(ok=False, name="bad_step", message="bad")
        result = await _RunStepWorkflow(step, raise_on_failure=False)()
        assert result.ok is False

    async def test_failed_step_with_raise_records_run_time_error(self):
        step = OperationResult(ok=False, name="bad_step", message="bad")
        result = await _RunStepWorkflow(step, raise_on_failure=True)()
        assert result.ok is False
        assert result.run_time_error is not None


class TestWorkflowProperties:
    def test_workflow_ref_includes_class_name(self):
        wf = _SuccessWorkflow()
        assert "_SuccessWorkflow" in wf.workflow_ref

    def test_workflow_name_includes_class_name_and_id(self):
        wf = _SuccessWorkflow()
        assert "_SuccessWorkflow" in wf.workflow_name
        assert wf.result.id in wf.workflow_name
