"""傳統介面用的 API：報表選單（GET /api/reports/catalog、POST /api/reports/run）與首頁儀表板（GET /api/dashboard）。

報表與儀表板直接執行 16 個既定程式（catalog/templates），**不經過 LLM**：
參數一樣經 intent.confirm() 驗證（白名單、名稱比對），SQL 一樣是寫死的模板、唯讀帳號、逾時 10 秒，
所以數字與問答頁完全一致。結論用模板的固定句型。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import audit
from ..agent import followups
from ..catalog import intent
from ..catalog.entities import default_index
from ..catalog.periods import resolve_period
from ..catalog.registry import TEMPLATES
from ..catalog.runner import execute, public_params
from ..catalog.templates.common import fmt

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

# 報表選單分組（依模板 id 前綴）
GROUPS = [("銷售", ("sales_",)), ("應收帳款", ("ar_",)), ("庫存", ("stock_",)), ("採購", ("supplier_", "purchase_"))]
PERIOD_CODES = ["this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year",
                "last_n_months:3", "last_n_months:6", "last_n_months:12", "last_n_months:18", "last_n_months:24", "all"]
OVERDUE_PRESETS = [(None, "不限"), (0, "已逾期"), (30, "逾期超過 30 天"), (60, "逾期超過 60 天"), (90, "逾期超過 90 天")]


def _group_of(tid: str) -> str:
    return next((g for g, prefixes in GROUPS if tid.startswith(prefixes)), "其他")


def _param_spec(s, today: date, entities) -> dict:
    out = {"name": s.name, "label": s.label, "kind": s.kind, "required": s.required, "default": s.default,
           "min": s.min, "max": s.max}
    if s.kind == "enum":
        out["options"] = [{"value": k, "label": intent.ENUM_DISPLAY.get(k, k)} for k in (s.choices or {})]
    elif s.kind == "period":
        codes = PERIOD_CODES if s.default in PERIOD_CODES else [s.default, *PERIOD_CODES]
        out["options"] = [{"value": c, "label": resolve_period(c, today).label} for c in codes]
    elif s.kind == "entity":
        out["options"] = [{"value": n, "label": n} for n in entities.names(s.entity)]
    elif s.name == "overdue_gt":
        out["kind"] = "enum"
        out["options"] = [{"value": v, "label": label} for v, label in OVERDUE_PRESETS
                          if v is not None or s.default is None]   # 預設已逾期的報表不提供「不限」
    return out


@router.get("/reports/catalog")
def catalog() -> dict:
    """報表選單：分組、每個報表的說明、條件欄位（含下拉選項）與結果欄位。"""
    today, entities = date.today(), default_index()
    groups: dict[str, list] = {g: [] for g, _ in GROUPS}
    for t in TEMPLATES.values():
        defaults = {s.name: s.default for s in t.params}
        try:
            cols = t.columns(defaults)
        except Exception:  # noqa: BLE001 — 欄位預覽只是說明
            cols = []
        groups.setdefault(_group_of(t.id), []).append({
            "id": t.id, "title": t.title, "description": re.sub(r"^【[^】]*】", "", t.description).split("。")[0],
            "example": t.examples[0], "columns": cols,
            "params": [_param_spec(s, today, entities) for s in t.params]})
    return {"groups": [{"name": g, "reports": items} for g, items in groups.items() if items]}


class RunRequest(BaseModel):
    template_id: str = Field(max_length=64)
    params: dict = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=64)


def run_template(template_id: str, params: dict, today: date | None = None) -> dict:
    """驗證參數 → 執行既定程式 → 程式算的 facts 與固定句型。參數不合法時丟 ValueError（訊息給使用者看）。"""
    today = today or date.today()
    it = intent.confirm(template_id, params, today)
    if it.kind != "template":
        raise ValueError(it.message or "參數不完整")
    t = TEMPLATES[template_id]
    q = t.build(it.params)
    cols, rows = execute(q)
    facts = t.facts(cols, rows)
    return {"template_id": t.id, "template_title": t.title, "params": public_params(it.params),
            "params_readable": it.params_readable, "notes": it.notes, "columns": cols, "rows": rows,
            "row_count": len(rows), "sql": q.sql, "binds": public_params(q.binds), "facts": facts,
            "answer": t.summary(facts)}


@router.post("/reports/run")
def run(req: RunRequest) -> dict:
    t0 = time.perf_counter()
    try:
        r = run_template(req.template_id, req.params)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:
        log.exception("報表 %s 執行失敗", req.template_id)
        return {"template_id": req.template_id, "error": f"查詢失敗：{str(e).splitlines()[0][:200]}",
                "columns": [], "rows": [], "row_count": 0}
    r["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    r["mode"], r["route"] = "template", "report"
    r.pop("facts")
    question = f"[報表] {r['template_title']}" + (f"：{'；'.join(r['params_readable'])}" if r["params_readable"] else "")
    r["followups"] = followups.suggest(question, route="sql", mode="template", template_id=r["template_id"],
                                       binds=r["binds"], columns=r["columns"], rows=r["rows"],
                                       params_readable=r["params_readable"], sources=[])
    r["audit_id"] = audit.write(audit.AuditRecord(
        question=question, session_id=req.session_id, route="report", sql_ok=True, sql_rows=r["row_count"],
        sql_text=f"{r['sql']}\n-- template: {r['template_id']}\n-- binds: {r['binds']}", answer=r["answer"],
        latency_ms=r["latency_ms"]))
    return r


# ---------------------------------------------------------------- 儀表板
def _row(r: dict, i: int = 0) -> dict:
    return dict(zip(r["columns"], r["rows"][i])) if len(r["rows"]) > i else {}


def _tile(key, title, value, unit, sub, tone, template_id, params, ask) -> dict:
    return {"key": key, "title": title, "value": value, "unit": unit, "sub": sub, "tone": tone,
            "report": {"template_id": template_id, "params": params}, "ask": ask}


def _pct_text(v) -> str:
    return "-" if v is None else f"{'+' if v > 0 else ''}{v:.1f}%"


TILES = {   # key: (template_id, params)
    "revenue": ("sales_compare", {"compare": "yoy_ytd", "metric": "營收", "dimension": "整體"}),
    "profit": ("sales_compare", {"compare": "yoy_ytd", "metric": "毛利", "dimension": "整體"}),
    "margin": ("sales_total", {"period": "this_year"}),
    "overdue": ("ar_summary", {"overdue_gt": 0}),
    "overdue60": ("ar_by_customer", {"overdue_gt": 60}),
    "dead": ("stock_dead_total", {}),
    "shortage": ("stock_shortage", {}),
    "ontime": ("supplier_ontime", {"order": "最低", "top_n": 3}),
}
CHARTS = {
    "trend": ("營收與毛利率（最近 12 個月）", "sales_trend", {"grain": "月", "period": "last_n_months:12"}),
    "top_customers": ("今年營收前 5 名客戶", "sales_rank", {"dimension": "客戶", "metric": "營收", "period": "this_year", "top_n": 5}),
    "aging": ("應收帳齡分布", "ar_aging", {}),
}


def _t_revenue(res):
    rev = _row(res["revenue"])
    return rev and _tile("revenue", "今年累計營收", rev["本期營收"], "元",
                         f"去年同期 {fmt('營收', rev['比較期營收'])}，{_pct_text(rev['增減(%)'])}",
                         "warn" if (rev["增減"] or 0) < 0 else "ok", *TILES["revenue"], "今年營收跟去年同期比如何？")


def _t_profit(res):
    prof, mar = _row(res["profit"]), _row(res["margin"])
    margin = f"毛利率 {fmt('毛利率', mar['毛利率(%)'])}；" if mar else ""
    return prof and _tile("profit", "今年累計毛利", prof["本期毛利"], "元",
                          f"{margin}去年同期 {fmt('毛利', prof['比較期毛利'])}，{_pct_text(prof['增減(%)'])}",
                          "warn" if (prof["增減"] or 0) < 0 else "ok", *TILES["profit"], "今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？")


def _t_overdue(res):
    od = _row(res["overdue"])
    return od and _tile("overdue", "逾期應收", od["未收總額"], "元",
                        f"{od['未收張數'] or 0} 張、{od['客戶數'] or 0} 個客戶；最久逾期 {od['最長逾期天數'] or 0} 天",
                        "warn" if od["未收總額"] else "ok", *TILES["overdue"], "逾期的應收帳款總共多少？")


def _t_overdue60(res):
    o60 = res["overdue60"]
    if not o60["columns"]:
        return None
    top = _row(o60)
    # 金額取帳齡分析「逾期 61 天以上」（先加總再四捨五入），和同頁的帳齡圖一致；客戶清單是逐客戶四捨五入
    aging = {r[0]: r[2] for r in res["aging"]["rows"]} if res["aging"]["columns"][:3] == ["帳齡", "張數", "未收金額"] else {}
    total = aging.get("逾期 61 天以上", sum(r[o60["columns"].index("未收金額")] or 0 for r in o60["rows"]))
    return _tile("overdue60", "逾期 60 天以上", total, "元",
                 f"{o60['row_count']} 個客戶" + (f"，最多：{top['客戶名稱']}" if top else ""),
                 "danger" if o60["row_count"] else "ok", *TILES["overdue60"], "哪些客戶的應收逾期超過 60 天？金額多少？")


def _t_dead(res):
    dead = _row(res["dead"])
    return dead and _tile("dead", "呆滯庫存（180 天未異動）", dead["呆滯庫存金額"], "元", f"{dead['呆滯料號數'] or 0} 個料號",
                          "warn" if dead["呆滯料號數"] else "ok", *TILES["dead"], "哪些料號超過 180 天沒動？壓了多少錢？")


def _t_shortage(res):
    sh = res["shortage"]
    if not sh["columns"]:
        return None
    skus = [r[sh["columns"].index("料號")] for r in sh["rows"]]
    return _tile("shortage", "缺料預警", sh["row_count"], "個料號", "、".join(skus[:3]) if skus else "目前沒有缺料",
                 "danger" if skus else "ok", *TILES["shortage"], "依目前待出貨訂單，哪些料號會缺料？建議採購多少？")


def _t_ontime(res):
    ot = _row(res["ontime"])
    return ot and _tile("ontime", "準時交貨率最低的供應商", ot["準時交貨率(%)"], "%", ot["供應商"] or "",
                        "warn", *TILES["ontime"], "各供應商的準時交貨率")


TILE_BUILDERS = [_t_revenue, _t_profit, _t_overdue, _t_overdue60, _t_dead, _t_shortage, _t_ontime]


def _tiles(res: dict, errors: list[str]) -> list[dict]:
    out = []
    for build in TILE_BUILDERS:   # 一張卡片出錯（例如欄位不符）只略過那一張
        try:
            t = build(res)
        except Exception as e:
            log.exception("儀表板卡片 %s 失敗", build.__name__)
            errors.append(f"{build.__name__[3:]}：{type(e).__name__} {e}"[:160])
            continue
        if t:
            out.append(t)
    return out


@router.get("/dashboard")
def dashboard() -> dict:
    """首頁指標卡與圖表。每一項都是既定程式的結果，附上「開啟報表」與「用問的」的連結。"""
    t0, today = time.perf_counter(), date.today()
    res, errors = {}, []
    for key, (tid, params) in {**TILES, **{k: (tid, p) for k, (_, tid, p) in CHARTS.items()}}.items():
        try:
            res[key] = run_template(tid, params, today)
        except Exception as e:
            log.exception("儀表板 %s 失敗", key)
            errors.append(f"{key}：{str(e).splitlines()[0][:120]}")
            res[key] = {"columns": [], "rows": [], "row_count": 0}
    charts = [{"key": k, "title": title, "columns": res[k]["columns"], "rows": res[k]["rows"],
               "report": {"template_id": tid, "params": p}} for k, (title, tid, p) in CHARTS.items() if res[k]["rows"]]
    tiles = _tiles(res, errors)
    return {"as_of": today.isoformat(), "tiles": tiles, "charts": charts, "errors": errors,
            "latency_ms": int((time.perf_counter() - t0) * 1000)}


@router.get("/docs")
def docs() -> dict:
    """系統介紹頁用：已收錄的文件，依類型分組（檔名前綴）。"""
    groups: dict[str, list[str]] = {}
    for name in sorted(followups.doc_names()):
        kind, sep, who = name.partition("_")
        groups.setdefault(kind if sep else "其他", []).append(who if sep else name)
    return {"groups": [{"name": k, "items": v} for k, v in groups.items()], "total": sum(len(v) for v in groups.values())}
