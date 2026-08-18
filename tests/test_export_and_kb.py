"""E7.1 反馈接受建 draft；E8 导出包不含敏感字段；B5 v3 片段为第一人称。"""

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from persona_compiler.kb_v3 import MBTI_V3, SIGN_V3
from pet_common.models import Device, KBFeedbackCandidate, MBTIKBEntry, ZodiacKBEntry
from web_api.exporting import build_export_bundle
from web_api.routers import admin as admin_router


class Store:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.max_mbti = 2
        self.max_zodiac = 2


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: object) -> None:
        self.store.added.append(obj)

    async def flush(self) -> None:
        for obj in self.store.added:
            item: Any = obj
            if getattr(item, "id", None) is None:
                item.id = 99

    async def scalar(self, statement: object) -> object:
        text = str(statement)
        if "mbti" in text.lower() or "MBTIKBEntry" in text:
            return self.store.max_mbti
        return self.store.max_zodiac


@pytest.mark.asyncio
async def test_accept_feedback_creates_mbti_draft_not_published() -> None:
    store = Store()
    row = KBFeedbackCandidate(
        id=1,
        device_id=1,
        kind="mbti",
        status="pending",
        payload={
            "kb_kind": "mbti",
            "key": "ENFP",
            "suggestion": "更活泼一点",
            "draft_payload": {"prompt_fragments": ["我会接住你的热情。"]},
        },
    )
    draft_id = await admin_router._draft_from_feedback(cast(AsyncSession, FakeSession(store)), row)
    assert draft_id == 99
    created = next(obj for obj in store.added if isinstance(obj, MBTIKBEntry))
    assert created.status == "draft"
    assert created.version == 3
    assert created.payload["prompt_fragments"][0].startswith("我")


@pytest.mark.asyncio
async def test_accept_feedback_creates_sign_draft() -> None:
    store = Store()
    row = KBFeedbackCandidate(
        id=2,
        kind="sign",
        status="pending",
        payload={
            "kb_kind": "sign",
            "key": "scorpio",
            "parent_key": "water",
            "suggestion": "少追问",
        },
    )
    await admin_router._draft_from_feedback(cast(AsyncSession, FakeSession(store)), row)
    created = next(obj for obj in store.added if isinstance(obj, ZodiacKBEntry))
    assert created.status == "draft"
    assert created.level == "sign"
    assert created.key == "scorpio"


@pytest.mark.asyncio
async def test_export_bundle_redacts_device_uid_and_bazi(monkeypatch: pytest.MonkeyPatch) -> None:
    device = Device(id=1, user_id=1, device_uid="aa:bb:cc:dd:ee:ff", name="星仔", capabilities={})

    class QueueSession:
        async def scalar(self, statement: object) -> object:
            return None

        async def execute(self, statement: object) -> Any:
            class Result:
                def scalars(self) -> Any:
                    return self

                def all(self) -> list[object]:
                    return []

            return Result()

    bundle = await build_export_bundle(cast(AsyncSession, QueueSession()), device)
    assert bundle["device"]["device_uid_redacted"] is True
    assert "device_uid" not in bundle["device"]
    assert bundle["bazi_recorded"] is False
    assert bundle["owner"] is None
    assert "birth_date" not in bundle


def test_kb_v3_covers_twelve_signs_and_sixteen_mbti() -> None:
    assert len(SIGN_V3) == 12
    assert len(MBTI_V3) == 16
    assert {item[0] for item in SIGN_V3} >= {"pisces", "scorpio", "aries"}
    assert all(item[2].startswith("我") for item in SIGN_V3)
    assert all(item[1].startswith("我") for item in MBTI_V3)
