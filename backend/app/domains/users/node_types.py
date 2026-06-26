from enum import Enum


class UserNodeTypeEnum(str, Enum):
    # User Info
    USER_INFO = "Retrieve_User_Info"
    DEVELOPER_INFO = "Retrieve_Developer_Info"
