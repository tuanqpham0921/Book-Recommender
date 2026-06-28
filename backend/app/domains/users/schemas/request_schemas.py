"""
Classification schemas for user domain strategies.
Use to query or update the user's information database.
Requires semantic parsing in the chat to understand the user's request.
Manual or traditional user info updates will be handled by a standard endpoint instead.

General Idea:
- Assistant: "What are your preferences for books? Are you a developer?"
- User: "I'm a developer / recruiter. I care more about the internal workings of the system."
- Tool: "Update user info to reflect the user's preferences."
- Assistant:
"Got it! I've remembered your background.
Now I can:
1. recommend books that are more relevant to you.
2. give you the developer information
3. give technology stack information or explain how the system is built

Let me know which direction you'd like to go.
"

Future Plan (agentic capabilities):
- support notifying developers who are interested in contributing to the project
- support reporting how many active users are using the system
- support reporting how many active developers are using the system
- as an admin, add a new developer to the system and grant them access to update their own information
"""

from typing import Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.users.schemas.filter_schema import DeveloperInfoEnum, UserInfoEnum
from app.domains.users.node_types import UserNodeTypeEnum


class UserInfoRequest(DomainRequest):
    """Get user information from the database."""

    node_type: Literal[UserNodeTypeEnum.USER_INFO] = UserNodeTypeEnum.USER_INFO
    field: list[UserInfoEnum] = Field(..., description="Field to retrieve")


class DeveloperInfoRequest(DomainRequest):
    """Get developer information from the database."""

    node_type: Literal[UserNodeTypeEnum.DEVELOPER_INFO] = UserNodeTypeEnum.DEVELOPER_INFO
    field: list[DeveloperInfoEnum] = Field(..., description="Field to retrieve")
