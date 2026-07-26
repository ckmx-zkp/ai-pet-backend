"""路由骨架，路径严格对应 docs/06-HTTP-API规范（前缀 /api）。

首版为空骨架：签名/路径/鉴权就位，业务逻辑统一 501 Not Implemented。
"""

from fastapi import HTTPException


def not_implemented() -> None:
    raise HTTPException(status_code=501, detail="not implemented")
