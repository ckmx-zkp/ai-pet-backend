# 05 — Memory MCP 与 Agent Worker

## Memory MCP

供 `xiaozhi-server` 在会话中调用，底层读写业务库。

### 建议工具

| 工具 | 行为 |
|------|------|
| `memory.search` | 按 device + query/tags；可吃 retrieval_hints |
| `memory.add` | 默认 candidate 或按参数 |
| `memory.forget` | 软删/归档，写审计 |

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
