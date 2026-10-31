"""聊天 API：POST /api/chat（T25 起接 Agent）、POST /api/feedback。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .. import audit
from ..agent import followups, graph

router = APIRouter(prefix="/api")
MAX_QUESTION_CHARS = 500
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 2000


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()[:MAX_HISTORY_CHARS]


class Choice(BaseModel):
    """使用者在「確認既定程式」畫面點選的程式；後端會重新驗證模板與參數。"""
    template_id: str = Field(max_length=64)
    params: dict = Field(default_factory=dict)


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = Field(default=None, max_length=64)
    history: list[Turn] = Field(default_factory=list)
    choice: Choice | None = None

    @field_validator("question")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= MAX_QUESTION_CHARS:
            raise ValueError(f"問題長度需為 1–{MAX_QUESTION_CHARS} 字")
        return v

    @field_validator("history")
    @classmethod
    def _last_turns(cls, v: list[Turn]) -> list[Turn]:
        return [t for t in v if t.content][-MAX_HISTORY_TURNS * 2:]  # 一輪 = 使用者 + 助理


class FeedbackRequest(BaseModel):
    audit_id: int = Field(gt=0)
    score: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    """同步端點（FastAPI 會放進 threadpool，不會卡住其他請求）。
    查詢失敗不是伺服器錯誤：一律回 HTTP 200，失敗原因放在 `error`。"""
    choice = req.choice.model_dump() if req.choice else None
    r = graph.run_agent(req.question, [t.model_dump() for t in req.history], req.session_id, choice=choice)
    try:
        nexts = followups.suggest(req.question, route=r.route, mode=r.mode, template_id=r.template_id, binds=r.binds,
                                  columns=r.columns, rows=r.rows, params_readable=r.params_readable,
                                  sources=r.sources, error=None if r.answer else r.error)
    except Exception:  # noqa: BLE001 — 追問只是輔助，失敗不影響回答
        nexts = []
    return {
        "question": req.question,
        "route": r.route,
        "rewritten": r.rewritten,
        "answer": r.answer,
        "explanation": r.answer,  # 舊欄位，保留相容
        "markdown": r.markdown,
        "sql": r.sql,
        "columns": r.columns,
        "rows": r.rows,
        "row_count": r.row_count,
        "attempts": r.attempts,
        "sources": r.sources,
        "mode": r.mode,
        "template_id": r.template_id,
        "template_title": r.template_title,
        "params_readable": r.params_readable,
        "params": r.params,
        "binds": r.binds,
        "answer_source": r.answer_source,
        "options": r.options,
        "proposals": r.proposals,
        "suggestions": r.suggestions,
        "notes": r.notes,
        "followups": nexts,
        "warning": r.warning,
        "error": r.error,
        "audit_id": r.audit_id,
        "latency_ms": r.latency_ms,
    }


@router.post("/feedback")
def feedback(req: FeedbackRequest) -> dict:
    fid = audit.add_feedback(req.audit_id, req.score, req.comment)
    if fid is None:
        raise HTTPException(503, "回饋寫入失敗（稽核編號不存在或資料庫無法連線）")
    return {"ok": True, "id": fid}
