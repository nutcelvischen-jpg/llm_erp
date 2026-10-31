"""銷售模板：排名、合計、趨勢、同期比較、最大訂單。資料來源 v_銷售明細（已排除取消單）。"""
from __future__ import annotations

from ..base import ParamSpec, QueryTemplate, guarded
from .common import (
    CATEGORIES,
    DIR,
    ORDER_CHOICES,
    REGIONS,
    compare_binds,
    first,
    fmt,
    opt_eq,
    period_binds,
    pick,
    top,
)

V = '"v_銷售明細"'
IN_PERIOD = '"訂單日期" >= :date_from AND "訂單日期" < :date_to'
CUSTOMER, CATEGORY, REP, REGION = '"客戶名稱"', '"產品類別"', '"負責業務"', '"客戶區域"'

DIMENSIONS = {"客戶": ('"客戶名稱"', "客戶名稱"), "產品": ('"品名"', "品名"), "料號": ('"料號"', "料號"),
              "產品類別": ('"產品類別"', "產品類別"), "業務": ('"負責業務"', "負責業務"),
              "區域": ('"客戶區域"', "客戶區域")}
DIM_CHOICES = {"客戶": ["顧客", "客人", "買家", "customer"], "產品": ["品名", "商品", "品項"],
               "料號": ["SKU", "sku", "零件編號", "品號"], "產品類別": ["類別", "產品線", "品類", "分類"],
               "業務": ["業務員", "業務人員", "銷售人員", "負責業務"], "區域": ["地區", "客戶區域", "區"]}
METRICS = {
    "營收": ('ROUND(SUM("銷售金額"), 0)', "營收"),
    "毛利": ('ROUND(SUM("毛利"), 0)', "毛利"),
    "毛利率": ('ROUND(100.0 * SUM("毛利") / NULLIF(SUM("銷售金額"), 0), 1)', "毛利率(%)"),
    "數量": ('SUM("數量")', "銷售數量"),
    "訂單數": ('COUNT(DISTINCT "訂單編號")', "訂單數"),
    "營收占比": ('ROUND(100.0 * SUM("銷售金額") / NULLIF(SUM(SUM("銷售金額")) OVER (), 0), 1)', "營收占比(%)"),
}
METRIC_CHOICES = {"營收": ["業績", "銷售額", "銷售金額", "收入", "營業額", "賣多少"], "毛利": ["毛利額", "賺多少"],
                  "毛利率": ["毛利百分比", "利潤率"], "數量": ["銷售數量", "銷量", "出貨量", "賣幾個"],
                  "訂單數": ["訂單量", "張數", "幾張訂單"], "營收占比": ["占比", "比例", "貢獻比例", "佔比"]}
PERIOD = ParamSpec("period", "period", "期間", default="this_year")


# ---------- sales_rank ----------
def _rank_build(p):
    dim_sql, dim_col = pick(DIMENSIONS, p["dimension"])
    m_sql, m_col = pick(METRICS, p["metric"])
    extra = ""
    if p["metric"] in ("毛利率", "營收占比"):
        extra = ', ROUND(SUM("銷售金額"), 0) AS "營收"'
    sql = (f'SELECT {dim_sql} AS "{dim_col}", {m_sql} AS "{m_col}"{extra} FROM {V} WHERE {IN_PERIOD} '
           f'GROUP BY 1 ORDER BY 2 {pick(DIR, p["order"])} NULLS LAST, 1 LIMIT {top(p, default=5)}')
    return guarded(sql, period_binds(p))


def _rank_facts(cols, rows):
    f = first(cols, rows)
    return {"維度": cols[0].removesuffix("名稱"), "指標": cols[1], "第一名": f.get(cols[0]), "第一名數值": f.get(cols[1]),
            "筆數": len(rows)}


def _rank_summary(f):
    if not f["筆數"]:
        return "查無符合條件的資料。"
    return f"{f['指標']}排第一的{f['維度']}是 {f['第一名']}（{fmt(f['指標'], f['第一名數值'])}），共列出 {f['筆數']} 筆。"


sales_rank = QueryTemplate(
    id="sales_rank", title="銷售排名",
    description="依客戶／產品／料號／產品類別／業務／區域，排出營收、毛利、毛利率、數量、訂單數或營收占比的前幾名（或後幾名）",
    examples=["今年營收前五名的客戶", "哪個業務今年業績最好", "今年賣最多的三個料號", "各產品類別的毛利率排名",
              "毛利最低的五個客戶是誰", "各區域營收占比", "去年哪個產品賣得最好", "本月訂單最多的客戶"],
    params=[ParamSpec("dimension", "enum", "排名對象", default="客戶", choices={k: v for k, v in DIM_CHOICES.items()}),
            ParamSpec("metric", "enum", "指標", default="營收", choices=METRIC_CHOICES),
            PERIOD,
            ParamSpec("top_n", "int", "筆數", default=5, min=1, max=50),
            ParamSpec("order", "enum", "排序", default="desc", choices=ORDER_CHOICES)],
    build=_rank_build, facts=_rank_facts, summary=_rank_summary,
    columns=lambda p: [DIMENSIONS[p["dimension"]][1], METRICS[p["metric"]][1]]
    + (["營收"] if p["metric"] in ("毛利率", "營收占比") else []),
)


