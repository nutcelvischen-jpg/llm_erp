import time

import pytest
from fastapi.testclient import TestClient

from backend.app.api import admin
from backend.app.main import app

client = TestClient(app)


def wait_done(timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        st = client.get("/admin/ingest").json()
        if st.get("status") in ("done", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("背景索引沒有結束")


def test_audit_endpoint(monkeypatch):
    monkeypatch.setattr(admin.audit, "list_recent", lambda n: [{"id": i} for i in range(n)])
    d = client.get("/admin/audit?limit=3").json()
    assert d == {"count": 3, "items": [{"id": 0}, {"id": 1}, {"id": 2}]}
    assert client.get("/admin/audit?limit=0").status_code == 422
    assert client.get("/admin/audit?limit=501").status_code == 422


@pytest.mark.parametrize("path", ["../", "/etc", "data/../backend", "data/不存在"])
def test_ingest_rejects_paths_outside_data(path):
    r = client.post("/admin/ingest", json={"path": path})
    assert r.status_code == 400


def test_ingest_runs_in_background_and_reports(monkeypatch):
    calls = []

    def fake(folder, force, progress):
        calls.append((folder.name, force))
        progress(1, 2, "a.pdf", 3)
        progress(2, 2, "b.pdf", None)
        return {"files": 2, "written": 3, "skipped": 1, "points": 355, "seconds": 0.1}

    monkeypatch.setattr(admin, "runner", fake)
    r = client.post("/admin/ingest", json={"path": "data/docs", "force": True})
    assert r.status_code == 202 and r.json()["status"] == "started"
    st = wait_done()
    assert st["status"] == "done" and st["result"]["written"] == 3 and st["done"] == 2
    assert calls == [("docs", True)]


def test_ingest_conflict_while_running(monkeypatch):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(admin, "runner", lambda f, force, p: gate.wait(5) and {"files": 0})
    assert client.post("/admin/ingest", json={}).status_code == 202
    assert client.post("/admin/ingest", json={}).status_code == 409
    gate.set()
    assert wait_done()["status"] == "done"


def test_ingest_error_is_reported(monkeypatch):
    def boom(*_):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(admin, "runner", boom)
    client.post("/admin/ingest", json={})
    st = wait_done()
    assert st["status"] == "error" and "qdrant down" in st["error"]


def test_compute_stats():
    rows = [{"route": "sql", "n": 3, "avg_ms": 2000, "sql_n": 3, "sql_ok_n": 2, "err_n": 1},
            {"route": "docs", "n": 1, "avg_ms": 6000, "sql_n": 0, "sql_ok_n": 0, "err_n": 0}]
    s = admin.compute_stats(rows)
    assert s == {"questions": 4, "avg_latency_ms": 3000, "by_route": {"sql": 3, "docs": 1},
                 "sql_queries": 3, "sql_success_rate": 0.667, "errors": 1}
    assert admin.compute_stats([])["avg_latency_ms"] is None


@pytest.mark.db
def test_stats_real_db():
    from backend.app import audit

    for _ in range(5):  # 自己寫足 5 筆，不依賴資料庫原有的紀錄（從零重建後可能不夠）
        audit.write(audit.AuditRecord(question="統計測試", session_id="pytest-stats", route="sql", sql_ok=True,
                                      latency_ms=1000))
    with_tests = client.get("/admin/stats?include_tests=true").json()
    without = client.get("/admin/stats").json()
    assert with_tests["questions"] >= 1 and with_tests["by_route"].get("sql", 0) >= 1
    assert with_tests["questions"] >= without["questions"]
    assert client.get("/admin/audit?limit=5").json()["count"] == 5
