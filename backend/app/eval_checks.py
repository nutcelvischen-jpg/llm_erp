"""Text-to-SQL 評估用的比對函式（純函式，不連資料庫、不連 LLM）。

黃金問答集（data/golden/text2sql.yaml）每題有一種檢查：
  rows_match   參考 SQL 的結果必須出現在答案裡（容許答案多帶欄位、順序不同；數字容許四捨五入誤差）
  contains     答案裡必須出現這些值（例如客戶名稱）
  row_count    答案列數必須等於 N
  row_count_gt 答案列數必須大於 N
  refusal      應該被婉拒：有 error 且沒有任何資料列（模型回「無法回答」或守門員擋下寫入指令都算）
"""
from __future__ import annotations

from numbers import Number


def _is_num(x) -> bool:
    return isinstance(x, Number) and not isinstance(x, bool)


def approx_equal(a: float, b: float) -> bool:
    """b 是參考值。依「答案看起來被四捨五入到什麼精度」決定容差，避免少算一筆也被判對：
    - 參考值是整數（計數、ROUND(…,0) 的金額）：只容許四捨五入誤差 ±0.5
    - 參考值有小數、答案是整數（答案四捨五入過）：±0.55
    - 兩邊都有小數（例如毛利率 25.6）：±0.055
    """
    if float(b).is_integer():
        tol = 0.5
    elif float(a).is_integer():
        tol = 0.55
    else:
        tol = 0.055
    return abs(a - b) <= tol + 1e-9


def cell_matches(ref, ans) -> bool:
    if ref is None or ans is None:
        return ref is None and ans is None
    if _is_num(ref) != _is_num(ans):  # 一個是數字、一個是字串：不算相等
        return False
    if _is_num(ref):
        return approx_equal(float(ans), float(ref))
    return str(ref).strip() == str(ans).strip()


def _row_matches(ref_row: list, ans_row: list) -> bool:
    """參考列的每個值，都要能在答案列的某一格找到。"""
    return all(any(cell_matches(rc, ac) for ac in ans_row) for rc in ref_row)


def rows_match(ref_rows: list[list], ans_rows: list[list], ans_total: int, same_count: bool = True) -> tuple[bool, str]:
    if not ref_rows:
        return False, "參考 SQL 沒有結果（黃金題本身有問題）"
    if same_count and ans_total != len(ref_rows):
        return False, f"列數不符：答案 {ans_total} 列，參考 {len(ref_rows)} 列"
    unused = list(range(len(ans_rows)))
    for ref in ref_rows:
        hit = next((i for i in unused if _row_matches(ref, ans_rows[i])), None)
        if hit is None:
            return False, f"答案裡找不到參考列：{ref}"
        unused.remove(hit)
    return True, ""


def contains_values(values: list, ans_rows: list[list]) -> tuple[bool, str]:
    cells = [c for row in ans_rows for c in row]
    for v in values:
        if not any(cell_matches(v, c) for c in cells):
            return False, f"答案裡找不到：{v}"
    return True, ""


def evaluate(check: dict, ans, ref_rows: list[list] | None = None) -> tuple[bool, str]:
    """ans 需有 .error / .rows / .row_count。回傳 (是否通過, 失敗原因)。"""
    if check.get("refusal"):
        if ans.error and not ans.rows:
            return True, ""
        return False, "應該婉拒卻回傳了資料" if ans.rows else "應該婉拒，但沒有產生任何錯誤訊息"
    if ans.error:
        return False, f"查詢失敗：{ans.error}"
    if "row_count" in check and ans.row_count != check["row_count"]:
        return False, f"列數 {ans.row_count}，應為 {check['row_count']}"
    if "row_count_gt" in check and not ans.row_count > check["row_count_gt"]:
        return False, f"列數 {ans.row_count}，應大於 {check['row_count_gt']}"
    if "contains" in check:
        ok, why = contains_values(check["contains"], ans.rows)
        if not ok:
            return False, why
    if "rows_match" in check:
        return rows_match(ref_rows or [], ans.rows, ans.row_count, same_count=not check.get("any_count"))
    return True, ""


# ---------- RAG 評估（data/golden/rag.yaml）----------
_DASHES = str.maketrans({c: "-" for c in "–—‒―−－~～"})


def normalize_text(s: str) -> str:
    """比對前正規化：PDF 部首字元（clean_text）、全形英數、去空白、破折號與波浪號統一、臺→台、×→x。
    只消除排版差異，不放寬語意（數字與用字仍須相同）。"""
    from .rag.parse import clean_text

    s = clean_text(s or "")
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E and c != "～" else c for c in s)
    s = s.translate(_DASHES).replace("臺", "台").replace("×", "x")
    return "".join(s.split())


def rag_contains(text: str, phrases: list[str]) -> tuple[bool, str]:
    t = normalize_text(text)
    missing = [p for p in phrases if normalize_text(p) not in t]
    return (not missing, "" if not missing else f"回答缺少：{missing}")


def rag_refused(text: str) -> bool:
    return "查無" in (text or "")
