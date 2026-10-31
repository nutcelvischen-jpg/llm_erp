"""期間代碼 → 日期區間。LLM 只輸出代碼，日期一律由程式計算。

Period.date_to 是「不含」的上界；「到目前為止」類的期間上界為明天（含今天）。
代碼：this_month、last_month、this_quarter、last_quarter、this_year、last_year、ytd、
      last_n_days:N、last_n_months:N（含本月）、all、
      quarter:<this_year|last_year|YYYY>:<1-4>、month:<this_year|last_year|YYYY>:<1-12>
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

ALL_FROM = date(2000, 1, 1)
MAX_N_DAYS = 3660
MAX_N_MONTHS = 120


@dataclass(frozen=True)
class Period:
    date_from: date
    date_to: date          # 不含
    label: str


def _add_months(d: date, n: int) -> date:
    """d 必須是每月 1 日。"""
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _quarter_start(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def _same_day(year: int, month: int, day: int) -> date:
    """去年／上月的同一天；不存在（2/29、31 日）就取該月最後一天。"""
    nxt = _add_months(date(year, month, 1), 1)
    return min(date(year, month, 1) + timedelta(days=day - 1), nxt - timedelta(days=1))


def _year_of(token: str, today: date) -> int:
    if token == "this_year":
        return today.year
    if token == "last_year":
        return today.year - 1
    if re.fullmatch(r"\d{4}", token) and 2000 <= int(token) <= 2100:
        return int(token)
    raise ValueError(f"不合法的年份：{token}")


def _year_note(y: int, today: date) -> str:
    return "（今年）" if y == today.year else "（去年）" if y == today.year - 1 else ""


def resolve_period(code: str, today: date) -> Period:
    code = (code or "").strip()
    tomorrow = today + timedelta(days=1)
    ms, qs = _month_start(today), _quarter_start(today)
    lm, lq = _add_months(ms, -1), _add_months(qs, -3)
    q = (today.month - 1) // 3 + 1
    simple = {
        "this_month": lambda: Period(ms, tomorrow, f"{today.year} 年 {today.month} 月（本月）"),
        "last_month": lambda: Period(lm, ms, f"{lm.year} 年 {lm.month} 月（上月）"),
        "this_quarter": lambda: Period(qs, tomorrow, f"{today.year} 年 Q{q}（本季）"),
        "last_quarter": lambda: Period(lq, qs, f"{lq.year} 年 Q{(lq.month - 1) // 3 + 1}（上一季）"),
        "this_year": lambda: Period(date(today.year, 1, 1), tomorrow, f"{today.year} 年（今年）"),
        "last_year": lambda: Period(date(today.year - 1, 1, 1), date(today.year, 1, 1), f"{today.year - 1} 年（去年）"),
        "ytd": lambda: Period(date(today.year, 1, 1), tomorrow,
                              f"{today.year} 年 1/1–{today.month}/{today.day}（今年累計）"),
        "all": lambda: Period(ALL_FROM, tomorrow, "全部期間"),
    }
    if code in simple:
        return simple[code]()
    m = re.fullmatch(r"last_n_days:(\d+)", code)
    if m and 1 <= int(m.group(1)) <= MAX_N_DAYS:
        n = int(m.group(1))
        return Period(tomorrow - timedelta(days=n), tomorrow, f"最近 {n} 天")
    m = re.fullmatch(r"last_n_months:(\d+)", code)
    if m and 1 <= int(m.group(1)) <= MAX_N_MONTHS:
        n = int(m.group(1))
        return Period(_add_months(ms, -(n - 1)), tomorrow, f"最近 {n} 個月（含本月）")
    m = re.fullmatch(r"quarter:(\w+):([1-4])", code)
    if m:
        y, qq = _year_of(m.group(1), today), int(m.group(2))
        s = date(y, (qq - 1) * 3 + 1, 1)
        return Period(s, _add_months(s, 3), f"{y} 年 Q{qq}{_year_note(y, today)}")
    m = re.fullmatch(r"month:(\w+):(\d{1,2})", code)
    if m and 1 <= int(m.group(2)) <= 12:
        y, mm = _year_of(m.group(1), today), int(m.group(2))
        s = date(y, mm, 1)
        return Period(s, _add_months(s, 1), f"{y} 年 {mm} 月{_year_note(y, today)}")
    raise ValueError(f"不合法的期間代碼：{code!r}")


def is_valid(code: str, today: date | None = None) -> bool:
    try:
        resolve_period(code, today or date.today())
        return True
    except ValueError:
        return False


COMPARE_KINDS = {"yoy_ytd": "今年累計 vs 去年同期", "mom": "本月累計 vs 上月同期", "qoq": "本季累計 vs 上季同期"}


def compare_periods(kind: str, today: date) -> tuple[Period, Period]:
    """回傳（本期, 比較期），兩者天數對齊。"""
    tomorrow = today + timedelta(days=1)
    if kind == "yoy_ytd":
        prev_end = _same_day(today.year - 1, today.month, today.day)
        return (Period(date(today.year, 1, 1), tomorrow, f"{today.year} 年 1/1–{today.month}/{today.day}"),
                Period(date(today.year - 1, 1, 1), prev_end + timedelta(days=1),
                       f"{today.year - 1} 年 1/1–{prev_end.month}/{prev_end.day}"))
    if kind == "mom":
        ms = _month_start(today)
        ps = _add_months(ms, -1)
        prev_end = _same_day(ps.year, ps.month, today.day)
        return (Period(ms, tomorrow, f"{today.year} 年 {today.month} 月 1–{today.day} 日"),
                Period(ps, prev_end + timedelta(days=1), f"{ps.year} 年 {ps.month} 月 1–{prev_end.day} 日"))
    if kind == "qoq":
        qs = _quarter_start(today)
        ps = _add_months(qs, -3)
        offset = (today - qs).days
        prev_end = min(ps + timedelta(days=offset), qs - timedelta(days=1))
        qn = (today.month - 1) // 3 + 1
        pqn = (ps.month - 1) // 3 + 1
        return (Period(qs, tomorrow, f"{today.year} 年 Q{qn}（至 {today.month}/{today.day}）"),
                Period(ps, prev_end + timedelta(days=1), f"{ps.year} 年 Q{pqn}（至 {prev_end.month}/{prev_end.day}）"))
    raise ValueError(f"不合法的比較方式：{kind!r}")
