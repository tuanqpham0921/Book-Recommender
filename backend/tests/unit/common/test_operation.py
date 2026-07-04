import pytest
from common.operation import task, OperationResult, RuntimeErrorInfo


@task
async def _returns_plain_value():
    return "hello"


@task
async def _returns_custom_result():
    return OperationResult(ok=True, message="custom message", output="custom_output")


@task
async def _raises_value_error():
    raise ValueError("something went wrong")


@task
async def _returns_none():
    return None


class TestTask:
    async def test_plain_value_wraps_in_operation_result(self):
        result = await _returns_plain_value()
        assert isinstance(result, OperationResult)
        assert result.ok is True
        assert result.output == "hello"
        assert result.duration is not None
        assert result.name is not None

    async def test_passthrough_when_returns_operation_result(self):
        result = await _returns_custom_result()
        assert isinstance(result, OperationResult)
        assert result.ok is True
        assert result.message == "custom message"
        assert result.output == "custom_output"
        assert result.duration is not None

    async def test_captures_exception_as_failed_result(self):
        result = await _raises_value_error()
        assert isinstance(result, OperationResult)
        assert result.ok is False
        assert "something went wrong" in result.message
        assert result.runtime_error is not None
        assert result.duration is not None

    async def test_runtime_error_is_structured(self):
        result = await _raises_value_error()
        error = result.runtime_error
        assert isinstance(error, RuntimeErrorInfo)
        assert error.type == "ValueError"
        assert error.message == "something went wrong"
        assert "_raises_value_error" in error.traceback

    async def test_runtime_error_serializes_to_plain_dict(self):
        # the whole point of the structured record: it must survive
        # model_dump for DB persistence without arbitrary types
        result = await _raises_value_error()
        dumped = result.model_dump()
        assert dumped["runtime_error"]["type"] == "ValueError"
        assert dumped["runtime_error"]["message"] == "something went wrong"

    async def test_sets_function_name_on_result(self):
        result = await _returns_plain_value()
        assert "test_operation" in result.name
        assert "_returns_plain_value" in result.name

    async def test_none_return_produces_ok_result(self):
        result = await _returns_none()
        assert result.ok is True
        assert result.output is None


class TestOperationResult:
    def test_defaults(self):
        # fail-closed: an envelope is failed until someone declares success
        result = OperationResult()
        assert result.ok is False
        assert result.message is None
        assert result.steps == []
        assert result.output is None
        assert result.runtime_error is None
        assert result.duration is None
        assert result.id.startswith("op_")

    def test_check_output_type_passes_on_type_match(self):
        result = OperationResult(output="hello", output_type="str")
        result.check_output_type()  # must not raise

    def test_check_output_type_raises_on_type_mismatch(self):
        result = OperationResult(output=42, output_type="str")
        with pytest.raises(TypeError):
            result.check_output_type()

    def test_check_output_type_skips_when_output_is_none(self):
        result = OperationResult(output=None, output_type="str")
        result.check_output_type()  # must not raise

    def test_check_output_type_skips_when_output_type_is_none(self):
        result = OperationResult(output="hello", output_type=None)
        result.check_output_type()  # must not raise
