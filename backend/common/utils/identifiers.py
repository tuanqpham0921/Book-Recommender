# Common utility functions for time operations
from pytz import UTC
from datetime import datetime
import uuid


def now_iso() -> str:
    """Get the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


def uuid_8() -> str:
    return str(uuid.uuid4())[:8]
