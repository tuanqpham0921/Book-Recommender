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
