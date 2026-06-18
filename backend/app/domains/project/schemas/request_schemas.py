"""
Classification schemas for project domain strategies
Use for query the project's information or update the project's information database
Need semantic parsing in the chat to understand the project's request
manual or traditional project info update is going to be a standard endpoint instead

support query:
- Can you send a feedback to the project? (HITL)
- Can you tell me about the project?

Future Plan:
- support how many active user is using the system
- support how many active developers is using the system
- as an admin, add a new developer to the system giving access to admin capabilities
- as an admin, monitor how much total token is used by the system
- as an admin, what's the average response time of the system

This is where you can really incorperate the agentic capabilities to the system
so you can log in as an admin, or develop more advanced features to the system
"""

from typing import Optional, Literal
from pydantic import Field
from app.domains.base_request import BaseRequest
from enum import Enum
from app.domains.project.types import NodeType

class FeedbackRequest(BaseRequest):
    """Classification schema for Feedback request"""
    node_type: Literal[NodeType.FEEDBACK] = NodeType.FEEDBACK
    # NOTE: good place to have a simple HITL (Human In The Loop) for feedback
    # something like awesome "can you please provide your email so we can get back to you? if not it's ok too"
    contact_info: Optional[str] = Field(
        default=None,
        description="Contact information of the user providing the feedback (email, phone, etc.)",
    )
    feedback: str = Field(..., description="User's feedback to the project")

    def get_suffix(self) -> str:
        return "_feedback_req"

    def get_type(self) -> NodeType:
        return NodeType.FEEDBACK
    
class ProjectInfoField(str, Enum):
    NAME = "name"
    DESCRIPTION = "description"
    TECHNOLOGY_STACK = "technology_stack"
    PROJECT_URL = "project_url"
    PROJECT_GITHUB_URL = "project_github_url"
    PROJECT_GITHUB_REPO_NAME = "project_github_repo_name"
    PROJECT_GITHUB_REPO_URL = "project_github_repo_url"
    ALL = "all"
    
class ProjectInfoRequest(BaseRequest):
    """Classification schema for Project Info request"""
    node_type: Literal[NodeType.PROJECT_INFO] = NodeType.PROJECT_INFO
    fields: list[ProjectInfoField] = Field(..., description="Fields to update or retrieve")

    def get_suffix(self) -> str:
        return "_project_info_req"

    def get_type(self) -> NodeType:
        return NodeType.PROJECT_INFO