from dataclasses import dataclass, asdict
import json
from pydantic import BaseModel, PrivateAttr


# ── Shared inner types ────────────────────────────────────────────────────────

@dataclass
class DataclassInner:
    title: str | None
    rating: float


class PydanticInner(BaseModel):
    title: str | None
    rating: float


# ── Pydantic outer containing a dataclass ─────────────────────────────────────

class PydanticOuter(BaseModel):
    name: str | None
    score: int
    book: DataclassInner          # pydantic wrapping a dataclass
    _cache: dict = PrivateAttr(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def set_cache(self, key: str, value: str) -> None:
        self._cache[key] = value

    def get_cache(self) -> dict:
        return self._cache


# ── Dataclass outer containing a pydantic model ───────────────────────────────

@dataclass
class DataclassOuter:
    name: str | None
    score: int
    book: PydanticInner           # dataclass wrapping a pydantic model


# ── Demo ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # --- Pydantic outer with dataclass inner (None + zero) ---
    pydantic_obj = PydanticOuter(
        name=None,
        score=0,
        book=DataclassInner(title="Dune", rating=0.0),
    )
    pydantic_obj.set_cache("last_seen", "2026-06-29")

    def exclude_zeros(d: dict) -> dict:
        return {k: v for k, v in d.items() if v != 0 and v != 0.0}

    print("=== Pydantic (contains dataclass) ===")
    print("default           :", pydantic_obj.model_dump())
    print("exclude_none      :", pydantic_obj.model_dump(exclude_none=True))
    print("exclude_defaults  :", pydantic_obj.model_dump(exclude_defaults=True))
    print("exclude_unset     :", pydantic_obj.model_dump(exclude_unset=True))
    print("exclude zeros*    :", exclude_zeros(pydantic_obj.model_dump()))
    print("private _cache    :", pydantic_obj.get_cache())
    print("_cache in dump?   :", "_cache" in pydantic_obj.model_dump())

    print()

    # --- Dataclass outer with pydantic inner (None + zero) ---
    dc_obj = DataclassOuter(
        name=None,
        score=0,
        book=PydanticInner(title=None, rating=0.0),
    )

    print("=== Dataclass (contains pydantic) ===")
    raw = asdict(dc_obj)
    # asdict() does NOT recurse into pydantic models — leaves them as objects
    print("asdict()          :", raw)

    # Fix: custom encoder that calls .model_dump() on pydantic models
    def encoder(obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        raise TypeError(f"not serializable: {type(obj)}")

    print("json.dumps()      :", json.dumps(raw, default=encoder))
