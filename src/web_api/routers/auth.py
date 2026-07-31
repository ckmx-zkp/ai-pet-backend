"""POST /auth/login、POST /auth/register、GET /auth/me（docs/06 §用户与设备）。

安全约束（AGENTS.md 红线 + 母文档）：
- 登录失败对用户不存在/密码错误返回统一的模糊 401，不泄露用户存在性；
- 注册/登录成功写 audit_logs；
- 密码用 argon2id（pwdlib 推荐）哈希，明文不落库、不落日志。
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pwdlib import PasswordHash
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.config import Settings
from pet_common.db import get_session
from pet_common.models import AuditLog, User
from web_api.deps import SettingsDep, get_current_claims

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_password_hash = PasswordHash.recommended()  # argon2id

# 登录失败统一提示：不区分“用户不存在”与“密码错误”，防用户枚举。
_INVALID_CREDENTIALS = "login_name or password incorrect"


class RegisterRequest(BaseModel):
    login_name: Annotated[
        str, StringConstraints(min_length=3, max_length=64, strip_whitespace=True)
    ]
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


class LoginRequest(BaseModel):
    login_name: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    login_name: str
    role: str
    status: str


async def _find_user_by_login_name(session: AsyncSession, login_name: str) -> User | None:
    result = await session.execute(select(User).where(User.login_name == login_name))
    return result.scalar_one_or_none()


async def _get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


def _create_access_token(settings: Settings, user: User) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _audit(session: AsyncSession, user: User, action: str) -> None:
    session.add(
        AuditLog(actor=f"user:{user.id}", action=action, target_type="user", target_id=str(user.id))
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: SessionDep) -> User:
    """注册：login_name 唯一（冲突 409），role/status 取模型默认 user/active。"""
    if await _find_user_by_login_name(session, payload.login_name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="login_name already registered"
        )
    user = User(
        login_name=payload.login_name,
        password_hash=_password_hash.hash(payload.password),
        role="user",
        status="active",
    )
    session.add(user)
    await session.flush()  # 取自增 id
    _audit(session, user, "register")
    await session.commit()
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    """登录：校验密码后签发 JWT；disabled 用户 403；其余失败统一模糊 401。"""
    user = await _find_user_by_login_name(session, payload.login_name)
    if user is None or not _password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS)
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account disabled")
    _audit(session, user, "login")
    await session.commit()
    return TokenResponse(access_token=_create_access_token(settings, user))


@router.get("/me", response_model=UserResponse)
async def me(
    claims: Annotated[dict[str, Any], Depends(get_current_claims)], session: SessionDep
) -> User:
    """当前用户信息。token 无效 401；用户不存在/已停用 401。"""
    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from exc
    user = await _get_user_by_id(session, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return user
