# 06 — HTTP API 规范

> 前缀假设 `/api`。鉴权：用户 JWT；`/internal/*` 服务间 token。  
> 字段名实现时可微调，路径语义保持。

## 通用约定

### 分页

所有列表端点统一分页参数：`limit`（默认 20，最大 100，红线 5）+ `offset`（默认 0）。
选型说明：首版用 `offset` 而非游标——列表规模小、实现简单；若后续历史类大表翻页出现深分页问题，再对单个端点升级游标（契约另行标注）。
响应为数组，首版不包 `total`。

### 设备在线状态

在线状态**以 xiaozhi 侧实时连接为准**；backend 只镜像 `devices.online_at`
（由 chat events / 心跳写入，E3 起）。E1 阶段 `online` 字段按 `online_at` 阈值粗判，
xiaozhi 未接入前恒为 `false`。

## 用户与设备

### 设备身份与归属（钉死）

- `device_uid`：设备硬件核心标识，即规范化 MAC/SN；仅供设备、小智与服务间接口使用，
  全局唯一，**不是** app 的绑定凭据。
- `devices.id`：后端平台管理 ID，仅作服务端关系主键与管理端运维定位；app 不得以连续数字
  ID 申请设备归属。
- `binding_id`：后端在首次见到 `device_uid` 时生成的独立、不连续、不可猜测绑定标识
  （UUID/随机码，适合二维码）；app 仅用它发起认领。它与 MAC 和平台管理 ID 均独立。
- `devices.user_id` 仅表示当前 app 用户归属。admin 不得调用用户绑定接口、不得占用该字段；
  管理台设备登记/诊断使用独立 `/admin/devices/*` 接口（后续 Epic），不改变用户归属。

绑定流程：小智 `devices/seen` 以 MAC 建立未认领设备 → 后端分配 `binding_id` → app 扫码/输入
`binding_id` → 后端写入 `devices.user_id`。解绑仅将 `user_id` 置空，`binding_id` 与历史保留。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录 |
| POST | `/auth/register` | 注册（若开放） |
| GET | `/devices?limit&offset` | 当前用户设备列表（名称/在线/固件版本/capabilities） |
| POST | `/devices/bind` | 以 `binding_id` 认领设备；已认领冲突 409；admin 调用 403；已解绑设备可重绑，保留原行与历史并写审计 |
| GET | `/devices/{id}` | 详情/能力/在线；越权访问他人或已解绑设备返回 404（不泄露存在性） |
| PATCH | `/devices/{id}` | 改名（`name`） |
| DELETE | `/devices/{id}` | 解绑：`user_id` 置空、历史数据保留、device_uid 可重绑（写审计） |

### `POST /devices/bind` 请求

```json
{"binding_id": "7b8d5c9e4bc94d47a244d4e6ff0c24e2", "name": "小白"}
```

`binding_id` 未找到返回 404；已被任一用户认领返回 409；仅 `role=user` 可调用，admin
返回 403。后端不会由此接口新建设备资产。

## 人设与知识库

### 管理端设备资产与授权

管理端路由均要求 `role=admin`，只用于运营/诊断，**不改变** `devices.user_id`，不复用用户
绑定接口。涉及用户内容时仅返回已脱敏消息，所有写操作写入 `audit_logs`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/devices?limit&offset&q` | 全量设备资产分页；`q` 匹配平台 ID、MAC、名称或 binding_id；返回绑定码与是否已认领，不返回用户身份 |
| GET | `/admin/devices/lookup?device_uid=` | 按规范化设备核心 ID（MAC/SN）精确查询单个资产及当前 `binding_id`；仅 admin 可用，不返回用户身份；不存在返回 404 |
| GET | `/admin/devices/{id}` | 设备资产详情/能力/在线镜像/当前 binding_id |
| POST | `/admin/devices/{id}/binding-id/rotate` | 生成新的 binding_id，旧码立即失效；不改变用户归属，写审计 |
| GET/PUT | `/admin/devices/{id}/persona` | 管理端读取/修改已认领设备人设；未认领设备返回 409；写操作审计 |
| GET | `/admin/devices/{id}/messages?from&to&limit&offset` | 只读脱敏历史 |
| GET | `/admin/devices/{id}/memories?q&status&limit&offset` | 记忆列表与审核操作（见下表） |
| GET | `/admin/devices/{id}/analyses?kind=&limit&offset` | 分析结果列表 |
| GET | `/admin/devices/{id}/peripheral` | 外设状态快照 |

`GET /admin/devices/lookup` 的响应至少包含 `id`、`device_uid`、`binding_id`、`name`、
`online`、`firmware_version`、`capabilities` 与 `claimed`。该端点用于管理台读取和展示绑定码，
不得由此认领、解绑、轮换或推断用户身份；绑定码轮换仅允许专用 rotate 端点执行并写审计。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/devices/{id}/persona` | 读/写星座 MBTI 忌口钉扎 |
| POST | `/devices/{id}/persona/questionnaire` | 问卷提交（可选） |
| GET | `/admin/kb/zodiac?limit&offset` | 列表条目 |
| POST/PUT | `/admin/kb/zodiac/{id}` | 编辑 draft |
| POST | `/admin/kb/zodiac/{id}/publish` | 发布 |
| GET | `/admin/kb/feedback?limit&offset` | 反馈候选 |
| POST | `/admin/kb/feedback/{id}/accept` | 合并 |
| POST | `/admin/kb/feedback/{id}/ignore` | 忽略候选（不合并，关闭该候选） |

