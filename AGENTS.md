# AGENTS.md — ai-pet-backend

> AI 协作入口。**先拉取根协作文档** `D:/Home_Work/work_dashboard/AI-Pet项目全景与进度.md`（第一信息源），再读 `D:/Home_Work/work_dashboard/AI-Pet协作看板.md`。
> 技术栈以 `docs/08-技术栈选型决策.md` 为最高优先级；表结构见 `docs/02`；API 契约见 `docs/06`。

## 技术栈决策摘要

- Python 3.12（本地开发允许 3.11+，`requires-python = ">=3.11"`）+ FastAPI + Pydantic v2
- SQLAlchemy 2.0（async + asyncpg）+ Alembic 异步迁移；数据库 PostgreSQL 16 + pgvector
- 队列：**PG `SKIP LOCKED`**（`agent_tasks` 表）；Redis 只做缓存
- Memory MCP：官方 Python MCP SDK，与后端同仓
- agent-worker：同代码库独立入口、独立容器、并发 = 1
- 日志：structlog JSON → stdout → Docker json-file 轮转（50m×5）
- CI 闸门：ruff + mypy(strict) + pytest，AI 产出过闸再进主干

## Monorepo 结构

单 `pyproject.toml`，src 布局。文档中的逻辑模块与代码包映射：

| 文档模块 | 代码包 | 入口 |
|----------|--------|------|
| `apps/web-api` | `src/web_api` | `uvicorn web_api.main:app` |
| `apps/memory-mcp` | `src/memory_mcp` | `python -m memory_mcp.server` |
| `apps/agent-worker` | `src/agent_worker` | `python -m agent_worker` |
| `packages/persona-compiler` | `src/persona_compiler` | 纯函数库，无入口 |
| 共享（settings/db/models/logging） | `src/pet_common` | 被以上三者引用 |

```
alembic/            # 异步迁移（env.py 从环境变量读 DATABASE_URL）
src/pet_common/     # config(pydantic-settings) / db(engine,session) / models(SQLAlchemy) / logging(structlog)
src/web_api/        # FastAPI 应用工厂、JWT 依赖、trace_id 日志中间件、routers/
src/memory_mcp/     # MCP server：memory.search / memory.add / memory.forget
src/agent_worker/   # PG SKIP LOCKED 消费循环 + 任务处理器注册表
src/persona_compiler/  # element/sign/mbti KB + overrides → persona_pack（纯函数）
tests/
```

## 业务红线（不可违反）

1. 对话只存 `content_redacted`，原始音频/原文不落库。
2. `source=agent` 的记忆默认 `status=candidate`，人审后才 `active`。
3. KB 发布必须 `version++`，Agent/Worker 不得直接 UPDATE `published` 行。
4. agent-worker **严禁**进入实时语音路径，只做队列异步任务。
5. 分页强制 `limit`（默认 20，上限 100），禁止无分页全表扫。
6. 日志不落对话原文，只记元数据（hash/长度）；固定字段 `ts/level/service/trace_id/device_id/session_id/kb_version`。
7. Agent 工具白名单：`memory.search` / `memory.add` / `memory.forget` 等，**无 shell / SQL / DBA 工具**。
8. 索引克制：每表 2~3 个；历史类查询走 `(device_id, created_at)` 复合索引短路径；向量只挂 `memories.embedding`。
9. 设备身份分离：`device_uid`（MAC/SN）仅供设备/小智；`devices.id` 是平台管理主键；app 只能以不可猜测的 `binding_id` 认领。admin 不得调用用户绑定接口或占用 `devices.user_id`。

## 常用命令

```bash
# 安装（虚拟环境）
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -e ".[dev]"

# 开发启动
uvicorn web_api.main:app --reload          # web-api，/healthz 探活
python -m memory_mcp.server                # memory-mcp（stdio）
python -m agent_worker                     # agent-worker（轮询 agent_tasks）

# 迁移（alembic.ini + alembic/env.py，URL 读 DATABASE_URL 环境变量）
alembic revision --autogenerate -m "xxx"   # 生成后必须人工 review
alembic upgrade head

# 质量闸门（提交前必跑）
ruff check src tests
mypy
pytest

# Docker
docker compose up -d --build               # postgres+redis+web-api+memory-mcp+agent-worker
```

## 依赖纪律

- 依赖钉版本：安装后 `pip freeze > requirements.lock` 进仓；新增依赖必须 review。
- Alembic migration 可由 AI 生成，**人工 review 后才执行**。
- 测试集中纯函数（persona-compiler、脱敏规则、KB 差分继承）——vibe coding 唯一不能省的投资。
