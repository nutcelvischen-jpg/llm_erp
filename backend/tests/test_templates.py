"""T14c：16 個既定查詢程式。"""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.app.catalog.base import TemplateError, guarded
from backend.app.catalog.registry import TEMPLATES
from backend.app.sql_guard import validate

TODAY = date(2026, 10, 31)
ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SAMPLE = {"customer": "台陽科技", "sku": "BRG-6205-2RS"}


def defaults(t, **over):
    p = {s.name: s.default for s in t.params}
    for s in t.params:
        if s.required:
            p[s.name] = REQUIRED_SAMPLE[s.name]
    return {**p, "_today": TODAY, **over}


def all_combos(t):
    """每個 enum 參數的每個標準值各試一次（其他用預設）。"""
    yield defaults(t)
    for s in t.params:
        if s.kind == "enum":
            for k in s.choices:
                yield defaults(t, **{s.name: k})


def test_sixteen_templates_well_formed():
    assert len(TEMPLATES) == 16
    for t in TEMPLATES.values():
        assert t.id and t.title and t.description
        assert len(t.examples) >= 5 and len(set(t.examples)) == len(t.examples), t.id
        for s in t.params:
            if s.kind == "enum":
                assert s.choices and (s.default is None or s.default in s.choices), (t.id, s.name)
            if s.kind == "entity":
                assert s.entity in ("customer", "supplier", "sku", "rep")


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_every_combo_passes_guard_and_uses_binds(tid):
    t = TEMPLATES[tid]
    for p in all_combos(t):
        q = t.build(p)
        g = validate(q.sql)
        assert g.ok, (tid, p, g.reason)
        for name in set(__import__("re").findall(r"(?<!:):(\w+)", q.sql)):
            assert name in q.binds, (tid, name)
        assert t.columns(p), tid


def test_user_strings_only_in_binds():
    evil = "x'; DROP TABLE erp.customers; --"
    for tid, key in [("sales_total", "customer"), ("sales_trend", "customer"), ("ar_summary", "customer"),
                     ("ar_invoices", "customer"), ("stock_lookup", "sku"), ("sales_total", "rep")]:
        t = TEMPLATES[tid]
        q = t.build(defaults(t, **{key: evil}))
        assert evil not in q.sql and "DROP" not in q.sql and q.binds[key] == evil


def test_invalid_enum_and_clamped_ints():
    t = TEMPLATES["sales_rank"]
    with pytest.raises(ValueError):
        t.build(defaults(t, dimension="薪資"))
    with pytest.raises(ValueError):
        t.build(defaults(t, order="desc; DROP"))
    assert t.build(defaults(t, top_n=999)).sql.endswith("LIMIT 50")
    assert t.build(defaults(t, top_n=0)).sql.endswith("LIMIT 1")
    with pytest.raises(ValueError):
        t.build(defaults(t, period="yesterday"))


def test_missing_required_param():
    with pytest.raises(KeyError):
        TEMPLATES["stock_lookup"].build({"_today": TODAY})


def test_period_binds_are_dates():
    q = TEMPLATES["sales_total"].build(defaults(TEMPLATES["sales_total"], period="last_year"))
    assert q.binds["date_from"] == date(2025, 1, 1) and q.binds["date_to"] == date(2026, 1, 1)
    q = TEMPLATES["sales_compare"].build(defaults(TEMPLATES["sales_compare"]))
    assert q.binds["prev_from"] == date(2025, 1, 1) and q.binds["prev_to"] == date(2025, 11, 1)


def test_guarded_rejects_bad_sql():
    with pytest.raises(TemplateError):
        guarded("DELETE FROM erp.customers", {})


