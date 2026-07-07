from typing import Optional, Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.project.schemas.filter_schemas import ProjectInfoField
from app.domains.project.node_types import ProjectNodeTypeEnum


class FeedbackRequest(DomainRequest):
    """Send the user's feedback about this app to the developer.

    Use when the user addresses the app or its builder with praise, complaints,
    or suggestions: "great app!", "tell the developer the compare feature is my
    favourite", "this could be faster".
    Not for: opinions about books (those are just conversation) or questions
    about the developer (Retrieve_Developer_Info).
    """

    node_type: Literal[ProjectNodeTypeEnum.FEEDBACK] = ProjectNodeTypeEnum.FEEDBACK
    # NOTE: good place to have a simple HITL (Human In The Loop) for feedback
    # something like awesome "can you please provide your email so we can get back to you? if not it's ok too"
    contact_info: Optional[str] = Field(
        default=None,
        description="Contact information of the user providing the feedback (email, phone, etc.)",
    )
    feedback: str = Field(..., description="User's feedback to the project")


class ProjectInfoRequest(DomainRequest):
    """Retrieve information about this app — what it is, its tech stack, and links.

    Use for questions about the project itself: "tell me about this app",
    "what's it built with", "where's the GitHub repo".
    Not for: facts about its developer as a person (Retrieve_Developer_Info).
    """

    node_type: Literal[ProjectNodeTypeEnum.PROJECT_INFO] = ProjectNodeTypeEnum.PROJECT_INFO
    fields: list[ProjectInfoField] = Field(..., description="Fields to retrieve")
