"""
Classification schemas for project domain strategies.
Use to query or update the project's information database.
Requires semantic parsing in the chat to understand the user's request.
Manual or traditional project info updates will be handled by a standard endpoint instead.

Supported queries:
- Can you send feedback about the project? (HITL)
- Can you tell me about the project?

Future Plan:
- support reporting how many active users are using the system
- support reporting how many active developers are using the system
- as an admin, add a new developer to the system and grant them admin capabilities
- as an admin, monitor total token usage by the system
- as an admin, report the average response time of the system

This is where you can really incorporate agentic capabilities into the system —
log in as an admin or develop more advanced features.
"""

from typing import Optional, Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.project.schemas.filter_schemas import ProjectInfoField
from app.domains.project.node_types import ProjectNodeTypeEnum


class FeedbackRequest(DomainRequest):
    """User wants to send feedback about the project (feedback text, optional contact_info)."""

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
