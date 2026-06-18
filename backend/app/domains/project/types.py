from enum import Enum

class NodeType(str, Enum):
    # Retrievals
    PROJECT_INFO = "Retrieve_Project_Info"
    FEEDBACK = "Provide_Feedback"
