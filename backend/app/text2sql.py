"""Text-to-SQL。

T12：few-shot 範例挑選（pick_examples）。
T13：主流程（run）會在此檔繼續擴充。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import text

from . import llm
from .db import engine


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
