from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from sqlalchemy import text

from backend.app import text2sql
from backend.app.sql_guard import validate

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = yaml.safe_load((ROOT / "data" / "seed" / "sql_examples.yaml").read_text(encoding="utf-8"))


# ---------- 範例檔本身 ----------
def test_twenty_well_formed_examples():
    assert len(EXAMPLES) == 20
    for ex in EXAMPLES:
        assert ex["question"].strip() and ex["sql"].strip() and ex["tags"]
    assert len({ex["question"] for ex in EXAMPLES}) == 20


def test_examples_cover_required_topics():
    tags = {t for ex in EXAMPLES for t in ex["tags"]}
    required = {"營收", "同期比較", "毛利率", "TopN", "應收", "逾期", "呆滯", "缺料", "業務", "供應商", "占比", "帳齡"}
    assert required <= tags, f"缺少主題：{required - tags}"


@pytest.mark.parametrize("ex", EXAMPLES, ids=[e["question"][:20] for e in EXAMPLES])
def test_every_example_passes_sql_guard(ex):
    r = validate(ex["sql"])
    assert r.ok, r.reason


@pytest.mark.parametrize("ex", EXAMPLES, ids=[e["question"][:20] for e in EXAMPLES])
def test_examples_use_quoted_chinese_identifiers_and_current_date(ex):
    sql = ex["sql"]
    assert '"v_' in sql  # View 名稱一律加雙引號
    assert "'20" not in sql  # 不寫死日期


# ---------- 需要資料庫：每一句都要真的跑得出結果 ----------
@pytest.mark.db
@pytest.mark.parametrize("ex", EXAMPLES, ids=[e["question"][:20] for e in EXAMPLES])
def test_every_example_runs_and_returns_rows(ex):
    from backend.app.db import engine_ro

    sql = validate(ex["sql"]).sql
    with engine_ro.connect() as conn:
        rows = conn.execute(text(sql)).all()
    assert len(rows) > 0, f"沒有結果：{ex['question']}"


# ---------- pick_examples（假的 embedding，不需要 LM Studio）----------
def make_examples():
    vecs = {"A": [1, 0, 0], "B": [0, 1, 0], "C": [0, 0, 1], "D": [0.9, 0.1, 0]}
    return [text2sql.Example(k, f"select {k}", [], np.asarray(v, dtype=np.float32)) for k, v in vecs.items()]


def test_pick_examples_orders_by_cosine_similarity(monkeypatch):
    monkeypatch.setattr(text2sql.llm, "embed", lambda texts: [[1.0, 0.05, 0.0]])
    assert [e.question for e in text2sql.pick_examples("q", k=2, examples=make_examples())] == ["A", "D"]


def test_pick_examples_k_larger_than_pool_and_empty_pool(monkeypatch):
    monkeypatch.setattr(text2sql.llm, "embed", lambda texts: [[0.0, 0.0, 1.0]])
    got = text2sql.pick_examples("q", k=10, examples=make_examples())
    assert len(got) == 4 and got[0].question == "C"
    assert text2sql.pick_examples("q", examples=[]) == []


def test_pick_examples_handles_zero_vector(monkeypatch):
    monkeypatch.setattr(text2sql.llm, "embed", lambda texts: [[0.0, 0.0, 0.0]])
    assert len(text2sql.pick_examples("q", k=2, examples=make_examples())) == 2  # 不會除以零


def test_load_examples_is_cached(monkeypatch):
    calls = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_a, **_k):
            calls.append(1)
            return SimpleNamespace(all=lambda: [("問", "select 1", ["t"], [0.1, 0.2])])

    monkeypatch.setattr(text2sql, "_cache", None)
    monkeypatch.setattr(text2sql, "engine", SimpleNamespace(connect=lambda: FakeConn()))
    a, b = text2sql.load_examples(), text2sql.load_examples()
    assert a is b and len(calls) == 1 and a[0].tags == ["t"]
    text2sql.load_examples(force=True)
    assert len(calls) == 2


# ---------- 真實 embedding + 已載入的範例（需先 make load-examples）----------
@pytest.mark.llm
@pytest.mark.db
@pytest.mark.parametrize(("question", "expected_tag"), [
    ("哪個客戶欠最多錢", "應收"),
    ("有哪些貨放很久沒賣掉", "呆滯"),
    ("目前缺什麼料要補貨", "缺料"),
    ("今年跟去年比，毛利率有沒有下降", "毛利率"),
    ("誰的業績最好", "業務"),
])
def test_real_pick_examples_finds_relevant_example(question, expected_tag):
    text2sql.load_examples(force=True)
    if not text2sql.load_examples():
        pytest.skip("app.sql_examples 是空的，請先執行 make load-examples")
    top = text2sql.pick_examples(question, k=2)
    assert any(expected_tag in e.tags for e in top), [e.question for e in top]
