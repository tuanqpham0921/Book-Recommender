from typing import Optional, Literal
from pydantic import Field
from app.domains.base_request import DomainRequest
from app.domains.project.schemas.filter_schemas import ProjectInfoField
from app.domains.project.node_types import ProjectNodeTypeEnum


class FeedbackRequest(DomainRequest):
    """Purpose: Record the user's feedback, opinion, bug report, or suggestion about this app itself.

    Args:
        contact_info: Optional contact info (email, phone, etc.) — fill only when
            the user volunteers it, for a possible follow-up.
        feedback: The user's feedback text.

    Returns: Confirmation that the feedback was recorded.

    Use when: the user is commenting on the app/planner/experience — "this
    recommendation tool is great", "the chat feels slow", "you should add X
    feature", "found a bug when I asked about...".

    Do not use: for reacting to a specific bad recommendation by wanting
    different books (that's a new recommendation request, not feedback), or
    asking questions about the project rather than commenting on it.

    Constraints: feedback is required text; contact_info is optional and must
    not be invented if the user didn't provide it.

    Example queries:
        - "this recommendation tool is great"
        - "the chat feels slow"
        - "you should add a dark mode"
        - "found a bug when I asked about sci-fi books"
    """

    node_type: Literal[ProjectNodeTypeEnum.FEEDBACK] = ProjectNodeTypeEnum.FEEDBACK
    # NOTE: good place to have a simple HITL (Human In The Loop) for feedback
    # something like awesome "can you please provide your email so we can get back to you? if not it's ok too"
    contact_info: Optional[str] = Field(
        default=None,
        json_schema_extra={"example": "user@example.com"},
    )
    feedback: str = Field(
        ..., json_schema_extra={"example": "The chat feels slow when comparing books."}
    )


class ProjectInfoRequest(DomainRequest):
    """Purpose: Retrieve information about the app, tech stack, architecture, or project metadata.

    Args:
        fields: One or more ProjectInfoField values to retrieve (name,
            description, technology_stack, project_url, project_github_url,
            project_github_repo_name, project_github_repo_url, all).

    Returns: The requested project metadata fields, rendered as a short
    description of the project.

    Use when: the user asks about the project itself — "what tech stack does
    this use", "what is this app", "where's the GitHub repo", "tell me about
    this project".

    Do not use: when the user is commenting on or critiquing the app rather
    than asking about it.

    Constraints: fields must come from ProjectInfoField; use "all" for a
    general "tell me about this project" ask.

    Example queries:
        - "what tech stack does this use"
        - "what is this app"
        - "where's the GitHub repo"
        - "tell me about this project"
    """

    node_type: Literal[ProjectNodeTypeEnum.PROJECT_INFO] = ProjectNodeTypeEnum.PROJECT_INFO
    fields: list[ProjectInfoField] = Field(
        ..., json_schema_extra={"example": ["technology_stack"]}
    )
