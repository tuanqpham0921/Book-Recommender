from .request_schemas import UserInfoRequest, DeveloperInfoRequest
from typing import Union


UserRequest = Union[
    UserInfoRequest,
    DeveloperInfoRequest,
]

__all__ = [
    "UserRequest",
]