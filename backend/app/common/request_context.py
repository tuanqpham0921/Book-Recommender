import logging
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.messages import UserMessage, AssistantMessage
from app.common.sse_stream import SSEStream
from db.stores.base_store import BaseStore

from clients import OpenAIClient

logger = logging.getLogger(__name__)

StoreT = TypeVar("StoreT", bound=BaseStore)


# class RequestContext(BaseModel):
#     model_config = ConfigDict(arbitrary_types_allowed=True)

#     app_env: str

#     session_id: str
#     user_message: UserMessage
#     llm_client: OpenAIClient
#     sse_stream: SSEStream

#     # Keyed by store class, reached with `require_store()` — the same
#     # select-by-type rule artifacts follow, so there is one vocabulary for both.
#     # A mapping rather than a field per store keeps this context from having to
#     # know every domain that will ever exist.
#     #
#     # These are *already constructed*, on the request-scoped session FastAPI
#     # manages (see get_sqlalchemy_session). Do not rebuild them lazily from
#     # session_factory below: that opens a different session, so a read in one
#     # node and a write in another would silently stop sharing a transaction.
#     stores: dict[type, BaseStore] = Field(default_factory=dict)

#     # for writes that outlive the request-scoped session (e.g. chat run records)
#     session_factory: async_sessionmaker[AsyncSession]

#     def require_store(self, cls: type[StoreT]) -> StoreT:
#         """The store of type `cls` for this request, or raise.

#         Checks the value, not just the key, so a mapping wired to the wrong
#         store fails here — instead of at the first query, as a confusing error
#         about a column that doesn't exist.
#         """
#         store = self.stores.get(cls)
#         if store is None:
#             have = ", ".join(sorted(c.__name__ for c in self.stores)) or "nothing"
#             raise LookupError(f"no {cls.__name__} on this request (have: {have})")
#         if not isinstance(store, cls):
#             # the key says one thing and the value is another — worth its own
#             # message, since "no BookStore (have: BookStore)" reads as nonsense.
#             # `__class__`, not `type()`: it names what isinstance actually
#             # consulted, which is also the useful answer under a spec'd mock.
#             raise LookupError(
#                 f"stores[{cls.__name__}] holds a {store.__class__.__name__}, "
#                 f"not a {cls.__name__}"
#             )
#         return store

# NOTE base request context
# a user or an assistant can make a request
# and the app needs to have llm_client for now?
class RequestContext(BaseModel):
    app_env: str

    session_id: str
    
    # need a way to communicate to the services
    query: UserMessage | AssistantMessage 
    llm_client: OpenAIClient = Field(..., exclude=True)