from enum import Enum

class ProjectInfoField(str, Enum):
    NAME = "name"
    DESCRIPTION = "description"
    TECHNOLOGY_STACK = "technology_stack"
    PROJECT_URL = "project_url"
    PROJECT_GITHUB_URL = "project_github_url"
    PROJECT_GITHUB_REPO_NAME = "project_github_repo_name"
    PROJECT_GITHUB_REPO_URL = "project_github_repo_url"
    ALL = "all"