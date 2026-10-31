"""採購模板：供應商準時交貨率、採購金額。資料來源 v_採購明細。"""
from __future__ import annotations

from ..base import ParamSpec, QueryTemplate, guarded
from .common import first, fmt, period_binds, pick, top

V = '"v_採購明細"'


# ---------- supplier_ontime ----------
ONTIME_ORDER = {"最低": "ASC", "最高": "DESC"}


def _ontime_build(p):
    sql = (f'SELECT "供應商", COUNT(*) AS "已收貨筆數", '
           f'COUNT(*) FILTER (WHERE "實際到貨日" <= "預計到貨日") AS "準時筆數", '
           f'ROUND(100.0 * COUNT(*) FILTER (WHERE "實際到貨日" <= "預計到貨日") / COUNT(*), 1) AS "準時交貨率(%)" '
           f'FROM {V} WHERE "採購狀態" = \'已收貨\' GROUP BY 1 ORDER BY 4 {pick(ONTIME_ORDER, p["order"])}, 1 '
           f'LIMIT {top(p)}')
    return guarded(sql, {})


def _ontime_facts(cols, rows):
    f = first(cols, rows)
    return {"筆數": len(rows), "第一名": f.get("供應商"), "第一名準時率": f.get("準時交貨率(%)")}


def _ontime_summary(f):
    if not f["筆數"]:
        return "沒有已收貨的採購資料。"
    return f"列出 {f['筆數']} 家供應商，第一名是 {f['第一名']}（準時交貨率 {fmt('率', f['第一名準時率'])}）。"


supplier_ontime = QueryTemplate(
    id="supplier_ontime", title="供應商準時交貨率",
    description="依已收貨的採購明細計算各供應商的準時交貨率（實際到貨日 ≤ 預計到貨日），由低到高或由高到低",
    examples=["各供應商的準時交貨率", "哪個供應商最常遲交", "準時率最高的供應商", "供應商交期達成率排名",
              "哪家供應商交貨最不準時"],
    params=[ParamSpec("order", "enum", "排序", default="最低",
                      choices={"最低": ["最差", "最不準時", "最常遲交", "由低到高"], "最高": ["最好", "最準時", "由高到低"]}),
            ParamSpec("top_n", "int", "筆數", default=10, min=1, max=50)],
    build=_ontime_build, facts=_ontime_facts, summary=_ontime_summary,
    columns=lambda p: ["供應商", "已收貨筆數", "準時筆數", "準時交貨率(%)"],
)


# ---------- purchase_summary ----------
STATUS = {"全部有效": '"採購狀態" <> \'取消\'', "待交貨": '"採購狀態" = \'待交貨\'', "已收貨": '"採購狀態" = \'已收貨\''}
GROUPS = {"無": None, "供應商": '"供應商"'}


def _purch_build(p):
    cond = pick(STATUS, p["status"])
    grp = pick(GROUPS, p["group"])
    where = f'"採購日期" >= :date_from AND "採購日期" < :date_to AND {cond}'
    if grp is None:
        sql = (f'SELECT ROUND(SUM("採購金額"), 0) AS "採購金額", COUNT(DISTINCT "採購單號") AS "採購單數" '
               f'FROM {V} WHERE {where}')
    else:
        sql = (f'SELECT {grp} AS "供應商", ROUND(SUM("採購金額"), 0) AS "採購金額", '
               f'COUNT(DISTINCT "採購單號") AS "採購單數" FROM {V} WHERE {where} '
               f'GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {top(p, default=50)}')
    return guarded(sql, period_binds(p))


def _purch_facts(cols, rows):
    if cols[0] == "供應商":
        f = first(cols, rows)
        return {"供應商數": len(rows), "採購金額合計": sum(r[1] or 0 for r in rows), "最高供應商": f.get("供應商"),
                "最高金額": f.get("採購金額")}
    return first(cols, rows)


def _purch_summary(f):
    if "供應商數" in f:
        if not f["供應商數"]:
            return "這段期間沒有採購資料。"
        return (f"共 {f['供應商數']} 家供應商，採購金額合計 {fmt('金額', f['採購金額合計'])}，"
                f"最高為 {f['最高供應商']}（{fmt('金額', f['最高金額'])}）。")
    if not f.get("採購單數"):
        return "這段期間沒有採購資料。"
    return f"採購金額 {fmt('金額', f['採購金額'])}，共 {f['採購單數']:,} 張採購單。"


purchase_summary = QueryTemplate(
    id="purchase_summary", title="採購金額",
    description="某段期間的採購金額合計，可只看待交貨（在途）或已收貨，或依供應商彙總",
    examples=["今年向供應商採購的總金額", "還在路上的採購單金額多少", "各供應商今年的採購金額", "上個月採購了多少錢",
              "待交貨的採購單合計", "去年跟哪個供應商買最多"],
    params=[ParamSpec("period", "period", "期間", default="this_year"),
            ParamSpec("status", "enum", "採購狀態", default="全部有效",
                      choices={"全部有效": ["全部", "有效", "不含取消"], "待交貨": ["在途", "還沒到", "未到貨", "路上"],
                               "已收貨": ["已到貨", "已交貨", "收到的"]}),
            ParamSpec("group", "enum", "彙總方式", default="無",
                      choices={"無": ["合計", "總額"], "供應商": ["依供應商", "各供應商", "按供應商"]}),
            ParamSpec("top_n", "int", "筆數", default=50, min=1, max=50)],
    build=_purch_build, facts=_purch_facts, summary=_purch_summary,
    columns=lambda p: (["供應商"] if p["group"] == "供應商" else []) + ["採購金額", "採購單數"],
)

TEMPLATES = [supplier_ontime, purchase_summary]
