"""Text-to-SQL。

T12：few-shot 範例挑選（pick_examples）。
T13：主流程 run()：問題 → 挑範例 → 產生 SQL → 守門員 → 唯讀執行；失敗時把原因回饋給 LLM 重寫（最多 3 次）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import numpy as np
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from . import llm
from .agent import prompts
from .db import engine, engine_ro
from .sql_guard import validate

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
MAX_ROWS = 200
STATEMENT_TIMEOUT = "10s"


@dataclass
class Example:
    question: str
    sql: str
    tags: list[str]
    embedding: np.ndarray


_cache: list[Example] | None = None


def load_examples(force: bool = False) -> list[Example]:
    """從 app.sql_examples 讀出範例（含向量），程序內快取；force=True 重新讀取。"""
    global _cache
    if _cache is None or force:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT question, sql_text, tags, embedding FROM app.sql_examples "
                "WHERE embedding IS NOT NULL ORDER BY id")).all()
        _cache = [Example(q, s, list(t or []), np.asarray(e, dtype=np.float32)) for q, s, t, e in rows]
    return _cache


def pick_examples(question: str, k: int = 4, examples: list[Example] | None = None) -> list[Example]:
    """依問題與範例問題的餘弦相似度，挑出最相近的 k 個範例（相似度高到低）。"""
    exs = load_examples() if examples is None else examples
    if not exs:
        return []
    q = np.asarray(llm.embed([question])[0], dtype=np.float32)
    mat = np.stack([e.embedding for e in exs])
    sims = mat @ q / (np.linalg.norm(mat, axis=1) * np.linalg.norm(q) + 1e-9)
    return [exs[i] for i in np.argsort(-sims)[:k]]


# ---------------------------------------------------------------- 主流程
@dataclass
class SqlAnswer:
    sql: str = ""
    explanation: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    attempts: int = 0
    error: str | None = None


_BIND_LIKE = re.compile(r"(?<![:\w\\]):(?=\w)")


def _escape_colons(sql: str) -> str:
    """SQLAlchemy text() 會把 ':name' 當成綁定參數；先跳脫，避免字串裡的 ':' 被誤判（'::int' 不受影響）。"""
    return _BIND_LIKE.sub(r"\\:", sql)


def _jsonable(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _execute(sql: str) -> tuple[list[str], list[list]]:
    """以唯讀角色執行，逾時 10 秒；回傳 (欄位, 全部列)。"""
    with engine_ro.connect() as conn:
        conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        res = conn.execute(text(_escape_colons(sql)))
        cols = list(res.keys())
        rows = [[_jsonable(v) for v in row] for row in res.fetchall()]
    return cols, rows


def _db_message(e: DBAPIError) -> str:
    return str(getattr(e, "orig", e)).strip().splitlines()[0][:300]


def _safe_pick(question: str) -> list[Example]:
    try:
        return pick_examples(question, k=4)
    except Exception as e:  # noqa: BLE001  範例挑選失敗不應讓整個查詢失敗
        log.warning("挑選 few-shot 範例失敗，改用無範例模式：%s", e)
        return []


def run(question: str) -> SqlAnswer:
    """把自然語言問題轉成 SQL 並執行；任何失敗都回傳 error，不丟例外。"""
    ans = SqlAnswer()
    messages = [
        {"role": "system", "content": prompts.build_sql_system(_safe_pick(question))},
        {"role": "user", "content": question},
    ]
    last_problem = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ans.attempts = attempt
        try:
            out = llm.chat_json(messages, prompts.SQL_JSON_HINT, max_tokens=1500)
        except llm.LLMError as e:
            ans.error = str(e)
            return ans
        raw = json.dumps(out, ensure_ascii=False)
        sql = out.get("sql")
        ans.explanation = str(out.get("explanation") or "")

        if isinstance(sql, str) and not sql.strip():  # 模型表示無法回答
            ans.error = f"這個問題無法用目前的 ERP 資料回答：{ans.explanation or '資料中沒有相關內容'}"
            return ans

        problem = ""
        if not isinstance(sql, str):
            problem = '輸出的 JSON 缺少 "sql" 欄位'
        else:
            g = validate(sql)
            if not g.ok:
                ans.sql, problem = sql, f"SQL 未通過安全檢查：{g.reason}"
            else:
                ans.sql = g.sql
                try:
                    cols, rows = _execute(g.sql)
                except DBAPIError as e:
                    if getattr(e.orig, "sqlstate", None) is None:  # 連不上資料庫：重試也沒用
                        ans.error = "無法連線資料庫，請確認 Postgres 是否運作中"
                        return ans
                    problem = f"SQL 執行失敗：{_db_message(e)}"
                else:
                    ans.columns, ans.row_count, ans.rows, ans.error = cols, len(rows), rows[:MAX_ROWS], None
                    return ans

        last_problem = problem
        log.info("Text-to-SQL 第 %d 次失敗：%s", attempt, problem)
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": f"{problem}。請修正後重新輸出 JSON。"},
        ]
    ans.error = f"嘗試 {MAX_ATTEMPTS} 次仍無法產生可執行的 SQL：{last_problem}"
    return ans
