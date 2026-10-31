"""LLM 回覆的數字檢查：回覆中的每個數字都必須能在查詢結果、文件片段或問題中找到。

允許：完全相同（去千分位）、依回覆的小數位數四捨五入後相同、萬／億換算、
年份（1900–2100）與 ≤ 31 的小整數（月份、日、名次、條次）。
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from numbers import Number

_NUM = re.compile(r"(?<![0-9A-Za-z_.,])(\d{1,3}(?:,\d{3})+(?!\d)|\d+)(\.\d+)?\s*(萬|億)?")  # 中文緊接數字也要抓到


def extract_numbers(text: str) -> list[tuple[float, int, str]]:
    """回傳 [(數值, 小數位數, 原文)]；萬／億已換算成原值。"""
    out = []
    for m in _NUM.finditer(text or ""):
        whole, frac, unit = m.group(1), m.group(2) or "", m.group(3)
        v = float(whole.replace(",", "") + frac)
        dec = len(frac) - 1 if frac else 0
        if unit == "萬":
            v *= 1e4
        elif unit == "億":
            v *= 1e8
        out.append((v, dec, m.group(0).strip()))
    return out


def allowed_values(texts: Iterable[str] = (), rows: Iterable[Iterable] = ()) -> list[float]:
    vals: list[float] = []
    for t in texts:
        vals += [v for v, _, _ in extract_numbers(t)]
    for row in rows:
        for c in row:
            if isinstance(c, Number) and not isinstance(c, bool):
                vals.append(float(c))
            elif isinstance(c, str):
                vals += [v for v, _, _ in extract_numbers(c)]
    return vals


def _supported(v: float, dec: int, raw: str, allowed: list[float]) -> bool:
    if float(v).is_integer() and (v <= 31 or 1900 <= v <= 2100) and "萬" not in raw and "億" not in raw:
        return True
    scale = 1e8 if "億" in raw else 1e4 if "萬" in raw else 1.0
    tol = 0.5 * scale * 10 ** (-dec) + 1e-9
    return any(abs(a - v) <= tol for a in allowed)


def unsupported_numbers(text: str, texts: Iterable[str] = (), rows: Iterable[Iterable] = ()) -> list[str]:
    allowed = allowed_values(texts, rows)
    return [raw for v, dec, raw in extract_numbers(text) if not _supported(v, dec, raw, allowed)]
