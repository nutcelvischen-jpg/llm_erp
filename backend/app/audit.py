"""稽核紀錄（app.audit_log）。寫入失敗只記 log、不拋錯：稽核不能拖垮回答。"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from sqlalchemy import text

log = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    question: str
    session_id: str | None = None
    user_id: str = "demo"
    route: str | None = None
    sql_text: str | None = None
    sql_ok: bool | None = None
    sql_rows: int | None = None
    doc_sources: list[dict] | None = None
    answer: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None


_INSERT = text("""
INSERT INTO app.audit_log (session_id, user_id, route, question, sql_text, sql_ok, sql_rows, doc_sources,
                           answer, latency_ms, prompt_tokens, completion_tokens, error)
VALUES (:session_id, :user_id, :route, :question, :sql_text, :sql_ok, :sql_rows, CAST(:doc_sources AS jsonb),
        :answer, :latency_ms, :prompt_tokens, :completion_tokens, :error)
RETURNING id
""")


def _engine():
    from .db import engine

    return engine


def write(rec: AuditRecord, engine=None) -> int | None:
    """寫入一筆稽核，回傳 id；失敗回傳 None。"""
    params = asdict(rec)
    params["doc_sources"] = None if rec.doc_sources is None else json.dumps(rec.doc_sources, ensure_ascii=False)
    try:
        with (engine or _engine()).begin() as conn:
            return int(conn.execute(_INSERT, params).scalar_one())
    except Exception as e:  # noqa: BLE001
        log.error("稽核寫入失敗：%s", str(e)[:300])
        return None


_COLUMNS = ("id, ts, session_id, user_id, route, question, sql_text, sql_ok, sql_rows, doc_sources, answer, "
            "latency_ms, prompt_tokens, completion_tokens, error")


def list_recent(n: int = 50, engine=None) -> list[dict]:
    """最近 n 筆稽核（新到舊）；n 夾在 1–500。失敗回傳空清單。"""
    n = max(1, min(int(n), 500))
    try:
        with (engine or _engine()).connect() as conn:
            rows = conn.execute(text(f"SELECT {_COLUMNS} FROM app.audit_log ORDER BY id DESC LIMIT :n"),
                                {"n": n}).mappings().all()
    except Exception as e:  # noqa: BLE001
        log.error("讀取稽核失敗：%s", str(e)[:300])
        return []
    out = []
    for r in rows:
        d = dict(r)
        d["ts"] = d["ts"].isoformat() if d["ts"] else None
        out.append(d)
    return out


def add_feedback(audit_id: int, score: int, comment: str | None = None, engine=None) -> int | None:
    """寫入 app.feedback（score：1 讚／-1 倒讚），回傳 id；分數不合法丟 ValueError，寫入失敗回傳 None。"""
    if score not in (1, -1):
        raise ValueError("score 只能是 1 或 -1")
    comment = (comment or "").strip()[:1000] or None
    try:
        with (engine or _engine()).begin() as conn:
            return int(conn.execute(
                text("INSERT INTO app.feedback (audit_id, score, comment) VALUES (:a, :s, :c) RETURNING id"),
                {"a": int(audit_id), "s": score, "c": comment}).scalar_one())
    except Exception as e:  # noqa: BLE001
        log.error("回饋寫入失敗：%s", str(e)[:300])
        return None
