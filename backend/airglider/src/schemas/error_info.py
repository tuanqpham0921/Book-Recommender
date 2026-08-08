import traceback
from pydantic import BaseModel

class RuntimeErrorInfo(BaseModel):
    """Serializable record of an unexpected exception — the error's type and
    message as first-class data for routing/aggregation, plus the formatted
    traceback for humans."""

    type: str
    message: str
    traceback: str

    @classmethod
    def from_exception(cls, e: BaseException) -> "RuntimeErrorInfo":
        return cls(
            type=type(e).__name__,
            message=str(e),
            traceback="".join(traceback.format_exception(e)),
        )