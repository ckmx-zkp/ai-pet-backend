# 11 — 设备社交 与 App 数据下发设计

> 版本：v1.0 · 日期：2026-08-01
> 范围：① 设备间 BLE 社交（好友）；② 设备数据下发 App 的可见性设计。
> 版本归属：社交 = **V0.3**（docs/01「首版不做社交」修订为 V0.3，见 §1.7）；App 数据下发 = V0.2 已有契约的明确化 + 推送后置。

---

## 1. 设备间社交（V0.3）

### 1.1 业务流程

```text
设备A ◄──BLE 社交广播（滚动 token）──► 设备B
                                         │ 捕获 token
                                         ▼ MQTT/MCP social.report
                                    xiaozhi-server
                                         │ POST /api/internal/social/events
                                         ▼
                          backend 解析 token → 认出设备A
                                         │
                    记录 B↔A 好友关系 ─────┤
                                         ▼
                          返回 A 的公开信息（宠物名+人设摘要）
```

### 1.2 社交 token：滚动码（强制，禁固定码）

- 绑定设备时 backend 生成 `social_secret` 随绑定响应下发（仅存设备与 backend）。
- 设备广播 `token = HMAC_SHA256(social_secret, time_slot)` 前 16 字节，**时间槽 10 分钟**，随 slot 滚动。
- backend 收到捕获 token 后，用候选设备的 secret 重放当前及前 2 个 slot 比对（容忍时钟漂移）；匹配即识别。
- 效果：广播内容周期性变化，外部嗅探无法关联追踪设备轨迹；仅 backend 可解析。
- `social_secret` 泄露处理：解绑即失效；重绑生成新 secret。

### 1.3 上传路径

设备**不直连** backend（与 docs/08 单通道原则一致）：设备经 MQTT 调 MCP 工具 `social.report` → xiaozhi-server 转发 `POST /api/internal/social/events`（`X-Internal-Token` 鉴权）。防刷：同一 device 上报频率限制（每分钟 ≤10 次，契约中注明）。

### 1.4 数据模型（新增 2 表）

**`device_social_keys`**（一设备一行）

| 字段 | 说明 |
|------|------|
| device_id (PK, FK) | |
| social_secret | 滚动码种子，仅 backend 与设备持有 |
| social_enabled | bool，默认 **false**（用户在 App 主动开启） |
| rotated_at | 上次轮换时间（运维观测用） |

**`device_friendships`**

| 字段 | 说明 |
|------|------|
| id (PK) | |
| device_id + friend_device_id | **联合唯一索引**；单向一条，查询时双向查 |
| first_met_at / last_met_at | |
| meet_count | 相遇次数（同一天去重后 +1） |
| status | active / blocked |

好友信息**不冗余存储**，展示时 join `devices`（宠物名）+ `persona_profiles`（人设摘要）。

### 1.5 API（契约待并入 docs/06）

| 端点 | 用途 |
|------|------|
| `POST /api/internal/social/events` | 小智转发：{device_id, token, ts} → 解析、记好友、返回对方公开信息 |
| `GET /devices/{id}/friends` | 好友列表（宠物名、人设摘要、last_met_at、meet_count），统一分页 |
| `DELETE /devices/{id}/friends/{fid}` | 删除好友（隐私删除权） |

### 1.6 隐私红线

- 广播内容与返回信息**只含宠物名 + 人设摘要**，绝不含主人账号信息。
- `social_enabled` 默认关；开启/关闭写 audit_logs。
- 好友关系对用户可见、可删；解绑设备时其 `device_social_keys` 行删除、friendships 置 blocked。

### 1.7 前置依赖与排期

- 固件：BLE 广播/扫描（未开发）——因此社交无法早于 V0.3 联调
- backend：表迁移 + 3 端点 + 绑定流程下发 secret（docs/10 记为 **E9**）
- xiaozhi-server：`social.report` MCP 工具转发
- **现在就要做的**：E2 前的某次迁移中把两表建掉（成本低），绑定响应预留 `social_secret` 字段——避免已绑定设备将来补发密钥

---

## 2. App 数据下发与可见性

### 2.1 原则

- App 一律经 HTTPS 用户 API **拉取**（JWT），快照轮询，不用 WebSocket（app docs/05 已定）。
- 可见性分三级：**用户可见可编辑 / 用户可见只读 / 内部不可见**。
- 脱敏红线：`chat_messages` 只出 `content_redacted`；prompt 片段、KB 原文、审计、internal 数据永不下发。

### 2.2 下发内容矩阵

