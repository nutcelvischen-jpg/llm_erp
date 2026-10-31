"""T29 LINE 推播（選配）：沒設定 LINE_CHANNEL_ACCESS_TOKEN / LINE_TARGET_ID 時自動跳過。

用法：
  uv run python -m backend.app.jobs.line_push            推送 app.notifications 中尚未送出的 LINE 訊息
  uv run python -m backend.app.jobs.line_push --test     送一則測試訊息，確認 token 與對象正確
設定方式見 docs/LINE_SETUP.md。
"""
from __future__ import annotations

import argparse
import logging

import httpx
from sqlalchemy import text

from ..config import settings

log = logging.getLogger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"
TIMEOUT = 10
MAX_CHARS = 5000  # LINE 文字訊息上限


def configured() -> bool:
    return bool(settings.line_channel_access_token and settings.line_target_id)


def push(message: str, client: httpx.Client | None = None) -> bool:
    """推送一則文字訊息；成功回 True。未設定或失敗回 False（只記 log，不拋錯）。"""
    if not configured():
        log.info("LINE 未設定，跳過")
        return False
    if len(message) > MAX_CHARS:
        message = message[: MAX_CHARS - 1] + "…"
    body = {"to": settings.line_target_id, "messages": [{"type": "text", "text": message}]}
    headers = {"Authorization": f"Bearer {settings.line_channel_access_token}"}
    try:
        if client is None:
            r = httpx.post(PUSH_URL, json=body, headers=headers, timeout=TIMEOUT)
        else:
            r = client.post(PUSH_URL, json=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        log.error("LINE 推播連線失敗：%s", e)
        return False
    if r.status_code != 200:
        log.error("LINE 推播失敗 HTTP %s：%s", r.status_code, r.text[:300])
        return False
    log.info("LINE 推播成功")
    return True


def mark_sent(notification_id: int, engine=None) -> None:
    if engine is None:
        from ..db import engine
    with engine.begin() as c:
        c.execute(text("UPDATE app.notifications SET sent = true WHERE id = :i"), {"i": notification_id})


def send_notification(notification_id: int, message: str, engine=None, client: httpx.Client | None = None) -> bool:
    """推送並在成功時把 notifications.sent 設為 true。"""
    ok = push(message, client)
    if ok:
        mark_sent(notification_id, engine)
    return ok


def push_pending(engine=None, client: httpx.Client | None = None) -> int:
    """推送所有 channel='line' 且尚未送出的通知，回傳成功筆數。"""
    if not configured():
        log.info("LINE 未設定，跳過")
        return 0
    if engine is None:
        from ..db import engine
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, payload FROM app.notifications WHERE channel = 'line' AND NOT sent ORDER BY id")).all()
    return sum(send_notification(i, p, engine, client) for i, p in rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="LINE 推播")
    ap.add_argument("--test", action="store_true", help="送一則測試訊息")
    a = ap.parse_args()
    if a.test:
        push("【ERP 智慧助理】LINE 推播測試成功。")
    else:
        print(f"推送 {push_pending()} 則")
