"""`RequestContext` — the services one turn can reach.

Deliberately **not** what a node is working on. That half is `WorkflowInput`
(app/domains/node_input.py), and the two are split because they have different
lifetimes: services are built once, at the request boundary, and are the same
for every node in the plan; an input is assembled fresh at each dispatch out of
the goal text and whatever ran before it. A context carrying `query` or
`artifacts` would have to be rebuilt per node, and then "what is this node
working on" would have two answers.

A node does not read this class directly. Each layer declares the view it needs
as a subclass with a `narrow()` — `BookRequestContext` (app/domains/books/
external.py) turns the opaque `stores` bag into a typed `store` — and
`NodeSpec.context` is where a node says which view it wants. The task runner
narrows at dispatch, because it is the first place that knows which node is
about to run.

`stores` stays a type-keyed mapping rather than becoming a field per domain:
it is the *carrier*, and it is what lets this module hold a `BookStore` without
importing the books domain. The typed views are where domain knowledge lives.
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

    # The turn's message — identity, not input. The `chat_id` on the wire and
    # `user_chat_id` in chat_runs both come from its id, which is why it lives
    # here rather than on an input: it outlives every node in the plan, while
    # `NodeInput.query` changes at every dispatch.
    user_message: UserMessage

    llm_client: OpenAIClient = Field(..., exclude=True)
    sse_stream: SSEStream = Field(..., exclude=True)

    # Keyed by store class, reached by `narrow()` on a subclass. These are
    # *already constructed*, on the request-scoped session FastAPI manages (see
    # get_sqlalchemy_session). Do not rebuild them lazily from session_factory
    # below: that opens a different session, so a read in one node and a write
    # in another would silently stop sharing a transaction.
    stores: dict[type, BaseStore] = Field(default_factory=dict, exclude=True)

    # for writes that outlive the request-scoped session (e.g. chat run records)
    session_factory: async_sessionmaker[AsyncSession] = Field(..., exclude=True)

    @classmethod
    def narrow(cls, ctx: "RequestContext") -> "RequestContext":
        """The widest context in, this layer's view out.

        Identity on the base, which is already the widest. A subclass overrides
        it to pull what it needs out of `stores`, and so fails *here* — once,
        at dispatch, naming the service — instead of at the first query.
        """
        return ctx

    def base_fields(self) -> dict[str, Any]:
        """This context's `RequestContext` half, for a subclass rebuilding
        itself around it.

        Pydantic passes model instances and arbitrary types through by
        reference, so `sse_stream` and `user_message` keep their identity
        across the rebuild — a *copied* stream would enqueue into a queue
        nothing reads, and nothing would raise.
        """
        return {name: getattr(self, name) for name in RequestContext.model_fields}

    def require_store(self, cls: type[StoreT]) -> StoreT:
        """The store of type `cls` for this request, or raise.

        Checks the value, not just the key, so a mapping wired to the wrong
        store fails here — instead of at the first query, as a confusing error
        about a column that doesn't exist.
        """
        store = self.stores.get(cls)
        if store is None:
            have = ", ".join(sorted(c.__name__ for c in self.stores)) or "nothing"
            raise LookupError(f"no {cls.__name__} on this request (have: {have})")
        if not isinstance(store, cls):
            # the key says one thing and the value is another — worth its own
            # message, since "no BookStore (have: BookStore)" reads as nonsense.
            # `__class__`, not `type()`: it names what isinstance actually
            # consulted, which is also the useful answer under a spec'd mock.
            raise LookupError(
                f"stores[{cls.__name__}] holds a {store.__class__.__name__}, "
                f"not a {cls.__name__}"
            )
        return store