| 数据 | API | 用户可见性 | 说明 |
|------|-----|-----------|------|
| 设备名/在线/last_seen/固件/capabilities | `GET /devices`、`GET /devices/{id}` | 可见可编辑（仅名称） | 在线状态以后端镜像为准，小智侧是真源 |
| 人设：星座/MBTI/忌口/follow_latest/kb_version | `GET/PUT /devices/{id}/persona` | 可见可编辑 | kb_version 展示"当前版本"，钉扎语义给开关 tooltip |
| persona_pack（编译产物） | 仅 `/api/internal/*` | **不可见** | 含 prompt 片段，属系统内部 |
| 对话历史 | `GET/DELETE /devices/{id}/messages` | 可见只读 + 可删 | 按日分组、分页；按日删除二次确认+审计 |
| 记忆 | memories CRUD + approve/reject | 可见可编辑 | candidate 需用户审核通过/驳回；source（manual/agent）打标展示 |
| 分析（日摘要/日运/情绪标签） | `GET /devices/{id}/analyses?kind=` | 可见只读 | 卡片流；含"生成中/失败"状态 |
| 外设状态（emotion/gaze/closed） | `GET /devices/{id}/peripheral` | 可见只读 | 快照轮询即可 |
| 好友（V0.3） | `GET /devices/{id}/friends` | 可见 + 可删 | 只展示对方宠物名+人设摘要 |
| KB 原文/审计/agent 队列/internal 事件 | — | **不可见** | admin 侧 KB 运营也不经 App |

### 2.3 下发方式与节奏

| 方式 | 用于 | 版本 |
|------|------|------|
| 拉取（进页面/下拉刷新） | 全部上述数据 | V0.2 |
| 推送通知（FCM/APNs） | "今日摘要已生成""有新的记忆候选待审核" | V0.3+（需新增 `POST /devices/{id}/push_tokens` 端点与 worker 推送任务，届时补契约） |

### 2.4 离线行为（app docs/05 已定，后端配合点）

- 设备离线时人设/记忆仍可编辑——后端 PUT/POST 不校验设备在线，App 自行展示状态条。
- 分页强制 limit（≤100），App 不无限缓存全量历史。

---

## 3. 人设初始化与下发流程（V0.2）

### 3.1 完整链路

```text
设备绑定（E1）
   │ App：GET persona → 未初始化（unset）→ 进入初始化引导
   ▼
初始化二选一：
  A. 做题：MBTI 短问卷 → POST /owner/questionnaire（或设备路径别名）
     → backend 按规则算型，写入 owner_profiles（主人，账号一份）；不改宠物人设
  B. 直选宠物：太阳星座 + MBTI + 忌口 → PUT /devices/{id}/persona
   ▼
backend：persona_profiles 落库（kb_version 取当前 published，follow_latest 默认开）
   → PersonaCompiler 编译 → persona_pack 就绪（含 default_emotion、retrieval_hints）
   │ 拉取式下发：小智在每次会话开始时 GET /api/internal/devices/{uid}/persona_pack
   ▼
xiaozhi-server 缓存 persona_pack → 注入 system prompt → 设备按此人设对话
```

### 3.2 关键规则

| 规则 | 说明 |
|------|------|
| 未初始化兜底 | persona 未设置时，persona_pack 返回**安全默认人设**（温和通用型 + `persona_state: "unset"` 标记），设备开箱即可对话；App 凭此标记弹初始化引导 |
| 下发方向 | **拉取式**（小智会话开始时拉），backend 不主动推。人设变更后最迟于"下次会话开始"生效——与"人设滞后展现"的设计一致 |
| 缓存刷新（V0.2 简化） | 小智每次会话开始都重新拉取并覆盖缓存，无需失效通知；主动失效 webhook 列入 V0.3 备选 |
| 问卷算型 | 问卷→MBTI 的映射规则放 backend（persona-compiler 包），App 只收答案不算型；结果写入主人档案，可用 `PUT /owner` 再改；宠物 MBTI 只能直选 |
| 修改路径 | 初始化后随时 `PUT persona` 修改；每次修改重编译，kb_version 依 follow_latest 策略 |

### 3.3 各端职责

- **App**：初始化引导页（检测 unset → 做题或直选）、人设展示与修改
- **backend**：问卷算型、persona 存储、编译、persona_pack 下发
- **小智**：拉取 + 缓存 + 注入，不理解人设内容
- **固件**：零参与（default_emotion 经小智 MCP 控眼下达到眼睛）
