"""MBTI 短问卷：题面与计分均在 backend（docs/06 E2.1）。客户端只提交 a/b，不算型。"""

from typing import Literal

Side = Literal["E", "I", "S", "N", "T", "F", "J", "P"]


class QuizQuestion(dict[str, str]):
    """题面字典，便于 JSON 序列化。"""


QUESTIONS: tuple[QuizQuestion, ...] = (
    QuizQuestion(
        id="ei1",
        dimension="EI",
        prompt="有人找你说话时，你更自然的反应是？",
        a="马上接话，越聊越有劲",
        b="先听一会儿，想清楚再开口",
        a_trait="E",
        b_trait="I",
    ),
    QuizQuestion(
        id="ei2",
        dimension="EI",
        prompt="一屋子人都在热闹聊天，你会？",
        a="凑过去一起闹",
        b="找个角落陪着就好",
        a_trait="E",
        b_trait="I",
    ),
    QuizQuestion(
        id="ei3",
        dimension="EI",
        prompt="你恢复精力的方式更接近？",
        a="找人说说话",
        b="自己待一会儿",
        a_trait="E",
        b_trait="I",
    ),
    QuizQuestion(
        id="ei4",
        dimension="EI",
        prompt="第一次见新朋友，你通常？",
        a="先打招呼、主动介绍自己",
        b="等对方先开口",
        a_trait="E",
        b_trait="I",
    ),
    QuizQuestion(
        id="ei5",
        dimension="EI",
        prompt="亲近的人一天没理你，你更可能？",
        a="自己找话题凑上去",
        b="安静等对方回头看你",
        a_trait="E",
        b_trait="I",
    ),
    QuizQuestion(
        id="sn1",
        dimension="SN",
        prompt="听亲近的人讲烦心事，你先抓住的是？",
        a="具体发生了什么、下一步能做什么",
        b="这件事背后的感觉和可能性",
        a_trait="S",
        b_trait="N",
    ),
    QuizQuestion(
        id="sn2",
        dimension="SN",
        prompt="你更相信？",
        a="眼前能验证的事实",
        b="灵感和尚未发生的趋势",
        a_trait="S",
        b_trait="N",
    ),
    QuizQuestion(
        id="sn3",
        dimension="SN",
        prompt="给建议时你更习惯？",
        a="拆成可执行的小步骤",
        b="先讲全貌和意义",
        a_trait="S",
        b_trait="N",
    ),
    QuizQuestion(
        id="sn4",
        dimension="SN",
        prompt="回忆一天时，你先想起？",
        a="细节：吃了什么、说了哪句",
        b="气氛：今天整段感觉如何",
        a_trait="S",
        b_trait="N",
    ),
    QuizQuestion(
        id="sn5",
        dimension="SN",
        prompt="对方说“以后吧”，你理解成？",
        a="还没排进具体时间",
        b="心里已经有另一种可能",
        a_trait="S",
        b_trait="N",
    ),
    QuizQuestion(
        id="tf1",
        dimension="TF",
        prompt="两难选择时，你先问？",
        a="怎样更合理、后果是什么",
        b="怎样更不伤害人",
        a_trait="T",
        b_trait="F",
    ),
    QuizQuestion(
        id="tf2",
        dimension="TF",
        prompt="亲近的人做错事，你更想？",
        a="把问题讲清楚",
        b="先接住对方的情绪",
        a_trait="T",
        b_trait="F",
    ),
    QuizQuestion(
        id="tf3",
        dimension="TF",
        prompt="你觉得一句好话更应该？",
        a="准确、有用",
        b="温柔、被听见",
        a_trait="T",
        b_trait="F",
    ),
    QuizQuestion(
        id="tf4",
        dimension="TF",
        prompt="吵架之后你优先？",
        a="厘清对错和边界",
        b="修复关系和安全感",
        a_trait="T",
        b_trait="F",
    ),
    QuizQuestion(
        id="tf5",
        dimension="TF",
        prompt="给评价时你更怕？",
        a="说得含糊、不解决问题",
        b="说得太硬、伤到人",
        a_trait="T",
        b_trait="F",
    ),
    QuizQuestion(
        id="jp1",
        dimension="JP",
        prompt="一天的安排，你更喜欢？",
        a="先列好顺序再开始",
        b="走到哪算哪，随时改",
        a_trait="J",
        b_trait="P",
    ),
    QuizQuestion(
        id="jp2",
        dimension="JP",
        prompt="面对截止日期，你通常？",
        a="提前收尾，留余量",
        b="临近才进入最佳状态",
        a_trait="J",
        b_trait="P",
    ),
    QuizQuestion(
        id="jp3",
        dimension="JP",
        prompt="房间乱了，你会？",
        a="忍不住先收拾出一块整齐",
        b="不影响找东西就先放着",
        a_trait="J",
        b_trait="P",
    ),
    QuizQuestion(
        id="jp4",
        dimension="JP",
        prompt="旅行更吸引你的是？",
        a="行程清楚、少意外",
        b="留白、能即兴拐弯",
        a_trait="J",
        b_trait="P",
    ),
    QuizQuestion(
        id="jp5",
        dimension="JP",
        prompt="做决定时你更舒服？",
        a="尽快定下来并执行",
        b="多留几个选项再看",
        a_trait="J",
        b_trait="P",
    ),
)


def question_public_view() -> list[dict[str, str]]:
    """给客户端的题面：不含计分键。"""
    return [
        {
            "id": item["id"],
            "dimension": item["dimension"],
            "prompt": item["prompt"],
            "a": item["a"],
            "b": item["b"],
        }
        for item in QUESTIONS
    ]


def score_mbti(answers: list[str]) -> str:
    """按多数计分；平票取 E/S/T/J。非法长度或选项抛 ValueError。"""
    if len(answers) != len(QUESTIONS):
        raise ValueError(f"questionnaire requires exactly {len(QUESTIONS)} answers")
    tallies: dict[str, int] = {key: 0 for key in ("E", "I", "S", "N", "T", "F", "J", "P")}
    for question, raw in zip(QUESTIONS, answers, strict=True):
        choice = raw.strip().lower()
        if choice not in {"a", "b"}:
            raise ValueError("each answer must be 'a' or 'b'")
        trait = question["a_trait"] if choice == "a" else question["b_trait"]
        tallies[trait] += 1
    return (
        ("E" if tallies["E"] >= tallies["I"] else "I")
        + ("S" if tallies["S"] >= tallies["N"] else "N")
        + ("T" if tallies["T"] >= tallies["F"] else "F")
        + ("J" if tallies["J"] >= tallies["P"] else "P")
    )
