import uuid

import pytest
from sqlalchemy import create_engine, text

from backend.app import audit
from backend.app.audit import AuditRecord


def test_write_failure_returns_none_and_does_not_raise(caplog):
    bad = create_engine("postgresql+psycopg://x:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1})
    assert audit.write(AuditRecord(question="q"), engine=bad) is None
    assert audit.list_recent(5, engine=bad) == []
    assert audit.add_feedback(1, 1, engine=bad) is None
    assert "稽核寫入失敗" in caplog.text


def test_feedback_score_validated():
    with pytest.raises(ValueError):
        audit.add_feedback(1, 5)


@pytest.mark.db
def test_write_and_read_back():
    sid = f"pytest-{uuid.uuid4().hex[:8]}"
    rec = AuditRecord(question="今年營收最高的三個客戶", session_id=sid, route="both", sql_text="SELECT 1",
                      sql_ok=True, sql_rows=3, doc_sources=[{"file_name": "銷售合約_鴻遠機械.pdf", "page": 2}],
                      answer="答案", latency_ms=1234, prompt_tokens=10, completion_tokens=5)
    aid = audit.write(rec)
    assert isinstance(aid, int)
    got = next(r for r in audit.list_recent(20) if r["id"] == aid)
    assert got["session_id"] == sid and got["route"] == "both" and got["sql_rows"] == 3
    assert got["doc_sources"][0]["page"] == 2 and got["latency_ms"] == 1234 and got["ts"]

    fid = audit.add_feedback(aid, -1, "  數字不對  ")
    from backend.app.db import engine

    with engine.connect() as c:
        row = c.execute(text("SELECT audit_id, score, comment FROM app.feedback WHERE id=:i"), {"i": fid}).one()
    assert tuple(row) == (aid, -1, "數字不對")


@pytest.mark.db
def test_feedback_for_missing_audit_returns_none():
    assert audit.add_feedback(10**12, 1) is None


@pytest.mark.db
def test_list_recent_order_and_clamp():
    ids = [audit.write(AuditRecord(question=f"q{i}", session_id="pytest-order")) for i in range(2)]
    rec = audit.list_recent(2)
    assert [r["id"] for r in rec] == ids[::-1]
    assert len(audit.list_recent(0)) == 1
