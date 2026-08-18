# ruff: noqa: E501
"""趣味测验计分与对外题面（不含计分键）。"""

from typing import Any

QUIZ_KINDS = ("psychology", "astrology", "metaphysics")


def public_questions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    raw = payload.get("questions")
    if not isinstance(raw, list):
        return questions
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        options = []
        for option in item.get("options", []) if isinstance(item.get("options"), list) else []:
            if isinstance(option, dict) and option.get("key") and option.get("text"):
                options.append({"key": str(option["key"]), "text": str(option["text"])[:80]})
        prompt = str(item.get("prompt") or "").strip()
        if prompt and options:
            qid = str(item.get("id") or f"q{len(questions) + 1}")
            questions.append({"id": qid, "prompt": prompt[:200], "options": options})
    return questions


def score_fun_quiz(payload: dict[str, Any], answers: list[str]) -> dict[str, Any]:
    questions = payload.get("questions")
    archetypes = payload.get("archetypes")
    if not isinstance(questions, list) or not isinstance(archetypes, dict) or not archetypes:
        raise ValueError("quiz payload missing questions or archetypes")
    if len(answers) != len(questions[:20]):
        raise ValueError("answer count must match question count")
    tallies: dict[str, int] = {str(key): 0 for key in archetypes}
    for question, raw in zip(questions[:20], answers, strict=True):
        if not isinstance(question, dict):
            continue
        choice = raw.strip().lower()
        options = question.get("options")
        if not isinstance(options, list):
            raise ValueError("invalid quiz option")
        matched = False
        for option in options:
            if not isinstance(option, dict):
                continue
            if str(option.get("key", "")).strip().lower() != choice:
                continue
            matched = True
            scores = option.get("scores")
            if isinstance(scores, dict):
                for key, value in scores.items():
                    if key in tallies and isinstance(value, (int, float)):
                        tallies[key] += int(value)
            break
        if not matched:
            raise ValueError("each answer must match an option key")
    winner = max(tallies, key=lambda key: (tallies[key], key))
    arch = archetypes.get(winner)
    if not isinstance(arch, dict):
        raise ValueError("winning archetype missing")
    title = str(arch.get("title") or winner)[:40]
    summary = str(arch.get("summary") or "")[:200]
    share_line = str(arch.get("share_line") or summary)[:80]
    return {
        "archetype": winner,
        "title": title,
        "summary": summary,
        "share_line": share_line,
        "scores": tallies,
    }


def share_card_for(
    kind_label: str, title: str, summary: str, extra_tags: list[str] | None = None
) -> dict[str, Any]:
    tags = [kind_label, title]
    if extra_tags:
        tags.extend(extra_tags)
    return {
        "title": "我测出了",
        "result": title,
        "summary": summary,
        "tags": tags[:4],
        "footer": "AI Pet · 趣味测试",
        "theme": "dusk",
        "save_hint": "保存海报后发到朋友圈",
    }


