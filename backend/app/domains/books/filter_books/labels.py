from enum import Enum


class FilterRetrievalNodeTypeEnum(str, Enum):
    """The planner-facing name for this node. One member: the request. The
    output and executor classes are reached through the slice's NodeSpec, so
    they need no string label of their own."""

    REQUEST = "Filter_Retrieval"
