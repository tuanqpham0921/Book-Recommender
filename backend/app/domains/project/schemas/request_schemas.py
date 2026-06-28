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
