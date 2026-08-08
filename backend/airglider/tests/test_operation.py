import pytest
from airglider import task, OperationResult, Response, RuntimeErrorInfo, TokenUsage
from airglider import to_serializable
from airglider import MODEL_PRICES, PER_MILLION, UNKNOWN_MODEL


@task
async def _returns_plain_value():
    return "hello"


@task
async def _returns_custom_result():
    return OperationResult(ok=True, response=Response(result="custom_output"))


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
        assert result.result == "hello"
        assert result.timing.duration is not None
        assert result.name is not None

    async def test_passthrough_when_returns_operation_result(self):
        result = await _returns_custom_result()
        assert isinstance(result, OperationResult)
        assert result.ok is True
        assert result.result == "custom_output"
        assert result.timing.duration is not None

    async def test_captures_exception_as_failed_result(self):
        result = await _raises_value_error()
        assert isinstance(result, OperationResult)
        assert result.ok is False
        assert result.runtime_error is not None
        assert "something went wrong" in result.runtime_error.message
        assert result.timing.duration is not None

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
        assert result.result is None


class TestTokenUsage:
    def test_defaults_to_zero(self):
        usage = TokenUsage()
        assert usage.total == 0
        assert usage.prompt == 0
        assert usage.completion == 0
        assert usage.cached == 0

    def test_iadd_sums_all_fields(self):
        usage = TokenUsage(total=10, prompt=7, completion=3, cached=4)
        usage += TokenUsage(total=20, prompt=15, completion=5, cached=10)

        assert usage.total == 30
        assert usage.prompt == 22
        assert usage.completion == 8
        assert usage.cached == 14

    def test_cache_hit_rate(self):
        usage = TokenUsage(total=10, prompt=8, completion=2, cached=6)
        assert usage.cache_hit_rate == 6 / 8

    def test_cache_hit_rate_zero_prompt_is_zero_not_error(self):
        assert TokenUsage().cache_hit_rate == 0.0

    def test_cache_hit_rate_recomputes_after_aggregation(self):
        # rates don't add — the property must reflect the summed counts
        usage = TokenUsage(prompt=100, cached=100)  # 1.0 alone
        usage += TokenUsage(prompt=100, cached=0)  # 0.0 alone

        assert usage.cache_hit_rate == 0.5

    def test_cached_survives_model_dump(self):
        # the serialized form is what lands in the chat_runs planner JSONB
        dumped = TokenUsage(total=10, prompt=8, completion=2, cached=6).model_dump()
        assert dumped["cached"] == 6


