from enum import Enum
class DeveloperInfoEnum(str, Enum):
    NAME = "name"
    BIO = "bio"
    EMAIL = "email"
    LINKEDIN_URL = "linkedin_url"
    
class UserInfoEnum(str, Enum):
    NAME = "name"
    AGE = "age"
    BIO = "bio"
    TOKEN_USAGE = "token_usage"
    SAVED_MEMORY = "saved_memory"
    PREVIOUS_CONVERSATION = "previous_conversation"
    CURRENT_CONVERSATION = "current_conversation"
