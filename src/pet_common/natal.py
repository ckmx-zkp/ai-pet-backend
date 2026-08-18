"""简略西洋星盘（测测风格）：太阳/月亮/水金火木土 + 可选上升。

算法为 Meeus 摘要 + J2000 开普勒根数，精度按「落在哪个星座」设计，
换座点附近约 ±1°。不作专业占星、不引入瑞士星历依赖。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

SIGN_KEYS = (
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
)

SIGN_NAMES_ZH = {
    "aries": "白羊座",
    "taurus": "金牛座",
    "gemini": "双子座",
    "cancer": "巨蟹座",
    "leo": "狮子座",
    "virgo": "处女座",
    "libra": "天秤座",
    "scorpio": "天蝎座",
    "sagittarius": "射手座",
    "capricorn": "摩羯座",
    "aquarius": "水瓶座",
    "pisces": "双鱼座",
}

PLANET_ROLES = {
    "sun": "自我与生命力",
    "moon": "情绪与安全感",
    "mercury": "说话和脑子转的方式",
    "venus": "审美与靠近人的方式",
    "mars": "行动和生气时的脾气",
    "jupiter": "扩张与好运感",
    "saturn": "规则、压力和成长课题",
    "ascendant": "别人第一眼看见的你",
}

# 常见出生地（东八区城市为主），只用于上升；未知城市则不算上升。
CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.90, 116.41),
    "上海": (31.23, 121.47),
    "广州": (23.13, 113.26),
    "深圳": (22.54, 114.06),
    "成都": (30.57, 104.07),
    "杭州": (30.25, 120.17),
    "武汉": (30.59, 114.31),
    "西安": (34.26, 108.94),
    "南京": (32.06, 118.80),
    "重庆": (29.56, 106.55),
    "天津": (39.13, 117.20),
    "苏州": (31.30, 120.62),
    "长沙": (28.23, 112.94),
    "郑州": (34.75, 113.63),
    "青岛": (36.07, 120.38),
    "大连": (38.91, 121.61),
    "厦门": (24.48, 118.09),
    "昆明": (25.04, 102.71),
    "哈尔滨": (45.76, 126.64),
    "沈阳": (41.81, 123.43),
    "合肥": (31.82, 117.23),
    "福州": (26.07, 119.30),
    "济南": (36.65, 117.12),
    "南昌": (28.68, 115.86),
    "南宁": (22.82, 108.37),
    "太原": (37.87, 112.55),
    "石家庄": (38.04, 114.51),
    "呼和浩特": (40.84, 111.75),
    "乌鲁木齐": (43.83, 87.62),
    "拉萨": (29.65, 91.17),
    "兰州": (36.06, 103.83),
    "银川": (38.49, 106.23),
    "西宁": (36.62, 101.78),
    "海口": (20.04, 110.20),
    "三亚": (18.25, 109.50),
    "香港": (22.32, 114.17),
    "澳门": (22.20, 113.54),
    "台北": (25.03, 121.57),
}


def _norm360(value: float) -> float:
    return value % 360.0


def _sind(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cosd(deg: float) -> float:
    return math.cos(math.radians(deg))


def julian_day(moment: datetime) -> float:
    """公历日期时间 → 儒略日（UT）。"""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    year, month = moment.year, moment.month
    day = (
        moment.day
        + (moment.hour + moment.minute / 60.0 + moment.second / 3600.0) / 24.0
    )
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    gregorian = 2 - century + century // 4
    return (
        int(365.25 * (year + 4716))
        + int(30.6001 * (month + 1))
        + day
        + gregorian
        - 1524.5
    )


def sign_from_longitude(longitude: float) -> tuple[str, float]:
    lon = _norm360(longitude)
    index = int(lon // 30) % 12
    return SIGN_KEYS[index], lon % 30.0


def _sun_longitude(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    mean_lon = _norm360(280.46646 + 36000.76983 * t + 0.0003032 * t * t)
    mean_anom = _norm360(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    center = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * _sind(mean_anom)
        + (0.019993 - 0.000101 * t) * _sind(2 * mean_anom)
        + 0.000289 * _sind(3 * mean_anom)
    )
    true_lon = mean_lon + center
    omega = 125.04 - 1934.136 * t
    return _norm360(true_lon - 0.00569 - 0.00478 * _sind(omega))


def _moon_longitude(jd: float) -> float:
    """Meeus 第 47 章主项，足够落到星座。"""
    t = (jd - 2451545.0) / 36525.0
    lp = _norm360(218.3164477 + 481267.88123421 * t)
    d = _norm360(297.8501921 + 445267.1114034 * t)
    m = _norm360(357.5291092 + 35999.0502909 * t)
    mp = _norm360(134.9633964 + 477198.8675055 * t)
    f = _norm360(93.2720950 + 483202.0175233 * t)
    terms = (
        (6.288774, mp, 0, 0, 0),
        (1.274027, 2 * d - mp, 0, 0, 0),
        (0.658314, 2 * d, 0, 0, 0),
        (0.213618, 2 * mp, 0, 0, 0),
        (-0.185116, m, 0, 0, 0),
        (-0.114332, 2 * f, 0, 0, 0),
        (0.058793, 2 * d - 2 * mp, 0, 0, 0),
        (0.057066, 2 * d - m - mp, 0, 0, 0),
        (0.053322, 2 * d + mp, 0, 0, 0),
        (0.045758, 2 * d - m, 0, 0, 0),
        (-0.040923, m - mp, 0, 0, 0),
        (-0.034720, d, 0, 0, 0),
        (-0.030383, m + mp, 0, 0, 0),
        (0.015327, 2 * d - 2 * f, 0, 0, 0),
    )
    delta = 0.0
    for amp, a, _b, _c, _d in terms:
        delta += amp * _sind(a)
    return _norm360(lp + delta)


# JPL 近似根数（J2000，度 / au）：a, e, I, L, long_peri, long_node
_PLANET_ELEMENTS: dict[str, tuple[float, float, float, float, float, float]] = {
    "mercury": (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
    "venus": (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
    "mars": (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
    "jupiter": (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
    "saturn": (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
}

_PLANET_RATES: dict[str, tuple[float, float, float, float, float, float]] = {
    "mercury": (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081),
    "venus": (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418),
    "mars": (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343),
    "jupiter": (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106),
    "saturn": (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794),
}


def _kepler_true_anomaly(mean_anom: float, ecc: float) -> float:
    m = math.radians(_norm360(mean_anom))
    e_anom = m
    for _ in range(8):
        e_anom = m + ecc * math.sin(e_anom)
    return 2 * math.atan2(
        math.sqrt(1 + ecc) * math.sin(e_anom / 2),
        math.sqrt(1 - ecc) * math.cos(e_anom / 2),
    )


def _planet_longitude(name: str, jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    _a0, e0, i0, l0, w0, n0 = _PLANET_ELEMENTS[name]
    _da, de, di, dl, dw, dn = _PLANET_RATES[name]
    ecc = e0 + de * t
    mean_lon = l0 + dl * t
    peri = w0 + dw * t
    node = n0 + dn * t
    inc = math.radians(i0 + di * t)
    mean_anom = _norm360(mean_lon - peri)
    true_anom = _kepler_true_anomaly(mean_anom, ecc)
    arg = true_anom + math.radians(_norm360(peri - node))
    lon = math.atan2(math.cos(inc) * math.sin(arg), math.cos(arg)) + math.radians(node)
    return _norm360(math.degrees(lon))


def _gmst_degrees(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    return _norm360(
        280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t
    )


def _ascendant(jd: float, latitude: float, longitude: float) -> float:
    ramc = math.radians(_norm360(_gmst_degrees(jd) + longitude))
    eps = math.radians(23.4392911)
    lat = math.radians(latitude)
    y = -math.cos(ramc)
    x = math.sin(ramc) * math.cos(eps) + math.tan(lat) * math.sin(eps)
    return _norm360(math.degrees(math.atan2(y, x)))


def resolve_city(place: str | None) -> tuple[float, float] | None:
    if not place:
        return None
    key = place.strip()
    if key in CITY_COORDS:
        return CITY_COORDS[key]
    for name, coords in CITY_COORDS.items():
        if name in key or key in name:
            return coords
    return None


@dataclass(frozen=True)
class Placement:
    body: str
    longitude: float
    sign: str
    degree_in_sign: float

    def as_public(self) -> dict[str, Any]:
        sign_zh = SIGN_NAMES_ZH[self.sign]
        role = PLANET_ROLES[self.body]
        return {
            "body": self.body,
            "sign": self.sign,
            "sign_zh": sign_zh,
            "degree_in_sign": round(self.degree_in_sign, 2),
            "blurb": f"{role}偏{sign_zh}。",
        }


def _place(body: str, longitude: float) -> Placement:
    sign, degree = sign_from_longitude(longitude)
    return Placement(body=body, longitude=_norm360(longitude), sign=sign, degree_in_sign=degree)


def compute_natal_chart(
    birth_date: date,
    birth_time: time | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    tz_offset_hours: float = 8.0,
) -> dict[str, Any]:
    """按东八区民用时间计算简略星盘。无时辰则用正午；无经纬度不算上升。"""
    clock = birth_time or time(12, 0)
    local = datetime.combine(birth_date, clock)
    ut = local - timedelta(hours=tz_offset_hours)
    jd = julian_day(ut)
    bodies = {
        "sun": _place("sun", _sun_longitude(jd)),
        "moon": _place("moon", _moon_longitude(jd)),
        "mercury": _place("mercury", _planet_longitude("mercury", jd)),
        "venus": _place("venus", _planet_longitude("venus", jd)),
        "mars": _place("mars", _planet_longitude("mars", jd)),
        "jupiter": _place("jupiter", _planet_longitude("jupiter", jd)),
        "saturn": _place("saturn", _planet_longitude("saturn", jd)),
    }
    has_rising = birth_time is not None and latitude is not None and longitude is not None
    rising: Placement | None = None
    if has_rising:
        assert latitude is not None and longitude is not None
        rising = _place("ascendant", _ascendant(jd, latitude, longitude))
    sun = bodies["sun"]
    moon = bodies["moon"]
    headline = f"日{SIGN_NAMES_ZH[sun.sign]} · 月{SIGN_NAMES_ZH[moon.sign]}"
    if rising is not None:
        headline += f" · 升{SIGN_NAMES_ZH[rising.sign]}"
    share = {
        "title": "我的简略星盘",
        "result": headline,
        "summary": f"太阳在{SIGN_NAMES_ZH[sun.sign]}，月亮在{SIGN_NAMES_ZH[moon.sign]}。",
        "tags": [SIGN_NAMES_ZH[sun.sign], SIGN_NAMES_ZH[moon.sign]],
        "footer": "AI Pet · 测测风格简略版",
        "theme": "dusk",
        "save_hint": "保存海报后发到朋友圈",
    }
    return {
        "has_time": birth_time is not None,
        "has_place": latitude is not None and longitude is not None,
        "has_rising": rising is not None,
        "headline": headline,
        "bodies": {name: item.as_public() for name, item in bodies.items()},
        "ascendant": rising.as_public() if rising is not None else None,
        "share_card": share,
    }
