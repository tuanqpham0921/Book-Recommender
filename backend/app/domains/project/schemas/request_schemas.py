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
from app.domains.base_request import DomainRequest
from app.domains.project.schemas.filter_schemas import ProjectInfoField
from app.domains.project.node_types import ProjectNodeTypeEnum


class FeedbackRequest(DomainRequest):
    """user wants to send feedback about the project (feedback text, optional contact_info)"""

    node_type: Literal[ProjectNodeTypeEnum.FEEDBACK] = ProjectNodeTypeEnum.FEEDBACK
    # NOTE: good place to have a simple HITL (Human In The Loop) for feedback
    # something like awesome "can you please provide your email so we can get back to you? if not it's ok too"
    contact_info: Optional[str] = Field(
        default=None,
        description="Contact information of the user providing the feedback (email, phone, etc.)",
    )
    feedback: str = Field(..., description="User's feedback to the project")


class ProjectInfoRequest(DomainRequest):
    """request information about the app, tech stack, architecture, or project metadata (fields list)"""

    node_type: Literal[ProjectNodeTypeEnum.PROJECT_INFO] = ProjectNodeTypeEnum.PROJECT_INFO
    fields: list[ProjectInfoField] = Field(..., description="Fields to retrieve")