SEED_QUIZZES: tuple[dict[str, Any], ...] = (
    {
        "kind": "psychology",
        "title": "你充电靠什么？",
        "subtitle": "8 道小题，看看你更外向还是更需要独处",
        "source": "seed",
        "payload": {
            "questions": [
                {
                    "id": "p1",
                    "prompt": "周末突然被约出门，第一反应是？",
                    "options": [
                        {
                            "key": "a",
                            "text": "好啊，人多才热闹",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {
                            "key": "b",
                            "text": "先看看还能不能改期",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
                {
                    "id": "p2",
                    "prompt": "累了之后你更想？",
                    "options": [
                        {
                            "key": "a",
                            "text": "找人说说话就活了",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {
                            "key": "b",
                            "text": "自己待一会儿才回血",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
                {
                    "id": "p3",
                    "prompt": "群聊一直在跳，你会？",
                    "options": [
                        {
                            "key": "a",
                            "text": "边看边回，生怕错过",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {"key": "b", "text": "静音，有空再翻", "scores": {"spark": 0, "harbor": 2}},
                    ],
                },
                {
                    "id": "p4",
                    "prompt": "认识新朋友时你通常？",
                    "options": [
                        {
                            "key": "a",
                            "text": "先开口，场面热起来",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {
                            "key": "b",
                            "text": "先听，觉得对味再靠近",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
                {
                    "id": "p5",
                    "prompt": "理想的晚上是？",
                    "options": [
                        {"key": "a", "text": "灯火和笑声", "scores": {"spark": 2, "harbor": 0}},
                        {
                            "key": "b",
                            "text": "灯暗一点，自己待着",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
                {
                    "id": "p6",
                    "prompt": "被夸奖时你更自然的是？",
                    "options": [
                        {
                            "key": "a",
                            "text": "当场接住，还能再聊两句",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {
                            "key": "b",
                            "text": "心里高兴，嘴上轻轻带过",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
                {
                    "id": "p7",
                    "prompt": "一天没人找你，你觉得？",
                    "options": [
                        {
                            "key": "a",
                            "text": "有点空，想主动撩一句",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {
                            "key": "b",
                            "text": "正好，世界安静很好",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
                {
                    "id": "p8",
                    "prompt": "恢复精力的最快方式？",
                    "options": [
                        {
                            "key": "a",
                            "text": "和喜欢的人待一起",
                            "scores": {"spark": 2, "harbor": 0},
                        },
                        {
                            "key": "b",
                            "text": "把门关上，谁也别来",
                            "scores": {"spark": 0, "harbor": 2},
                        },
                    ],
                },
            ],
            "archetypes": {
                "spark": {
                    "title": "社交小太阳",
                    "summary": "你靠人和热闹回血，一个人待太久会发蔫。",
                    "share_line": "测出来我是社交小太阳，独处会掉电。",
                },
                "harbor": {
                    "title": "静音充电桩",
                    "summary": "你需要自己的频率，热闹可以玩，回血还得安静。",
                    "share_line": "测出来我是静音充电桩，别一直喊我回消息。",
                },
            },
        },
    },
    {
        "kind": "astrology",
        "title": "你的星象气场更像谁？",
        "subtitle": "不看生日，只看你平时怎么待人",
        "source": "seed",
        "payload": {
            "questions": [
                {
                    "id": "a1",
                    "prompt": "朋友来找你诉苦，你先做的是？",
                    "options": [
                        {
                            "key": "a",
                            "text": "给方向、给步骤",
                            "scores": {"fire": 2, "earth": 1, "air": 0, "water": 0},
                        },
                        {
                            "key": "b",
                            "text": "先陪着，让对方把话说完",
                            "scores": {"fire": 0, "earth": 0, "air": 1, "water": 2},
                        },
                    ],
                },
                {
                    "id": "a2",
                    "prompt": "计划被打乱时？",
                    "options": [
                        {
                            "key": "a",
                            "text": "立刻另起一版接着干",
                            "scores": {"fire": 2, "earth": 1, "air": 1, "water": 0},
                        },
                        {
                            "key": "b",
                            "text": "先停一下，感觉对了再动",
                            "scores": {"fire": 0, "earth": 1, "air": 0, "water": 2},
                        },
                    ],
                },
                {
                    "id": "a3",
                    "prompt": "你更受不了别人？",
                    "options": [
                        {
                            "key": "a",
                            "text": "拖泥带水、不给准话",
                            "scores": {"fire": 2, "earth": 2, "air": 0, "water": 0},
                        },
                        {
                            "key": "b",
                            "text": "冷冰冰、不接情绪",
                            "scores": {"fire": 0, "earth": 0, "air": 1, "water": 2},
                        },
                    ],
                },
                {
                    "id": "a4",
                    "prompt": "聊天时你更常？",
                    "options": [
                        {
                            "key": "a",
                            "text": "跳话题、抛新点子",
                            "scores": {"fire": 1, "earth": 0, "air": 2, "water": 0},
                        },
                        {
                            "key": "b",
                            "text": "盯着一件事往深处聊",
                            "scores": {"fire": 0, "earth": 1, "air": 0, "water": 2},
                        },
                    ],
                },
                {
                    "id": "a5",
                    "prompt": "对承诺的态度？",
                    "options": [
                        {
                            "key": "a",
                            "text": "说了就尽量兑现",
                            "scores": {"fire": 1, "earth": 2, "air": 0, "water": 1},
                        },
                        {
                            "key": "b",
                            "text": "先看心情和缘分",
                            "scores": {"fire": 1, "earth": 0, "air": 2, "water": 1},
                        },
                    ],
                },
                {
                    "id": "a6",
                    "prompt": "你被形容成哪种天气更开心？",
                    "options": [
                        {
                            "key": "a",
                            "text": "大晴天或雷阵雨",
                            "scores": {"fire": 2, "earth": 0, "air": 1, "water": 0},
                        },
                        {
                            "key": "b",
                            "text": "薄雾或细雨",
                            "scores": {"fire": 0, "earth": 1, "air": 0, "water": 2},
                        },
                    ],
                },
                {
                    "id": "a7",
                    "prompt": "做决定靠什么？",
                    "options": [
                        {
                            "key": "a",
                            "text": "直觉冲一把",
                            "scores": {"fire": 2, "earth": 0, "air": 1, "water": 1},
                        },
                        {
                            "key": "b",
                            "text": "利弊列清楚",
                            "scores": {"fire": 0, "earth": 2, "air": 2, "water": 0},
                        },
                    ],
                },
                {
                    "id": "a8",
                    "prompt": "亲密关系里你更想被？",
                    "options": [
                        {
                            "key": "a",
                            "text": "看见光芒、一起往前冲",
                            "scores": {"fire": 2, "earth": 0, "air": 1, "water": 0},
                        },
                        {
                            "key": "b",
                            "text": "接住脆弱、给一个窝",
                            "scores": {"fire": 0, "earth": 1, "air": 0, "water": 2},
                        },
                    ],
                },
            ],
            "archetypes": {
                "fire": {
                    "title": "火相气场",
                    "summary": "启动快、情绪亮，适合被鼓励而不是被按头。",
                    "share_line": "测出来我是火相气场，别熄我。",
                },
                "earth": {
                    "title": "土相气场",
                    "summary": "稳、靠谱，变化可以有，但得给台阶。",
                    "share_line": "测出来我是土相气场，先让我站稳。",
                },
                "air": {
                    "title": "风相气场",
                    "summary": "脑子转得快，需要呼吸感和新角度。",
                    "share_line": "测出来我是风相气场，别把话题钉死。",
                },
                "water": {
                    "title": "水相气场",
                    "summary": "感受深、护边界，先被理解再谈方案。",
                    "share_line": "测出来我是水相气场，先接住我再讲道理。",
                },
            },
        },
    },
    {
        "kind": "metaphysics",
        "title": "你今天的玄学按钮",
        "subtitle": "宜忌趣味版，不当真，只助兴",
        "source": "seed",
        "payload": {
            "questions": [
                {
                    "id": "m1",
                    "prompt": "此刻更想求什么？",
                    "options": [
                        {"key": "a", "text": "顺一点、少碰壁", "scores": {"calm": 2, "spark": 0}},
                        {"key": "b", "text": "来点惊喜和好运", "scores": {"calm": 0, "spark": 2}},
                    ],
                },
                {
                    "id": "m2",
                    "prompt": "出门前你更可能？",
                    "options": [
                        {"key": "a", "text": "检查三遍再走", "scores": {"calm": 2, "spark": 0}},
                        {"key": "b", "text": "感觉对了就出门", "scores": {"calm": 0, "spark": 2}},
                    ],
                },
                {
                    "id": "m3",
                    "prompt": "看到「今日宜祈福」你会？",
                    "options": [
                        {
                            "key": "a",
                            "text": "心里默念一下图个安心",
                            "scores": {"calm": 2, "spark": 1},
                        },
                        {"key": "b", "text": "马上想去试试手气", "scores": {"calm": 0, "spark": 2}},
                    ],
                },
                {
                    "id": "m4",
                    "prompt": "选颜色当护身符，你拿？",
                    "options": [
                        {
                            "key": "a",
                            "text": "米白、浅灰，干净就好",
                            "scores": {"calm": 2, "spark": 0},
                        },
                        {
                            "key": "b",
                            "text": "赤金、朱红，亮一点",
                            "scores": {"calm": 0, "spark": 2},
                        },
                    ],
                },
                {
                    "id": "m5",
                    "prompt": "今晚更想？",
                    "options": [
                        {
                            "key": "a",
                            "text": "早点休息，把气养回来",
                            "scores": {"calm": 2, "spark": 0},
                        },
                        {
                            "key": "b",
                            "text": "熬一下，灵感还在线",
                            "scores": {"calm": 0, "spark": 2},
                        },
                    ],
                },
                {
                    "id": "m6",
                    "prompt": "有人说「你最近运势起伏」？",
                    "options": [
                        {
                            "key": "a",
                            "text": "那就少作死、走稳路",
                            "scores": {"calm": 2, "spark": 0},
                        },
                        {"key": "b", "text": "起伏才有故事", "scores": {"calm": 0, "spark": 2}},
                    ],
                },
            ],
            "archetypes": {
                "calm": {
                    "title": "今日宜养气",
                    "summary": "适合收一收、把节奏放慢，别硬刚。",
                    "share_line": "我的玄学按钮是今日宜养气。",
                },
                "spark": {
                    "title": "今日宜借运",
                    "summary": "适合轻轻试一把，别把好运想成必须兑现。",
                    "share_line": "我的玄学按钮是今日宜借运。",
                },
            },
        },
    },
)
