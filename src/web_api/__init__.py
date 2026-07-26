"""web-api：HTTP API 入口（FastAPI）。路由契约见 docs/06-HTTP-API规范。"""

from web_api.main import create_app

__all__ = ["create_app"]
