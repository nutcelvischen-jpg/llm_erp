"""SQL 守門員：LLM 產生的每一句 SQL 都必須先通過 validate()，才能送去資料庫執行。

規則（任何一條不符就拒絕，reason 以中文說明，可直接回饋給 LLM 重寫）：
1. 必須能以 PostgreSQL 語法解析，且只有「一個」敘述。
2. 只允許 SELECT（含 WITH/CTE、UNION）；整棵語法樹內不得有 INSERT/UPDATE/DELETE/DDL/COPY 等。
3. 不允許 SELECT ... INTO、FOR UPDATE、FETCH FIRST（請用 LIMIT）。
4. 只能引用白名單 View（可帶 erp. 前綴），或本句自己定義的 CTE 名稱；不允許表函式。
5. 不允許 pg_ 開頭函式與其他危險函式（set_config、dblink、lo_* …）；系統目錄因白名單而自然被擋。
6. 最外層沒有 LIMIT 就補 200；LIMIT 超過 1000 就壓成 1000。
回傳的 sql 是重新產生的標準化 SQL（已去除註解與結尾分號）。
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_VIEWS = {"v_銷售明細", "v_應收帳款", "v_庫存狀況", "v_採購明細"}
ALLOWED_SCHEMAS = {"", "erp"}
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

_SET_OPS = (exp.Union, exp.Intersect, exp.Except)
_FORBIDDEN_NODE_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Alter", "Create", "Command", "Merge", "Copy",
    "TruncateTable", "Grant", "Set", "Use", "Transaction", "Commit", "Rollback", "LoadData", "Pragma",
]
_FORBIDDEN_NODES = tuple(t for n in _FORBIDDEN_NODE_NAMES if (t := getattr(exp, n, None)) is not None)
_DENY_FUNC_PREFIXES = ("pg_", "dblink", "lo_")
_DENY_FUNCS = {
    "set_config", "current_setting", "query_to_xml", "query_to_xml_and_xmlschema",
    "table_to_xml", "database_to_xml", "txid_current",
}


@dataclass
class GuardResult:
    ok: bool
    sql: str
    reason: str = ""


def _reject(sql: str, reason: str) -> GuardResult:
    return GuardResult(False, sql, reason)


def _check_ctes(root: exp.Expression) -> str | None:
    """CTE 的作用域規則（PostgreSQL 語意）：CTE 本體裡的同名參照，指的是「真實資料表」而非 CTE，
    若放行會形成白名單繞過。因此：不允許 RECURSIVE、不允許巢狀 WITH、CTE 本體不得引用自己或排在後面的 CTE。"""
    for w in root.find_all(exp.With):
        if w.args.get("recursive"):
            return "不允許 WITH RECURSIVE"
        if w.parent is not root:
            return "不允許巢狀 WITH，請把所有 CTE 寫在最外層"
        ctes = list(w.expressions)
        for i, c in enumerate(ctes):
            later = {x.alias_or_name.lower() for x in ctes[i:]}
            for t in c.this.find_all(exp.Table):
                if not t.db and t.name.lower() in later:
                    return f"CTE「{c.alias_or_name}」不可引用自己或排在後面的 CTE（{t.name}）"
    return None


def _check_tree(root: exp.Expression) -> str | None:
    """回傳拒絕原因；通過回傳 None。"""
    if not isinstance(root, (exp.Select, *_SET_OPS)):
        return "只允許 SELECT 查詢（可使用 WITH / UNION）"

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return f"不允許 {type(node).__name__.upper()} 類型的敘述"
    if root.find(exp.Into):
        return "不允許 SELECT ... INTO"
    if root.find(exp.Lock):
        return "不允許 FOR UPDATE / FOR SHARE"
    if root.find(exp.Fetch):
        return "不允許 FETCH FIRST，請改用 LIMIT n"

    cte_reason = _check_ctes(root)
    if cte_reason:
        return cte_reason
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    for t in root.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            return "不允許使用表函式（例如 generate_series、unnest）"
        name, schema = t.name, t.db.lower()
        if t.catalog:
            return "不允許跨資料庫查詢"
        if schema.startswith("pg_") or schema == "information_schema":
            return "不允許存取系統目錄"
        if not schema and name.lower() in cte_names:
            continue
        if name.startswith("pg_"):
            return "不允許存取系統目錄"
        if schema not in ALLOWED_SCHEMAS or name not in ALLOWED_VIEWS:
            ref = f"{t.db}.{name}" if t.db else name
            return f"不允許引用「{ref}」，只能查詢：{'、'.join(sorted(ALLOWED_VIEWS))}"

    for f in root.find_all(exp.Func):
        fname = (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()
        if fname.startswith(_DENY_FUNC_PREFIXES) or fname in _DENY_FUNCS:
            return f"不允許使用函式 {fname}"
    return None


def _apply_limit(root: exp.Expression) -> None:
    limit = root.args.get("limit")
    if limit is None:
        root.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_LIMIT)))
        return
    count = limit.expression
    if isinstance(count, exp.Literal) and not count.is_string:
        try:
            n = int(count.name)
        except ValueError:
            n = MAX_LIMIT + 1
        if n > MAX_LIMIT:
            limit.set("expression", exp.Literal.number(MAX_LIMIT))
    else:  # LIMIT ALL 或非常數運算式 → 一律壓成上限
        root.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))


def validate(sql: str) -> GuardResult:
    """驗證並改寫（補 LIMIT）。ok=False 時 reason 說明原因，sql 為原始輸入。"""
    original = sql
    if not sql or not sql.strip():
        return _reject(original, "SQL 是空的")
    try:
        stmts = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        return _reject(original, f"SQL 語法錯誤：{str(e).splitlines()[0][:150]}")
    if len(stmts) != 1:
        return _reject(original, "只允許單一敘述，不可用分號串接多個 SQL" if stmts else "SQL 是空的")

    root = stmts[0]
    reason = _check_tree(root)
    if reason:
        return _reject(original, reason)
    _apply_limit(root)
    return GuardResult(True, root.sql(dialect="postgres", comments=False))
