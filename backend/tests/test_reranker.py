import time

import pytest

from backend.app import reranker


class FakeModel:
    """分數 = 文件裡「罰款」出現次數，方便預測排序。"""

    def __init__(self):
        self.calls = []

    def predict(self, pairs, **_):
        self.calls.append(list(pairs))
        return [float(d.count("罰款")) for _, d in pairs]


@pytest.fixture
def fake(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(reranker, "_model", m)
    return m


def test_rerank_orders_by_score_and_returns_original_index(fake):
    docs = ["無關", "罰款 罰款 罰款", "罰款"]
    assert reranker.rerank("q", docs, top_n=3) == [(1, 3.0), (2, 1.0), (0, 0.0)]
    assert fake.calls[0] == [("q", d) for d in docs]


def test_rerank_top_n_limits_and_exceeding_is_ok(fake):
    docs = ["a", "罰款", "b"]
    assert len(reranker.rerank("q", docs, top_n=1)) == 1
    assert len(reranker.rerank("q", docs, top_n=10)) == 3


def test_rerank_default_top_n_from_settings(fake, monkeypatch):
    monkeypatch.setattr(reranker.settings, "rerank_top_n", 2)
    assert len(reranker.rerank("q", ["a", "b", "c"])) == 2


def test_rerank_empty_docs_does_not_load_model(monkeypatch):
    monkeypatch.setattr(reranker, "_model", None)
    monkeypatch.setattr(reranker, "_load", lambda: pytest.fail("不該載入模型"))
    assert reranker.rerank("q", []) == []


def test_model_is_lazy_loaded_once(monkeypatch):
    loads = []
    monkeypatch.setattr(reranker, "_model", None)
    monkeypatch.setattr(reranker, "_load", lambda: loads.append(1) or FakeModel())
    reranker.rerank("q", ["a"])
    reranker.rerank("q", ["b"])
    assert loads == [1]


# ---------- 真實模型（首次會下載約 2.2 GB）----------
@pytest.mark.llm
def test_real_rerank_penalty_clause_first():
    docs = [
        "付款條件：貨到驗收後 45 日內以電匯方式支付貨款。",
        "延遲交貨罰款：賣方逾期交貨者，每日按未交貨金額 0.3% 計罰，上限 10%。",
        "本公司成立於 1998 年，位於台中市，主要生產精密軸承與齒輪。",
    ]
    ranked = reranker.rerank("合約延遲交貨罰款", docs)
    assert ranked[0][0] == 1
    assert ranked[0][1] > ranked[-1][1]


@pytest.mark.llm
def test_real_rerank_20_docs_is_fast_enough():
    docs = [f"第 {i} 條 一般性條款內容，說明雙方權利義務與付款方式。" for i in range(19)]
    docs.append("延遲交貨罰款：每日按未交貨金額 0.3% 計罰。")
    reranker.rerank("延遲交貨罰款", docs[:2])  # 暖機
    t = time.perf_counter()
    ranked = reranker.rerank("延遲交貨罰款", docs)
    dt = time.perf_counter() - t
    print(f"\nrerank 20 筆耗時 {dt:.2f} 秒")
    assert ranked[0][0] == 19
    assert dt < 5
