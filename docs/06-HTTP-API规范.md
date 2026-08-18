# 06 — HTTP API 规范

> 所有下列路径均为最终路径。鉴权：用户 JWT；`/api/internal/*` 服务间 token。
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

### 主人 vs 宠物（主体钉死）

- **宠物人设**挂设备：`GET/PUT /devices/{id}/persona` 的 `sun_sign` / `mbti` / `dossier` 只描述这只宠物，编译进 `persona_pack` 身份行。
- **主人档案**挂用户账号：一账号一份，该账号下全部设备共享。问卷、趣味测试、八字、星盘写入主人，不改宠物人设。
- 日运 L1 星座键取 **主人** `sun_sign`；问候语仍按该设备宠物口吻生成。

### `GET/PUT /owner` 与问卷

```json
{"sun_sign": "scorpio", "answers": ["a", "b", "a", "...共 20 项"]}
```

`answers` 必须与问卷题面等长，每项只能是 `a` 或 `b`。`sun_sign` 可选：提供则写入主人太阳星座（须为已发布键）。响应为主人档案，**不写** `persona_profiles`。客户端不得自行映射 MBTI。平票时该维取 E/S/T/J。

`GET /devices/{id}/persona/questionnaire` 与 `POST .../questionnaire` 仍可用（须设备归属），语义与 `/owner/questionnaire` 相同，只是用设备校验登录用户。

### `POST /devices/{id}/persona/preview`

body 与 PUT persona 相同。返回 `persona_pack` 7 字段，不写 `persona_profiles`，不入队
worker。未发布的星座/MBTI 仍 422。

### `POST /devices/{id}/export` 响应

```json
{
  "exported_at": "2026-08-18T12:00:00+00:00",
  "device": {"id": 1, "name": "星仔", "device_uid_redacted": true},
  "persona": {"sun_sign": "scorpio", "mbti": "ENFP", "follow_latest": true, "kb_version": 3},
  "owner": {"sun_sign": "capricorn", "mbti": "INFP", "quiz_results": {}},
  "bazi_recorded": true,
  "memories": [{"id": 1, "title": "...", "content": "...", "status": "active", "tags": []}],
  "messages": [{"id": 1, "role": "user", "content_redacted": "...", "created_at": "..."}],
  "analyses": [{"id": 1, "kind": "daily_summary", "payload": {}, "created_at": "..."}]
}
```

`device_uid`、八字生辰、JWT、内部 token 不进包。消息最多 200 条（按时间倒序），记忆与
分析各最多 100 条。

`GET /admin/devices/lookup` 的响应至少包含 `id`、`device_uid`、`binding_id`、`name`、
`online`、`firmware_version`、`capabilities` 与 `claimed`。该端点用于管理台读取和展示绑定码，
不得由此认领、解绑、轮换或推断用户身份；绑定码轮换仅允许专用 rotate 端点执行并写审计。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/devices/{id}/persona` | 读/写**宠物**星座、MBTI、忌口、钉扎与稳定角色档案 `dossier`；仅直选，问卷不走此表 |
| GET/PUT | `/owner` | 当前账号主人档案：`sun_sign` / `mbti` / `quiz_results`；未建档 GET 404 |
| GET | `/owner/questionnaire` | 主人 MBTI 问卷题面（20 题，四维各 5）；客户端只展示，不算型 |
| POST | `/owner/questionnaire` | 提交 `answers`；**MBTI 只在 backend 计分**；写入主人档案并返回 `/owner` 对象 |
| GET | `/devices/{id}/persona/questionnaire` | 与 `/owner/questionnaire` 相同（设备归属校验） |
| POST | `/devices/{id}/persona/questionnaire` | 与 `/owner/questionnaire` 相同；**写入主人，不改宠物人设** |
| POST | `/devices/{id}/persona/preview` | 编译预览：body 同 PUT，**不改库**，返回固定 7 字段 `persona_pack` |
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
| GET | `/devices/{id}/analyses?kind=&limit&offset` | 分析结果；`kind=memory_profile` 为 E6.1 画像卡片 |
| POST | `/devices/{id}/analyses/{aid}/apply-persona-growth` | 将 `persona_growth` 建议合并到该设备私有 `overrides`，写审计 |
| GET | `/devices/{id}/peripheral` | 外设快照 |
| POST | `/devices/{id}/export` | 导出我的数据（E8）：同步返回 JSON 包并落 `data_export` |
| GET | `/admin/ops/metrics` | 运营只读：近 24h/`pending`/`failed` 任务计数，按 kind 分组，不含原文 |

## 运势与八字（E10，设计见 docs/12）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/devices/{id}/bazi` | 主人八字读写（账号一份，经任一已归属设备访问）；未录入 GET 返回 404；PUT 覆盖写并触发该账号下已认领设备当日 `bazi_fortune` 重生成 |
| GET | `/devices/{id}/fortune/daily?date=` | 当日运势聚合；`date` 缺省为今天；当日内容缺失时后台懒入队、字段返回 null |
| GET | `/admin/devices/{id}/fortune/daily?date=` | 运营核对用当日运势聚合（只读，与用户版同结构同语义，不触发懒入队） |

