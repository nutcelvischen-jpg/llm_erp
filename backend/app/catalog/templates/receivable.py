"""應收模板：合計、客戶清單、單一客戶發票明細、帳齡。資料來源 v_應收帳款。"""
from __future__ import annotations

from ..base import ParamSpec, QueryTemplate, guarded
from .common import DIR, ORDER_CHOICES, first, fmt, opt_eq, top

V = '"v_應收帳款"'
UNPAID = '"未收金額" > 0'
CUSTOMER = '"客戶名稱"'
OVERDUE = '(CAST(:overdue_gt AS INTEGER) IS NULL OR "逾期天數" > :overdue_gt)'
OVERDUE_PARAM = ParamSpec("overdue_gt", "int", "逾期超過天數", min=0, max=3650)


def overdue_text(p) -> str:
    n = p.get("overdue_gt")
    return "全部未收" if n is None else "已逾期" if n == 0 else f"逾期超過 {n} 天"


# ---------- ar_summary ----------
def _sum_build(p):
    sql = (f'SELECT ROUND(SUM("未收金額"), 0) AS "未收總額", COUNT(*) AS "未收張數", '
           f'COUNT(DISTINCT "客戶名稱") AS "客戶數", MAX("逾期天數") AS "最長逾期天數" FROM {V} '
           f'WHERE {UNPAID} AND {OVERDUE} AND {opt_eq(CUSTOMER, "customer")}')
    return guarded(sql, {"overdue_gt": p.get("overdue_gt"), "customer": p.get("customer")})


def _sum_summary(f):
    if not f.get("未收張數"):
        return "沒有符合條件的未收帳款。"
    return (f"未收總額 {fmt('總額', f['未收總額'])}，共 {f['未收張數']:,} 張發票、{f['客戶數']:,} 個客戶，"
            f"最長逾期 {f['最長逾期天數']:,} 天。")


ar_summary = QueryTemplate(
    id="ar_summary", title="應收合計",
    description="未收帳款合計（金額、張數、客戶數、最長逾期天數）；可限定客戶，或只看已逾期／逾期超過 N 天",
    examples=["目前總共有多少應收帳款沒收回來", "逾期超過 30 天的應收總共多少", "台陽科技目前欠我們多少錢",
              "精興金屬有幾張逾期發票", "現在逾期未收的金額合計", "應收帳款總額是多少"],
    params=[ParamSpec("customer", "entity", "客戶", entity="customer"), OVERDUE_PARAM],
    build=_sum_build, facts=lambda c, r: first(c, r), summary=_sum_summary,
    columns=lambda p: ["未收總額", "未收張數", "客戶數", "最長逾期天數"],
)


# ---------- ar_by_customer ----------
def _by_build(p):
    sql = (f'SELECT "客戶名稱", COUNT(*) AS "未收張數", ROUND(SUM("未收金額"), 0) AS "未收金額", '
           f'MAX("逾期天數") AS "最長逾期天數" FROM {V} WHERE {UNPAID} AND {OVERDUE} '
           f'GROUP BY 1 ORDER BY 3 {DIR[p["order"]]}, 1 LIMIT {top(p)}')
    return guarded(sql, {"overdue_gt": p.get("overdue_gt")})


def _by_facts(cols, rows):
    f = first(cols, rows)
    return {"客戶數": len(rows), "第一名": f.get("客戶名稱"), "第一名金額": f.get("未收金額"),
            "合計": sum(r[2] or 0 for r in rows)}


def _by_summary(f):
    if not f["客戶數"]:
        return "沒有符合條件的客戶。"
    return f"共 {f['客戶數']} 個客戶，未收金額最高的是 {f['第一名']}（{fmt('金額', f['第一名金額'])}）。"


ar_by_customer = QueryTemplate(
    id="ar_by_customer", title="欠款客戶清單",
    description="列出有未收帳款（或已逾期、逾期超過 N 天）的客戶，含張數、金額、最長逾期天數",
    examples=["哪些客戶有逾期未收的發票", "哪些客戶的應收逾期超過 60 天", "欠最多錢的前十個客戶",
              "逾期超過 90 天的客戶有誰", "哪個客戶欠款最多", "目前有欠款的客戶清單"],
    params=[OVERDUE_PARAM, ParamSpec("top_n", "int", "筆數", default=10, min=1, max=100),
            ParamSpec("order", "enum", "排序", default="desc", choices=ORDER_CHOICES)],
    build=_by_build, facts=_by_facts, summary=_by_summary,
    columns=lambda p: ["客戶名稱", "未收張數", "未收金額", "最長逾期天數"],
)


