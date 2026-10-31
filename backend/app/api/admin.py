"""管理端點：最近稽核、背景重建索引、今日統計。

PoC 沒有登入機制；`make dev` 只綁 127.0.0.1。要開放給其他人連線前，必須先加上驗證。
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from .. import audit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"

_ingest_lock = threading.Lock()
_ingest_state: dict = {"status": "idle"}


def _engine():
    from ..db import engine

    return engine


@router.get("/audit")
def recent_audit(limit: int = Query(50, ge=1, le=500)) -> dict:
    rows = audit.list_recent(limit)
    return {"count": len(rows), "items": rows}


# ---------- 重建索引 ----------
class IngestRequest(BaseModel):
    path: str = "data/docs"
    force: bool = False


def resolve_docs_path(path: str) -> Path:
    """只允許專案 data/ 底下已存在的資料夾，避免任意路徑。"""
    p = (ROOT / path).resolve()
    if not p.is_relative_to(DATA_DIR.resolve()) or not p.is_dir():
        raise HTTPException(400, f"路徑必須是專案 data/ 底下存在的資料夾：{path}")
    return p


def _default_runner(folder: Path, force: bool, progress) -> dict:
    from qdrant_client import QdrantClient

    from .. import llm
    from ..config import settings
    from ..rag.ingest import ingest_folder

    return ingest_folder(QdrantClient(url=settings.qdrant_url, timeout=30), folder, llm.embed, force,
                         progress=progress)


runner = _default_runner  # 測試時替換


def _run_ingest(folder: Path, force: bool) -> None:
    def progress(i, n, name, written):
        _ingest_state.update(done=i, total=n, current=name)

    try:
        result = runner(folder, force, progress)
        _ingest_state.update(status="done", result=result, finished_at=time.time())
        log.info("背景重建索引完成：%s", result)
    except Exception as e:
        log.exception("背景重建索引失敗")
        _ingest_state.update(status="error", error=str(e)[:300], finished_at=time.time())
    finally:
        _ingest_lock.release()


@router.post("/ingest", status_code=202)
def start_ingest(req: IngestRequest) -> dict:
    folder = resolve_docs_path(req.path)
    if not _ingest_lock.acquire(blocking=False):
        raise HTTPException(409, "索引正在執行中，請稍後再試")
    _ingest_state.clear()
    _ingest_state.update(status="running", path=req.path, force=req.force, started_at=time.time(), done=0)
    threading.Thread(target=_run_ingest, args=(folder, req.force), daemon=True, name="ingest").start()
    return {"status": "started", "path": req.path}


@router.get("/ingest")
def ingest_status() -> dict:
    return dict(_ingest_state)


# ---------- 排程工作 ----------
@router.post("/jobs/dead_stock/run")
def run_dead_stock_now() -> dict:
    """手動觸發呆滯庫存與缺料預警（Demo 用），同步執行並寫入 app.notifications。"""
    from ..jobs import scheduler

    try:
        r = scheduler.run_dead_stock()
    except scheduler.JobBusy as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:
        log.exception("手動執行呆滯庫存預警失敗")
        raise HTTPException(503, f"呆滯庫存預警執行失敗：{str(e)[:200]}") from e
    return {"ok": True, "notification_id": r["id"], "message": r["message"], "line_sent": r.get("line_sent", False),
            "next_run_time": scheduler.next_run_time()}


# ---------- 統計 ----------
_STATS = text("""
SELECT route, COUNT(*) AS n, AVG(latency_ms) AS avg_ms,
       COUNT(*) FILTER (WHERE sql_ok IS NOT NULL) AS sql_n,
       COUNT(*) FILTER (WHERE sql_ok) AS sql_ok_n,
       COUNT(*) FILTER (WHERE error IS NOT NULL) AS err_n
FROM app.audit_log
WHERE (ts AT TIME ZONE :tz)::date = (now() AT TIME ZONE :tz)::date
  AND (:include_tests OR session_id IS NULL OR session_id NOT LIKE 'pytest%')
GROUP BY route
""")


def compute_stats(rows: list[dict]) -> dict:
    total = sum(r["n"] for r in rows)
    sql_n = sum(r["sql_n"] for r in rows)
    sql_ok = sum(r["sql_ok_n"] for r in rows)
    lat = sum((r["avg_ms"] or 0) * r["n"] for r in rows)
    return {
        "questions": total,
        "avg_latency_ms": round(lat / total) if total else None,
        "by_route": {r["route"] or "unknown": r["n"] for r in rows},
        "sql_queries": sql_n,
        "sql_success_rate": round(sql_ok / sql_n, 3) if sql_n else None,
        "errors": sum(r["err_n"] for r in rows),
    }


@router.get("/stats")
def stats(include_tests: bool = False) -> dict:
    from ..config import settings

    try:
        with _engine().connect() as c:
            rows = [dict(r) for r in c.execute(_STATS, {"tz": settings.app_tz, "include_tests": include_tests})
                    .mappings().all()]
    except Exception as e:
        raise HTTPException(503, f"無法讀取統計（資料庫）：{str(e)[:200]}") from e
    return {"date_tz": settings.app_tz, "include_tests": include_tests, **compute_stats(rows)}
