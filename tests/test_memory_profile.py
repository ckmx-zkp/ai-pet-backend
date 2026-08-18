"""E6.1 记忆画像：入队去重、空记忆不调 LLM、handler 写卡片。"""

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import agent_worker.tasks as worker_tasks
from pet_common.models import AgentTask, AnalysisResult, Memory
from web_api.queue import enqueue_memory_profile


class Store:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.memories: list[Memory] = []


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: object) -> None:
        self.store.added.append(obj)

    async def execute(self, statement: object) -> Any:
        class Result:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def scalars(self) -> Any:
                return self

            def all(self) -> list[object]:
                return self._rows

        kind = getattr(getattr(statement, "column_descriptions", [{}])[0], "get", lambda *_: None)
        del kind
        if self.store.memories:
            return Result(list(self.store.memories))
        pending = [obj for obj in self.store.added if isinstance(obj, AgentTask)]
        return Result(pending)


@pytest.mark.asyncio
async def test_enqueue_memory_profile_skips_existing_pending() -> None:
    store = Store()
    session = FakeSession(store)
    await enqueue_memory_profile(cast(AsyncSession, session), 1, "create")
    await enqueue_memory_profile(cast(AsyncSession, session), 1, "create")
    tasks = [obj for obj in store.added if isinstance(obj, AgentTask)]
    assert len(tasks) == 1
    assert tasks[0].payload == {"device_id": 1, "reason": "create"}


@pytest.mark.asyncio
async def test_memory_profile_empty_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()

    async def boom(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("LLM should not run when there is no active memory")

    monkeypatch.setattr(worker_tasks, "generate_memory_profile", boom)
    await worker_tasks.memory_profile_handler(
        {"device_id": 7, "reason": "create"}, cast(AsyncSession, FakeSession(store))
    )
    cards = [obj for obj in store.added if isinstance(obj, AnalysisResult)]
    assert len(cards) == 1
    assert cards[0].kind == "memory_profile"
    assert cards[0].payload["memory_count"] == 0
    assert cards[0].payload["remembered"] == []


@pytest.mark.asyncio
async def test_memory_profile_handler_writes_card(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    store.memories = [
        Memory(
            id=1,
            device_id=3,
            user_id=1,
            title="加班",
            content="经常很晚回家",
            tags=["care"],
            source="manual",
            status="active",
        )
    ]

    async def fake_generate(
        settings: object, memories: list[dict[str, Any]], reason: str
    ) -> dict[str, Any]:
        assert reason == "approve"
        assert memories[0]["title"] == "加班"
        return {
            "remembered": [{"title": "晚归", "summary": "希望有人等", "tags": ["care"]}],
            "companion_impact": "先问累不累",
        }

    monkeypatch.setattr(worker_tasks, "generate_memory_profile", fake_generate)
    await worker_tasks.memory_profile_handler(
        {"device_id": 3, "reason": "approve"}, cast(AsyncSession, FakeSession(store))
    )
    card = next(obj for obj in store.added if isinstance(obj, AnalysisResult))
    assert card.payload["companion_impact"] == "先问累不累"
    assert card.payload["memory_count"] == 1
    assert card.payload["remembered"][0]["title"] == "晚归"
