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

from typing import Optional, Literal
from pydantic import Field
from app.domains.base_request import BaseRequest
from enum import Enum

from app.domains.users.types import NodeType

class UserInfoEnum(str, Enum):
    NAME = "name"
    AGE = "age"
    BIO = "bio"
    TOKEN_USAGE = "token_usage"
    SAVED_MEMORY = "saved_memory"
    PREVIOUS_CONVERSATION = "previous_conversation"
    CURRENT_CONVERSATION = "current_conversation"

class UserInfoRequest(BaseRequest):
    """get user information from database"""
    node_type: Literal[NodeType.USER_INFO] = NodeType.USER_INFO
    field: list[UserInfoEnum] = Field(..., description="Field to retrieve")
    

class DeveloperInfoEnum(str, Enum):
    NAME = "name"
    BIO = "bio"
    EMAIL = "email"
    LINKEDIN_URL = "linkedin_url"
    
class DeveloperInfoRequest(BaseRequest):
    """get developer information from database"""
    node_type: Literal[NodeType.DEVELOPER_INFO] = NodeType.DEVELOPER_INFO
    field: list[DeveloperInfoEnum] = Field(..., description="Field to retrieve")