# 05 — Memory MCP 与 Agent Worker

## Memory MCP

供 `xiaozhi-server` 在会话中调用，底层读写业务库。

### 传输与鉴权契约

- 生产传输固定为 **streamable HTTP MCP**：`POST/GET /mcp`，由 `memory-mcp` 独立容器提供；本地命令仍可用 stdio 调试。
- 仅允许受控 Docker 内网访问，必须携带 `X-Internal-Token`；服务不映射公网端口。
- 工具一律传 `device_uid`（规范化小写 MAC/SN），不得传递或依赖平台自增 `devices.id`。
- 小智调用预算 800ms～1.5s；网络错误、401、5xx 或 MCP 协议错误均降级为无记忆会话，不阻塞语音/TTS。

### 建议工具

| 工具 | 行为 |
|------|------|
| `memory.search` | 按 device + query/tags；可吃 retrieval_hints |
| `memory.add` | 默认 candidate 或按参数 |
| `memory.forget` | 软删/归档，写审计 |

工具参数摘要：

| 工具 | 必填参数 | 结果 |
|------|----------|------|
| `memory.search` | `device_uid`, `query` | 仅返回该设备已审核 `active` 记忆，`limit` 上限 20 |
| `memory.add` | `device_uid`, `title`, `content` | 固定写 `source=agent,status=candidate`，不允许实时链路绕过审核 |
| `memory.forget` | `device_uid`, `memory_id` | 仅可归档该设备自身的记忆，并写审计 |

### 约束

- 超时短（如 800ms～1.5s），失败则对话降级无记忆  
- 不做浏览器、不跑重摘要  
- 鉴权：仅内网或带服务间 token  

## Agent Worker

队列消费者（Redis/PG skip locked 等均可）。

| 任务 | 产出 |
|------|------|
| 会话/日摘要 | `analysis_results` |
| 记忆提炼 | `memories` candidate |
| KB 反馈 | `kb_feedback_candidates` |
| 运势小记草稿 | `analysis_results` / daily_context 建议 |

### 严禁

- 与 `xiaozhi-server` 共享无限额进程打满 CPU/内存  
- 直接 `UPDATE` published KB  
- 同步插入实时 TTS 路径  

### Docker 建议

单独 container；`cpus`/`mem_limit` 低于实时面；并发 worker 数可配置为 1～2（样机）。

## 噱头 vs 提升（提醒）

- ✅ 异步整理资产、KB 候选  
- ❌ 「接了 Agent 对话更聪明」、通话中算星盘  
