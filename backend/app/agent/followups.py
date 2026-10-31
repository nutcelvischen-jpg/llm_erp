"""每題答完的「接著問」：依這次用到的既定程式、查詢對象與引用的文件，產生最多 3 個追問。

規則寫死、不呼叫 LLM（不增加延遲，也不會冒出系統答不出來的問題）：
  - 追問一律是既定程式或現有文件答得出來的問法。
  - 要問合約／規格書時，只有對應的 PDF 確實存在（data/ 底下）才建議。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = ROOT / "data"
MAX_FOLLOWUPS = 3
_CACHE_SECONDS = 300
_cache: tuple[float, frozenset[str]] = (0.0, frozenset())


def doc_names() -> frozenset[str]:
    """data/ 底下所有 PDF 的檔名（不含副檔名）；5 分鐘更新一次，新匯入的文件不用重開服務。"""
    global _cache
    now = time.monotonic()
    if now - _cache[0] > _CACHE_SECONDS:
        _cache = (now, frozenset(p.stem for p in DOCS_ROOT.rglob("*.pdf")))
    return _cache[1]


def _first(columns: list[str], rows: list[list], col: str, skip: tuple = ("（全公司）",)) -> str | None:
    if col not in columns:
        return None
    i = columns.index(col)
    return next((str(r[i]) for r in rows if r[i] not in (None, "") and r[i] not in skip), None)


def _values(columns: list[str], rows: list[list], col: str) -> list[str]:
    if col not in columns:
        return []
    i = columns.index(col)
    return list(dict.fromkeys(str(r[i]) for r in rows if r[i]))


def _customer_qs(c: str, docs: frozenset[str], *, trend=True, contract=True, invoices=True, total=False) -> list[str]:
    out = []
    if trend:
        out.append(f"{c}最近 12 個月每個月的營收")
    if total:
        out.append(f"{c}今年營收多少？")
    if contract and f"銷售合約_{c}" in docs:
        out.append(f"{c}的合約，年度採購多少可以拿到折讓？")
    if invoices:
        out.append(f"{c}有哪些發票逾期？")
    return out


def _supplier_contract_q(suppliers: list[str], docs: frozenset[str]) -> list[str]:
    s = next((s for s in suppliers if f"採購合約_{s}" in docs), None)
    return [f"{s}依合約延遲交貨，我們可以怎麼扣款？"] if s else []


def _template_qs(tid: str, binds: dict, columns: list[str], rows: list[list],
                 params_readable: list[str], docs: frozenset[str]) -> list[str]:
    c = binds.get("customer")
    sku = binds.get("sku")
    by_customer = any(p.endswith("：客戶") for p in params_readable)
    if tid == "sales_trend":
        return (_customer_qs(c, docs, trend=False, total=True) if c
                else ["哪個客戶今年的營收比去年同期掉最多？", "今年營收前五名的客戶"])
    if tid == "sales_total":
        return _customer_qs(c, docs) if c else ["最近 12 個月每個月的營收", "今年營收前五名的客戶"]
    if tid in ("sales_compare", "sales_rank"):
        top = _first(columns, rows, "對象" if tid == "sales_compare" else "客戶名稱")
        qs = _customer_qs(top, docs, invoices=False) if top and (by_customer or "客戶名稱" in columns) else []
        return qs + ["最近 18 個月每個月的毛利率"]
    if tid == "sales_largest_orders":
        top = _first(columns, rows, "客戶名稱")
        return _customer_qs(top, docs, trend=False, total=True, contract=False) if top else []
    if tid == "ar_summary":
        return ([f"{c}有哪些發票逾期？"] if c else []) + ["哪些客戶的應收逾期超過 60 天？金額多少？", "應收帳款的帳齡分佈"]
    if tid == "ar_by_customer":
        top = _first(columns, rows, "客戶名稱")
        qs = [f"{top}有哪些發票逾期？"] if top else []
        if top and f"銷售合約_{top}" in docs:
            qs.append(f"依合約，{top}逾期多久我們可以暫停出貨？")
        return qs + ["應收帳款的帳齡分佈"]
    if tid == "ar_aging":
        return ["哪些客戶的應收逾期超過 60 天？金額多少？", "目前總共有多少應收帳款沒收回來？"]
    if tid == "ar_invoices" and c:
        qs = [f"依合約，{c}逾期多久我們可以暫停出貨？信用額度多少？"] if f"銷售合約_{c}" in docs else []
        return qs + [f"{c}今年營收多少？"]
    if tid in ("stock_dead", "stock_dead_total"):
        top = _first(columns, rows, "料號")
        return ([f"{top}目前庫存多少？"] if top else []) + ["依目前待出貨訂單，哪些料號會缺料？建議採購多少？"]
    if tid == "stock_shortage":
        return _supplier_contract_q(_values(columns, rows, "供應商"), docs) + ["各供應商的準時交貨率"]
    if tid == "stock_lookup":
        qs = [f"{sku}的材質與硬度是什麼？"] if sku and f"規格書_{sku}" in docs else []
        return qs + _supplier_contract_q(_values(columns, rows, "供應商"), docs) + ["依目前待出貨訂單，哪些料號會缺料？建議採購多少？"]
    if tid == "stock_rank":
        return ["哪些料號超過 180 天沒動？壓了多少錢？", "依目前待出貨訂單，哪些料號會缺料？建議採購多少？"]
    if tid == "supplier_ontime":
        return _supplier_contract_q(_values(columns, rows, "供應商"), docs) + ["依目前待出貨訂單，哪些料號會缺料？建議採購多少？"]
    if tid == "purchase_summary":
        return ["各供應商的準時交貨率", "還在路上的採購單金額多少？"]
    return []


def _doc_qs(sources: list[dict], docs: frozenset[str]) -> list[str]:
    out: list[str] = []
    for name in dict.fromkeys(Path(s.get("file_name", "")).stem for s in sources):
        kind, _, who = name.partition("_")
        if kind == "銷售合約" and who:
            out += [f"{who}今年營收多少？", f"{who}有哪些發票逾期？"]
        elif kind == "採購合約" and who:
            out.append("各供應商的準時交貨率")
        elif kind == "規格書" and who:
            out.append(f"{who}目前庫存多少？")
    return out


def _norm(q: str) -> str:
    return re.sub(r"[\s？?。，,：:]", "", q)


def suggest(question: str, *, route: str, mode: str | None, template_id: str | None, binds: dict,
            columns: list[str], rows: list[list], params_readable: list[str], sources: list[dict],
            error: str | None = None, docs: frozenset[str] | None = None) -> list[str]:
    """回傳最多 3 個追問；反問、確認、未命中、失敗與閒聊不給。"""
    if route == "chat" or error or mode in ("clarify", "confirm", "no_match", "error"):
        return []
    docs = doc_names() if docs is None else docs
    qs: list[str] = []
    if mode == "template" and template_id and rows:
        qs += _template_qs(template_id, binds or {}, columns, rows, params_readable, docs)
    if sources:
        qs += _doc_qs(sources, docs)
    seen = {_norm(question)}
    out = []
    for q in qs:
        if _norm(q) not in seen:
            seen.add(_norm(q))
            out.append(q)
    return out[:MAX_FOLLOWUPS]
