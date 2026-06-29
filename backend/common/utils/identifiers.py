# Common utility functions for time operations
from pytz import UTC
from datetime import datetime
import uuid


def now_iso():
    """Get the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


def uuid_8():
    return str(uuid.uuid4())[:8]
