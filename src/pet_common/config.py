"""Pydantic v2 settings：所有配置走环境变量（本地可用 .env）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。字段与 .env.example 一一对应。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "web-api"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_pet"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24

    internal_service_token: str = "change-me-internal"

    llm_api_key: str = ""

    worker_poll_interval_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """进程级缓存的 Settings 实例（也作为 FastAPI Depends 使用）。"""
    return Settings()
