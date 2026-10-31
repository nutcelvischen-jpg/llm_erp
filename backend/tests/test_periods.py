from datetime import date

import pytest

from backend.app.catalog.periods import compare_periods, is_valid, resolve_period

D = date


def r(code, today):
    p = resolve_period(code, today)
    return p.date_from, p.date_to


T1, T2, T3, T4 = D(2026, 10, 30), D(2026, 3, 31), D(2024, 2, 29), D(2026, 1, 1)


@pytest.mark.parametrize("code, today, expect", [
    ("this_month", T1, (D(2026, 10, 1), D(2026, 10, 31))),
    ("last_month", T1, (D(2026, 9, 1), D(2026, 10, 1))),
    ("this_quarter", T1, (D(2026, 10, 1), D(2026, 10, 31))),
    ("last_quarter", T1, (D(2026, 7, 1), D(2026, 10, 1))),
    ("this_year", T1, (D(2026, 1, 1), D(2026, 10, 31))),
    ("last_year", T1, (D(2025, 1, 1), D(2026, 1, 1))),
    ("ytd", T1, (D(2026, 1, 1), D(2026, 10, 31))),
    ("last_n_days:7", T1, (D(2026, 10, 24), D(2026, 10, 31))),
    ("last_n_months:6", T1, (D(2026, 5, 1), D(2026, 10, 31))),
    ("all", T1, (D(2000, 1, 1), D(2026, 10, 31))),
    ("quarter:last_year:3", T1, (D(2025, 7, 1), D(2025, 10, 1))),
    ("quarter:2024:4", T1, (D(2024, 10, 1), D(2025, 1, 1))),
    ("month:this_year:2", T1, (D(2026, 2, 1), D(2026, 3, 1))),
    # 月底、季末
    ("this_month", T2, (D(2026, 3, 1), D(2026, 4, 1))),
    ("last_month", T2, (D(2026, 2, 1), D(2026, 3, 1))),
    ("this_quarter", T2, (D(2026, 1, 1), D(2026, 4, 1))),
    ("last_quarter", T2, (D(2025, 10, 1), D(2026, 1, 1))),
    ("last_n_months:3", T2, (D(2026, 1, 1), D(2026, 4, 1))),
    # 閏年
    ("this_month", T3, (D(2024, 2, 1), D(2024, 3, 1))),
    ("month:this_year:2", T3, (D(2024, 2, 1), D(2024, 3, 1))),
    ("last_n_days:30", T3, (D(2024, 1, 31), D(2024, 3, 1))),
    # 跨年
    ("last_month", T4, (D(2025, 12, 1), D(2026, 1, 1))),
    ("last_quarter", T4, (D(2025, 10, 1), D(2026, 1, 1))),
    ("this_year", T4, (D(2026, 1, 1), D(2026, 1, 2))),
    ("last_n_months:2", T4, (D(2025, 12, 1), D(2026, 1, 2))),
    ("month:last_year:12", T4, (D(2025, 12, 1), D(2026, 1, 1))),
])
def test_resolve(code, today, expect):
    assert r(code, today) == expect


def test_labels():
    assert resolve_period("this_year", T1).label == "2026 年（今年）"
    assert resolve_period("quarter:last_year:3", T1).label == "2025 年 Q3（去年）"
    assert resolve_period("last_month", T4).label == "2025 年 12 月（上月）"
    assert resolve_period("ytd", T1).label == "2026 年 1/1–10/30（今年累計）"


@pytest.mark.parametrize("code", ["", "yesterday", "last_n_days:0", "last_n_days:99999", "quarter:2026:5",
                                  "month:this_year:13", "quarter:1999:1", "last_n_months:x", "this_year;drop"])
def test_invalid(code):
    with pytest.raises(ValueError):
        resolve_period(code, T1)
    assert not is_valid(code, T1)


def test_compare_yoy_ytd():
    cur, prev = compare_periods("yoy_ytd", T1)
    assert (cur.date_from, cur.date_to) == (D(2026, 1, 1), D(2026, 10, 31))
    assert (prev.date_from, prev.date_to) == (D(2025, 1, 1), D(2025, 10, 31))


def test_compare_yoy_ytd_leap_day():
    cur, prev = compare_periods("yoy_ytd", T3)
    assert (cur.date_to, prev.date_to) == (D(2024, 3, 1), D(2023, 3, 1))  # 去年同期到 2/28（含）


def test_compare_mom_and_qoq():
    cur, prev = compare_periods("mom", T2)  # 3/31 → 上月只有 28 天
    assert (cur.date_from, cur.date_to) == (D(2026, 3, 1), D(2026, 4, 1))
    assert (prev.date_from, prev.date_to) == (D(2026, 2, 1), D(2026, 3, 1))
    cur, prev = compare_periods("mom", T4)
    assert (prev.date_from, prev.date_to) == (D(2025, 12, 1), D(2025, 12, 2))
    cur, prev = compare_periods("qoq", T1)  # Q4 第 30 天 vs Q3 第 30 天
    assert (cur.date_from, prev.date_from, prev.date_to) == (D(2026, 10, 1), D(2026, 7, 1), D(2026, 7, 31))
    with pytest.raises(ValueError):
        compare_periods("wow", T1)