class TestCostAttribution:
    """Per-model spend must survive the roll-up from call -> workflow -> run."""

    def test_leaf_prices_itself(self):
        usage = TokenUsage(model="gpt-4.1-mini", prompt=1_000_000, completion=0)
        assert usage.cost_usd == MODEL_PRICES["gpt-4.1-mini"].input

    def test_cached_prompt_tokens_billed_at_the_cheaper_rate(self):
        price = MODEL_PRICES["gpt-4.1-mini"]
        full = TokenUsage(model="gpt-4.1-mini", prompt=1_000_000)
        half = TokenUsage(model="gpt-4.1-mini", prompt=1_000_000, cached=500_000)

        assert full.cost_usd == price.input
        assert half.cost_usd == round((price.input + price.cached_input) / 2, 6)

    def test_reasoning_tokens_are_not_billed_on_top_of_completion(self):
        # reasoning is a subset of completion, so it must not add cost
        plain = TokenUsage(model="gpt-5-nano", completion=1000)
        thinking = TokenUsage(model="gpt-5-nano", completion=1000, reasoning_tokens=800)
        assert plain.cost_usd == thinking.cost_usd

    def test_iadd_splits_spend_by_model(self):
        roll = TokenUsage()
        roll += TokenUsage(model="gpt-4.1-mini", total=100, prompt=80, completion=20)
        roll += TokenUsage(model="gpt-5-nano", total=50, prompt=40, completion=10)

        assert set(roll.by_model) == {"gpt-4.1-mini", "gpt-5-nano"}
        assert roll.by_model["gpt-4.1-mini"].prompt == 80
        assert roll.by_model["gpt-5-nano"].prompt == 40
        assert roll.total == 150

    def test_cost_is_the_sum_of_its_models(self):
        a = TokenUsage(model="gpt-4.1-mini", total=100, prompt=80, completion=20)
        b = TokenUsage(model="gpt-5-nano", total=50, prompt=40, completion=10)

        roll = TokenUsage()
        roll += a
        roll += b

        assert roll.cost_usd == round(a.cost_usd + b.cost_usd, 6)

    def test_nested_rollup_does_not_double_count(self):
        # PlannerWorkflow merging a child workflow merges buckets, not calls
        child = TokenUsage()
        child += TokenUsage(model="gpt-4.1-mini", total=100, prompt=80, completion=20)

        parent = TokenUsage()
        parent += child

        assert parent.total == child.total
        assert parent.cost_usd == child.cost_usd
        assert parent.by_model["gpt-4.1-mini"].prompt == 80

    def test_same_model_twice_accumulates_into_one_bucket(self):
        roll = TokenUsage()
        roll += TokenUsage(model="gpt-5-nano", total=10, prompt=8, completion=2)
        roll += TokenUsage(model="gpt-5-nano", total=10, prompt=8, completion=2)

        assert list(roll.by_model) == ["gpt-5-nano"]
        assert roll.by_model["gpt-5-nano"].total == 20

    def test_longer_model_name_wins_over_a_prefix_of_it(self):
        # "gpt-4.1" is a prefix of "gpt-4.1-mini" but 5x the rate — matching
        # the shorter one would quintuple every mini run's reported cost
        mini = TokenUsage(model="gpt-4.1-mini", prompt=1_000_000)
        full = TokenUsage(model="gpt-4.1", prompt=1_000_000)

        assert mini.cost_usd == MODEL_PRICES["gpt-4.1-mini"].input
        assert full.cost_usd == MODEL_PRICES["gpt-4.1"].input
        assert mini.cost_usd != full.cost_usd

    def test_dated_snapshot_model_resolves_to_base_rate(self):
        pinned = TokenUsage(model="gpt-4.1-mini-2025-04-14", prompt=1_000_000)
        assert pinned.cost_usd == MODEL_PRICES["gpt-4.1-mini"].input
        assert pinned.unpriced_models == []

    def test_unpriced_model_is_flagged_not_silently_free(self):
        usage = TokenUsage(model="gpt-9-omega", total=100, prompt=80, completion=20)

        assert usage.cost_usd == 0.0
        assert usage.unpriced_models == ["gpt-9-omega"]

    def test_usage_without_a_model_is_bucketed_not_dropped(self):
        # otherwise per-model counts would silently stop summing to the total
        roll = TokenUsage()
        roll += TokenUsage(total=100, prompt=80, completion=20)

        assert roll.by_model[UNKNOWN_MODEL].total == 100
        assert roll.unpriced_models == [UNKNOWN_MODEL]

    def test_empty_usage_creates_no_buckets(self):
        roll = TokenUsage()
        roll += TokenUsage()

        assert roll.by_model == {}
        assert roll.cost_usd == 0.0
        assert roll.unpriced_models == []

    def test_each_model_reports_its_own_cache_hit_rate(self):
        # the blended rate on the parent hides per-model differences, which is
        # why cache_hit_rate sits on ModelUsage rather than on TokenUsage
        roll = TokenUsage()
        roll += TokenUsage(model="gpt-4.1-mini", prompt=100, cached=90)
        roll += TokenUsage(model="gpt-5-nano", prompt=100, cached=10)

        assert roll.by_model["gpt-4.1-mini"].cache_hit_rate == 0.9
        assert roll.by_model["gpt-5-nano"].cache_hit_rate == 0.1
        assert roll.cache_hit_rate == 0.5

    def test_cost_survives_to_serializable(self):
        # to_serializable walks model_fields and drops computed ones, so cost
        # has to be a real field or it never reaches the chat_runs JSONB
        roll = TokenUsage()
        roll += TokenUsage(model="gpt-4.1-mini", total=100, prompt=80, completion=20)

        dumped = to_serializable(roll)
        assert dumped["cost_usd"] == roll.cost_usd
        assert dumped["by_model"]["gpt-4.1-mini"]["prompt"] == 80


class TestOperationResult:
    def test_defaults(self):
        # fail-closed: an envelope is failed until someone declares success
        result = OperationResult()
        assert result.ok is False
        assert result.steps == []
        assert result.result is None
        assert result.runtime_error is None
        assert result.timing.duration is None
        assert result.id.startswith("op_")

    def test_check_output_type_passes_on_type_match(self):
        result = OperationResult(response=Response(result="hello", output_type="str"))
        result.check_output_type()  # must not raise

    def test_check_output_type_raises_on_type_mismatch(self):
        result = OperationResult(response=Response(result=42, output_type="str"))
        with pytest.raises(TypeError):
            result.check_output_type()

    def test_check_output_type_raises_when_declared_but_missing(self):
        result = OperationResult(response=Response(result=None, output_type="str"))
        result.check_output_type()

    def test_check_output_type_raises_on_undeclared_output(self):
        result = OperationResult(response=Response(result="hello", output_type=None))
        with pytest.raises(TypeError, match="without a declared output_type"):
            result.check_output_type()

    def test_check_output_type_skips_when_nothing_was_claimed(self):
        # failure envelopes legitimately carry neither output nor output_type
        result = OperationResult(response=Response(result=None, output_type=None))
        result.check_output_type()  # must not raise
