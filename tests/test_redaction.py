"""脱敏规则单测（pet_common.redaction，纯函数）：每类规则命中 + 不误伤普通文本。"""

from pet_common.redaction import redact_text


def test_phone_redacted() -> None:
    assert (
        redact_text("我的电话是13812345678，记得打给我") == "我的电话是[已脱敏:手机号]，记得打给我"
    )


def test_phone_prefix_boundary() -> None:
    # 非 1[3-9] 开头的 11 位数字不算手机号（如 12345678901）
    assert redact_text("编号12345678901") == "编号12345678901"


def test_id_card_redacted() -> None:
    text = "身份证号11010119900307123X别告诉别人"
    assert redact_text(text) == "身份证号[已脱敏:身份证号]别告诉别人"


def test_id_card_all_digits_redacted_as_id_not_bank() -> None:
    # 18 位纯数字证件号应先按身份证命中，而不是被银行卡规则（16~19 位）切走
    assert redact_text("110101199003071234") == "[已脱敏:身份证号]"


def test_email_redacted() -> None:
    assert redact_text("邮箱 xiao.ming+pet@example.com 收") == "邮箱 [已脱敏:邮箱] 收"


def test_bank_card_redacted() -> None:
    assert redact_text("卡号6222021001116242886") == "卡号[已脱敏:银行卡号]"


def test_plain_text_untouched() -> None:
    text = "今天天气真好，我想带小白去公园玩，花了 25 块钱，门牌 1001 号。"
    assert redact_text(text) == text


def test_short_numbers_untouched() -> None:
    # 普通长度数字（金额、年份、年龄）不误伤
    text = "2026年我3岁了，还有10086步要走"  # 10086 仅 5 位，不达银行卡下限
    assert redact_text(text) == text


def test_multiple_rules_in_one_text() -> None:
    text = "手机13900001111，邮箱a@b.co，卡号6222021001116242886"
    assert redact_text(text) == "手机[已脱敏:手机号]，邮箱[已脱敏:邮箱]，卡号[已脱敏:银行卡号]"
