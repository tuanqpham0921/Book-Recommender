import asyncio

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


def _make_flaky_task(fail_times: int, **task_kwargs):
    """@task that raises on its first `fail_times` calls, then succeeds."""
    calls = {"count": 0}

    @task(log_info=False, **task_kwargs)
    async def flaky():
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise ValueError(f"attempt {calls['count']} failed")
        return f"succeeded on attempt {calls['count']}"

    return flaky


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

    async def test_default_retries_field_is_zero(self):
        # default retries=1 (no retry) — retries field counts attempts
        # consumed beyond the first, so a single-attempt call is 0
        result = await _raises_value_error()
        assert result.retries == 0


class TestTaskRetries:
    async def test_succeeds_after_retrying(self):
        flaky = _make_flaky_task(fail_times=2, retries=3)
        result = await flaky()
        assert result.ok is True
        assert result.output == "succeeded on attempt 3"
        assert result.retries == 2

    async def test_exhausts_retries_and_returns_failed_result(self):
        flaky = _make_flaky_task(fail_times=99, retries=3)
        result = await flaky()
        assert result.ok is False
        assert result.retries == 2
        assert result.runtime_error is not None
        assert result.runtime_error.type == "ValueError"

    async def test_retries_default_of_one_means_no_retry(self):
        # matches pre-existing behavior: retries defaults to 1 attempt total
        flaky = _make_flaky_task(fail_times=1)
        result = await flaky()
        assert result.ok is False
        assert result.retries == 0

    async def test_cancelled_error_is_never_retried(self):
        calls = {"count": 0}

        @task(log_info=False, retries=3)
        async def cancels():
            calls["count"] += 1
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await cancels()
        assert calls["count"] == 1


class TestTaskTimeout:
    async def test_default_timeout_is_none(self):
        @task(log_info=False)
        async def slow():
            await asyncio.sleep(0.01)
            return "done"

        result = await slow()
        assert result.ok is True
        assert result.output == "done"

    async def test_timeout_produces_failed_result(self):
        @task(log_info=False, timeout=0.01)
        async def slow():
            await asyncio.sleep(1)
            return "done"

        result = await slow()
        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "TimeoutError"

    async def test_timeout_retries_then_succeeds(self):
        calls = {"count": 0}

        @task(log_info=False, timeout=0.05, retries=2)
        async def slow_then_fast():
            calls["count"] += 1
            if calls["count"] == 1:
                await asyncio.sleep(1)
            return "done"

        result = await slow_then_fast()
        assert result.ok is True
        assert result.output == "done"
        assert result.retries == 1


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

    def test_check_output_type_raises_when_declared_but_missing(self):
        result = OperationResult(output=None, output_type="str")
        result.check_output_type()

    def test_check_output_type_raises_on_undeclared_output(self):
        result = OperationResult(output="hello", output_type=None)
        with pytest.raises(TypeError, match="without a declared output_type"):
            result.check_output_type()

    def test_check_output_type_skips_when_nothing_was_claimed(self):
        # failure envelopes legitimately carry neither output nor output_type
        result = OperationResult(output=None, output_type=None)
        result.check_output_type()  # must not raise
