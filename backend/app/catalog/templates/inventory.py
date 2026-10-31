"""庫存模板：呆滯明細、呆滯合計、缺料、單一料號、庫存排名。資料來源 v_庫存狀況。"""
from __future__ import annotations

from ..base import ParamSpec, QueryTemplate, guarded
from .common import DIR, ORDER_CHOICES, first, fmt, pick, top

V = '"v_庫存狀況"'
DEAD = '"未異動天數" >= :idle_days AND "現有庫存" > 0'
IDLE = ParamSpec("idle_days", "int", "未異動天數門檻", default=180, min=30, max=1000)


# ---------- stock_dead ----------
def _dead_build(p):
    sql = (f'SELECT "料號", "品名", "現有庫存", ROUND("庫存金額", 0) AS "庫存金額", "未異動天數", "最後異動日" '
           f'FROM {V} WHERE {DEAD} ORDER BY "庫存金額" DESC, "料號" LIMIT {top(p, default=50, hi=200)}')
    return guarded(sql, {"idle_days": p.get("idle_days") or 180})


def _dead_facts(cols, rows):
    f = first(cols, rows)
    return {"料號數": len(rows), "庫存金額合計": sum(r[3] or 0 for r in rows), "最高料號": f.get("料號"),
            "最高金額": f.get("庫存金額")}


def _dead_summary(f):
    if not f["料號數"]:
        return "沒有呆滯料號。"
    return (f"共 {f['料號數']} 個呆滯料號，庫存金額合計 {fmt('金額', f['庫存金額合計'])}，"
            f"最高為 {f['最高料號']}（{fmt('金額', f['最高金額'])}）。")


stock_dead = QueryTemplate(
    id="stock_dead", title="呆滯庫存明細",
    description="超過 N 天（預設 180 天）沒有異動且仍有庫存的料號「明細」，含各料號庫存金額，並提供金額合計。問「哪些料號」（即使同時問合計）用這個",
    examples=["哪些料號超過 180 天沒有異動", "呆滯庫存有哪些料號", "列出半年沒動的庫存", "超過一年沒出貨的料號",
              "哪些庫存放著不動", "呆料清單"],
    params=[IDLE, ParamSpec("top_n", "int", "筆數", default=50, min=1, max=200)],
    build=_dead_build, facts=_dead_facts, summary=_dead_summary,
    columns=lambda p: ["料號", "品名", "現有庫存", "庫存金額", "未異動天數", "最後異動日"],
)


# ---------- stock_dead_total ----------
def _dead_total_build(p):
    sql = (f'SELECT COUNT(*) AS "呆滯料號數", ROUND(SUM("庫存金額"), 0) AS "呆滯庫存金額" FROM {V} WHERE {DEAD}')
    return guarded(sql, {"idle_days": p.get("idle_days") or 180})


def _dead_total_summary(f):
    if not f.get("呆滯料號數"):
        return "沒有呆滯料號。"
    return f"呆滯料號 {f['呆滯料號數']} 個，共壓了 {fmt('金額', f['呆滯庫存金額'])}。"


stock_dead_total = QueryTemplate(
    id="stock_dead_total", title="呆滯庫存合計",
    description="呆滯（超過 N 天未異動）料號的數量與庫存金額「合計」，不列出料號。只問總數或總金額時用這個；問「哪些料號」請用呆滯庫存明細",
    examples=["呆滯庫存一共壓了多少錢", "呆料總金額", "有幾個料號是呆滯的", "半年沒動的庫存值多少錢", "呆滯庫存金額合計"],
    params=[IDLE],
    build=_dead_total_build, facts=lambda c, r: first(c, r), summary=_dead_total_summary,
    columns=lambda p: ["呆滯料號數", "呆滯庫存金額"],
)


# ---------- stock_shortage ----------
# 缺口 = max(待出貨 − 現有 − 在途, 0)；建議採購量 = 缺口 + 安全庫存（與每週預警 jobs/dead_stock.py 相同）
def _short_build(p):
    sql = (f'SELECT "料號", "品名", "現有庫存", "在途數量", "待出貨數量", "安全庫存", '
           f'GREATEST("待出貨數量" - "現有庫存" - "在途數量", 0) AS "缺口", '
           f'GREATEST("待出貨數量" - "現有庫存" - "在途數量", 0) + "安全庫存" AS "建議採購量", '
           f'"供應商", "供應商交期天數" FROM {V} '
           f'WHERE "現有庫存" + "在途數量" < "待出貨數量" OR "現有庫存" < "安全庫存" '
           f'ORDER BY "缺口" DESC, "料號" LIMIT 200')
    return guarded(sql, {})


def _short_facts(cols, rows):
    f = first(cols, rows)
    return {"料號數": len(rows), "建議採購合計": sum(r[7] or 0 for r in rows), "缺口最大料號": f.get("料號"),
            "缺口最大數量": f.get("缺口")}


