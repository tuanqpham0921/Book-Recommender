"""Shared utility surface for the app.

The identity and serialization helpers now live in `airglider` — they are what
its record tree is built and persisted with, so the library owns them rather
than borrowing them from here. They are re-exported (not re-implemented) so
app code keeps importing them from one place and the two can never drift.
"""

from airglider import (
    now_iso,
    remove_empty_values,
    strip_zero_token_usage,
    to_serializable,
    uuid_8,
)

from .json_handler import print_json, load_json, save_file, save_text

__all__ = [
    "save_file",
    "save_text",
    "now_iso",
    "uuid_8",
    "print_json",
    "load_json",
    "remove_empty_values",
    "strip_zero_token_usage",
    "to_serializable",
]
