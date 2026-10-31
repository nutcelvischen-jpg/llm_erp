"""T14f 整合：問題 → 意圖辨識 → 執行既定程式（唯讀、逾時 10 秒）→ 結果回覆。

mode：
  template  命中並執行既定程式
  clarify   需要反問（缺參數、名稱不明確），options 是可點選的答案
  confirm   沒有明確命中，proposals 是最接近的既定程式，使用者點選後以 choice 再呼叫一次
  no_match  不支援的問題（已記錄），suggestions 是可以改問的範例
  error     執行失敗
AI 不寫 SQL：要執行的 SQL 一律來自 templates/ 的寫死模板。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from . import answer as answer_mod
from . import intent as intent_mod
from .base import BuiltQuery
from .registry import TEMPLATES

log = logging.getLogger(__name__)

MAX_ROWS = 200
STATEMENT_TIMEOUT = "10s"


@dataclass
class CatalogAnswer:
    mode: str
    template_id: str | None = None
    template_title: str | None = None
    params_readable: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    sql: str = ""
    binds: dict = field(default_factory=dict)
    answer: str = ""
    answer_source: str | None = None
    options: list[str] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warning: str | None = None
    error: str | None = None
    latency_ms: int = 0


def jsonable(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, date | datetime):
        return v.isoformat()
    return v


def public_params(params: dict) -> dict:
    """給前端的參數：去掉內部用的 _today 等鍵，值轉成 JSON 可用。"""
    return {k: jsonable(v) for k, v in params.items() if not k.startswith("_")}


def execute(q: BuiltQuery) -> tuple[list[str], list[list]]:
    """以唯讀角色執行模板 SQL（值全部是綁定參數），逾時 10 秒。"""
    from sqlalchemy import text

    from ..db import engine_ro

    with engine_ro.connect() as c:
        c.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        r = c.execute(text(q.sql), q.binds)
        return list(r.keys()), [[jsonable(v) for v in row] for row in r.fetchmany(MAX_ROWS)]


@dataclass
class Deps:
    recognize: Callable | None = None
    confirm: Callable | None = None
    execute: Callable | None = None
    chat: Callable | None = None   # 結果回覆用；None 用預設 LLM

    def __post_init__(self):
        self.recognize = self.recognize or intent_mod.recognize
        self.confirm = self.confirm or intent_mod.confirm
        self.execute = self.execute or execute


def _suggestions(candidates: list[dict]) -> list[str]:
    return [TEMPLATES[c["template_id"]].examples[0] for c in candidates[:3] if c["template_id"] in TEMPLATES]


def answer_question(question: str, today: date | None = None, choice: dict | None = None,
                    deps: Deps | None = None, data_part_only: bool = False) -> CatalogAnswer:
    """choice = {"template_id": ..., "params": {...}}：使用者在 confirm 畫面點選的既定程式。
    data_part_only：問題同時問數字與文件（路由為 both），意圖辨識只看數字的部分。"""
    deps = deps or Deps()
    today = today or date.today()
    t0 = time.perf_counter()

    def done(a: CatalogAnswer) -> CatalogAnswer:
        a.latency_ms = int((time.perf_counter() - t0) * 1000)
        return a

    if choice:
        it = deps.confirm(str(choice.get("template_id") or ""), choice.get("params") or {}, today)
    else:
        it = (deps.recognize(question, today, data_part_only=True) if data_part_only
              else deps.recognize(question, today))

    if it.kind == "clarify":
        return done(CatalogAnswer("clarify", it.template_id,
                                  TEMPLATES[it.template_id].title if it.template_id in TEMPLATES else None,
                                  answer=it.message, options=it.options, notes=it.notes))
    if it.kind == "confirm":
        props = [{"template_id": p.template_id, "title": p.title, "description": p.description,
                  "params": public_params(p.params), "params_readable": p.params_readable,
                  "columns": p.columns, "notes": p.notes} for p in it.proposals]
        return done(CatalogAnswer("confirm", answer=it.message, proposals=props))
    if it.kind != "template":
        return done(CatalogAnswer("no_match", answer=it.message, suggestions=_suggestions(it.candidates)))

    t = TEMPLATES[it.template_id]
    base = CatalogAnswer("template", t.id, t.title, it.params_readable, notes=it.notes)
    try:
        q = t.build(it.params)
        base.sql, base.binds = q.sql, public_params(q.binds)
        cols, rows = deps.execute(q)
    except Exception as e:
        log.exception("執行既定程式 %s 失敗", t.id)
        base.mode, base.error = "error", f"查詢失敗：{str(e).splitlines()[0][:200]}"
        return done(base)
    base.columns, base.rows, base.row_count = cols, rows, len(rows)
    facts = t.facts(cols, rows)
    top_n = it.params.get("top_n") if isinstance(it.params.get("top_n"), int) else 0
    a = answer_mod.summarize(question, t, it.params_readable, cols, rows, facts, top_n=top_n, chat=deps.chat)
    base.answer, base.answer_source = a.text, a.source
    return done(base)
