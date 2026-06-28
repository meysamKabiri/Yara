from pydantic import BaseModel


class HealthCheck(BaseModel):
    status: str
    database: str = "unavailable"
    redis: str = "unavailable"
    ollama: str = "unavailable"
