from typing import Union
from app.domains.books.schemas import RetrievalTask as BookRetrievalTask
from app.domains.books.schemas import AnalyzeTask as BookAnalyzeTask
from app.domains.users.schemas import UserRequest as UserInfoTask
from app.domains.project.schemas import ProjectRequest as ProjectInfoTask

AllRequests = Union[
    BookRetrievalTask,
    BookAnalyzeTask,
    UserInfoTask,
    ProjectInfoTask,
]

__all__ = [
    "AllRequests",
]