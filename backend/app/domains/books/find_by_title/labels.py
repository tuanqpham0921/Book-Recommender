from enum import Enum

class FindTitleNodeTypeEnum(str, Enum):
    REQUEST = "Retrieve_By_Title"
    OUTPUT  = "Retrieve_By_Title_Output"
    EXECUTOR = "Retrieve_By_Title_Executor"
