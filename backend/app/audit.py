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
