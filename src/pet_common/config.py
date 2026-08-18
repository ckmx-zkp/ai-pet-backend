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

    # CORS 允许来源（逗号分隔）；默认放本地 Vite 开发端口，生产配管理台域名
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    llm_api_key: str = ""
    # OpenAI-compatible Chat Completions endpoint, supplied only in deployment .env.
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 20.0
    # Development may let the worker apply an LLM-reviewed private persona suggestion.
    # Keep false by default: enabling it is an explicit deployment decision.
    llm_auto_apply_persona_growth: bool = False

    # E10 运势联网搜索（docs/12 §4）：MiniMax 服务端 web_search 仅 Anthropic Messages
    # API 支持，且实测 MiniMax-M2.5 不执行服务端检索（降级为客户端 tool_use），
    # 故 L1 整合搜索固定走 fortune_search_model（默认 MiniMax-M3，已实测可用）。
    # 搜索未真正执行时任务走延迟重试，不静默降级为纯生成。
    fortune_search_enabled: bool = True
    fortune_search_model: str = "MiniMax-M3"

    worker_poll_interval_seconds: float = 2.0

    # Memory MCP is stdio in local tooling and streamable HTTP in deployment.
    memory_mcp_transport: str = "stdio"
    memory_mcp_host: str = "0.0.0.0"
    memory_mcp_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """进程级缓存的 Settings 实例（也作为 FastAPI Depends 使用）。"""
    return Settings()
