from enum import Enum

class Role(str, Enum):
    SYSTEM    = "system"
    USER      = "user"
    ASSISTANT = "assistant"
    TOOL      = "tool"

class GenreEnum(str, Enum):
    FICTION    = "fiction"
    NONFICTION = "non-fiction"