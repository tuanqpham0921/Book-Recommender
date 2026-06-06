# Common utility functions for time operations
from datetime import datetime

from pytz import UTC


def now_iso():
    """Get the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()
