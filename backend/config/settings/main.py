from pydantic import BaseModel
from pydantic_settings import SettingsConfigDict

from .app import AppSettings
from .openai import OpenAISettings
from .sqlalchemy import SQLAlchemySettings

from config.constants import FilesLocationConstants


class Settings(BaseModel):
    """Unified application settings (aggregates all sub-configs)."""

    model_config = SettingsConfigDict(
        env_file=FilesLocationConstants.ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # the "missing" constructor args are loaded from the env file by
    # pydantic-settings at runtime — pyright can't see that
    sqlalchemy: SQLAlchemySettings = SQLAlchemySettings()  # pyright: ignore[reportCallIssue]
    openai: OpenAISettings = OpenAISettings()  # pyright: ignore[reportCallIssue]
    app: AppSettings = AppSettings()  # pyright: ignore[reportCallIssue]


settings = Settings()
