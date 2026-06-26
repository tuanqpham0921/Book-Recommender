"""
Classification schemas for user domain strategies
Use for query the user's information or update the user's information database
Need semantic parsing in the chat to understand the user's request
manual or traditional user info update is going to be a standard endpoint instead

General Idea:
- Assistant: "What is your preferences for books? are you a developer?"
- User: "I'm a developer / recruiter. I care more about the internal working of the system"
- Tool: "Update user info to reflect the user's preferences"
- Assistant:
"Got it! I've remembered your background.
Now I can:
1. recommend books that are more relevant to you.
2. give you the developer information
3. give technology stack information or how the system is built

Let me know what way you want to go.
"

Future Plan (agentic capabilities):
- support send the developer I'm intersted in contributing to the project
- support how many active user is using the system
- support how many active developers is using the system
- as an admin, add a new developer to the system giving them access to update their own information
"""

from typing import Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.users.schemas.filter_schema import DeveloperInfoEnum, UserInfoEnum
from app.domains.users.node_types import UserNodeTypeEnum


class UserInfoRequest(DomainRequest):
    """get user information from database"""

    node_type: Literal[UserNodeTypeEnum.USER_INFO] = UserNodeTypeEnum.USER_INFO
    field: list[UserInfoEnum] = Field(..., description="Field to retrieve")


class DeveloperInfoRequest(DomainRequest):
    """get developer information from database"""

    node_type: Literal[UserNodeTypeEnum.DEVELOPER_INFO] = UserNodeTypeEnum.DEVELOPER_INFO
    field: list[DeveloperInfoEnum] = Field(..., description="Field to retrieve")
