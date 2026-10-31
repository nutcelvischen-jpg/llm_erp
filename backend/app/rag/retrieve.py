"""T19 混合檢索：dense（bge-m3）+ sparse（jieba BM25）→ RRF 融合 → reranker 重排。

client / embed / rerank 可注入，單元測試用 QdrantClient(":memory:") 與假模型。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from qdrant_client import QdrantClient, models

from ..config import settings
from .ingest import point_id, sparse_vector

log = logging.getLogger(__name__)

QDRANT_TIMEOUT = 10
# 片段以「如下表：」「如下：」結尾時，內容在下一塊（通常是表格被切成獨立一塊）
_CONTINUES = re.compile(r"如下\s*(?:表|列|所示)?\s*[:：]?\s*$")  # PDF 抽字可能是「如下 表：」
_client: QdrantClient | None = None


class RetrieveError(RuntimeError):
    """檢索失敗（Qdrant、embedding 或 reranker），訊息可直接顯示給使用者。"""


@dataclass
class Hit:
    chunk_id: str
    score: float
    text: str
    file_name: str
    page: int
    heading_path: list[str] = field(default_factory=list)
    doc_type: str = ""


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url, timeout=QDRANT_TIMEOUT)
    return _client


def _default_embed(texts: list[str]) -> list[list[float]]:
    from .. import llm

    return llm.embed(texts)


def _default_rerank(query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
    from .. import reranker

    return reranker.rerank(query, docs, top_n)


def _filter(doc_type: str | None) -> models.Filter | None:
    if not doc_type:
        return None
    return models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))])


def candidates(query: str, top_k: int = 20, doc_type: str | None = None, *,
               client: QdrantClient | None = None, embed: Callable | None = None,
               name: str | None = None) -> list[Hit]:
    """dense 與 bm25 各取 top_k，以 RRF 融合後回傳前 top_k 筆（score 為 RRF 分數）。"""
    client = client or get_client()
    embed = embed or _default_embed
    name = name or settings.qdrant_collection
    flt = _filter(doc_type)
    try:
        dense = embed([query])[0]
    except Exception as e:
        raise RetrieveError(f"問題向量化失敗：{e}") from e
    try:
        res = client.query_points(
            name,
            prefetch=[
                models.Prefetch(query=dense, using="dense", limit=top_k, filter=flt),
                models.Prefetch(query=sparse_vector(query, query=True), using="bm25", limit=top_k, filter=flt),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
    except Exception as e:
        raise RetrieveError(f"文件檢索失敗（Qdrant {settings.qdrant_url}）：{str(e)[:200]}") from e
    return [_hit_from(p) for p in res.points]


def _hit_from(p) -> Hit:
    pl = p.payload or {}
    return Hit(chunk_id=pl.get("chunk_id", str(p.id)), score=float(getattr(p, "score", 0) or 0),
               text=pl.get("text", ""), file_name=pl.get("file_name", ""), page=int(pl.get("page", 0)),
               heading_path=list(pl.get("heading_path") or []), doc_type=pl.get("doc_type", ""))


def next_chunk_id(chunk_id: str) -> str | None:
    head, _, seq = chunk_id.rpartition("-")
    return f"{head}-{int(seq) + 1:0{len(seq)}d}" if head and seq.isdigit() else None


def expand_continuations(hits: list[Hit], client: QdrantClient, name: str) -> list[Hit]:
    """片段以「如下表：」結尾時，把同文件的下一塊插在它後面（已在結果中則略過）。失敗就原樣回傳。"""
    have = {h.chunk_id for h in hits}
    want = {}
    for h in hits:
        nid = next_chunk_id(h.chunk_id)
        if nid and nid not in have and _CONTINUES.search(h.text):
            want[h.chunk_id] = nid
    if not want:
        return hits
    try:
        pts = client.retrieve(name, ids=[point_id(n) for n in want.values()], with_payload=True)
    except Exception as e:  # noqa: BLE001
        log.warning("取得接續片段失敗：%s", e)
        return hits
    found = {h.chunk_id: h for h in map(_hit_from, pts)}
    out = []
    for h in hits:
        out.append(h)
        nxt = found.get(want.get(h.chunk_id, ""))
        if nxt:
            nxt.score = h.score
            out.append(nxt)
    return out


def retrieve(query: str, top_k: int = 20, top_n: int = 5, doc_type: str | None = None, *,
             client: QdrantClient | None = None, embed: Callable | None = None,
             rerank: Callable | None = None, name: str | None = None) -> list[Hit]:
    """混合檢索 + 重排，回傳 top_n 筆（score 為 reranker 分數，高到低）。"""
    hits = candidates(query, top_k, doc_type, client=client, embed=embed, name=name)
    if not hits:
        return []
    rerank = rerank or _default_rerank
    try:
        ranked = rerank(query, [h.text for h in hits], top_n)
    except Exception as e:  # noqa: BLE001 — reranker 失敗時退回 RRF 順序
        log.warning("reranker 失敗，改用 RRF 順序：%s", e)
        return hits[:top_n]
    out = []
    for i, s in ranked[:top_n]:
        h = hits[i]
        h.score = float(s)
        out.append(h)
    return expand_continuations(out, client or get_client(), name or settings.qdrant_collection)
