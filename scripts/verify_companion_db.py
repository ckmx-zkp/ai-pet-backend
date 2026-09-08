"""只允许在独立临时数据库运行的真实SQL/HTTP验收。"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from sqlalchemy import select

from pet_common.db import get_engine, get_session_factory
from pet_common.models import Device, Memory, User
from web_api.main import create_app


async def main():
    assert "@companion-test-db:" in os.environ["DATABASE_URL"], "refuse production database"
    async with get_session_factory()() as session:
        u1 = User(login_name="companion-test1", password_hash="disabled")
        u2 = User(login_name="companion-test2", password_hash="disabled")
        session.add_all([u1, u2])
        await session.flush()
        device = Device(
            device_uid="companion-test-device", binding_id="test-binding", user_id=u1.id
        )
        session.add(device)
        await session.commit()
        uid1, uid2, did = u1.id, u2.id, device.id
    token = jwt.encode(
        dict(sub=str(uid1), role="user"), os.environ["JWT_SECRET_KEY"], algorithm="HS256"
    )
    headers = {"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"]}
    user_headers = {"Authorization": "Bearer " + token}
    root = "/api/internal/companion/devices/companion-test-device"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        assert (await client.get(root + "/context")).status_code == 401
        assert (await client.get(root + "/context", headers=headers)).status_code == 200
        r = await client.post(
            root + "/feedback",
            headers=headers,
            json=dict(preference="reply_length", value="short", evidence="请说短一点"),
        )
        assert r.status_code == 200, r.text
        mid = r.json()["memory_id"]
        assert r.json()["status"] == "candidate"
        assert not (await client.get(root + "/context", headers=headers)).json()[
            "approved_preferences"
        ]
        r = await client.post(f"/api/devices/{did}/memories/{mid}/approve", headers=user_headers)
        assert r.status_code == 200, r.text
        assert (await client.get(root + "/context", headers=headers)).json()[
            "approved_preferences"
        ] == {"reply_length": "short"}
        due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        body = dict(request_id="integration001", topic="明天分享阅读感想", due_at=due)
        r = await client.post(root + "/followups", headers=headers, json=body)
        assert r.status_code == 200, r.text
        item = r.json()["id"]
        assert (await client.post(root + "/followups", headers=headers, json=body)).json()[
            "id"
        ] == item
        assert (
            await client.post(
                root + "/followups", headers=headers, json={**body, "topic": "conflict"}
            )
        ).status_code == 409
        assert (
            len((await client.get(f"/api/devices/{did}/followups", headers=user_headers)).json())
            == 1
        )
        assert (
            await client.patch(
                root + "/followups/" + item, headers=headers, json={"status": "cancelled"}
            )
        ).status_code == 200
        assert (
            await client.patch(
                root + "/followups/" + item, headers=headers, json={"status": "completed"}
            )
        ).status_code == 409
        # 模拟换绑：旧主人的记忆、偏好和约定不能被新主人读到或修改。
        async with get_session_factory()() as session:
            row = await session.scalar(select(Device).where(Device.id == did))
            row.user_id = uid2
            session.add(
                Memory(
                    device_id=did,
                    user_id=uid2,
                    status="active",
                    source="agent",
                    title="未经审批的模型标签",
                    content="test",
                    tags=["companion_preference", "preference:tone:direct"],
                )
            )
            await session.commit()
        context = (await client.get(root + "/context", headers=headers)).json()
        assert not context["approved_preferences"]
        assert not (await client.get(root + "/followups?status=cancelled", headers=headers)).json()
        assert (
            await client.patch(
                root + "/followups/" + item, headers=headers, json={"status": "cancelled"}
            )
        ).status_code == 404
        assert (
            await client.get(f"/api/devices/{did}/followups", headers=user_headers)
        ).status_code in (403, 404)
    from memory_mcp.server import memory_add, memory_forget, memory_search

    found = await memory_search("companion-test-device", "")
    assert mid not in {item["id"] for item in found["items"]}
    assert (await memory_forget("companion-test-device", mid))["status"] == "not_found"
    created = await memory_add(
        "companion-test-device", "测试记忆", "电话13800138000", status="active"
    )
    assert created["status"] == "candidate"
    async with get_session_factory()() as session:
        saved = await session.get(Memory, created["id"])
        assert saved is not None and "13800138000" not in saved.content
    assert (await memory_forget("companion-test-device", created["id"]))["status"] == "archived"
    await get_engine().dispose()
    print(
        "PASS: real PostgreSQL migration, auth, approval, idempotency, terminal state, owner isolation"
    )


asyncio.run(main())
