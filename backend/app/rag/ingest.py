"""T18 建立索引：Chunk → Qdrant（dense bge-m3 + sparse BM25）。

sparse 不用 fastembed 的 Qdrant/bm25 模型（要從 HuggingFace 下載、且不會中文斷詞），
改為：jieba 斷詞 → crc32 雜湊成 token id → BM25 的 TF 飽和權重；IDF 由 Qdrant 端
（Modifier.IDF）在查詢時計算。查詢向量每個 token 權重 1。
"""
from __future__ import annotations

import re
import uuid
import zlib
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from qdrant_client import QdrantClient, models

from ..config import settings
from .chunk import Chunk, chunk_blocks

BM25_K, BM25_B, AVG_LEN = 1.2, 0.75, 120.0  # AVG_LEN：切塊後平均 token 數的近似值
BATCH = 64
EMBED_BATCH = 16
_NS = uuid.UUID("6f1c1d62-2d0e-4c53-9d0a-7a0c8b3f5e11")
_WORD = re.compile(r"\w", re.U)
_jieba = None


def tokenize(text: str) -> list[str]:
    global _jieba
    if _jieba is None:
        import jieba

        jieba.setLogLevel(60)
        _jieba = jieba
    return [t.lower() for t in _jieba.cut_for_search(text) if _WORD.search(t)]


def _tid(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def sparse_vector(text: str, query: bool = False) -> models.SparseVector:
    tf = Counter(tokenize(text))
    n = sum(tf.values())
    idx, val = [], []
    for tok, c in tf.items():
        idx.append(_tid(tok))
        val.append(1.0 if query else c * (BM25_K + 1) / (c + BM25_K * (1 - BM25_B + BM25_B * n / AVG_LEN)))
    merged: dict[int, float] = {}
    for i, v in zip(idx, val):  # crc32 碰撞時合併
        merged[i] = merged.get(i, 0.0) + v
    return models.SparseVector(indices=list(merged), values=list(merged.values()))


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


def ensure_collection(client: QdrantClient, name: str | None = None, dim: int | None = None,
                      recreate: bool = False) -> str:
    name = name or settings.qdrant_collection
    dim = dim or settings.embed_dim
    if recreate and client.collection_exists(name):
        client.delete_collection(name)
    if not client.collection_exists(name):
        client.create_collection(
            name,
            vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for f in ("doc_id", "doc_type", "file_name", "kind"):
            client.create_payload_index(name, f, models.PayloadSchemaType.KEYWORD)
    return name


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


def indexed_mtime(client: QdrantClient, name: str, doc_id: str) -> int | None:
    """回傳已索引文件的 mtime（整數奈秒；浮點數經 Qdrant JSON 存取精度會對不上）。"""
    pts, _ = client.scroll(name, scroll_filter=_doc_filter(doc_id), limit=1, with_payload=["mtime_ns"])
    return pts[0].payload.get("mtime_ns") if pts else None


def ingest_chunks(client: QdrantClient, chunks: list[Chunk], embed: Callable[[list[str]], list[list[float]]],
                  mtime_ns: int = 0, name: str | None = None) -> int:
    """寫入同一份文件的 chunks（先刪舊的再寫，避免舊版殘留）。回傳寫入筆數。"""
    name = name or settings.qdrant_collection
    if not chunks:
        return 0
    client.delete(name, points_selector=models.FilterSelector(filter=_doc_filter(chunks[0].doc_id)))
    done = 0
    for s in range(0, len(chunks), BATCH):
        part = chunks[s : s + BATCH]
        dense: list[list[float]] = []
        for e in range(0, len(part), EMBED_BATCH):
            dense += embed([c.text for c in part[e : e + EMBED_BATCH]])
        pts = [
            models.PointStruct(
                id=point_id(c.chunk_id),
                vector={"dense": d, "bm25": sparse_vector(c.text)},
                payload={**asdict(c), "mtime_ns": int(mtime_ns)},
            )
            for c, d in zip(part, dense)
        ]
        client.upsert(name, pts)
        done += len(pts)
    return done


def ingest_pdf(client: QdrantClient, path: Path, embed: Callable[[list[str]], list[list[float]]],
               force: bool = False, name: str | None = None) -> int | None:
    """索引一份 PDF；已索引且 mtime 未變則回傳 None（跳過）。"""
    from .parse import doc_id_of, parse_pdf

    path = Path(path)
    name = name or settings.qdrant_collection
    mt = path.stat().st_mtime_ns
    if not force and indexed_mtime(client, name, doc_id_of(path.name)) == mt:
        return None
    return ingest_chunks(client, chunk_blocks(parse_pdf(path)), embed, mt, name)


def ingest_folder(client: QdrantClient, folder: Path, embed: Callable[[list[str]], list[list[float]]],
                  force: bool = False, recreate: bool = False,
                  progress: Callable[[int, int, str, int | None], None] | None = None) -> dict:
    """索引資料夾內所有 PDF。progress(i, n, 檔名, 寫入塊數或 None=跳過)。回傳統計。"""
    import time

    t0 = time.time()
    name = ensure_collection(client, recreate=recreate)
    pdfs = sorted(Path(folder).glob("*.pdf"))
    written, skipped = 0, 0
    for i, p in enumerate(pdfs, 1):
        n = ingest_pdf(client, p, embed, force=force or recreate, name=name)
        if n is None:
            skipped += 1
        else:
            written += n
        if progress:
            progress(i, len(pdfs), p.name, n)
    return {"files": len(pdfs), "written": written, "skipped": skipped,
            "points": client.count(name, exact=True).count, "seconds": round(time.time() - t0, 1)}
