"""auth 路由测试（tests 无 PG：用内存 FakeSession + monkeypatch 仓储函数）。

覆盖：注册成功/重复 409/弱密码 422、登录成功签发 JWT、错误密码与用户不存在
返回一致的模糊 401（防枚举）、disabled 用户 403、带 token 访问 me。
"""

from collections.abc import AsyncIterator
from typing import cast

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.config import get_settings
from pet_common.db import get_session
from pet_common.models import AuditLog, User
from web_api.main import create_app
from web_api.routers import auth as auth_router


class FakeSession:
    """内存版 AsyncSession：只实现 auth 流程用到的 add/flush/commit。"""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.audit_logs: list[AuditLog] = []
        self.next_id = 1

    def add(self, obj: object) -> None:
        if isinstance(obj, User):
            self.users[obj.login_name] = obj
        elif isinstance(obj, AuditLog):
            self.audit_logs.append(obj)

    async def flush(self) -> None:
        for user in self.users.values():
            if user.id is None:
                user.id = self.next_id
                self.next_id += 1

    async def commit(self) -> None:
        pass


def seed_user(
    store: FakeSession,
    login_name: str = "tester",
    password: str = "password123",
    status: str = "active",
) -> User:
    """预置一个用户（密码走真实 argon2 哈希）。"""
    user = User(
        login_name=login_name,
        password_hash=auth_router._password_hash.hash(password),  # noqa: SLF001
        role="user",
        status=status,
    )
    store.add(user)
    user.id = store.next_id
    store.next_id += 1
    return user


@pytest.fixture
def store() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(store: FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_find_by_login_name(session: AsyncSession, login_name: str) -> User | None:
        assert isinstance(session, FakeSession)
        return session.users.get(login_name)

    async def fake_get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
        assert isinstance(session, FakeSession)
        return next((u for u in session.users.values() if u.id == user_id), None)

    monkeypatch.setattr(auth_router, "_find_user_by_login_name", fake_find_by_login_name)
    monkeypatch.setattr(auth_router, "_get_user_by_id", fake_get_user_by_id)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def register_user(
    client: TestClient, login_name: str = "tester", password: str = "password123"
) -> Response:
    resp: Response = client.post(
        "/api/auth/register", json={"login_name": login_name, "password": password}
    )
    return resp


def test_register_success(client: TestClient, store: FakeSession) -> None:
    resp = register_user(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["login_name"] == "tester"
    assert body["role"] == "user"
    assert body["status"] == "active"

    user = store.users["tester"]
    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$argon2")
    assert [log.action for log in store.audit_logs] == ["register"]
    assert store.audit_logs[0].actor == f"user:{user.id}"


def test_register_duplicate_409(client: TestClient) -> None:
    assert register_user(client).status_code == 201
    resp = register_user(client)
    assert resp.status_code == 409


def test_register_weak_password_422(client: TestClient) -> None:
    resp = register_user(client, password="short")
    assert resp.status_code == 422


def test_login_success(client: TestClient, store: FakeSession) -> None:
    user = seed_user(store)
    resp = client.post("/api/auth/login", json={"login_name": "tester", "password": "password123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"

    settings = get_settings()
    claims = jwt.decode(
        body["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    assert claims["sub"] == str(user.id)
    assert claims["role"] == "user"
    assert [log.action for log in store.audit_logs] == ["login"]


def test_login_failure_is_unambiguous(client: TestClient, store: FakeSession) -> None:
    seed_user(store)
    wrong_pw = client.post(
        "/api/auth/login", json={"login_name": "tester", "password": "wrong-password"}
    )
    no_such_user = client.post(
        "/api/auth/login", json={"login_name": "nobody", "password": "password123"}
    )
    # 防用户枚举：两种失败的状态码与提示完全一致
    assert wrong_pw.status_code == 401
    assert no_such_user.status_code == 401
    assert wrong_pw.json() == no_such_user.json()
    assert store.audit_logs == []  # 登录失败不写审计


def test_login_disabled_403(client: TestClient, store: FakeSession) -> None:
    seed_user(store, status="disabled")
    resp = client.post("/api/auth/login", json={"login_name": "tester", "password": "password123"})
    assert resp.status_code == 403


def test_me_with_token(client: TestClient, store: FakeSession) -> None:
    seed_user(store)
    token = client.post(
        "/api/auth/login", json={"login_name": "tester", "password": "password123"}
    ).json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["login_name"] == "tester"
    assert resp.json()["role"] == "user"


def test_me_without_token_401(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
