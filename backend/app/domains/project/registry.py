"""Project-domain registry: class tuples and node_type -> class lookup for
this domain only. app/registry.py composes this with the other domains'
registries plus the catalog and executor mapping — see that module for the
full picture.
"""

from app.domains.project.node_types import ProjectNodeTypeEnum
from app.domains.project.schemas.request_schemas import (
    FeedbackRequest,
    ProjectInfoRequest,
)

# FeedbackRequest is deliberately not in a CATALOG_TIERS class list (it's
# neither a retrieval nor an analyze step) — catalog_entries() in
# app/registry.py falls any class registered-but-untiered into an "Other
# supported actions" section, which fits an action node like this one.
PROJECT_RETRIEVAL_CLASSES = (
    ProjectInfoRequest,
)
PROJECT_REQUEST_CLASSES = (
    ProjectInfoRequest,
    FeedbackRequest,
)

# Manual node_type -> class lookup — add new mappings here
PROJECT_NODE_TYPE_TO_CLS: dict[str, type] = {
    ProjectNodeTypeEnum.PROJECT_INFO.value: ProjectInfoRequest,
    ProjectNodeTypeEnum.FEEDBACK.value: FeedbackRequest,
}
