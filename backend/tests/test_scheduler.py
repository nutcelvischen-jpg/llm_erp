import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.jobs import dead_stock, scheduler
from backend.app.main import app

client = TestClient(app)


@pytest.fixture
def sched(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "scheduler_enabled", True)
    yield
    scheduler.shutdown()


def test_start_registers_weekly_job_in_taipei(sched):
    s = scheduler.start()
    job = s.get_job(scheduler.JOB_ID)
    nxt = job.next_run_time
    assert str(nxt.tzinfo) == "Asia/Taipei"
    assert (nxt.weekday(), nxt.hour, nxt.minute) == (0, 8, 0)
    assert scheduler.next_run_time() == nxt.isoformat()
    assert scheduler.start() is s  # 重複啟動不會建立第二個


def test_disabled(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "scheduler_enabled", False)
    assert scheduler.start() is None and scheduler.next_run_time() is None


def test_lifespan_starts_and_stops(sched):
    with TestClient(app):
        assert scheduler.next_run_time() is not None
    assert scheduler.next_run_time() is None


def test_run_dead_stock_saves_and_returns_id(monkeypatch):
    monkeypatch.setattr(dead_stock, "save_notification", lambda m, c: 123)
    monkeypatch.setattr(dead_stock, "run", lambda dry_run, save: save("msg", "console") and "msg")
    assert scheduler.run_dead_stock() == {"id": 123, "message": "msg"}


def test_scheduled_job_swallows_errors(monkeypatch, caplog):
    def boom(**_):
        raise RuntimeError("db down")

    monkeypatch.setattr(dead_stock, "run", boom)
    scheduler._scheduled_job()
    assert "呆滯庫存預警失敗" in caplog.text


def test_manual_trigger_endpoint(monkeypatch):
    monkeypatch.setattr(scheduler, "run_dead_stock", lambda: {"id": 5, "message": "預警"})
    d = client.post("/admin/jobs/dead_stock/run").json()
    assert d["ok"] and d["notification_id"] == 5 and d["message"] == "預警"


def test_manual_trigger_busy_and_error(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(dead_stock, "run", lambda dry_run, save: gate.wait(5) and "x")
    t = threading.Thread(target=scheduler.run_dead_stock)
    t.start()
    try:
        assert client.post("/admin/jobs/dead_stock/run").status_code == 409
    finally:
        gate.set()
        t.join()

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(scheduler, "run_dead_stock", boom)
    r = client.post("/admin/jobs/dead_stock/run")
    assert r.status_code == 503 and "db down" in r.json()["detail"]
