"""Demo: pyright/mypy checking THIS project's own classes, not a toy example.
Both mistakes below are the same *shape* as real errors pyright found this
week when scanning the real codebase:
  1. OperationResult (common.operation) constructed with a wrong field type
     — mirrors two real bugs pyright found in db/ingestion/store.py
  2. A helper typed too broadly against BaseRequest, then reading a field
     (depends_on) that only exists on AnalyzeBaseRequest — mirrors the
     attribute-access errors pyright found throughout strategy_classification.py

Run:
    poetry run pyright playground.py
    mypy playground.py
    make playground   (executes it — see which mistakes crash and which don't)
"""
from common.operation import OperationResult
from app.domains.base_request import BaseRequest, AnalyzeBaseRequest
from app.domains.node_types import UnknownNodeTypeEnum


# --- 1. OperationResult: wrong field types ---------------------------------

good = OperationResult(ok=True, message="the intended shape")
print(f"good:   ok={good.ok!r} ({type(good.ok).__name__})")

# mistake A (pyright/mypy: reportArgumentType) — `ok` is declared `bool`.
# pydantic's lax validation silently coerces int 1 -> True, so this does
# NOT crash at runtime — it quietly does something you may not have meant.
sneaky = OperationResult(ok=1, message="int silently coerced to bool")
print(f"sneaky: ok={sneaky.ok!r} ({type(sneaky.ok).__name__})")

# mistake B (pyright/mypy: reportArgumentType) — `details` is declared
# `list[str]`. pydantic does NOT coerce a dict into a list, so this DOES
# raise at runtime. Caught here only so the rest of the file still runs.
try:
    OperationResult(details={"count": 5})
except Exception as e:
    print(f"bad:    raised {type(e).__name__} at runtime, as pyright warned")


# --- 2. BaseRequest vs AnalyzeBaseRequest: attribute not on the base -------

class _FakeAnalyze(AnalyzeBaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def get_dependency_ids(strategies: list[BaseRequest]) -> list[str]:
    """Typed to accept the common base — but depends_on only exists on
    AnalyzeBaseRequest, not BaseRequest. Works today because every caller
    happens to pass AnalyzeBaseRequest instances; pyright flags it because
    the signature promises more than the body actually supports."""
    ids: list[str] = []
    for strat in strategies:
        ids.extend(strat.depends_on)  # error: "depends_on" unknown on BaseRequest
    return ids


analyze_instance = _FakeAnalyze(
    id="task_1",
    depends_on=["task_2"],
    target_goal=["goal_a1b2c3d4"],
    description="A sufficiently long description for the demo",
    reasoning="A sufficiently long reasoning for the demo",
    confidence=0.9,
)
print(f"dependency ids: {get_dependency_ids([analyze_instance])}")  # runs fine -- for now
