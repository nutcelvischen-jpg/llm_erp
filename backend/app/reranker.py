"""Reranker：bge-reranker-v2-m3（CrossEncoder，CPU）。

- lazy load：第一次呼叫 rerank() 才載入模型（首次需下載約 2.2 GB，之後走快取）。
- 固定用 CPU，避免和 LM Studio 搶 GPU 記憶體。
"""
from __future__ import annotations

import logging
import threading
import time

from .config import settings

log = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()
SLOW_SECONDS = 3.0


def _load():
    from sentence_transformers import CrossEncoder  # 延後匯入，單元測試不必載入 torch

    log.info("載入 reranker %s（第一次會下載約 2.2 GB）", settings.rerank_model)
    return CrossEncoder(settings.rerank_model, device="cpu", max_length=512)


def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _load()
    return _model


def rerank(query: str, docs: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """依相關度由高到低重排，回傳 [(原索引, 分數)]，最多 top_n 筆（預設 RERANK_TOP_N）。"""
    if not docs:
        return []
    top_n = top_n or settings.rerank_top_n
    t0 = time.perf_counter()
    scores = get_model().predict([(query, d) for d in docs], batch_size=16, show_progress_bar=False)
    dt = time.perf_counter() - t0
    if dt > SLOW_SECONDS:
        log.warning("rerank %d 筆耗時 %.1f 秒（> %.0f 秒）", len(docs), dt, SLOW_SECONDS)
    ranked = sorted(enumerate(float(s) for s in scores), key=lambda x: x[1], reverse=True)
    return ranked[:top_n]