# ---------- sales_total ----------
def _total_build(p):
    sql = (f'SELECT ROUND(SUM("銷售金額"), 0) AS "營收", ROUND(SUM("毛利"), 0) AS "毛利", '
           f'ROUND(100.0 * SUM("毛利") / NULLIF(SUM("銷售金額"), 0), 1) AS "毛利率(%)", '
           f'COUNT(DISTINCT "訂單編號") AS "訂單數" FROM {V} WHERE {IN_PERIOD} '
           f'AND {opt_eq(CUSTOMER, "customer")} AND {opt_eq(CATEGORY, "category")} '
           f'AND {opt_eq(REP, "rep")} AND {opt_eq(REGION, "region")}')
    binds = {**period_binds(p), **{k: p.get(k) for k in ("customer", "category", "rep", "region")}}
    return guarded(sql, binds)


def _total_facts(cols, rows):
    return first(cols, rows)


def _total_summary(f):
    if f.get("營收") is None:
        return "這段期間沒有銷售資料。"
    return (f"營收 {fmt('營收', f['營收'])}，毛利 {fmt('毛利', f['毛利'])}，毛利率 {fmt('毛利率(%)', f['毛利率(%)'])}，"
            f"訂單 {f['訂單數']:,} 張。")


sales_total = QueryTemplate(
    id="sales_total", title="銷售合計",
    description="某段期間的營收、毛利、毛利率與訂單數合計；可限定客戶、產品類別、業務或區域",
    examples=["今年到目前總營收多少", "上個月的毛利率是多少", "去年全年營收和毛利", "這個月接了幾張訂單",
              "鴻遠機械今年的營收", "軸承類今年賣了多少錢", "北部客戶去年的業績", "去年第三季的毛利率"],
    params=[PERIOD,
            ParamSpec("customer", "entity", "客戶", entity="customer"),
            ParamSpec("category", "enum", "產品類別", choices=CATEGORIES),
            ParamSpec("rep", "entity", "業務", entity="rep"),
            ParamSpec("region", "enum", "區域", choices=REGIONS)],
    build=_total_build, facts=_total_facts, summary=_total_summary,
    columns=lambda p: ["營收", "毛利", "毛利率(%)", "訂單數"],
)


# ---------- sales_trend ----------
GRAINS = {"月": ("'YYYY-MM'", "month", "月份"), "季": ("'YYYY\"Q\"Q'", "quarter", "季度")}
TREND_ORDER = {"time": "1 ASC", "desc": "2 DESC", "asc": "2 ASC"}


def _trend_build(p):
    fmt_sql, trunc, label = pick(GRAINS, p["grain"])
    limit = f" LIMIT {top(p, default=200, hi=200)}" if p.get("top_n") else ""
    sql = (f'SELECT TO_CHAR(DATE_TRUNC(\'{trunc}\', "訂單日期"), {fmt_sql}) AS "{label}", '
           f'ROUND(SUM("銷售金額"), 0) AS "營收", ROUND(SUM("毛利"), 0) AS "毛利", '
           f'ROUND(100.0 * SUM("毛利") / NULLIF(SUM("銷售金額"), 0), 1) AS "毛利率(%)" '
           f'FROM {V} WHERE {IN_PERIOD} AND {opt_eq(CUSTOMER, "customer")} '
           f'GROUP BY 1 ORDER BY {pick(TREND_ORDER, p["order"])}{limit}')
    return guarded(sql, {**period_binds(p), "customer": p.get("customer")})


def _trend_facts(cols, rows):
    if not rows:
        return {"期數": 0}
    rev = [r[1] or 0 for r in rows]
    hi, lo = rows[rev.index(max(rev))], rows[rev.index(min(rev))]
    return {"期別": cols[0], "期數": len(rows), "最高期": hi[0], "最高營收": hi[1], "最低期": lo[0], "最低營收": lo[1],
            "營收合計": sum(rev)}


