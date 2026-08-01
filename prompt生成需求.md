# AI Pet 宠物形象生成需求

## 交付清单

| 优先级 | 素材 | 规格 | 验收结果 |
|---|---|---|---|
| P0 | 星仔主视觉全身立绘 | 透明 PNG，2048×2048 | 完整身体、3/4 正面、边缘留白、无文字 |
| P0 | 星仔头像 | 透明 PNG，1024×1024 | 与主视觉为同一角色，小尺寸仍清晰 |
| P0 | 表情组 | 8 张透明 PNG，1024×1024 | calm/happy/curious/sad/encourage/sleepy/surprised/thinking；配色与饰品一致 |
| P1 | 待机关键帧 | 4 张透明 PNG | 睁眼、半闭、闭眼、恢复；用于眨眼动效 |
| P1 | 首页场景 | 3 张 16:9 PNG/WebP | 晨间、夜晚、学习；右侧保留文字安全区 |
| P2 | 设备屏幕图 | 4 张 1:1 PNG，480×480 | 高对比、无小字、适合小屏 |

统一命名：`xingzai_[asset]_[emotion]_v01.png`。

## 固定角色设定

- 名称：星仔。
- 定位：温暖、好奇、有活力的 AI 智能宠物；不是拟真人、不是现有 IP 的仿制品。
- 外形：圆润小型数字宠物，柔和白色/奶油色主体，星空蓝与暖橙点缀，胸前或额头有星光识别元素，大而简洁的电子眼。
- 气质：亲近、可靠、轻盈、有探索欲；避免恐怖机械感、过分幼态或性感化。
- 画风：高品质 3D 动画电影/数字玩具质感，干净柔和棚拍光，适合中文 AI 陪伴产品。

## 主视觉生图 Prompt

```text
Create an original AI companion pet named “Xingzai”. A small, round, friendly digital pet with a soft ivory white body, deep starlight-blue details, subtle warm orange accents, and one distinctive glowing star-shaped light element on its chest. Large expressive electronic eyes, gentle smile, tiny rounded ears, compact full body, soft paws. Personality: warm, curious, energetic, trustworthy, comforting. High-end 3D animated film character design, polished matte material with subtle translucent glow, clean studio lighting, three-quarter front full-body pose, centered composition, transparent background, no text, no logo, no watermark, no UI, no props, 2048x2048. Original character design, consistent proportions suitable for a mobile app avatar and an embedded device screen.
```

负面提示词：

```text
human, child, anime girl, realistic animal, existing cartoon character, copyrighted character, aggressive expression, horror, weapon, sexualized body, cluttered background, text, letters, watermark, logo, cropped body, extra limbs, distorted face, blurry eyes, low resolution.
```

## 表情组 Prompt

主视觉定稿后上传为参考图，并追加：

```text
same Xingzai character identity, same color palette, same star chest light, same proportions, transparent background, no text.
```

| 表情键 | 追加描述 |
|---|---|
| calm | calm attentive expression, soft relaxed eyes, gentle neutral smile |
| happy | joyful warm smile, eyes sparkling, subtle celebratory posture |
| curious | curious tilted head, bright questioning eyes, slightly raised ears |
| sad | gentle empathetic concern, softened eyes, never crying dramatically |
| encourage | supportive confident smile, warm open gesture |
| sleepy | sleepy peaceful expression, half-closed eyes, cozy calm mood |
| surprised | pleasant small surprise, widened eyes, never frightened |
| thinking | thoughtful curious expression, looking slightly upward, subtle glow |

## 场景 Prompt

```text
The approved Xingzai character beside a softly glowing morning window, minimal cozy desk, subtle floating star particles, large empty space on the right for app text, premium 3D illustration, no text, no logo, 16:9.
```

夜间版本将 `morning window` 改为 `quiet nighttime room with moonlit blue palette and a gentle bedside lamp`；学习版本改为 `focused study session, small desk lamp, book shapes without readable text`。

## 角色档案文案：交给文本 AI 的 Prompt

```text
你是 AI 陪伴产品的角色设定编辑。请为原创 AI 宠物“星仔”写一份稳定、可长期使用的中文角色档案。

已知事实：星仔是温暖、好奇、有活力的 AI 智能宠物；视觉特征是圆润数字宠物、白色主体、星空蓝和暖橙点缀、胸前星光；它只依据用户明确确认的偏好逐步学习。

禁止：虚构具体主人姓名、性别、关系史、团队托付、真实人生经历、产品数据或夸大能力；禁止声称保存未经允许的隐私；禁止医疗或心理诊断承诺。

请仅输出 JSON：
{
  "identity": "不超过180字，第一人称自我介绍",
  "background": ["3-5条，每条不超过60字"],
  "roles": ["3-5条"],
  "goals": ["3-5条"],
  "evolution_rules": ["3-5条，强调确认后学习、可回退、不杜撰事实"],
  "relationship": "不超过100字，使用通用的主人/你描述，不虚构专属关系"
}
```

验收：JSON 可解析；无具体虚构事实；语气温暖不过度承诺；每个字段可直接写入后端 `dossier`。
