"""E10 运势与八字测试（FakeSession + monkeypatch，同 test_persona 风格；LLM mock 不起 PG）。

覆盖：bazi PUT→GET 往返、未录入 404、生辰变更清空排盘缓存并重生成、
fortune/daily 无人设 404、缺内容时 generating=true 且懒入队、内容齐全聚合、
compile_profile 注入当日引导语、daily_sign_fortune 幂等写入与非实时标注、
daily_device_content 的 L1 缺失延迟重试 / 无八字不产 bazi_fortune / 排盘缓存分支。
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import agent_worker.tasks as worker_tasks
from agent_worker.llm import SIGN_KEYS
from pet_common.config import Settings
from pet_common.dates import today_cn
from pet_common.db import get_session
from pet_common.models import (
    AgentTask,
    AuditLog,
    DailySignFortune,
    Device,
    DeviceDailyContent,
    MBTIKBEntry,
    OwnerBaziProfile,
    PersonaProfile,
    ZodiacKBEntry,
)
from test_devices import auth_headers
from web_api.main import create_app
from web_api.routers import admin_devices as admin_router
from web_api.routers import fortune as fortune_router

TODAY = today_cn()

FORTUNE_PAYLOAD = {
    "overall": "整体平顺的一天",
    "career": "事业稳步推进",
    "wealth": "财运宜守不宜攻",
    "study": "学业适合复盘",
    "love": "情感多倾听",
    "source_digest": "示例摘要",
}


class Store:
    """路由测试的内存状态：设备/人设/八字/当日内容/入队任务。"""

    def __init__(self) -> None:
        self.device = Device(
            id=1,
            user_id=1,
            device_uid="aa:bb:cc:dd:ee:ff",
            binding_id="binding-aabbccddeeff001122334455",
            capabilities={},
        )
        self.profile: PersonaProfile | None = None
        self.bazi: OwnerBaziProfile | None = None
        self.sign_fortunes: dict[tuple[date, str], DailySignFortune] = {}
        self.contents: dict[tuple[int, date, str], DeviceDailyContent] = {}
        self.tasks: list[AgentTask] = []
        self.audits: list[AuditLog] = []


class FakeSession:
    """内存版 AsyncSession：fortune 路由只用到 add/delete/commit（查询全部 monkeypatch）。"""

    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: object) -> None:
        if isinstance(obj, OwnerBaziProfile):
            self.store.bazi = obj
        elif isinstance(obj, DeviceDailyContent):
            self.store.contents[(obj.device_id, obj.content_date, obj.kind)] = obj
        elif isinstance(obj, AgentTask):
            self.store.tasks.append(obj)
        elif isinstance(obj, AuditLog):
            self.store.audits.append(obj)

    async def delete(self, obj: object) -> None:
        if isinstance(obj, DeviceDailyContent):
            self.store.contents.pop((obj.device_id, obj.content_date, obj.kind), None)

    async def commit(self) -> None:
        pass


def make_profile() -> PersonaProfile:
    return PersonaProfile(
        user_id=1,
        device_id=1,
        sun_sign="scorpio",
        mbti="ENFP",
        follow_latest=True,
        overrides={},
        dossier={},
    )


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def client(store: Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    session = FakeSession(store)

    async def fake_get_own_device(s: AsyncSession, device_id: int, user_id: int) -> Device:
        assert isinstance(s, FakeSession)
        assert device_id == store.device.id and user_id == store.device.user_id
        return store.device

    async def fake_get_profile(s: AsyncSession, device_id: int) -> PersonaProfile | None:
        return store.profile

    async def fake_bazi(s: AsyncSession, device_id: int) -> OwnerBaziProfile | None:
        return store.bazi

    async def fake_sign_fortune(
        s: AsyncSession, fortune_date: date, sign: str
    ) -> DailySignFortune | None:
        return store.sign_fortunes.get((fortune_date, sign))

    async def fake_daily_content(
        s: AsyncSession, device_id: int, content_date: date, kind: str
    ) -> DeviceDailyContent | None:
        return store.contents.get((device_id, content_date, kind))

    monkeypatch.setattr(fortune_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(fortune_router, "get_profile", fake_get_profile)
    monkeypatch.setattr(fortune_router, "_bazi_profile", fake_bazi)
    monkeypatch.setattr(fortune_router, "_sign_fortune", fake_sign_fortune)
    monkeypatch.setattr(fortune_router, "_daily_content", fake_daily_content)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


# ---------- GET/PUT /devices/{id}/bazi ----------


def test_bazi_put_then_get_roundtrip(client: TestClient, store: Store) -> None:
    body = {
        "calendar_type": "solar",
        "birth_date": "1995-11-08",
        "birth_time": "14:30",
        "birth_place": "北京",
        "gender": "female",
    }
    resp = client.put("/api/devices/1/bazi", json=body, headers=auth_headers())
    assert resp.status_code == 200
    # 只回显录入字段，不回显 bazi_text 等派生内容；time 序列化为 HH:MM:SS
    expected = {**body, "birth_time": "14:30:00"}
    assert resp.json() == expected

    resp = client.get("/api/devices/1/bazi", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == expected

    # PUT 后入队当日内容重生成 + 审计只记字段变更键名（不落生辰原文）
    assert [task.kind for task in store.tasks] == ["daily_device_content"]
    assert store.tasks[0].payload == {"device_id": 1, "date": TODAY.isoformat()}
    assert len(store.audits) == 1
    assert store.audits[0].action == "bazi_upsert"
    assert set(store.audits[0].detail) == {"changed_fields"}
    assert "1995" not in str(store.audits[0].detail)


def test_bazi_get_not_recorded_404(client: TestClient) -> None:
    assert client.get("/api/devices/1/bazi", headers=auth_headers()).status_code == 404


def test_bazi_put_change_clears_chart_and_regenerates(client: TestClient, store: Store) -> None:
    store.bazi = OwnerBaziProfile(
        device_id=1,
        calendar_type="solar",
        birth_date=date(1995, 11, 8),
        birth_time=time(14, 30),
        birth_place="北京",
        gender="female",
        bazi_text="乙亥年 丙戌月 …（旧排盘缓存）",
    )
    stale = DeviceDailyContent(device_id=1, content_date=TODAY, kind="bazi_fortune", payload={})
    store.contents[(1, TODAY, "bazi_fortune")] = stale

    resp = client.put(
        "/api/devices/1/bazi",
        json={"calendar_type": "solar", "birth_date": "1996-01-01"},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    assert store.bazi.bazi_text is None  # 出生信息变更：排盘缓存作废
    assert store.bazi.birth_time is None  # 覆盖写：未提供字段清空
    assert (1, TODAY, "bazi_fortune") not in store.contents  # 当日旧 bazi_fortune 已删
    assert [task.kind for task in store.tasks] == ["daily_device_content"]


# ---------- GET /devices/{id}/fortune/daily ----------


def test_daily_fortune_persona_not_configured_404(client: TestClient) -> None:
    resp = client.get("/api/devices/1/fortune/daily", headers=auth_headers())
    assert resp.status_code == 404


def test_daily_fortune_missing_content_generating_and_lazy_enqueue(
    client: TestClient, store: Store
) -> None:
    store.profile = make_profile()
    resp = client.get("/api/devices/1/fortune/daily", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == TODAY.isoformat()
    assert body["sign"] == "scorpio"
    assert body["generating"] is True
    assert body["sign_fortune"] is None
    assert body["greeting"] is None
    assert body["bazi_fortune"] is None  # 未录八字：恒 null，不参与生成

    kinds = [task.kind for task in store.tasks]
    assert "daily_device_content" in kinds  # 设备内容懒入队
    assert "daily_sign_fortune" in kinds  # L1 缺失也懒入队（handler 幂等）


def test_daily_fortune_full_content(client: TestClient, store: Store) -> None:
    store.profile = make_profile()
    store.sign_fortunes[(TODAY, "scorpio")] = DailySignFortune(
        fortune_date=TODAY, sign="scorpio", payload=dict(FORTUNE_PAYLOAD), llm_model="m"
    )
    store.contents[(1, TODAY, "greeting")] = DeviceDailyContent(
        device_id=1, content_date=TODAY, kind="greeting", payload={"text": "早上好呀"}
    )
    store.bazi = OwnerBaziProfile(
        device_id=1,
        calendar_type="solar",
        birth_date=date(1995, 11, 8),
        birth_time=None,
        birth_place=None,
        gender=None,
        bazi_text="乙亥年 丙戌月 …",
    )
    store.contents[(1, TODAY, "bazi_fortune")] = DeviceDailyContent(
        device_id=1,
        content_date=TODAY,
        kind="bazi_fortune",
        payload={key: f"八字{key}" for key in ("overall", "career", "wealth", "study", "love")},
    )

    resp = client.get("/api/devices/1/fortune/daily", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["generating"] is False
    assert body["sign_fortune"] == {
        key: FORTUNE_PAYLOAD[key] for key in ("overall", "career", "wealth", "study", "love")
    }  # source_digest 不下发
    assert body["greeting"] == "早上好呀"
    assert body["bazi_fortune"]["overall"] == "八字overall"
    assert store.tasks == []  # 内容齐全：不再入队


# ---------- compile_profile 当日内容注入 ----------


async def test_compile_profile_appends_daily_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    from web_api import persona_service

    async def fake_get_zodiac(
        session: AsyncSession, level: str, key: str, kb_version: int | None
    ) -> ZodiacKBEntry | None:
        if level == "sign":
            return ZodiacKBEntry(
                level="sign", key="scorpio", parent_key="water", version=2,
                status="published", payload={},
            )
        return ZodiacKBEntry(
            level="element", key="water", parent_key=None, version=1,
            status="published", payload={},
        )

    async def fake_get_mbti(
        session: AsyncSession, key: str, kb_version: int | None
    ) -> MBTIKBEntry | None:
        return MBTIKBEntry(key="ENFP", version=2, status="published", payload={})

    guidance = ["今天开场时可以自然地提到：昨晚的星星很亮", "今天聊天时可以自然地提到今日运势：顺"]
    captured: dict[str, Any] = {}

    async def fake_daily_guidance(
        session: AsyncSession, device_id: int, sun_sign: str
    ) -> list[str]:
        captured["args"] = (device_id, sun_sign)
        return guidance

    def fake_compile_persona(*args: object, **kwargs: object) -> dict[str, Any]:
        captured["daily_context"] = kwargs.get("daily_context")
        return {
            "kb_version": 2,
            "prompt_fragments": [],
            "taboo": [],
            "traits": {},
            "style": {},
            "emotion_map": {},
            "retrieval_hints": {},
            "daily_context": kwargs.get("daily_context"),
        }

    monkeypatch.setattr(persona_service, "get_zodiac_entry", fake_get_zodiac)
    monkeypatch.setattr(persona_service, "get_mbti_entry", fake_get_mbti)
    monkeypatch.setattr(persona_service, "get_daily_guidance", fake_daily_guidance)
    monkeypatch.setattr(persona_service, "compile_persona", fake_compile_persona)

    pack = await persona_service.compile_profile(cast(AsyncSession, object()), make_profile())
    assert captured["args"] == (1, "scorpio")
    assert captured["daily_context"] == "\n".join(guidance)
    fragments = pack["system_prompt_fragments"]
    assert fragments[0].startswith("你的星座是天蝎座")
    assert fragments[-2:] == guidance  # 引导语追加在片段末尾，7 字段契约不变


# ---------- worker：daily_sign_fortune ----------


class WorkerStore:
    def __init__(self) -> None:
        self.added: list[object] = []


class FakeWorkerSession:
    def __init__(self, store: WorkerStore) -> None:
        self.store = store

    def add(self, obj: object) -> None:
        self.store.added.append(obj)


def _mock_sign_fortunes(
    monkeypatch: pytest.MonkeyPatch, calls: list[date]
) -> None:
    async def fake_generate(settings: object, fortune_date: date) -> dict[str, Any]:
        calls.append(fortune_date)
        return {
            "source_digest": "当日星象平稳",
            "signs": {
                sign: {
                    "overall": f"{sign} 总述",
                    "career": "事业",
                    "wealth": "财运",
                    "study": "学业",
                    "love": "情感",
                }
                for sign in SIGN_KEYS
            },
        }

    monkeypatch.setattr(worker_tasks, "generate_sign_fortunes", fake_generate)


def _pin_settings(monkeypatch: pytest.MonkeyPatch, *, search_enabled: bool) -> None:
    """固定 worker 侧 Settings，避免默认开关随部署配置漂移影响断言。"""
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: Settings(fortune_search_enabled=search_enabled),
    )


async def test_sign_fortune_handler_writes_missing_signs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkerStore()
    calls: list[date] = []
    _pin_settings(monkeypatch, search_enabled=False)

    async def fake_existing(session: AsyncSession, fortune_date: date) -> set[str]:
        return {"aries"}  # aries 已存在：幂等跳过

    monkeypatch.setattr(worker_tasks, "_existing_fortune_signs", fake_existing)
    _mock_sign_fortunes(monkeypatch, calls)

    await worker_tasks.daily_sign_fortune_handler(
        {"date": TODAY.isoformat()}, cast(AsyncSession, FakeWorkerSession(store))
    )
    assert calls == [TODAY]
    rows = [obj for obj in store.added if isinstance(obj, DailySignFortune)]
    assert len(rows) == 11  # 12 - 已存在的 aries
    assert {row.sign for row in rows} == set(SIGN_KEYS) - {"aries"}
    for row in rows:
        assert set(row.payload) == {
            "overall",
            "career",
            "wealth",
            "study",
            "love",
            "source_digest",
        }
        # 搜索开关默认关闭：source_digest 强制标注"非实时检索"
        assert "非实时检索" in row.payload["source_digest"]


async def test_sign_fortune_handler_all_existing_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkerStore()
    calls: list[date] = []

    async def fake_existing(session: AsyncSession, fortune_date: date) -> set[str]:
        return set(SIGN_KEYS)

    monkeypatch.setattr(worker_tasks, "_existing_fortune_signs", fake_existing)
    _mock_sign_fortunes(monkeypatch, calls)

    await worker_tasks.daily_sign_fortune_handler(
        {"date": TODAY.isoformat()}, cast(AsyncSession, FakeWorkerSession(store))
    )
    assert calls == []  # 全部已存在：不调用 LLM
    assert store.added == []


# ---------- worker：daily_device_content ----------


def _mock_device_queries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: PersonaProfile | None,
    sign_fortune: DailySignFortune | None,
    bazi: OwnerBaziProfile | None,
) -> None:
    async def fake_profile(session: AsyncSession, device_id: int) -> PersonaProfile | None:
        return profile

    async def fake_sign(
        session: AsyncSession, fortune_date: date, sign: str
    ) -> DailySignFortune | None:
        return sign_fortune

    async def fake_content(
        session: AsyncSession, device_id: int, content_date: date, kind: str
    ) -> DeviceDailyContent | None:
        return None

    async def fake_bazi(session: AsyncSession, device_id: int) -> OwnerBaziProfile | None:
        return bazi

    async def fake_summary(session: AsyncSession, device_id: int) -> None:
        return None

    async def fake_memories(session: AsyncSession, device_id: int) -> list[object]:
        return []

    monkeypatch.setattr(worker_tasks, "_profile", fake_profile)
    monkeypatch.setattr(worker_tasks, "_sign_fortune", fake_sign)
    monkeypatch.setattr(worker_tasks, "_device_content", fake_content)
    monkeypatch.setattr(worker_tasks, "_bazi_profile", fake_bazi)
    monkeypatch.setattr(worker_tasks, "_recent_summary", fake_summary)
    monkeypatch.setattr(worker_tasks, "_top_active_memories", fake_memories)


async def test_device_content_defers_when_l1_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    store = WorkerStore()
    _mock_device_queries(monkeypatch, profile=make_profile(), sign_fortune=None, bazi=None)

    with pytest.raises(worker_tasks.TaskDeferredError):
        await worker_tasks.daily_device_content_handler(
            {"device_id": 1, "date": TODAY.isoformat()},
            cast(AsyncSession, FakeWorkerSession(store)),
        )
    tasks = [obj for obj in store.added if isinstance(obj, AgentTask)]
    assert len(tasks) == 1
    assert tasks[0].kind == "daily_sign_fortune"  # 先入队 L1，自身延迟重试
    assert tasks[0].payload == {"date": TODAY.isoformat()}


async def test_device_content_without_bazi_only_greeting(monkeypatch: pytest.MonkeyPatch) -> None:
    store = WorkerStore()
    sign_row = DailySignFortune(
        fortune_date=TODAY, sign="scorpio", payload=dict(FORTUNE_PAYLOAD), llm_model="m"
    )
    _mock_device_queries(monkeypatch, profile=make_profile(), sign_fortune=sign_row, bazi=None)

    async def fake_generate(settings: object, context: dict[str, Any]) -> dict[str, Any]:
        assert context["owner_bazi"] is None
        assert context["sign_fortune"]["overall"] == FORTUNE_PAYLOAD["overall"]
        return {"greeting": "早上好呀，今天适合聊聊星星", "bazi_fortune": None}

    monkeypatch.setattr(worker_tasks, "generate_device_daily_content", fake_generate)

    await worker_tasks.daily_device_content_handler(
        {"device_id": 1, "date": TODAY.isoformat()},
        cast(AsyncSession, FakeWorkerSession(store)),
    )
    rows = [obj for obj in store.added if isinstance(obj, DeviceDailyContent)]
    assert [row.kind for row in rows] == ["greeting"]  # 无八字：不产 bazi_fortune
    assert rows[0].payload == {"text": "早上好呀，今天适合聊聊星星"}


async def test_device_content_with_bazi_casts_chart_and_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkerStore()
    sign_row = DailySignFortune(
        fortune_date=TODAY, sign="scorpio", payload=dict(FORTUNE_PAYLOAD), llm_model="m"
    )
    bazi = OwnerBaziProfile(
        device_id=1,
        calendar_type="solar",
        birth_date=date(1995, 11, 8),
        birth_time=None,
        birth_place=None,
        gender=None,
        bazi_text=None,  # 空：先排盘缓存
    )
    _mock_device_queries(monkeypatch, profile=make_profile(), sign_fortune=sign_row, bazi=bazi)

    cast_calls: list[dict[str, Any]] = []

    async def fake_cast(settings: object, birth: dict[str, Any]) -> str:
        cast_calls.append(birth)
        return "乙亥年 丙戌月 癸卯日（时辰未知）"

    async def fake_generate(settings: object, context: dict[str, Any]) -> dict[str, Any]:
        assert context["owner_bazi"] == "乙亥年 丙戌月 癸卯日（时辰未知）"
        return {
            "greeting": "早上好呀",
            "bazi_fortune": {
                "overall": "总述",
                "career": "事业",
                "wealth": "财运",
                "study": "学业",
                "love": "情感",
            },
        }

    monkeypatch.setattr(worker_tasks, "generate_bazi_text", fake_cast)
    monkeypatch.setattr(worker_tasks, "generate_device_daily_content", fake_generate)

    await worker_tasks.daily_device_content_handler(
        {"device_id": 1, "date": TODAY.isoformat()},
        cast(AsyncSession, FakeWorkerSession(store)),
    )
    assert cast_calls[0]["birth_date"] == "1995-11-08"
    assert bazi.bazi_text == "乙亥年 丙戌月 癸卯日（时辰未知）"  # 排盘结果已缓存
    kinds = sorted(
        row.kind for row in store.added if isinstance(row, DeviceDailyContent)
    )
    assert kinds == ["bazi_fortune", "greeting"]


# ---------- worker：整合搜索（fortune_search_enabled=true） ----------


async def test_sign_fortune_handler_search_enabled_marks_digest_and_metaphysics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkerStore()
    _pin_settings(monkeypatch, search_enabled=True)

    async def fake_existing(session: AsyncSession, fortune_date: date) -> set[str]:
        return set()

    async def fake_generate(settings: object, fortune_date: date) -> dict[str, Any]:
        return {
            "source_digest": "黄历宜祭祀，星象平稳",
            "metaphysics": "今日宜祈福，吉时在午后",
            "signs": {
                sign: {
                    "overall": f"{sign} 总述",
                    "career": "事业",
                    "wealth": "财运",
                    "study": "学业",
                    "love": "情感",
                }
                for sign in SIGN_KEYS
            },
        }

    monkeypatch.setattr(worker_tasks, "_existing_fortune_signs", fake_existing)
    monkeypatch.setattr(worker_tasks, "generate_sign_fortunes", fake_generate)

    await worker_tasks.daily_sign_fortune_handler(
        {"date": TODAY.isoformat()}, cast(AsyncSession, FakeWorkerSession(store))
    )
    rows = [obj for obj in store.added if isinstance(obj, DailySignFortune)]
    assert len(rows) == 12
    for row in rows:
        assert "已联网检索" in row.payload["source_digest"]  # 区分检索来源（docs/12 §4）
        assert row.payload["metaphysics"] == "今日宜祈福，吉时在午后"  # payload 扩展键


# ---------- llm：MiniMax 服务端 web_search（Anthropic Messages API） ----------


def _mock_search_http(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """以 MockTransport 替代外发请求，返回捕获的请求体列表。"""
    import httpx

    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient  # patch 前捕获，避免 lambda 内自引用递归
    # llm 模块在调用时经 httpx.AsyncClient 查找，patch 模块属性即可生效
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport))
    return requests


def _search_settings() -> Settings:
    return Settings(
        llm_base_url="https://api.minimaxi.com/v1",
        llm_api_key="test-key",
        llm_model="MiniMax-M2.5",
    )


def test_web_search_evidence_extracts_digest_without_page_body() -> None:
    import agent_worker.llm as worker_llm

    executed, digest = worker_llm._web_search_evidence(
        [
            {"type": "text", "text": "今日宜祈福。"},
            {"type": "server_tool_use", "name": "web_search", "input": {"query": "今日黄历"}},
            {
                "type": "web_search_tool_result",
                "content": [
                    {"type": "web_search_result", "title": "黄历网", "content": "超长正文不应入库"},
                ],
            },
        ]
    )
    assert executed is True
    assert "今日宜祈福" in digest
    assert "黄历网" in digest
    assert "今日黄历" in digest
    assert "超长正文不应入库" not in digest


async def test_web_search_digest_parses_when_search_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_worker.llm as worker_llm

    requests = _mock_search_http(
        monkeypatch,
        {
            "content": [
                {"type": "thinking", "thinking": "（推理不外泄）"},
                {"type": "server_tool_use", "name": "web_search", "input": {"query": "x"}},
                {"type": "web_search_tool_result", "content": [{"title": "来源A"}]},
                {"type": "text", "text": "今日宜祈福。"},
            ]
        },
    )
    digest = await worker_llm._web_search_digest(_search_settings(), "搜今日黄历")
    assert "今日宜祈福" in digest
    assert "来源A" in digest
    assert requests[0]["model"] == "MiniMax-M3"  # M2.7/M2.5 不执行服务端检索
    assert requests[0]["tools"] == [{"type": "web_search_20250305", "name": "web_search"}]
    assert "tool_choice" not in requests[0]
    assert "system" not in requests[0]


async def test_web_search_digest_without_search_blocks_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_worker.llm as worker_llm

    _mock_search_http(
        monkeypatch,
        {"content": [{"type": "tool_use", "name": "plugin_web_search", "input": {}}]},
    )
    # M2.7/M2.5 降级为客户端 tool_use（未真正检索）：抛错走延迟重试，不静默降级
    with pytest.raises(worker_llm.LLMUnavailableError):
        await worker_llm._web_search_digest(_search_settings(), "搜今日黄历")


async def test_generate_sign_fortunes_routes_by_search_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_worker.llm as worker_llm

    called: list[str] = []
    search_payloads: list[str] = []

    async def fake_search(settings: Settings, query: str) -> str:
        called.append("search")
        return "已检索：宜祈福"

    async def fake_chat(settings: Settings, system: str, user: str) -> dict[str, Any]:
        called.append("chat")
        search_payloads.append(user)
        return {"signs": {}}

    monkeypatch.setattr(worker_llm, "_web_search_digest", fake_search)
    monkeypatch.setattr(worker_llm, "_chat_json", fake_chat)

    await worker_llm.generate_sign_fortunes(Settings(fortune_search_enabled=True), TODAY)
    await worker_llm.generate_sign_fortunes(Settings(fortune_search_enabled=False), TODAY)
    assert called == ["search", "chat", "chat"]
    assert "已检索：宜祈福" in search_payloads[0]


# ---------- worker：每日定时预生成（docs/12 §4） ----------


async def test_prefill_enqueues_missing_l1_and_l2(monkeypatch: pytest.MonkeyPatch) -> None:
    store = WorkerStore()

    async def fake_existing(session: AsyncSession, fortune_date: date) -> set[str]:
        return {"aries"}  # L1 未齐：需入队整合生成

    async def fake_claimed(session: AsyncSession) -> list[int]:
        return [1, 2, 3]

    async def fake_have(
        session: AsyncSession, device_ids: list[int], content_date: date, kind: str
    ) -> set[int]:
        return {2}  # 设备 2 当日 greeting 已存在：幂等跳过

    async def fake_quiz_kinds(session: AsyncSession, quiz_date: date) -> set[str]:
        return set()

    monkeypatch.setattr(worker_tasks, "_existing_fortune_signs", fake_existing)
    monkeypatch.setattr(worker_tasks, "_claimed_device_ids", fake_claimed)
    monkeypatch.setattr(worker_tasks, "_devices_with_content", fake_have)
    monkeypatch.setattr(worker_tasks, "_existing_quiz_kinds", fake_quiz_kinds)

    stats = await worker_tasks.prefill_daily_content(
        cast(AsyncSession, FakeWorkerSession(store)), TODAY
    )
    assert stats == {"daily_sign_fortune": 1, "daily_device_content": 2, "fun_quiz_generate": 1}
    tasks = [obj for obj in store.added if isinstance(obj, AgentTask)]
    assert tasks[0].kind == "daily_sign_fortune"
    assert tasks[0].payload == {"date": TODAY.isoformat()}
    l2 = [task for task in tasks if task.kind == "daily_device_content"]
    assert {task.payload["device_id"] for task in l2} == {1, 3}
    assert all(task.payload["date"] == TODAY.isoformat() for task in l2)


async def test_prefill_idempotent_when_content_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkerStore()

    async def fake_existing(session: AsyncSession, fortune_date: date) -> set[str]:
        return set(SIGN_KEYS)

    async def fake_claimed(session: AsyncSession) -> list[int]:
        return [1, 2]

    async def fake_have(
        session: AsyncSession, device_ids: list[int], content_date: date, kind: str
    ) -> set[int]:
        return {1, 2}

    async def fake_quiz_kinds(session: AsyncSession, quiz_date: date) -> set[str]:
        from pet_common.fun_quiz import QUIZ_KINDS

        return set(QUIZ_KINDS)

    monkeypatch.setattr(worker_tasks, "_existing_fortune_signs", fake_existing)
    monkeypatch.setattr(worker_tasks, "_claimed_device_ids", fake_claimed)
    monkeypatch.setattr(worker_tasks, "_devices_with_content", fake_have)
    monkeypatch.setattr(worker_tasks, "_existing_quiz_kinds", fake_quiz_kinds)

    stats = await worker_tasks.prefill_daily_content(
        cast(AsyncSession, FakeWorkerSession(store)), TODAY
    )
    assert stats == {
        "daily_sign_fortune": 0,
        "daily_device_content": 0,
        "fun_quiz_generate": 0,
    }
    assert store.added == []  # 内容齐全：不入队


def test_prefill_due_gates_on_cn_5am() -> None:
    from agent_worker import worker as worker_module

    before = datetime(2026, 8, 18, 20, 30, tzinfo=UTC)  # 东八区次日 04:30：未到 05:00
    after = datetime(2026, 8, 18, 21, 30, tzinfo=UTC)  # 东八区次日 05:30
    assert not worker_module.prefill_due(before, None)
    assert worker_module.prefill_due(after, None)


def test_prefill_due_interval_gating() -> None:
    from agent_worker import worker as worker_module

    now = datetime(2026, 8, 18, 22, 0, tzinfo=UTC)  # 东八区次日 06:00
    assert not worker_module.prefill_due(now, now - timedelta(minutes=5))
    assert worker_module.prefill_due(now, now - timedelta(minutes=16))


# ---------- get_daily_guidance：昨日回退（docs/12 §6） ----------


class ScalarQueueSession:
    """按调用顺序返回 scalar 结果（get_daily_guidance 的查询次序固定）。"""

    def __init__(self, results: list[object]) -> None:
        self._results = list(results)

    async def scalar(self, statement: object) -> object:
        return self._results.pop(0)


async def test_daily_guidance_today_content_no_fallback() -> None:
    from web_api import persona_service

    session = ScalarQueueSession([{"text": "今天的素材"}, {"overall": "今日顺"}])
    fragments = await persona_service.get_daily_guidance(
        cast(AsyncSession, session), 1, "scorpio"
    )
    assert fragments == [
        "今天开场时可以自然地提到：今天的素材",
        "今天聊天时可以自然地提到今日运势：今日顺",
    ]


async def test_daily_guidance_falls_back_to_recent_content() -> None:
    from web_api import persona_service

    session = ScalarQueueSession(
        [
            None,  # 当日 greeting 缺失
            {"text": "昨天聊到一半的星星话题"},  # 最近一期 greeting 回退
            None,  # 当日运势缺失
            {"overall": "昨日整体平顺"},  # 最近一期运势回退
        ]
    )
    fragments = await persona_service.get_daily_guidance(
        cast(AsyncSession, session), 1, "scorpio"
    )
    # 回退内容标注"今日早些时候"语义
    assert fragments == [
        "今天开场时可以延续今日早些时候的素材：昨天聊到一半的星星话题",
        "今天聊天时可以延续今日早些时候提到的运势：昨日整体平顺",
    ]


async def test_daily_guidance_empty_when_no_content_at_all() -> None:
    from web_api import persona_service

    session = ScalarQueueSession([None, None, None, None])
    fragments = await persona_service.get_daily_guidance(
        cast(AsyncSession, session), 1, "scorpio"
    )
    assert fragments == []  # 全无内容才返回空


# ---------- admin：GET /admin/devices/{id}/fortune/daily（只读） ----------


@pytest.fixture
def admin_client(store: Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    session = FakeSession(store)

    async def fake_get_device(s: AsyncSession, device_id: int) -> Device:
        return store.device

    async def fake_get_profile(s: AsyncSession, device_id: int) -> PersonaProfile | None:
        return store.profile

    async def fake_bazi(s: AsyncSession, device_id: int) -> OwnerBaziProfile | None:
        return store.bazi

    async def fake_sign_fortune(
        s: AsyncSession, fortune_date: date, sign: str
    ) -> DailySignFortune | None:
        return store.sign_fortunes.get((fortune_date, sign))

    async def fake_daily_content(
        s: AsyncSession, device_id: int, content_date: date, kind: str
    ) -> DeviceDailyContent | None:
        return store.contents.get((device_id, content_date, kind))

    monkeypatch.setattr(admin_router, "_get_device", fake_get_device)
    monkeypatch.setattr(admin_router, "get_profile", fake_get_profile)
    monkeypatch.setattr(admin_router, "_bazi_profile", fake_bazi)
    monkeypatch.setattr(admin_router, "_sign_fortune", fake_sign_fortune)
    monkeypatch.setattr(admin_router, "_daily_content", fake_daily_content)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_admin_daily_fortune_full_content_readonly(
    admin_client: TestClient, store: Store
) -> None:
    store.profile = make_profile()
    store.sign_fortunes[(TODAY, "scorpio")] = DailySignFortune(
        fortune_date=TODAY, sign="scorpio", payload=dict(FORTUNE_PAYLOAD), llm_model="m"
    )
    store.contents[(1, TODAY, "greeting")] = DeviceDailyContent(
        device_id=1, content_date=TODAY, kind="greeting", payload={"text": "早上好呀"}
    )

    resp = admin_client.get(
        "/api/admin/devices/1/fortune/daily", headers=auth_headers(role="admin")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generating"] is False
    assert body["sign_fortune"]["overall"] == FORTUNE_PAYLOAD["overall"]
    assert body["greeting"] == "早上好呀"
    assert body["bazi_fortune"] is None  # 未录八字：恒 null
    assert store.tasks == []  # 只读：不触发懒入队


def test_admin_daily_fortune_persona_not_configured_404(admin_client: TestClient) -> None:
    resp = admin_client.get(
        "/api/admin/devices/1/fortune/daily", headers=auth_headers(role="admin")
    )
    assert resp.status_code == 404


def test_admin_daily_fortune_requires_admin_role(admin_client: TestClient) -> None:
    resp = admin_client.get(
        "/api/admin/devices/1/fortune/daily", headers=auth_headers(role="user")
    )
    assert resp.status_code == 403
