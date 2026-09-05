#!/usr/bin/env bash
# 在服务器仓库根执行；沿用服务器 compose 与私有环境配置。
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo '已跟踪文件存在修改，请先核对，发布已停止。' >&2
  exit 1
fi
revision=$(git rev-parse HEAD)
image="ai-pet-backend-release:${revision}"
docker build --build-arg "VCS_REF=$revision" -t "$image" -t ai-pet-backend:local .
# 只更新三个应用服务，不重建数据库和 Redis；不隐式执行数据库迁移。
docker compose up -d --no-build --no-deps web-api memory-mcp agent-worker
python3 scripts/verify_release.py "$revision"
