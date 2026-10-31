import pytest
from fastapi.testclient import TestClient

from backend.app.api import reports
from backend.app.catalog import intent
from backend.app.catalog.entities import EntityIndex
from backend.app.main import app

client = TestClient(app)
ENT = EntityIndex({"customer": lambda: ["台陽科技", "鴻遠機械"], "sku": lambda: ["GEAR-M2-40T"],
                   "rep": lambda: ["陳怡君"], "supplier": lambda: ["精密熱處理"]})


@pytest.fixture
def fake(monkeypatch):
    calls, audits = [], []

    def execute(q):
        calls.append(q)
        return ["發票號碼", "發票日期", "到期日", "發票金額", "未收金額", "逾期天數"], [["INV-1", "2026-05-18", "2026-06-17", 100, 100, 136]]
    monkeypatch.setattr(reports, "execute", execute)
    monkeypatch.setattr(reports, "default_index", lambda: ENT)
    monkeypatch.setattr(intent, "default_index", lambda: ENT)
    monkeypatch.setattr(reports.audit, "write", lambda rec: audits.append(rec) or 42)
    return calls, audits


def test_catalog_lists_all_sixteen_with_form_fields(fake):
    body = client.get("/api/reports/catalog").json()
    reports_ = [r for g in body["groups"] for r in g["reports"]]
    assert [g["name"] for g in body["groups"]] == ["銷售", "應收帳款", "庫存", "採購"] and len(reports_) == 16
    inv = next(r for r in reports_ if r["id"] == "ar_invoices")
    cust, overdue = inv["params"]
    assert cust["required"] and [o["value"] for o in cust["options"]] == ["台陽科技", "鴻遠機械"]
    assert overdue["kind"] == "enum" and None not in [o["value"] for o in overdue["options"]]   # 預設已逾期，不給「不限」
    trend = next(r for r in reports_ if r["id"] == "sales_trend")
    period = next(p for p in trend["params"] if p["name"] == "period")
    assert period["default"] == "last_n_months:6" and any(o["label"].startswith("最近 12 個月") for o in period["options"])


def test_run_executes_template_without_llm_and_audits(fake):
    calls, audits = fake
    r = client.post("/api/reports/run", json={"template_id": "ar_invoices", "params": {"customer": "台陽", "overdue_gt": 60}})
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "template" and body["route"] == "report"
    assert calls[0].binds["customer"] == "台陽科技" and body["binds"]["overdue_gt"] == 60   # 名稱經過比對
    assert body["params"] == {"customer": "台陽科技", "overdue_gt": 60} and "逾期超過 60 天" in body["params_readable"]
    assert body["answer"] and body["row_count"] == 1 and body["audit_id"] == 42
    assert audits[0].route == "report" and audits[0].question.startswith("[報表] 客戶逾期發票明細")
    assert body["followups"] and "facts" not in body


def test_run_rejects_bad_input(fake):
    assert client.post("/api/reports/run", json={"template_id": "nope", "params": {}}).status_code == 400
    r = client.post("/api/reports/run", json={"template_id": "ar_invoices", "params": {}})
    assert r.status_code == 400 and "客戶" in r.json()["detail"]
    r = client.post("/api/reports/run", json={"template_id": "ar_invoices", "params": {"customer": "不存在公司"}})
    assert r.status_code == 400


def test_run_db_error_returns_200_with_error(fake, monkeypatch):
    def boom(q):
        raise RuntimeError("connection refused\nmore")
    monkeypatch.setattr(reports, "execute", boom)
    body = client.post("/api/reports/run", json={"template_id": "ar_aging", "params": {}}).json()
    assert body["error"] == "查詢失敗：connection refused" and body["rows"] == []


def test_dashboard_survives_partial_failure(fake, monkeypatch):
    def flaky(q):
        if "v_庫存狀況" in q.sql:
            raise RuntimeError("timeout")
        return ["對象", "本期營收", "比較期營收", "增減", "增減(%)"], [["（全公司）", 120, 100, 20, 20.0]]
    monkeypatch.setattr(reports, "execute", flaky)
    body = client.get("/api/dashboard").json()
    assert body["errors"] and any("timeout" in e for e in body["errors"])
    rev = next(t for t in body["tiles"] if t["key"] == "revenue")
    assert rev["value"] == 120 and rev["sub"] == "去年同期 100 元，+20.0%" and rev["report"]["template_id"] == "sales_compare"


def test_pages_served():
    for path in ("/", "/dashboard", "/reports", "/about"):
        r = client.get(path)
        assert r.status_code == 200 and "<nav" in r.text, path


@pytest.mark.db
def test_dashboard_real_db():
    body = client.get("/api/dashboard").json()
    keys = [t["key"] for t in body["tiles"]]
    assert body["errors"] == [] and keys == ["revenue", "profit", "overdue", "overdue60", "dead", "shortage", "ontime"]
    aging = next(c for c in body["charts"] if c["key"] == "aging")
    o60 = next(t for t in body["tiles"] if t["key"] == "overdue60")
    assert o60["value"] == next(r[2] for r in aging["rows"] if r[0] == "逾期 61 天以上")   # 同頁數字一致
    for t in body["tiles"]:   # 每張卡片的報表連結都能執行
        assert client.post("/api/reports/run", json=t["report"]).status_code == 200, t["key"]
