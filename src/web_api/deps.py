"""JWT 鉴权依赖（PyJWT）与服务间 token 校验。

- 用户 JWT：Authorization: Bearer <jwt>，负载即 claims dict（sub=user_id 等）。
- /internal/*：X-Internal-Token 头，与 INTERNAL_SERVICE_TOKEN 比对（服务间共享密钥）。
"""

from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pet_common.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: SettingsDep,
) -> dict[str, Any]:
    """解析并校验用户 JWT，返回 claims。校验失败一律 401。"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token"
        )
    try:
        claims: dict[str, Any] = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from exc
    return claims


def require_admin(
    claims: Annotated[dict[str, Any], Depends(get_current_claims)],
) -> dict[str, Any]:
    """/admin/* 路由依赖：要求 JWT 内 role=admin。"""
    if claims.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return claims


def require_internal_token(
    settings: SettingsDep,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    """/internal/* 路由依赖：服务间共享 token。"""
    if not x_internal_token or x_internal_token != settings.internal_service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token"
        )
