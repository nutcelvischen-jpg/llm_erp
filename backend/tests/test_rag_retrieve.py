import hashlib

import pytest
from qdrant_client import QdrantClient

from backend.app.rag.chunk import Chunk
from backend.app.rag.ingest import ensure_collection, ingest_chunks
from backend.app.rag.retrieve import RetrieveError, candidates, retrieve

DIM = 8


def fake_embed(texts):
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        out.append([b / 255 + 0.01 for b in h[:DIM]])
    return out


def fake_rerank(query, docs, top_n):
    """分數 = 文件中「違約金」出現次數。"""
    ranked = sorted(enumerate(float(d.count("違約金")) for d in docs), key=lambda x: x[1], reverse=True)
    return ranked[:top_n]


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    ensure_collection(c, "t", DIM)
    contract = [
        Chunk("a-000", "a", "銷售合約_甲.pdf", 2, ["第五條"], "延遲交貨每日按 0.3% 計付違約金，違約金上限 10%。",
              "text", "合約"),
        Chunk("a-001", "a", "銷售合約_甲.pdf", 3, ["第六條"], "付款條件為月結 30 天。", "text", "合約"),
    ]
    hr = [Chunk("h-000", "h", "人資_請假.pdf", 1, ["特休"], "特別休假依年資給予，滿一年七天。", "text", "人資")]
    ingest_chunks(c, contract, fake_embed, 1, "t")
    ingest_chunks(c, hr, fake_embed, 1, "t")
    return c


def kw(client):
    return {"client": client, "embed": fake_embed, "name": "t"}


def test_candidates_returns_hits_with_payload(client):
    hits = candidates("違約金", top_k=10, **kw(client))
    assert {h.chunk_id for h in hits} == {"a-000", "a-001", "h-000"}
    top = next(h for h in hits if h.chunk_id == "a-000")
    assert top.file_name == "銷售合約_甲.pdf" and top.page == 2 and top.heading_path == ["第五條"]
    assert top.doc_type == "合約"


def test_bm25_match_ranks_first_in_fusion(client):
    hits = candidates("違約金上限", top_k=10, **kw(client))
    assert hits[0].chunk_id == "a-000"


def test_doc_type_filter(client):
    hits = candidates("違約金", top_k=10, doc_type="人資", **kw(client))
    assert [h.chunk_id for h in hits] == ["h-000"]


def test_retrieve_reranks_and_limits_top_n(client):
    hits = retrieve("付款", top_k=10, top_n=2, rerank=fake_rerank, **kw(client))
    assert len(hits) == 2
    assert hits[0].chunk_id == "a-000" and hits[0].score == 2.0


def test_retrieve_falls_back_to_rrf_when_reranker_fails(client):
    def boom(*_):
        raise RuntimeError("no model")

    hits = retrieve("違約金上限", top_k=10, top_n=1, rerank=boom, **kw(client))
    assert [h.chunk_id for h in hits] == ["a-000"]


def test_retrieve_empty_collection_skips_rerank():
    c = QdrantClient(":memory:")
    ensure_collection(c, "t", DIM)
    assert retrieve("x", rerank=lambda *_: pytest.fail("不該呼叫"), client=c, embed=fake_embed, name="t") == []


def test_qdrant_error_is_wrapped():
    c = QdrantClient(":memory:")  # 沒有 collection
    with pytest.raises(RetrieveError, match="文件檢索失敗"):
        candidates("x", client=c, embed=fake_embed, name="missing")


def test_embed_error_is_wrapped(client):
    def boom(_):
        raise RuntimeError("down")

    with pytest.raises(RetrieveError, match="向量化失敗"):
        candidates("x", client=client, embed=boom, name="t")


# ---------- 真實服務（LM Studio embedding + Qdrant + reranker）----------
@pytest.mark.llm
def test_real_penalty_query_hits_sales_contract():
    hits = retrieve("鴻遠機械的合約，延遲交貨罰款怎麼算？")
    assert hits, "沒有檢索結果，請先 make ingest"
    assert hits[0].file_name.startswith("銷售合約") and "0.3%" in hits[0].text


@pytest.mark.llm
def test_real_annual_leave_query_hits_hr():
    hits = retrieve("特休幾天")
    assert hits and hits[0].doc_type == "人資"
