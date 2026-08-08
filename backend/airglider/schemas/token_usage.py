
from pydantic import BaseModel, model_validator, Field

# NOTE: this should not be linked to others
# so airglider can be stand alone
from config.pricing import UNKNOWN_MODEL, cost_of

class ModelUsage(BaseModel):
    """Token counts attributable to a single model."""

    total: int = 0
    prompt: int = 0
    completion: int = 0

    # Subset of `prompt`; never additional tokens.
    cached: int = 0

    # Internal reasoning tokens used by the model. Subset of `completion`.
    reasoning_tokens: int = 0

    def __iadd__(self, other: "ModelUsage") -> "ModelUsage":
        self.total += other.total
        self.prompt += other.prompt
        self.completion += other.completion
        self.cached += other.cached
        self.reasoning_tokens += other.reasoning_tokens
        return self

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of prompt tokens served from the provider's cache.

        Lives here rather than on TokenUsage so each `by_model` bucket reports
        its own rate — the blended figure across models hides the differences
        that make it worth watching.
        """
        return self.cached / self.prompt if self.prompt else 0.0


class TokenUsage(ModelUsage):
    """Usage for one LLM call, or the roll-up of many.

    A *leaf* — what `OpenAIClient._extract_token_usage` builds — names its
    `model` and leaves `by_model` empty. Adding leaves together (see
    `OperationResult.add_step`) produces an *aggregate*: the flat counts still sum
    across everything, and `by_model` keeps the per-model split that the flat
    counts alone can't express once more than one model is in play.

    `cost_usd` and `unpriced_models` are stored fields rather than properties
    on purpose — `common.utils.to_serializable` walks `model_fields` and would
    drop computed ones, so a property would never reach the chat_runs JSONB.
    Both are recomputed on construction and after every `+=`.
    """

    model: str = ''
    by_model: dict[str, ModelUsage] = Field(default_factory=dict)

    # USD, priced at PRICES_CHECKED_ON rates and frozen into the run record.
    cost_usd: float = 0.0

    # Models that contributed tokens but carry no rate, so their spend is
    # missing from cost_usd. Empty is the healthy state.
    unpriced_models: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _price_on_build(self) -> "TokenUsage":
        self._reprice()
        return self

    def contributions(self) -> dict[str, ModelUsage]:
        """The per-model rows this usage contributes to a parent — its own
        counts if it's a leaf, otherwise the buckets it already aggregated.
        Handling both is what lets roll-ups nest to any depth."""
        if self.by_model:
            return self.by_model

        # TODO: Remove these compute them later(?)
        if self.total or self.prompt or self.completion:
            return {
                self.model or UNKNOWN_MODEL: ModelUsage(
                    total=self.total,
                    prompt=self.prompt,
                    completion=self.completion,
                    cached=self.cached,
                    reasoning_tokens=self.reasoning_tokens,
                )
            }

        return {}

    def _reprice(self) -> None:
        total = 0.0
        unpriced = []
        for model, usage in self.contributions().items():
            cost = cost_of(model, usage.prompt, usage.cached, usage.completion)
            if cost is None:
                unpriced.append(model)
            else:
                total += cost

        self.cost_usd = round(total, 6)
        self.unpriced_models = sorted(unpriced)

    def __iadd__(self, other: "TokenUsage") -> "TokenUsage":
        super().__iadd__(other)

        for model, usage in other.contributions().items():
            bucket = self.by_model.setdefault(model, ModelUsage())
            bucket += usage

        self._reprice()
        return self