### `PUT /devices/{id}/bazi` 请求

```json
{"calendar_type": "solar", "birth_date": "1995-11-08", "birth_time": "14:30", "birth_place": "北京", "gender": "female"}
```

`birth_time`（时辰未知）/`birth_place`/`gender` 可空；`calendar_type` 为 `solar|lunar`。
八字为敏感数据：响应与日志不回显完整生辰原文以外的派生内容，admin 无读取接口。

### `GET /devices/{id}/fortune/daily` 响应

```json
{
  "date": "2026-08-18",
  "sign": "scorpio",
  "sign_fortune": {"overall": "...", "career": "...", "wealth": "...", "study": "...", "love": "..."},
  "greeting": "今日开场素材",
  "bazi_fortune": {"overall": "...", "career": "...", "wealth": "...", "study": "...", "love": "..."},
  "generating": false
}
```

设备未配置**宠物**人设（无星座）返回 404。`sign` / `sign_fortune` 取主人 `sun_sign`（未录入则为
null，不回退宠物星座）。未录入八字时 `bazi_fortune` 为 null；当日内容尚未生成时
`generating: true` 且对应字段为 null，客户端显示"生成中"空态稍后重查。`sign_fortune` 为全站
共享内容，`greeting`/`bazi_fortune` 为该设备个性化生成（均异步产出，见 docs/12）。

## 趣味测试与简略星盘

默认只在 App 展示；用户明确选择后才写入记忆。测验题由 worker 每日预生成（每 kind 至多 1 套，
≤20 题），失败时用内置种子。星盘为测测风格简略版：太阳/月亮/水金火木土 + 有时辰与地点时的上升；
近星座换座点约 ±1°，不作专业占星。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/fun-quizzes?kind=&limit&offset` | 可作答测验列表（不含计分键） |
| GET | `/fun-quizzes/{id}` | 题面详情（不含 scores） |
| POST | `/fun-quizzes/{id}/submit` | 提交答案；返回结果 + `share_card`；`apply=memory` 时写入当前设备一条记忆 |
| GET | `/fun-quizzes/attempts/{aid}` | 回看一次作答（含 share_card） |
| GET/PUT | `/devices/{id}/natal-chart` | 简略星盘（账号一份）；PUT 覆盖计算并缓存，并回写主人 `sun_sign`；`use_bazi=true` 且八字为公历时可复用生辰 |

### `POST /fun-quizzes/{id}/submit`

```json
{"answers": ["a", "b", "a"], "device_id": 1, "apply": "none"}
```

`apply` ∈ `none|memory`。`memory` 必须带已归属的 `device_id`。无论 `apply`，作答都会写入当前
账号 `owner_profiles.quiz_results[kind]`（最近一次）。响应含 `result.title` /
`result.summary` / `share_card`（海报文案，App 本地绘成图再保存发朋友圈）。

### `PUT /devices/{id}/natal-chart`

```json
{"birth_date": "1995-11-08", "birth_time": "14:30", "birth_place": "北京", "use_bazi": false}
```

`birth_time` / `birth_place` 可空：无时辰或无法解析地点时不算上升。生辰只用于当次计算，
日志不记。响应为各星体的 `sign` + `degree_in_sign` + 一句解读 + `share_card`。

## 主动播报（E11，设计见 docs/13）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/devices/{id}/broadcast/prefs` | 播报配置：`enabled`（默认 false）、`kinds`（`care`/`fortune` 子集）、`send_window`（如 `08:00-21:00`，东八区） |
| POST | `/admin/devices/{id}/broadcast/test` | admin 下发测试播报：body 可带自定义 `text`（缺省内置测试句），写 `kind=test, priority=0` 消息，返回 `{id, status}`；状态经 admin 设备详情/专用查询查看 |

