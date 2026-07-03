from pydantic import BeforeValidator

def bounded_float(min_float: float, max_float: float) -> BeforeValidator:
    """Clamp a confidence-like float; 
    anything unusable falls back to min"""

    def validate(value):
        if not isinstance(value, (float, int)):
            return min_float
        if not (min_float <= value <= max_float):
            return min_float
        return float(value)

    return BeforeValidator(validate)

def bounded_string(
    max_length: int,
    fallback: str | None = None,
) -> BeforeValidator:
    """Coerce to a non-blank string capped at max_length. Non-strings are
    salvaged via str(); None/blank values become fallback. Short-but-real
    content passes through unchanged. With the default fallback=None the
    field behaves as optional (annotate it str | None)."""

    def validate(value):
        if value is None:
            return fallback
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if not value:
            return fallback
        if len(value) > max_length:
            return value[:max_length-3] + "..."
        return value

    return BeforeValidator(validate)