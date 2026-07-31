# ai-pet-backend — AI Pet 业务后端

> 职责：用户/设备资产、星座×MBTI 知识库、PersonaCompiler、脱敏历史、记忆真源、Memory MCP、异步分析 Worker。  
> 产品母文档：`../ESP32_XIAOZHI/` 下业务设计 / 服务器需求 / 赛道决策  

## 本仓库不负责

- 实时 ASR/LLM/TTS 与 MQTT 会话 → 见 `../xiaozhi-server`
- 管理台前端页面 → 见 `../ai-pet-admin`
- 固件 MCP 实现 → 见 `../ESP32_XIAOZHI/xiaozhi-esp32`

## 建议模块划分（实现时可 monorepo）

| 模块 | 说明 |
|------|------|
| `web-api` | HTTP API：用户、设备、人设、历史、记忆、KB、分析 |
| `persona-compiler` | 元素→星座→MBTI 编译为 persona_pack |
| `memory-mcp` | 供小智/Agent 调用的记忆工具服务 |
| `agent-worker` | 摘要、记忆候选、KB 反馈候选（**禁止进实时语音路径**） |

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/00-文档索引与协作边界.md](./docs/00-文档索引与协作边界.md) | 三仓分工 |
| [docs/01-项目概述与范围.md](./docs/01-项目概述与范围.md) | 目标与版本 |
| [docs/02-数据模型与表结构.md](./docs/02-数据模型与表结构.md) | PG 表与索引规则 |
| [docs/03-人设与星座知识库.md](./docs/03-人设与星座知识库.md) | KB 分层、编译、发布 |
| [docs/04-记忆历史与分析.md](./docs/04-记忆历史与分析.md) | 脱敏、记忆、摘要 |
| [docs/05-Memory-MCP与Agent-Worker.md](./docs/05-Memory-MCP与Agent-Worker.md) | 工具与异步任务 |
| [docs/06-HTTP-API规范.md](./docs/06-HTTP-API规范.md) | 对外 API 清单 |
| [docs/07-开发任务清单.md](./docs/07-开发任务清单.md) | backlog |
| [docs/08-技术栈选型决策.md](./docs/08-技术栈选型决策.md) | 技术栈决策与依据（vibe coding 前提） |
| [docs/09-部署进度与运维.md](./docs/09-部署进度与运维.md) | 服务器、端口分配、部署状态与运维命令 |

## 与小智服务的关系

```text
设备 ──协议──► xiaozhi-server（实时）
                 │ 旁路事件 / 拉 persona_pack
                 ▼
              ai-pet-backend（本仓）
                 ▲
              ai-pet-admin（管理台）
```