def _trend_summary(f):
    if not f["期數"]:
        return "這段期間沒有銷售資料。"
    if f["期數"] == 1:
        return f"{f['最高期']} 營收 {fmt('營收', f['最高營收'])}。"
    return (f"共 {f['期數']} 期，營收最高為 {f['最高期']}（{fmt('營收', f['最高營收'])}），"
            f"最低為 {f['最低期']}（{fmt('營收', f['最低營收'])}）。")


sales_trend = QueryTemplate(
    id="sales_trend", title="營收趨勢",
    description="每月或每季的營收、毛利、毛利率走勢；也可以找出營收最高或最低的月份／季度；可限定客戶",
    examples=["最近 6 個月每個月的營收", "今年哪個月營收最高", "近兩年每一季的毛利率走勢", "鴻遠機械每個月的訂單金額",
              "營收最差的是哪個月", "去年各月份業績", "最近一年營收趨勢"],
    params=[ParamSpec("grain", "enum", "時間單位", default="月", choices={"月": ["每月", "月份", "按月"],
                                                                     "季": ["每季", "季度", "按季"]}),
            ParamSpec("period", "period", "期間", default="last_n_months:6"),
            ParamSpec("customer", "entity", "客戶", entity="customer"),
            ParamSpec("order", "enum", "排序", default="time",
                      choices={"time": ["依時間", "時間順序"], "desc": ORDER_CHOICES["desc"], "asc": ORDER_CHOICES["asc"]}),
            ParamSpec("top_n", "int", "筆數", min=1, max=200)],
    build=_trend_build, facts=_trend_facts, summary=_trend_summary,
    columns=lambda p: [GRAINS[p["grain"]][2], "營收", "毛利", "毛利率(%)"],
)


# ---------- sales_compare ----------
CMP_METRICS = {"營收": ('SUM("銷售金額")', "營收"), "毛利": ('SUM("毛利")', "毛利"), "數量": ('SUM("數量")', "銷售數量")}
CMP_DIMS = {"整體": None, "客戶": '"客戶名稱"', "產品類別": '"產品類別"', "業務": '"負責業務"', "區域": '"客戶區域"'}
CMP_ORDER = {"下滑最多": "ASC", "成長最多": "DESC"}


def _cmp_build(p):
    m_sql, m_col = pick(CMP_METRICS, p["metric"])
    dim = pick(CMP_DIMS, p["dimension"])
    binds = compare_binds(p)
    cur = '"訂單日期" >= :cur_from AND "訂單日期" < :cur_to'
    prev = '"訂單日期" >= :prev_from AND "訂單日期" < :prev_to'
    pct_expr = "ROUND(100.0 * (now_v - prev_v) / NULLIF(prev_v, 0), 1)"
    if dim is None:
        sql = (f"WITH t AS (SELECT {m_sql} FILTER (WHERE {cur}) AS now_v, {m_sql} FILTER (WHERE {prev}) AS prev_v "
               f"FROM {V}) SELECT '（全公司）' AS \"對象\", ROUND(now_v, 0) AS \"本期{m_col}\", "
               f"ROUND(prev_v, 0) AS \"比較期{m_col}\", ROUND(now_v - prev_v, 0) AS \"增減\", "
               f'{pct_expr} AS "增減(%)" FROM t')
        return guarded(sql, binds)
    sql = (f"WITH g AS (SELECT {dim} AS k, COALESCE({m_sql} FILTER (WHERE {cur}), 0) AS now_v, "
           f"COALESCE({m_sql} FILTER (WHERE {prev}), 0) AS prev_v FROM {V} "
           f"WHERE ({cur}) OR ({prev}) GROUP BY 1), "
           f"r AS (SELECT 0 AS ord, '（全公司）' AS k, SUM(now_v) AS now_v, SUM(prev_v) AS prev_v FROM g "
           f"UNION ALL SELECT * FROM (SELECT 1, k, now_v, prev_v FROM g "
           f"ORDER BY now_v - prev_v {pick(CMP_ORDER, p['order'])}, k LIMIT {top(p)}) s) "
           f'SELECT k AS "對象", ROUND(now_v, 0) AS "本期{m_col}", ROUND(prev_v, 0) AS "比較期{m_col}", '
           f'ROUND(now_v - prev_v, 0) AS "增減", {pct_expr} AS "增減(%)" FROM r '
           f"ORDER BY ord, now_v - prev_v {pick(CMP_ORDER, p['order'])}, k")
    return guarded(sql, binds)


def _cmp_facts(cols, rows):
    if not rows:
        return {"筆數": 0}
    total = rows[0]
    f = {"指標": cols[1].removeprefix("本期"), "整體本期": total[1], "整體比較期": total[2], "整體增減": total[3],
         "整體增減(%)": total[4], "筆數": len(rows) - 1}
    if len(rows) > 1:
        f.update({"第一名": rows[1][0], "第一名增減": rows[1][3], "第一名增減(%)": rows[1][4]})
    return f


