from .request_schemas import ProjectInfoRequest, FeedbackRequest
from typing import Union
ProjectRequest = Union[
    ProjectInfoRequest,
    FeedbackRequest,
]

__all__ = [
    "ProjectRequest",
]