# ---------- ar_invoices ----------
def _inv_build(p):
    sql = (f'SELECT "發票號碼", "發票日期", "到期日", ROUND("發票金額", 0) AS "發票金額", '
           f'ROUND("未收金額", 0) AS "未收金額", "逾期天數" FROM {V} '
           f'WHERE "客戶名稱" = :customer AND {UNPAID} AND "逾期天數" > :overdue_gt '
           f'ORDER BY "逾期天數" DESC, "發票號碼" LIMIT 200')
    return guarded(sql, {"customer": p["customer"], "overdue_gt": p.get("overdue_gt") or 0})


def _inv_facts(cols, rows):
    return {"張數": len(rows), "未收合計": sum(r[4] or 0 for r in rows), "最長逾期天數": max((r[5] for r in rows), default=0)}


def _inv_summary(f):
    if not f["張數"]:
        return "這個客戶沒有符合條件的逾期發票。"
    return f"共 {f['張數']} 張，未收合計 {fmt('金額', f['未收合計'])}，最長逾期 {f['最長逾期天數']:,} 天。"


ar_invoices = QueryTemplate(
    id="ar_invoices", title="客戶逾期發票明細",
    description="某一個客戶的逾期（或逾期超過 N 天）未收發票明細",
    examples=["台陽科技有哪些發票逾期", "列出鴻遠機械逾期的發票", "精興金屬逾期超過 30 天的發票明細",
              "台陽科技欠款明細", "這個客戶哪幾張發票還沒付"],
    params=[ParamSpec("customer", "entity", "客戶", required=True, entity="customer"),
            ParamSpec("overdue_gt", "int", "逾期超過天數", default=0, min=0, max=3650)],
    build=_inv_build, facts=_inv_facts, summary=_inv_summary,
    columns=lambda p: ["發票號碼", "發票日期", "到期日", "發票金額", "未收金額", "逾期天數"],
)


# ---------- ar_aging ----------
def _aging_build(p):
    sql = (f"WITH b AS (SELECT CASE WHEN \"逾期天數\" <= 0 THEN 0 WHEN \"逾期天數\" <= 30 THEN 1 "
           f"WHEN \"逾期天數\" <= 60 THEN 2 ELSE 3 END AS k, \"未收金額\" FROM {V} WHERE {UNPAID}) "
           f"SELECT CASE k WHEN 0 THEN '未到期' WHEN 1 THEN '逾期 1–30 天' WHEN 2 THEN '逾期 31–60 天' "
           f"ELSE '逾期 61 天以上' END AS \"帳齡\", COUNT(*) AS \"張數\", ROUND(SUM(\"未收金額\"), 0) AS \"未收金額\", "
           f"ROUND(100.0 * SUM(\"未收金額\") / NULLIF(SUM(SUM(\"未收金額\")) OVER (), 0), 1) AS \"占比(%)\" "
           f"FROM b GROUP BY k ORDER BY k")
    return guarded(sql, {})


def _aging_facts(cols, rows):
    over = [r for r in rows if r[0] != "未到期"]
    return {"未收合計": sum(r[2] or 0 for r in rows), "逾期合計": sum(r[2] or 0 for r in over),
            "逾期61天以上": next((r[2] for r in rows if r[0] == "逾期 61 天以上"), 0)}


def _aging_summary(f):
    return (f"未收合計 {fmt('金額', f['未收合計'])}，其中已逾期 {fmt('金額', f['逾期合計'])}，"
            f"逾期 61 天以上 {fmt('金額', f['逾期61天以上'])}。")


ar_aging = QueryTemplate(
    id="ar_aging", title="應收帳齡分析",
    description="未收帳款依帳齡分組：未到期、逾期 1–30 天、31–60 天、61 天以上的張數、金額與占比",
    examples=["應收帳款的帳齡分佈", "逾期帳款分別逾期多久", "帳齡分析", "未收款依逾期天數分組", "應收帳齡結構"],
    params=[],
    build=_aging_build, facts=_aging_facts, summary=_aging_summary,
    columns=lambda p: ["帳齡", "張數", "未收金額", "占比(%)"],
)

TEMPLATES = [ar_summary, ar_by_customer, ar_invoices, ar_aging]
