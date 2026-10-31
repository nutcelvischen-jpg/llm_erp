import hashlib

import pytest
from qdrant_client import QdrantClient, models

from backend.app.rag.chunk import Chunk
from backend.app.rag.ingest import (ensure_collection, indexed_mtime, ingest_chunks, point_id,
                                    sparse_vector, tokenize)

DIM = 8


def fake_embed(texts):
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        out.append([b / 255 + 0.01 for b in h[:DIM]])
    return out


def C(i, text, doc="d1", page=1):
    return Chunk(f"{doc}-{i:03d}", doc, "銷售合約_甲.pdf", page, ["第三條"], text, "text", "合約")


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    ensure_collection(c, "t", DIM)
    return c


def test_tokenize_chinese_and_numbers():
    t = tokenize("延遲交貨每日按0.3%計付違約金")
    assert "違約金" in t and "0.3%" in t and all(x.strip() for x in t)


def test_sparse_doc_vs_query():
    d = sparse_vector("違約金 違約金 上限", query=False)
    q = sparse_vector("違約金", query=True)
    assert len(d.indices) == len(d.values) and set(q.indices) <= set(d.indices)
    assert q.values == [1.0]


def test_point_id_deterministic():
    assert point_id("d1-000") == point_id("d1-000") != point_id("d1-001")


def test_ingest_and_sparse_search(client):
    cs = [C(0, "延遲交貨每日按0.3%計付違約金，上限10%"), C(1, "付款條件為月結30天"), C(2, "保固期間為12個月")]
    assert ingest_chunks(client, cs, fake_embed, mtime=123.0, name="t") == 3
    assert client.count("t", exact=True).count == 3
    assert indexed_mtime(client, "t", "d1") == 123.0
    r = client.query_points("t", query=sparse_vector("違約金上限", query=True), using="bm25", limit=1, with_payload=True)
    assert r.points[0].payload["chunk_id"] == "d1-000" and r.points[0].payload["heading_path"] == ["第三條"]
    r = client.query_points("t", query=fake_embed([cs[1].text])[0], using="dense", limit=1, with_payload=True)
    assert r.points[0].payload["chunk_id"] == "d1-001"


def test_reingest_replaces_old_points(client):
    ingest_chunks(client, [C(0, "舊一"), C(1, "舊二"), C(2, "舊三")], fake_embed, 1.0, "t")
    ingest_chunks(client, [C(0, "新一")], fake_embed, 2.0, "t")
    assert client.count("t", exact=True).count == 1 and indexed_mtime(client, "t", "d1") == 2.0
    ingest_chunks(client, [C(0, "其他文件", doc="d2")], fake_embed, 3.0, "t")
    assert client.count("t", exact=True).count == 2


def test_indexed_mtime_missing(client):
    assert indexed_mtime(client, "t", "none") is None


def test_batches_over_64(client):
    cs = [C(i, f"第{i}段內容") for i in range(150)]
    assert ingest_chunks(client, cs, fake_embed, 1.0, "t") == 150
    assert client.count("t", exact=True).count == 150
