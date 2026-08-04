from enum import Enum


class UnknownNodeTypeEnum(Enum):
    UNKNOWN = "unknown"


# NodeTypeEnum — the flat enum of every registered capability name — is built
# from the node specs in app/registry.py, not declared here. It cannot live in
# this module: request schemas import BaseRequest, which would import this,
# which would have to import the slices back. Import it from app.registry.
