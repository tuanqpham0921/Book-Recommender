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

from typing import Optional, Literal, List
from uuid import uuid4
from pydantic import Field
from app.domains.base_request import BaseRequest
from enum import Enum

from app.domains.users.types import NodeType

class UserInfoAction(str, Enum):
    GET = "get"
    UPDATE = "update"

class UserInfoEnum(str, Enum):
    NAME = "name"
    AGE = "age"
    BIO = "bio"
    TOKEN_USAGE = "token_usage"
    SAVED_MEMORY = "saved_memory"
    PREVIOUS_CONVERSATION = "previous_conversation"
    CURRENT_CONVERSATION = "current_conversation"
    ALL = "all"

class UserInfoRequest(BaseRequest):
    """Classification schema for User Info request"""
    node_type: Literal[NodeType.USER_INFO] = NodeType.USER_INFO
    action: UserInfoAction = Field(..., description="Action to perform on user info")
    field: UserInfoEnum = Field(..., description="Field to update or retrieve")
    # value: Optional[str] = Field(..., description="Value to update or retrieve")
    
    def model_post_init(self, __context) -> None:
        if not self.refusal:
            base_id = str(uuid4())[:8]
            self.id = base_id + "_usr_req"
        super().model_post_init(__context)
    
    def get_type(self) -> NodeType:
        return NodeType.USER_INFO

class DeveloperInfoEnum(str, Enum):
    NAME = "name"
    BIO = "bio"
    EMAIL = "email"
    LINKEDIN_URL = "linkedin_url"
    ALL = "all"
    

class DeveloperInfoRequest(BaseRequest):
    """Classification schema for Developer Info request"""
    node_type: Literal[NodeType.DEVELOPER_INFO] = NodeType.DEVELOPER_INFO
    action: UserInfoAction = Field(..., description="Action to perform on user info")

    field: DeveloperInfoEnum = Field(..., description="Field to update or retrieve")
    # value: Optional[str] = Field(..., description="Value to update or retrieve")
    
    def model_post_init(self, __context) -> None:
        if not self.refusal:
            base_id = str(uuid4())[:8]
            self.id = base_id + "_dev_req"
        super().model_post_init(__context)
    
    def get_type(self) -> NodeType:
        return NodeType.DEVELOPER_INFO