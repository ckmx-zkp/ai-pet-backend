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

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录 |
| POST | `/auth/register` | 注册（若开放） |
| GET | `/devices?limit&offset` | 当前用户设备列表（名称/在线/固件版本/capabilities） |
| POST | `/devices/bind` | 绑定 device_uid（已绑定中冲突 409；已解绑设备执行重绑，保留原行与历史；写审计） |
| GET | `/devices/{id}` | 详情/能力/在线；越权访问他人或已解绑设备返回 404（不泄露存在性） |
| PATCH | `/devices/{id}` | 改名（`name`） |
| DELETE | `/devices/{id}` | 解绑：`user_id` 置空、历史数据保留、device_uid 可重绑（写审计） |

## 人设与知识库

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
| POST | `/internal/chat/events` | 旁路消息 |
| POST | `/internal/peripheral/events` | 外设事件 |
| POST | `/internal/chat/sessions/{id}/end` | 触发摘要入队 |

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
  "device_id": 1,
  "session_id": 10,
  "role": "user | assistant",
  "content": "...",
  "ts": "2026-08-01T12:00:00Z"
}
```

body 支持单条对象或对象数组（批量）。**脱敏由 backend 落库前执行**（docs/08 已决）：
只存 `content_redacted`，原文不落库、不落日志。

## 错误约定

- `401/403` 鉴权  
- `404` 资源不存在（含越权访问他人资源，不泄露存在性）  
- `409` 冲突（device_uid 绑定冲突、KB 发布版本冲突）  
- `422` 校验失败  
- `503` 依赖降级（编译临时失败等）  
