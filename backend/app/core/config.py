from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Yara API"
    environment: str = "local"
    debug: bool = False
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    llm: str = Field(default="local", validation_alias="LLM")
    trace_enabled: bool = Field(default=True, validation_alias="TRACE_ENABLED")
    reconciliation: bool = Field(default=False, validation_alias="RECONCILIATION")
    anomaly_detection: bool = Field(default=False, validation_alias="ANOMALY_DETECTION")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/yara",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379", validation_alias="REDIS_URL")
    jwt_secret: str = Field(default="dev-only-yara-secret", validation_alias="JWT_SECRET")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
