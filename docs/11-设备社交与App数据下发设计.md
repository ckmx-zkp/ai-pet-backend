# 11 — 设备社交 与 App 数据下发设计

> 版本：v1.1 · 日期：2026-08-19
> 范围：① 设备间 BLE 社交（好友）；② 设备数据下发 App 的可见性设计。
> 版本归属：社交 = **V0.3**（docs/01「首版不做社交」修订为 V0.3，见 §1.7）；App 数据下发 = V0.2 已有契约的明确化 + 推送后置。

---

## 1. 设备间社交（V0.3）

### 1.1 产品定义与业务流程

该能力用于两只机器人在主人外出时自然偶遇，不是 App/智控台发起的设备配对，也不是
xiaozhi-server 把两个实时语音会话互桥。完整状态机为：

```text
设备 A、B 低速 BLE 匿名广播并互相发现
                │
                ▼
其中一只机器人主动唤醒并询问主人是否同意打招呼
                │
         ┌──────┴──────┐
       拒绝             双方主人同意
  结束且不换 token          │
                           ▼
               A、B 通过 BLE 交换短期 social_token
                           │
                           ▼
            双方各自经 xiaozhi-server 上报 peer_token
                           │
                           ▼
       backend 匹配两份报告、生成本次双方要交换的内容
                           │
                           ▼
             两只机器人按受控内容播报并明确结束
```

主人同意是硬前置：任一方拒绝或超时，均不得交换 token、不得上报社交事件、不得建立好友。
前置主动播报属于本地 BLE 偶遇提示，不等于 E11 的远程主动播报能力。

### 1.2 BLE 发现与社交 token

- **发现广播与身份 token 分离**：同意前的低速 BLE 广播只携带协议版本、能力位和一次性
  `discovery_nonce`，不得携带可被 backend 解析为设备身份的 token、设备 UID 或固定标识。
- 双方主人同意后，设备才交换 `social_token`。token 必须短期有效、不可作为设备登录凭据、
  不得写日志或展示给用户。
- `social_token` 继续使用 backend 下发的 `social_secret` 派生滚动码；建议首版为
  `HMAC_SHA256(social_secret, time_slot)` 前 16 字节，时间槽 10 分钟。backend 只接受当前及
  有限相邻时间槽，并校验重放与重复报告。
- `discovery_nonce` 只用于把同一次物理偶遇的双方报告关联起来，不承担身份识别；
  `social_token` 只用于 backend 解析对端设备，不包含主人账号信息。
- `social_secret` 仅存设备与 backend；解绑/轮换后旧 token 失效。

### 1.3 上报、配对与内容生成

设备**不直连** backend（与 docs/08 单通道原则一致）。每一侧在交换 token 后，经设备控制通道
调用 xiaozhi-server 的 `social.encounter.report`，由其转发
`POST /api/internal/devices/{device_uid}/social/encounter-reports`。首份报告进入 `waiting_peer`，第二份互相匹配后进入
`generating`；backend 异步生成本次给 A、B 的受控播报内容，完成后状态为 `ready`。

设备按 `report_id` 轮询报告状态和自己的内容，播完后回执 `played`，双方完成或超时后事件进入
`finished`。内容由 backend 生成，首版禁止把 A 的实时麦克风/助理输出直接注入 B，也禁止机器人
自由循环对话。生成内容不得包含主人身份、原始 token、内部 Prompt 或未经脱敏的历史。

首版待产品/架构确认的参数：

1. 设备空闲时承载 `social.encounter.report` 与结果轮询的控制通道（独立 MQTTS/控制 WS，还是
   其他已有常驻通道）。语音 WS 已断开时不能假设可直接轮询。
2. backend 每次生成几段内容、双方最大播报轮数和总时长。
3. 播放完成/失败回执粒度，以及一方离线时另一方的收尾文案。
4. 双方同意如何在 BLE 协议中互相确认，避免单边同意即交换 token。

### 1.4 数据模型（目标态）

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

正式实现还需新增偶遇事件与单侧报告数据，用于幂等配对、生成状态、超时和播放回执；字段在
实现前随迁移设计确定，但至少包含 `report_id`、`encounter_id`、双方设备、`discovery_nonce`、
token 指纹、状态、生成内容引用和时间戳。原始 `social_token` 不落库，只保存不可逆指纹或解析结果。

### 1.5 API（草案已并入 docs/06，开发前再冻结 schema）

| 端点 | 用途 |
|------|------|
| `POST /api/internal/devices/{device_uid}/social/encounter-reports` | 小智转发单侧同意后的偶遇报告；返回 `report_id` 与状态 |
| `GET /api/internal/devices/{device_uid}/social/encounter-reports/{report_id}` | 查询匹配/生成状态；ready 时只返回该设备可播放内容 |
| `POST /api/internal/devices/{device_uid}/social/encounter-reports/{report_id}/ack` | 回执 played/failed，幂等结束本侧流程 |
| `GET /devices/{id}/friends` | 好友列表（宠物名、人设摘要、last_met_at、meet_count），统一分页 |
| `DELETE /devices/{id}/friends/{fid}` | 删除好友（隐私删除权） |

### 1.6 隐私红线

- 同意前广播不含身份 token；生成内容与好友信息绝不含主人账号信息。
- `social_enabled` 默认关；开启/关闭写 audit_logs。
- 主人拒绝/超时不得留下好友关系或可识别的社交事件；token 与生成正文不进日志。
- 好友关系对用户可见、可删；解绑设备时其 `device_social_keys` 行删除、friendships 置 blocked。

### 1.7 前置依赖与排期

- 固件：低速 BLE 匿名发现、主人同意状态机、同意后 token 交换均未开发。
- backend：偶遇报告/匹配/内容生成/回执模型与端点未实现（docs/10 仍归 **E9**）。
- xiaozhi-server：控制通道与 `social.encounter.report` 转发未实现；不承担实时会话桥。
- 开工顺序：先冻结 BLE 包格式、双边同意与控制通道，再冻结 docs/06 schema，随后按
  固件 → xiaozhi-server → backend 联调。当前只可做协议 spike 和内容生成离线原型，不可宣称可用。

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
