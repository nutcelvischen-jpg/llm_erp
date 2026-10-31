import pytest

from backend.app.agent.graph import AI_SQL_WARNING, Deps, md_table, run_agent
from backend.app.agent.router import Route
from backend.app.llm import ChatResult
from backend.app.rag.answer import RagAnswer, Source
from backend.app.text2sql import SqlAnswer

SQL_OK = SqlAnswer(sql='SELECT "客戶名稱", 營收 FROM v LIMIT 3', explanation="今年營收最高的 3 個客戶",
                   columns=["客戶名稱", "營收"], rows=[["鴻遠機械", 12000000], ["台陽科技", 9000000],
                                                       ["華發|實業", None]], row_count=3, attempts=1)
RAG_OK = RagAnswer("- 每逾一日 0.3%，上限 10% [來源 1]",
                   [Source("銷售合約_鴻遠機械.pdf", 2, "第五條", "每逾一日…")], 50, 10, 300)


def make(kind, sql=SQL_OK, rag=RAG_OK, chat_text="綜合結論", audits=None, rewritten=None, **kw):
    audits = [] if audits is None else audits
    calls = {"sql": [], "docs": [], "chat": []}

    def sql_fn(q):
        calls["sql"].append(q)
        if isinstance(sql, Exception):
            raise sql
        return sql

    def chat_fn(msgs):
        calls["chat"].append(msgs)
        return ChatResult(chat_text, 7, 3, 100)

    deps = Deps(route=lambda q, h: Route(kind, rewritten or q), sql=sql_fn,
                retrieve=lambda q: calls["docs"].append(q) or ["hit"], rag_answer=lambda q, hits: rag,
                chat=chat_fn, audit_write=lambda rec: audits.append(rec) or 42, **kw)
    return deps, calls, audits


def test_sql_route_builds_table_sql_and_warning():
    deps, calls, audits = make("sql")
    r = run_agent("今年營收最高的三個客戶", None, "s1", deps)
    assert r.route == "sql" and r.row_count == 3 and r.warning == AI_SQL_WARNING
    assert "| 鴻遠機械 | 12,000,000 |" in r.markdown and "華發\\|實業" in r.markdown and "| - |" in r.markdown
    assert "<details><summary>查詢的 SQL</summary>" in r.markdown and AI_SQL_WARNING in r.markdown
    assert calls["docs"] == [] and r.audit_id == 42
    a = audits[0]
    assert (a.route, a.session_id, a.sql_ok, a.sql_rows, a.error) == ("sql", "s1", True, 3, None)


def test_sql_explanation_with_unsupported_number_uses_fixed_sentence():
    bad = SqlAnswer(sql="SELECT 1", explanation="營收成長 37%", columns=["x"], rows=[[1]], row_count=1)
    r = run_agent("q", deps=make("sql", sql=bad)[0])
    assert r.answer == "查詢結果如下表（共 1 列）。"


def test_docs_route_has_sources_and_no_table():
    deps, calls, audits = make("docs")
    r = run_agent("鴻遠罰款", deps=deps)
    assert r.route == "docs" and calls["sql"] == []
    assert "0.3%" in r.markdown and "**來源**" in r.markdown and "銷售合約_鴻遠機械.pdf 第 2 頁 › 第五條" in r.markdown
    assert "**數據**" not in r.markdown and r.warning is None
    assert audits[0].doc_sources[0]["page"] == 2 and audits[0].prompt_tokens == 50


def test_both_runs_both_and_merges_with_number_check():
    deps, calls, _ = make("both", chat_text="鴻遠機械營收 12,000,000 元；違約金 0.3% [來源 1]")
    r = run_agent("q", deps=deps)
    assert calls["sql"] and calls["docs"] and r.answer.startswith("鴻遠機械營收 12,000,000")
    assert "**數據**" in r.markdown and "**來源**" in r.markdown
    assert r.tokens == {"prompt": 57, "completion": 13}


def test_both_merge_with_invented_number_falls_back():
    deps, _, _ = make("both", chat_text="營收成長 99%")
    r = run_agent("q", deps=deps)
    assert "99" not in r.answer and r.answer.startswith("今年營收最高的 3 個客戶") and "0.3%" in r.answer


def test_both_sql_not_applicable_is_silent():
    na = SqlAnswer(error="這個問題無法用目前的 ERP 資料回答：資料中沒有特休")
    deps, calls, _ = make("both", sql=na)
    r = run_agent("特休幾天", deps=deps)
    assert r.answer == RAG_OK.text and "查詢失敗" not in r.markdown and r.error is None
    assert calls["chat"] == []


def test_branch_failure_reported_not_raised():
    deps, _, audits = make("both", sql=RuntimeError("db down"))
    r = run_agent("q", deps=deps)
    assert "> 這部分查詢失敗：數據查詢失敗：db down" in r.markdown and "0.3%" in r.markdown
    assert "db down" in audits[0].error


def test_docs_failure():
    deps, _, _ = make("docs", rag=RagAnswer("x", error="LLM 回應逾時"))
    r = run_agent("q", deps=deps)
    assert "這部分查詢失敗：文件回答失敗：LLM 回應逾時" in r.markdown


def test_chat_route_and_history():
    deps, calls, _ = make("chat", chat_text="你好，我是 ERP 助理")
    r = run_agent("你好", [{"role": "user", "content": "嗨"}, {"role": "system", "content": "x"}], deps=deps)
    assert r.answer == "你好，我是 ERP 助理" and r.route == "chat"
    msgs = calls["chat"][0]
    assert [m["role"] for m in msgs] == ["system", "user", "user"]


def test_chat_with_made_up_number_is_replaced():
    deps, _, _ = make("chat", chat_text="今年營收約 5,000 萬")
    assert "5,000" not in run_agent("聊聊", deps=deps).answer


def test_router_failure_falls_back_to_chat():
    def boom(q, h):
        raise RuntimeError("router down")

    deps, _, _ = make("chat")
    deps.route = boom
    r = run_agent("q", deps=deps)
    assert r.route == "chat" and "問題分類失敗" in r.error


def test_rewritten_question_is_used():
    deps, calls, _ = make("sql", rewritten="鴻遠機械去年營收")
    r = run_agent("那去年呢", deps=deps)
    assert calls["sql"] == ["鴻遠機械去年營收"] and r.rewritten == "鴻遠機械去年營收"


def test_md_table_truncates():
    t = md_table(["a"], [[i] for i in range(25)], 25)
    assert t.count("\n| ") == 20 and "僅顯示前 20 列，共 25 列" in t


# ---------- 真實服務 ----------
DEMO = [("今年營收最高的三個客戶", "sql"), ("鴻遠機械的合約，延遲交貨罰款怎麼算？", "docs"),
        ("台陽科技逾期的應收有多少？依合約逾期多久可以暫停出貨？", "both")]


@pytest.mark.llm
@pytest.mark.db
def test_real_three_demo_questions():
    from sqlalchemy import text

    from backend.app.db import engine

    with engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM app.audit_log")).scalar()
    for q, kind in DEMO:
        r = run_agent(q, session_id="pytest")
        print(f"\n--- {q} [{r.route}] {r.latency_ms} ms\n{r.markdown[:600]}")
        assert r.markdown and r.route == kind and r.audit_id
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app.audit_log")).scalar() == before + 3
