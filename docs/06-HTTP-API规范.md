# 06 — HTTP API 规范（首版）

> 前缀假设 `/api`。鉴权：用户 JWT；`/internal/*` 服务间 token。  
> 字段名实现时可微调，路径语义保持。

## 用户与设备

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录 |
| POST | `/auth/register` | 注册（若开放） |
| GET | `/devices` | 当前用户设备列表 |
| POST | `/devices/bind` | 绑定 device_uid |
| GET | `/devices/{id}` | 详情/能力/在线 |

## 人设与知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/devices/{id}/persona` | 读/写星座 MBTI 忌口钉扎 |
| POST | `/devices/{id}/persona/questionnaire` | 问卷提交（可选） |
| GET | `/admin/kb/zodiac` | 列表条目 |
| POST/PUT | `/admin/kb/zodiac/{id}` | 编辑 draft |
| POST | `/admin/kb/zodiac/{id}/publish` | 发布 |
| GET | `/admin/kb/feedback` | 反馈候选 |
| POST | `/admin/kb/feedback/{id}/accept` | 合并 |

## 历史 / 记忆 / 分析 / 外设

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/devices/{id}/messages?from&to&limit` | 历史 |
| DELETE | `/devices/{id}/messages` | 按条件删除 |
| GET/POST/PATCH/DELETE | `/devices/{id}/memories` | 记忆 CRUD |
| POST | `/devices/{id}/memories/{mid}/approve` | 候选通过 |
| GET | `/devices/{id}/analyses?kind=` | 分析结果 |
| GET | `/devices/{id}/peripheral` | 外设快照 |
| POST | `/devices/{id}/export` | 导出（建议 V0.2） |

## 内部接口（xiaozhi-server）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/internal/devices/{device_uid}/persona_pack` | 编译或读缓存 |
| POST | `/internal/chat/events` | 旁路消息 |
| POST | `/internal/peripheral/events` | 外设事件 |
| POST | `/internal/chat/sessions/{id}/end` | 触发摘要入队 |

## 错误约定

- `401/403` 鉴权  
- `404` 资源不存在  
- `409` 版本冲突（KB 发布）  
- `422` 校验失败  
- `503` 依赖降级（编译临时失败等）  