def _short_summary(f):
    if not f["料號數"]:
        return "目前沒有缺料的料號。"
    return f"共 {f['料號數']} 個料號會缺料，缺口最大的是 {f['缺口最大料號']}（缺 {f['缺口最大數量']:,}）。"


stock_shortage = QueryTemplate(
    id="stock_shortage", title="缺料預警",
    description="依待出貨訂單、在途採購與安全庫存，找出會缺料的料號，並算出缺口與建議採購量",
    examples=["哪些料號會缺料", "依目前待出貨訂單，哪些料號庫存不夠", "建議採購多少", "庫存不夠出貨的料號",
              "低於安全庫存的料號", "缺料清單和建議採購量"],
    params=[],
    build=_short_build, facts=_short_facts, summary=_short_summary,
    columns=lambda p: ["料號", "品名", "現有庫存", "在途數量", "待出貨數量", "安全庫存", "缺口", "建議採購量",
                       "供應商", "供應商交期天數"],
)


# ---------- stock_lookup ----------
def _lookup_build(p):
    sql = (f'SELECT "料號", "品名", "現有庫存", "安全庫存", "待出貨數量", "在途數量", ROUND("庫存金額", 0) AS "庫存金額", '
           f'"最後異動日", "未異動天數", "供應商", "供應商交期天數" FROM {V} WHERE "料號" = :sku')
    return guarded(sql, {"sku": p["sku"]})


def _lookup_summary(f):
    if not f:
        return "查無這個料號。"
    return (f"{f['料號']}（{f['品名']}）現有庫存 {f['現有庫存']:,}，安全庫存 {f['安全庫存']:,}，"
            f"最後異動日 {f['最後異動日']}，供應商 {f['供應商']}。")


stock_lookup = QueryTemplate(
    id="stock_lookup", title="料號庫存查詢",
    description="單一料號的現有庫存、安全庫存、待出貨、在途、最後異動日與供應商",
    examples=["BRG-6205-2RS 目前庫存多少", "GEAR-M2-40T 還有幾個", "這個料號最後一次異動是什麼時候",
              "FST-M8x30-HEX 的供應商是誰", "查一下 BRG-6204-2RS 的庫存"],
    params=[ParamSpec("sku", "entity", "料號", required=True, entity="sku")],
    build=_lookup_build, facts=lambda c, r: first(c, r), summary=_lookup_summary,
    columns=lambda p: ["料號", "品名", "現有庫存", "安全庫存", "待出貨數量", "在途數量", "庫存金額", "最後異動日",
                       "未異動天數", "供應商", "供應商交期天數"],
)


# ---------- stock_rank ----------
STOCK_METRICS = {"庫存金額": ('ROUND("庫存金額", 0)', "庫存金額"), "現有庫存": ('"現有庫存"', "現有庫存"),
                 "未異動天數": ('"未異動天數"', "未異動天數")}


def _srank_build(p):
    m_sql, m_col = pick(STOCK_METRICS, p["metric"])
    sql = (f'SELECT "料號", "品名", {m_sql} AS "{m_col}" FROM {V} '
           f'ORDER BY 3 {DIR[p["order"]]} NULLS LAST, 1 LIMIT {top(p)}')
    return guarded(sql, {})


def _srank_facts(cols, rows):
    f = first(cols, rows)
    return {"指標": cols[2], "第一名": f.get("料號"), "第一名數值": f.get(cols[2]), "筆數": len(rows)}


def _srank_summary(f):
    if not f["筆數"]:
        return "查無庫存資料。"
    return f"{f['指標']}排第一的料號是 {f['第一名']}（{fmt(f['指標'], f['第一名數值'])}）。"


stock_rank = QueryTemplate(
    id="stock_rank", title="庫存排名",
    description="依庫存金額、現有庫存數量或未異動天數排出前幾名（或後幾名）料號",
    examples=["庫存金額最高的 5 個料號", "哪些料號庫存最多", "庫存量最少的十個料號", "壓最多錢的庫存是哪些",
              "放最久沒動的料號排名"],
    params=[ParamSpec("metric", "enum", "指標", default="庫存金額",
                      choices={"庫存金額": ["金額", "庫存價值", "壓多少錢"], "現有庫存": ["庫存量", "數量", "庫存數"],
                               "未異動天數": ["沒動多久", "放最久", "未異動"]}),
            ParamSpec("top_n", "int", "筆數", default=10, min=1, max=50),
            ParamSpec("order", "enum", "排序", default="desc", choices=ORDER_CHOICES)],
    build=_srank_build, facts=_srank_facts, summary=_srank_summary,
    columns=lambda p: ["料號", "品名", STOCK_METRICS[p["metric"]][1]],
)

TEMPLATES = [stock_dead, stock_dead_total, stock_shortage, stock_lookup, stock_rank]
