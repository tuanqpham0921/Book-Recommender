from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from config.constants import FilesLocationConstants


class AppSettings(BaseSettings):
    NAME: str
    ENVIRONMENT: str
    # NoDecode: pydantic-settings otherwise tries to JSON-decode env values
    # for list-typed fields before validators run, which breaks on a plain
    # comma-separated string. The field_validator below does the real split.
    ALLOW_ORIGINS: Annotated[list[str], NoDecode]

    model_config = SettingsConfigDict(
        env_file=FilesLocationConstants.ENV_FILE,
        env_prefix="APP_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ALLOW_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        # CORSMiddleware does exact-membership checks against this list; a
        # plain str would do substring matching instead, which is a CORS
        # bypass once more than one origin is configured. Env var stays a
        # comma-separated string; this splits it before it reaches Settings.
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