def _cmp_summary(f):
    if f.get("整體本期") is None:
        return "查無比較資料。"
    unit = "數量" if f["指標"] == "銷售數量" else "金額"  # fmt 依欄位名稱決定「元」或千分位
    d = f["整體增減"] or 0
    s = (f"全公司{f['指標']}本期 {fmt(unit, f['整體本期'])}，比較期 {fmt(unit, f['整體比較期'])}，"
         f"{'減少' if d < 0 else '增加'} {fmt(unit, abs(d))}（{fmt('%', f['整體增減(%)'])}）。")
    if f.get("第一名") is not None:
        s += f"變化最大的是 {f['第一名']}（{fmt(unit, f['第一名增減'])}）。"
    return s


sales_compare = QueryTemplate(
    id="sales_compare", title="同期比較",
    description="今年累計 vs 去年同期、本月 vs 上月同期、本季 vs 上季同期的營收／毛利／數量比較；可依客戶、產品類別、業務、區域找出下滑或成長最多者",
    examples=["今年營收跟去年同期比如何", "哪個客戶今年的營收比去年同期掉最多", "今年毛利跟去年同期比，哪個客戶掉最多",
              "這個月業績比上個月同期好嗎", "本季跟上季比，哪個產品類別成長最多", "哪個業務今年衰退最多",
              "各區域營收和去年同期相比"],
    params=[ParamSpec("compare", "enum", "比較方式", default="yoy_ytd",
                      choices={"yoy_ytd": ["去年同期", "年增", "YoY", "跟去年比"], "mom": ["上月同期", "月增", "跟上個月比"],
                               "qoq": ["上季同期", "季增", "跟上一季比"]}),
            ParamSpec("metric", "enum", "指標", default="營收",
                      choices={"營收": METRIC_CHOICES["營收"], "毛利": METRIC_CHOICES["毛利"], "數量": METRIC_CHOICES["數量"]}),
            ParamSpec("dimension", "enum", "比較對象", default="整體",
                      choices={"整體": ["全公司", "總體", "公司整體"], "客戶": DIM_CHOICES["客戶"],
                               "產品類別": DIM_CHOICES["產品類別"], "業務": DIM_CHOICES["業務"], "區域": DIM_CHOICES["區域"]}),
            ParamSpec("top_n", "int", "筆數", default=10, min=1, max=50),
            ParamSpec("order", "enum", "排序", default="下滑最多",
                      choices={"下滑最多": ["衰退最多", "掉最多", "減少最多", "最差"], "成長最多": ["增加最多", "進步最多", "最好"]})],
    build=_cmp_build, facts=_cmp_facts, summary=_cmp_summary,
    columns=lambda p: ["對象", f"本期{CMP_METRICS[p['metric']][1]}", f"比較期{CMP_METRICS[p['metric']][1]}", "增減", "增減(%)"],
)


# ---------- sales_largest_orders ----------
def _orders_build(p):
    sql = (f'SELECT "訂單編號", "客戶名稱", "訂單日期", ROUND(SUM("銷售金額"), 0) AS "訂單金額" FROM {V} '
           f'WHERE {IN_PERIOD} GROUP BY 1, 2, 3 ORDER BY 4 DESC, 1 LIMIT {top(p, default=5)}')
    return guarded(sql, period_binds(p))


def _orders_facts(cols, rows):
    f = first(cols, rows)
    return {"筆數": len(rows), "最大訂單": f.get("訂單編號"), "客戶": f.get("客戶名稱"), "金額": f.get("訂單金額")}


def _orders_summary(f):
    if not f["筆數"]:
        return "這段期間沒有訂單。"
    return f"金額最大的訂單是 {f['最大訂單']}（{f['客戶']}，{fmt('金額', f['金額'])}）。"


sales_largest_orders = QueryTemplate(
    id="sales_largest_orders", title="最大訂單",
    description="某段期間金額最大的幾張銷售訂單（訂單編號、客戶、日期、金額）",
    examples=["今年金額最大的一張訂單", "上個月最大的五筆訂單", "去年最大單是哪一張", "本季金額最高的訂單有哪些",
              "最近 30 天的大單"],
    params=[PERIOD, ParamSpec("top_n", "int", "筆數", default=5, min=1, max=50)],
    build=_orders_build, facts=_orders_facts, summary=_orders_summary,
    columns=lambda p: ["訂單編號", "客戶名稱", "訂單日期", "訂單金額"],
)

TEMPLATES = [sales_rank, sales_total, sales_trend, sales_compare, sales_largest_orders]
