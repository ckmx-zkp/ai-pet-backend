# syntax=docker/dockerfile:1
# 多阶段构建：一份镜像三个入口（web-api / memory-mcp / agent-worker），
# 由 APP_SERVICE 环境变量区分（docker-compose 各服务分别设置）。

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_SERVICE=web-api

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

# APP_SERVICE: web-api | memory-mcp | agent-worker
CMD ["sh", "-c", "case \"$APP_SERVICE\" in \
  web-api) exec uvicorn web_api.main:app --host 0.0.0.0 --port 8000 ;; \
  memory-mcp) exec python -m memory_mcp.server ;; \
  agent-worker) exec python -m agent_worker ;; \
  *) echo \"unknown APP_SERVICE=$APP_SERVICE\" >&2; exit 1 ;; esac"]