### `GET /api/internal/devices/{device_uid}/broadcasts/pending`（小智轮询）

返回该设备 `pending` 消息（按 priority、created_at 升序，`limit` 上限 5）：
`[{"id": 1, "kind": "care", "text": "...", "priority": 1}]`。设备离线时小智不拉取；消息由 backend
自产，不落对话历史、不经脱敏。

### `POST /api/internal/devices/{device_uid}/broadcasts/{id}/ack`

回执 `{"status": "delivered|played|failed"}`；`played` 写 `played_at`。仅允许 pending/delivered
状态的消息回执，其他状态 409。

## 内部接口（xiaozhi-server）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/internal/devices/{device_uid}/persona_pack` | 编译或读缓存 |
| POST | `/api/internal/chat/events` | 旁路消息（脱敏落库） |
| POST | `/api/internal/peripheral/events` | 外设事件（单行覆盖写） |
| POST | `/api/internal/chat/sessions/{id}/end` | 触发摘要入队（幂等） |
| POST | `/api/internal/devices/seen` | 设备首见登记/活跃上报；首次见到 MAC 时分配 app `binding_id` |
| GET | `/api/internal/context/device` | 小智 Context Provider；读取 `device-id` 请求头，返回动态短上下文 `{"code":0,"data":[]}`，未知/未认领设备也空成功降级 |
| GET | `/api/internal/devices/{device_uid}/broadcasts/pending` | 小智轮询拉取待播报消息（E11/docs/13） |
| POST | `/api/internal/devices/{device_uid}/broadcasts/{id}/ack` | 播报回执 delivered/played/failed（E11/docs/13） |

### `GET /api/internal/context/device`（小智 C5）

鉴权仍为 `X-Internal-Token`；小智上游自动传 `device-id: {device_uid}`。响应 `data` 最多 6
条、总计最多约 800 字符，只包含最近 36 小时的 `daily_summary`、可跟进事项及已确认的
`active` 记忆。稳定角色档案、星座/MBTI、KB 与已应用 overrides 已由 `persona_pack` 注入，
不得重复返回；接口不得同步调用 LLM、不得返回原始对话、候选记忆、敏感字段或内部 ID。

### `persona_pack` 响应 schema（钉死 7 字段）

设备不存在或尚未配置人设时返回 `404`；小智服务应加载本地安全 onboarding 人设并继续会话，
不得把 404 视为重试风暴或后端故障。已配置人设时才返回下列固定 7 字段。

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

> 2026-08-16 起，`system_prompt_fragments` 首条固定为编译层注入的身份行
> （"你的星座是天蝎座，MBTI 是 ENFP；被问到时自然承认……"），其后才是 KB 风格片段。
> 原因：KB v2 片段只描述沟通风格，模型在基础行为"不编造人设"约束下会否认自己有星座。
> 契约 7 字段不变，仅片段内容语义明确化。
>
> 2026-08-18（E10/docs/12）：`system_prompt_fragments` 末尾可追加当日个性化内容引导语
> （打招呼素材、当日星座运势总述），由编译层读 `device_daily_contents`/`daily_sign_fortunes`
> 拼入；契约 7 字段不变，小智侧无感知。

### `POST /api/internal/chat/events` 请求 schema（钉死 5 字段）

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

### `POST /api/internal/peripheral/events` 请求 schema

```json
{"device_uid": "aa:bb:cc:dd:ee:ff", "emotion": "happy", "gaze": "center", "closed": false, "extra": {}}
```

`device_peripheral_state` 一设备一行**全量覆盖写**（未提供的字段清空）；设备不存在 404；响应 204。

### `POST /api/internal/chat/sessions/{id}/end` 响应

路径 `{id}` 为 xiaozhi 侧字符串会话号（external_session_id）。置 `ended_at` 并入队
`agent_tasks`（`kind=daily_summary`，payload 含 `session_id`（内部 id）/`external_session_id`/`device_id`，`status=pending`）。
幂等：已结束的会话重复调用不重复入队。响应：`{"session_id": "sess-e3-test-001", "ended": true, "task_id": 123}`。

### `POST /api/internal/devices/seen` 请求/响应

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
