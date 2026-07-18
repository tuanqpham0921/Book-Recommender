from typing import Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.users.schemas.filter_schema import DeveloperInfoEnum, UserInfoEnum
from app.domains.users.node_types import UserNodeTypeEnum


class UserInfoRequest(DomainRequest):
    """Purpose: Retrieve information about the current user from the database.

    Args:
        field: One or more UserInfoEnum values to retrieve (name, age, bio,
            token_usage, saved_memory, previous_conversation,
            current_conversation).

    Returns: The requested user profile/session fields.

    Use when: the user asks about themselves — "what's my saved memory", "how
    many tokens have I used", "what's in my profile".

    Do not use: for questions about the developer/maintainer of the app, or
    about the project itself.

    Constraints: field values must come from UserInfoEnum.

    Example queries:
        - "what's my saved memory"
        - "how many tokens have I used"
        - "what's in my profile"
    """

    node_type: Literal[UserNodeTypeEnum.USER_INFO] = UserNodeTypeEnum.USER_INFO
    field: list[UserInfoEnum] = Field(
        ..., json_schema_extra={"example": ["saved_memory"]}
    )


class DeveloperInfoRequest(DomainRequest):
    """Purpose: Retrieve information about the developer/maintainer of this app.

    Args:
        field: One or more DeveloperInfoEnum values to retrieve (name, bio,
            email, linkedin_url).

    Returns: The requested developer profile fields.

    Use when: the user asks about who built the app — "who made this", "what's
    the developer's email", "link me their LinkedIn".

    Do not use: for questions about the user themselves, or about the
    project's tech/architecture.

    Constraints: field values must come from DeveloperInfoEnum.

    Example queries:
        - "who made this"
        - "what's the developer's email"
        - "link me their LinkedIn"
    """

    node_type: Literal[UserNodeTypeEnum.DEVELOPER_INFO] = UserNodeTypeEnum.DEVELOPER_INFO
    field: list[DeveloperInfoEnum] = Field(
        ..., json_schema_extra={"example": ["name", "linkedin_url"]}
    )
