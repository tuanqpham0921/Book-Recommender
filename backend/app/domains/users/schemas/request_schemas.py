from typing import Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.users.schemas.filter_schema import DeveloperInfoEnum, UserInfoEnum
from app.domains.users.node_types import UserNodeTypeEnum


class UserInfoRequest(DomainRequest):
    """Retrieve the current user's account data — profile, usage, memory, history.

    Use for "my" questions about the account: "my token usage", "what do you
    remember about me", "my previous conversations".
    Not for: the user's shelf of books (Retrieve_Reading_List /
    Retrieve_Reading_Stats) or info about the app's developer
    (Retrieve_Developer_Info).
    """

    node_type: Literal[UserNodeTypeEnum.USER_INFO] = UserNodeTypeEnum.USER_INFO
    field: list[UserInfoEnum] = Field(..., description="Fields to retrieve")


class DeveloperInfoRequest(DomainRequest):
    """Retrieve facts about the person who built this app — name, bio, contact links.

    Use for "who made this" questions: "who is the developer", "what's their
    LinkedIn/email".
    Not for: facts about book authors (Retrieve_Author_Info) or the app itself
    (Retrieve_Project_Info).
    """

    node_type: Literal[UserNodeTypeEnum.DEVELOPER_INFO] = UserNodeTypeEnum.DEVELOPER_INFO
    field: list[DeveloperInfoEnum] = Field(..., description="Fields to retrieve")
