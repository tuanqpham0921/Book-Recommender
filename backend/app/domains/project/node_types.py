from enum import Enum


class ProjectNodeTypeEnum(str, Enum):
    # Retrievals
    PROJECT_INFO = "Retrieve_Project_Info"
    FEEDBACK = "Provide_Feedback"
