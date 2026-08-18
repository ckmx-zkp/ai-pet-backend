"""东八区切日工具：每日内容统一按 Asia/Shanghai 判定"今日"（docs/12 §4）。

中国自 1991 年起不实行夏令时，东八区固定偏移安全；zoneinfo 依赖 tzdata 包
（Windows 无系统时区库），已在 pyproject 依赖中钉版本。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")


def today_cn(now: datetime | None = None) -> date:
    """东八区的当前日期；now 缺省为当前时刻（可注入便于测试）。"""
    if now is None:
        now = datetime.now(CN_TZ)
    return now.astimezone(CN_TZ).date()
