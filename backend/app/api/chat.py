"""聊天 API（T13b：只接 Text-to-SQL；T25 會換成 Agent）。"""
from __future__ import annotations

import time
from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from .. import text2sql

router = APIRouter(prefix="/api")
MAX_QUESTION_CHARS = 500


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None

    @field_validator("question")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= MAX_QUESTION_CHARS:
            raise ValueError(f"問題長度需為 1–{MAX_QUESTION_CHARS} 字")
        return v


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    """同步端點（FastAPI 會放進 threadpool，不會卡住其他請求）。
    查詢失敗不是伺服器錯誤：一律回 HTTP 200，失敗原因放在 `error`。"""
    t0 = time.perf_counter()
    ans = text2sql.run(req.question)
    return {
        "question": req.question,
        **asdict(ans),
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