# ---------- facts / summary：以範例資料驗證 ----------
SAMPLES = {
    "sales_rank": (["客戶名稱", "營收"], [["華發實業", 11979390], ["鴻遠機械", 9869353]]),
    "sales_total": (["營收", "毛利", "毛利率(%)", "訂單數"], [[83487889, 20465169, 24.5, 2470]]),
    "sales_trend": (["月份", "營收", "毛利", "毛利率(%)"], [["2026-05", 7000000, 1700000, 24.3], ["2026-06", 8600000, 2100000, 24.4]]),
    "sales_compare": (["對象", "本期營收", "比較期營收", "增減", "增減(%)"],
                      [["（全公司）", 83487889, 82463973, 1023916, 1.2], ["鴻遠機械", 9869353, 10804945, -935592, -8.7]]),
    "sales_largest_orders": (["訂單編號", "客戶名稱", "訂單日期", "訂單金額"], [["SO1", "華發實業", "2026-09-15", 206055]]),
    "ar_summary": (["未收總額", "未收張數", "客戶數", "最長逾期天數"], [[11896496, 377, 39, 136]]),
    "ar_by_customer": (["客戶名稱", "未收張數", "未收金額", "最長逾期天數"], [["台陽科技", 3, 241643, 120]]),
    "ar_invoices": (["發票號碼", "發票日期", "到期日", "發票金額", "未收金額", "逾期天數"], [["INV1", "2026-05-01", "2026-06-01", 100000, 80000, 150]]),
    "ar_aging": (["帳齡", "張數", "未收金額", "占比(%)"], [["未到期", 300, 8000000, 70.0], ["逾期 61 天以上", 5, 274239, 2.3]]),
    "stock_dead": (["料號", "品名", "現有庫存", "庫存金額", "未異動天數", "最後異動日"], [["CUS-008", "客製件", 1080, 1576869, 222, "2026-03-23"]]),
    "stock_dead_total": (["呆滯料號數", "呆滯庫存金額"], [[12, 2902033]]),
    "stock_shortage": (["料號", "品名", "現有庫存", "在途數量", "待出貨數量", "安全庫存", "缺口", "建議採購量", "供應商", "供應商交期天數"],
                       [["GEAR-M2-40T", "正齒輪", 349, 0, 998, 113, 649, 762, "精密熱處理", 28]]),
    "stock_lookup": (["料號", "品名", "現有庫存", "安全庫存", "待出貨數量", "在途數量", "庫存金額", "最後異動日", "未異動天數", "供應商", "供應商交期天數"],
                     [["BRG-6205-2RS", "軸承", 570, 20, 0, 0, 30000, "2026-03-31", 214, "中鋼軸承材料", 14]]),
    "stock_rank": (["料號", "品名", "庫存金額"], [["CUS-008", "客製件", 1576869]]),
    "supplier_ontime": (["供應商", "已收貨筆數", "準時筆數", "準時交貨率(%)"], [["億豐表面處理", 149, 30, 20.1]]),
    "purchase_summary": (["採購金額", "採購單數"], [[50245143, 324]]),
}


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_facts_and_summary(tid):
    t = TEMPLATES[tid]
    cols, rows = SAMPLES[tid]
    s = t.summary(t.facts(cols, rows))
    assert s and "None" not in s, (tid, s)
    empty = t.summary(t.facts(cols, []))
    assert empty and "None" not in empty, (tid, empty)


def test_purchase_by_supplier_summary():
    t = TEMPLATES["purchase_summary"]
    s = t.summary(t.facts(["供應商", "採購金額", "採購單數"], [["大成鋼鐵", 900000, 12], ["永信金屬", 500000, 8]]))
    assert "2 家供應商" in s and "1,400,000 元" in s


# ---------- 真實資料庫 ----------
def run(t, p):
    from sqlalchemy import text

    from backend.app.db import engine_ro
    from backend.app.text2sql import _jsonable

    q = t.build(p)
    with engine_ro.connect() as c:
        r = c.execute(text(q.sql), q.binds)
        return list(r.keys()), [[_jsonable(v) for v in row] for row in r]


@pytest.mark.db
@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_every_template_runs_on_real_db(tid):
    t = TEMPLATES[tid]
    p = defaults(t, _today=date.today())
    cols, rows = run(t, p)
    assert rows, tid
    assert cols == t.columns(p), tid


@pytest.mark.db
def test_template_map_matches_golden_answers():
    from backend.app import eval_checks
    from backend.app.text2sql import _execute

    golden = {q["id"]: q for q in yaml.safe_load((ROOT / "data/golden/text2sql.yaml").read_text(encoding="utf-8"))}
    mapping = yaml.safe_load((ROOT / "data/golden/template_map.yaml").read_text(encoding="utf-8"))
    assert len(mapping) == 26
    failures = []
    for m in mapping:
        q, t = golden[m["id"]], TEMPLATES[m["template"]]
        p = {**{s.name: s.default for s in t.params}, **m["params"], "_today": date.today()}
        _, rows = run(t, p)
        ref = _execute(q["rows_match"])[1] if "rows_match" in q else None
        ok, why = eval_checks.evaluate(q, SimpleNamespace(error=None, rows=rows, row_count=len(rows)), ref)
        if not ok:
            failures.append(f"{m['id']} {m['template']}：{why}")
    assert not failures, "\n".join(failures)
