from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Yara API"
    environment: str = "local"
    debug: bool = False
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/yara",
        validation_alias="DATABASE_URL",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
