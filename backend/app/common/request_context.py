"""`RequestContext` — the services one turn can reach.

Not what a node is working on; that half is `WorkflowInput`. They split on
lifetime: services are built once at the request boundary and are the same for
every node, while an input is assembled fresh at each dispatch.

A node does not read this class directly. Each layer declares the view it needs
as a subclass with a `narrow()` (`BookRequestContext` turns the opaque `stores`
bag into a typed `store`), and `NodeSpec.context` says which view a node wants.
The task runner narrows at dispatch, the first place that knows which node is
about to run.

`stores` stays a type-keyed mapping — the carrier that lets this module hold a
`BookStore` without importing the books domain.
"""

import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clients.messages import UserMessage
from app.common.sse_stream import SSEStream
from db.stores.base_store import BaseStore

from clients import OpenAIClient

logger = logging.getLogger(__name__)

StoreT = TypeVar("StoreT", bound=BaseStore)


class RequestContext(BaseModel):
    """Everything a turn can reach, before anything decides what to do with it."""

    # OpenAIClient, SSEStream and the session factory are plain classes, not
    # pydantic models — without this the class raises at import time.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    app_env: str
    session_id: str

    # The turn's message — identity, not input: the wire `chat_id` and
    # `user_chat_id` in chat_runs both come from its id, and it outlives every
    # node in the plan while `NodeInput.query` changes at each dispatch.
    user_message: UserMessage

    llm_client: OpenAIClient = Field(..., exclude=True)
    sse_stream: SSEStream = Field(..., exclude=True)

    # Keyed by store class, reached by `narrow()` on a subclass. Already
    # constructed, on the request-scoped session FastAPI manages. Do not rebuild
    # them from session_factory below — that opens a different session, so two
    # nodes would silently stop sharing a transaction.
    stores: dict[type, BaseStore] = Field(default_factory=dict, exclude=True)

    # for writes that outlive the request-scoped session (e.g. chat run records)
    session_factory: async_sessionmaker[AsyncSession] = Field(..., exclude=True)

    @classmethod
    def narrow(cls, ctx: "RequestContext") -> "RequestContext":
        """The widest context in, this layer's view out.

        Identity on the base. A subclass overrides it to pull what it needs out
        of `stores`, and so fails here — once, at dispatch, naming the service.
        """
        return ctx

    def base_fields(self) -> dict[str, Any]:
        """This context's `RequestContext` half, for a subclass rebuilding
        itself around it. Pydantic passes these through by reference, so
        `sse_stream` keeps its identity — a copied stream would enqueue into a
        queue nothing reads, and nothing would raise.
        """
        return {name: getattr(self, name) for name in RequestContext.model_fields}

    def require_store(self, cls: type[StoreT]) -> StoreT:
        """The store of type `cls` for this request, or raise. Checks the
        value, not just the key, so a mapping wired to the wrong store fails
        here rather than as a confusing error about a missing column."""
        store = self.stores.get(cls)
        if store is None:
            have = ", ".join(sorted(c.__name__ for c in self.stores)) or "nothing"
            raise LookupError(f"no {cls.__name__} on this request (have: {have})")
        if not isinstance(store, cls):
            # its own message, since "no BookStore (have: BookStore)" reads as
            # nonsense. `__class__`, not `type()`: it names what isinstance
            # consulted, the useful answer under a spec'd mock.
            raise LookupError(
                f"stores[{cls.__name__}] holds a {store.__class__.__name__}, "
                f"not a {cls.__name__}"
            )
        return store
