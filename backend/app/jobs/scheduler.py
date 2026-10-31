"""T28 排程器：每週一 08:00（Asia/Taipei）執行呆滯庫存與缺料預警。於 FastAPI lifespan 啟動與關閉。"""
from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings

log = logging.getLogger(__name__)

JOB_ID = "dead_stock_weekly"
_scheduler: BackgroundScheduler | None = None
_run_lock = threading.Lock()


class JobBusy(RuntimeError):
    """同一個工作正在執行中。"""


def run_dead_stock() -> dict:
    """執行一次預警並寫入 app.notifications，回傳 {id, message}。同時只允許一個在跑。"""
    from . import dead_stock, line_push

    if not _run_lock.acquire(blocking=False):
        raise JobBusy("呆滯庫存預警正在執行中")
    try:
        ids: list[int] = []

        def save(message: str, channel: str) -> int:
            ids.append(dead_stock.save_notification(message, channel))
            return ids[-1]

        message = dead_stock.run(dry_run=False, save=save)
        nid = ids[0] if ids else None
        pushed = line_push.send_notification(nid, message) if nid is not None else False
        return {"id": nid, "message": message, "line_sent": pushed}
    finally:
        _run_lock.release()


def _scheduled_job() -> None:
    try:
        r = run_dead_stock()
        log.info("排程：呆滯庫存預警完成，notifications id=%s", r["id"])
    except Exception:  # 排程失敗只記錄，不能讓排程器停掉
        log.exception("排程：呆滯庫存預警失敗")


def start() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("排程器已停用（SCHEDULER_ENABLED=false）")
        return None
    if _scheduler and _scheduler.running:
        return _scheduler
    s = BackgroundScheduler(timezone=settings.app_tz)
    s.add_job(_scheduled_job, CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=settings.app_tz),
              id=JOB_ID, name="呆滯庫存與缺料預警", replace_existing=True, coalesce=True,
              misfire_grace_time=3600, max_instances=1)
    s.start()
    _scheduler = s
    log.info("排程器啟動：%s 下次執行 %s", JOB_ID, next_run_time())
    return s


def shutdown() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("排程器已關閉")
    _scheduler = None


def next_run_time() -> str | None:
    job = _scheduler.get_job(JOB_ID) if _scheduler else None
    return job.next_run_time.isoformat() if job and job.next_run_time else None
