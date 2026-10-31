"""實體比對：使用者說的客戶／供應商／料號／業務名稱 → 資料庫裡的正式名稱。

順序：exact（正規化後相同）→ fuzzy（唯一的包含關係，或相似度 ≥ 0.75 且領先第二名 ≥ 0.1）
     → ambiguous（多個接近，options 最多 5 個）→ none（options 為最相近的名稱，供推薦）。
"""
from __future__ import annotations

import difflib
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["customer", "supplier", "sku", "rep"]
KIND_LABELS = {"customer": "客戶", "supplier": "供應商", "sku": "料號", "rep": "業務"}
_SUFFIX = re.compile(r"(股份有限公司|有限公司|公司)$")
FUZZY_MIN, FUZZY_GAP, NEAR_MIN, MAX_OPTIONS = 0.75, 0.1, 0.5, 5


@dataclass
class Match:
    status: Literal["exact", "fuzzy", "ambiguous", "none"]
    value: str | None = None
    options: list[str] = field(default_factory=list)


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(s.split()).casefold()
    return _SUFFIX.sub("", s) or s


class EntityIndex:
    """providers：{kind: () -> list[str]}。第一次使用某類時才載入，之後快取；refresh() 清除快取。"""

    def __init__(self, providers: dict[str, Callable[[], list[str]]]):
        self._providers = providers
        self._cache: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def names(self, kind: str) -> list[str]:
        if kind not in self._cache:
            with self._lock:
                if kind not in self._cache:
                    self._cache[kind] = sorted({n for n in self._providers[kind]() if n})
        return self._cache[kind]

    def refresh(self) -> None:
        with self._lock:
            self._cache.clear()

    def match(self, kind: str, text: str) -> Match:
        names = self.names(kind)
        q = normalize(text)
        if not q:
            return Match("none")
        norm = {n: normalize(n) for n in names}
        exact = [n for n, v in norm.items() if v == q]
        if len(exact) == 1:
            return Match("exact", exact[0])
        if len(exact) > 1:
            return Match("ambiguous", options=exact[:MAX_OPTIONS])
        contains = [n for n, v in norm.items() if q in v or v in q]
        if len(contains) == 1:
            return Match("fuzzy", contains[0])
        if len(contains) > 1:
            # 「華發」同時包含在多個名稱裡 → 讓使用者選
            return Match("ambiguous", options=sorted(contains, key=lambda n: -_ratio(q, norm[n]))[:MAX_OPTIONS])
        scored = sorted(((n, _ratio(q, v)) for n, v in norm.items()), key=lambda x: -x[1])
        if not scored:
            return Match("none")
        best, s1 = scored[0]
        s2 = scored[1][1] if len(scored) > 1 else 0.0
        if s1 >= FUZZY_MIN and s1 - s2 >= FUZZY_GAP:
            return Match("fuzzy", best)
        near = [n for n, s in scored if s >= NEAR_MIN and s1 - s < FUZZY_GAP]
        if s1 >= FUZZY_MIN and len(near) > 1:
            return Match("ambiguous", options=near[:MAX_OPTIONS])
        return Match("none", options=[n for n, s in scored[:3] if s >= NEAR_MIN])


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------- 正式版：從唯讀 View 讀名單 ----------
_SQL = {
    "customer": 'SELECT DISTINCT "客戶名稱" FROM erp."v_應收帳款" UNION SELECT DISTINCT "客戶名稱" FROM erp."v_銷售明細"',
    "supplier": 'SELECT DISTINCT "供應商" FROM erp."v_採購明細" UNION SELECT DISTINCT "供應商" FROM erp."v_庫存狀況"',
    "sku": 'SELECT DISTINCT "料號" FROM erp."v_庫存狀況" UNION SELECT DISTINCT "料號" FROM erp."v_銷售明細"',
    "rep": 'SELECT DISTINCT "負責業務" FROM erp."v_銷售明細"',
}


def _db_provider(kind: str) -> Callable[[], list[str]]:
    def load() -> list[str]:
        from sqlalchemy import text

        from ..db import engine_ro

        with engine_ro.connect() as c:
            c.execute(text("SET LOCAL statement_timeout = '10s'"))
            return [r[0] for r in c.execute(text(_SQL[kind]))]
    return load


_index: EntityIndex | None = None


def default_index() -> EntityIndex:
    global _index
    if _index is None:
        _index = EntityIndex({k: _db_provider(k) for k in _SQL})
    return _index
