import json
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Latext"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/latext"
    
    # Security
    JWT_SECRET: str = "supersecretjwtkeythatisverylongandsecurechangeinproduction"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    # CORS Origins
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:3000"]
    
    NEXT_PUBLIC_API_URL: str = "http://localhost:8000"
    BACKEND_INTERNAL_URL: str = "http://backend:8000"
    REDIS_URL: str = "redis://localhost:6379/0"
    MAX_SCHEDULED_MESSAGE_ATTEMPTS: int = 4
    RETRY_BASE_DELAY_SECONDS: int = 10
    MAX_RETRY_DELAY_SECONDS: int = 90
    WORKER_CONCURRENCY: int = 10

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, str) and v.startswith("["):
            try:
                return json.loads(v)
            except Exception:
                return [v]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