KB 条目遵循不可变发布：`POST /admin/kb/zodiac`、`POST /admin/kb/mbti` 自动以同键的
下一版本创建 `draft`；只有 `draft` 可编辑或发布，发布后不得更新。`GET` 支持
`status`、键与分页筛选。MBTI 与星座路径对称：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/admin/kb/zodiac` | 查询/创建星座、元素或宫位 draft |
| PUT | `/admin/kb/zodiac/{id}` | 编辑 draft |
| POST | `/admin/kb/zodiac/{id}/publish` | 发布 draft 版本 |
| GET/POST | `/admin/kb/mbti` | 查询/创建 MBTI draft |
| PUT | `/admin/kb/mbti/{id}` | 编辑 draft |
| POST | `/admin/kb/mbti/{id}/publish` | 发布 draft 版本 |

## 历史 / 记忆 / 分析 / 外设

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/devices/{id}/messages?from&to&limit&offset` | 历史 |
| DELETE | `/devices/{id}/messages` | 按条件删除 |
| GET | `/devices/{id}/memories?q&status&limit&offset` | 记忆列表；`q` 标题/正文模糊，`status` 筛选（candidate/active/...） |
| POST/PATCH/DELETE | `/devices/{id}/memories[/{mid}]` | 记忆写入/编辑/删除 |
| POST | `/devices/{id}/memories/{mid}/approve` | 候选通过（candidate → active） |
| POST | `/devices/{id}/memories/{mid}/reject` | 候选驳回（candidate → rejected；写审计） |
| GET | `/devices/{id}/analyses?kind=&limit&offset` | 分析结果 |
| GET | `/devices/{id}/peripheral` | 外设快照 |
| POST | `/devices/{id}/export` | 导出（建议 V0.2） |

## 内部接口（xiaozhi-server）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/internal/devices/{device_uid}/persona_pack` | 编译或读缓存 |
| POST | `/internal/chat/events` | 旁路消息（脱敏落库） |
| POST | `/internal/peripheral/events` | 外设事件（单行覆盖写） |
| POST | `/internal/chat/sessions/{id}/end` | 触发摘要入队（幂等） |
| POST | `/internal/devices/seen` | 设备首见登记/活跃上报；首次见到 MAC 时分配 app `binding_id` |

### `persona_pack` 响应 schema（钉死 7 字段）

```json
{
  "kb_version": 3,
  "system_prompt_fragments": ["..."],
  "style_constraints": ["..."],
  "taboo": ["..."],
  "default_emotion": "calm",
  "blink_profile": {"interval_ms": 3200, "duration_ms": 180},
  "retrieval_hints": ["..."]
}
```

### `POST /internal/chat/events` 请求 schema（钉死 5 字段）

```json
{
  "device_uid": "aa:bb:cc:dd:ee:ff",
  "session_id": "sess-e3-test-001",
  "role": "user | assistant",
  "content": "...",
  "ts": "2026-08-01T12:00:00Z"
}
```

body 支持单条对象或对象数组（批量）。**脱敏由 backend 落库前执行**（docs/08 已决）：
只存 `content_redacted`，原文不落库、不落日志。

- **设备标识统一用 `device_uid`（MAC）**：小智侧只持有 MAC，不知道 backend 自增 id；
  与 `persona_pack` 路径参数保持一致（本表早先草稿写作 `device_id`，以此为准）。
- **`session_id` 为字符串**（小智侧分配、全局唯一，UUID 风格如 `"sess-e3-test-001"`）：
  backend 存 `chat_sessions.external_session_id`（唯一索引），首次见自动建行；
  backend 内部自增 id **不暴露给小智**，仅作 `chat_messages.session_id` 外键；
  事件的 `ts` 写入 `chat_messages.created_at`（该表无独立 ts 列）。
- 未知设备 404（批量时任一未知整体不落库）；session 已存在但属于其他设备 404。
- 响应：`{"accepted": n}`；每批镜像 `devices.online_at`（无 last_seen_at 列，online_at 兼任）。

### `POST /internal/peripheral/events` 请求 schema

```json
{"device_uid": "aa:bb:cc:dd:ee:ff", "emotion": "happy", "gaze": "center", "closed": false, "extra": {}}
```

`device_peripheral_state` 一设备一行**全量覆盖写**（未提供的字段清空）；设备不存在 404；响应 204。

### `POST /internal/chat/sessions/{id}/end` 响应

路径 `{id}` 为 xiaozhi 侧字符串会话号（external_session_id）。置 `ended_at` 并入队
`agent_tasks`（`kind=daily_summary`，payload 含 `session_id`（内部 id）/`external_session_id`/`device_id`，`status=pending`）。
幂等：已结束的会话重复调用不重复入队。响应：`{"session_id": "sess-e3-test-001", "ended": true, "task_id": 123}`。

### `POST /internal/devices/seen` 请求/响应

```json
{"device_uid": "aa:bb:cc:dd:ee:ff", "firmware_version": "1.2.3", "capabilities": {"screen": true}}
```

设备首见登记：`device_uid` 不存在则建行（`user_id=NULL` 待认领，同时生成独立的 app
`binding_id`，与 `/devices/bind` 重绑逻辑兼容）；
已存在则更新 `online_at` 及可选字段（`firmware_version`/`capabilities`，仅提供时更新）。
响应：`{"id": 1, "device_uid": "...", "binding_id": "...", "created": true|false}`。

## 错误约定

- `401/403` 鉴权  
- `404` 资源不存在（含越权访问他人资源，不泄露存在性）  
- `409` 冲突（device_uid 绑定冲突、KB 发布版本冲突）  
- `422` 校验失败  
- `503` 依赖降级（编译临时失败等）  
