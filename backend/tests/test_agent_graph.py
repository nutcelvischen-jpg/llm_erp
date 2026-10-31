import pytest

from backend.app.agent.graph import Deps, md_table, run_agent
from backend.app.agent.router import Route
from backend.app.catalog.runner import CatalogAnswer
from backend.app.llm import ChatResult
from backend.app.rag.answer import RagAnswer, Source

SQL_OK = CatalogAnswer("template", "sales_rank", "銷售排名", ["排名對象：客戶", "期間：2026 年（今年）"],
                       ["客戶名稱", "營收"], [["鴻遠機械", 12000000], ["台陽科技", 9000000], ["華發|實業", None]], 3,
                       'SELECT "客戶名稱" FROM "v_銷售明細" WHERE "訂單日期" >= :date_from LIMIT 3',
                       {"date_from": "2026-01-01"}, "今年營收第一名是鴻遠機械，12,000,000 元。", "llm")
RAG_OK = RagAnswer("- 每逾一日 0.3%，上限 10% [來源 1]",
                   [Source("銷售合約_鴻遠機械.pdf", 2, "第五條", "每逾一日…")], 50, 10, 300)
CONFIRM = CatalogAnswer("confirm", answer="找不到完全符合的既定查詢。", proposals=[
    {"template_id": "sales_rank", "title": "銷售排名", "description": "d", "params": {"dimension": "客戶"},
     "params_readable": ["排名對象：客戶"], "columns": ["客戶名稱", "營收"], "notes": []}])


def make(kind, sql=SQL_OK, rag=RAG_OK, chat_text="綜合結論", audits=None, rewritten=None, **kw):
    audits = [] if audits is None else audits
    calls = {"sql": [], "docs": [], "chat": [], "choice": []}

    def sql_fn(q, choice=None, data_part_only=False):
        calls["sql"].append(q)
        calls["choice"].append(choice)
        calls.setdefault("data_part_only", []).append(data_part_only)
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


def test_sql_route_shows_template_badge_table_sql_and_binds():
    deps, calls, audits = make("sql")
    r = run_agent("今年營收最高的三個客戶", None, "s1", deps)
    assert r.route == "sql" and r.mode == "template" and r.template_id == "sales_rank" and r.row_count == 3
    assert r.answer == SQL_OK.answer and r.answer_source == "llm" and r.warning is None
    assert r.params_readable == SQL_OK.params_readable and r.binds == {"date_from": "2026-01-01"}
    assert "**數據**（標準查詢：銷售排名｜排名對象：客戶｜期間：2026 年（今年））" in r.markdown
    assert "| 鴻遠機械 | 12,000,000 |" in r.markdown and "華發\\|實業" in r.markdown and "| - |" in r.markdown
    assert "-- :date_from = '2026-01-01'" in r.markdown and "AI 即時產生" not in r.markdown
    assert calls["docs"] == [] and calls["chat"] == [] and r.audit_id == 42
    a = audits[0]
    assert (a.route, a.session_id, a.sql_ok, a.sql_rows, a.error) == ("sql", "s1", True, 3, None)
    assert "-- template: sales_rank" in a.sql_text


def test_sql_confirm_lists_programs_without_failure():
    deps, _, audits = make("sql", sql=CONFIRM)
    r = run_agent("今年哪個客戶平均訂單最大", deps=deps)
    assert r.mode == "confirm" and r.error is None and r.rows == [] and r.sql == ""
    assert r.proposals[0]["template_id"] == "sales_rank" and "1. **銷售排名**：排名對象：客戶" in r.markdown
    assert "查詢失敗" not in r.markdown and audits[0].sql_ok is None


def test_sql_clarify_and_no_match():
    deps, _, _ = make("sql", sql=CatalogAnswer("clarify", answer="「華發」對應到多個客戶，請問是哪一個？",
                                                options=["華發實業", "華發精密"]))
    r = run_agent("華發營收", deps=deps)
    assert r.mode == "clarify" and r.options == ["華發實業", "華發精密"] and "可選：華發實業、華發精密" in r.markdown
    deps, _, _ = make("sql", sql=CatalogAnswer("no_match", answer="這類問題目前沒有對應的既定查詢",
                                                suggestions=["今年營收前五名的客戶"]))
    r = run_agent("員工薪資", deps=deps)
    assert r.mode == "no_match" and r.error is None and "可以這樣問：今年營收前五名的客戶" in r.markdown


def test_choice_skips_routing_and_runs_program():
    deps, calls, _ = make("docs")
    r = run_agent("今年哪個客戶平均訂單最大", deps=deps, choice={"template_id": "sales_rank", "params": {}})
    assert r.route == "sql" and r.mode == "template" and calls["docs"] == []
    assert calls["choice"] == [{"template_id": "sales_rank", "params": {}}]


def test_sql_execution_error_is_reported():
    deps, _, audits = make("sql", sql=CatalogAnswer("error", "sales_rank", "銷售排名", error="查詢失敗：逾時"))
    r = run_agent("q", deps=deps)
    assert r.mode == "error" and "> 這部分查詢失敗：查詢失敗：逾時" in r.markdown and audits[0].sql_ok is False


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
    assert "**數據**（標準查詢：銷售排名" in r.markdown and "**來源**" in r.markdown and r.mode == "template"
    assert calls["data_part_only"] == [True]   # both：意圖辨識只看數字的部分
    assert r.tokens == {"prompt": 57, "completion": 13}


def test_both_uses_split_parts_from_router():
    deps, calls, _ = make("both")
    deps.route = lambda q, h: Route("both", q, "llm", "台陽逾期多少？", "台陽合約逾期多久可暫停出貨？")
    run_agent("台陽逾期多少？依合約多久可暫停出貨？", deps=deps)
    assert calls["sql"] == ["台陽逾期多少？"] and calls["data_part_only"] == [False]
    assert calls["docs"] == ["台陽合約逾期多久可暫停出貨？"]


def test_both_merge_with_invented_number_falls_back():
    deps, _, _ = make("both", chat_text="營收成長 99%")
    r = run_agent("q", deps=deps)
    assert "99" not in r.answer and r.answer.startswith(SQL_OK.answer) and "0.3%" in r.answer


def test_both_sql_not_applicable_is_silent():
    for na in (CatalogAnswer("no_match", answer="沒有對應的既定查詢"), CONFIRM):
        deps, calls, _ = make("both", sql=na)
        r = run_agent("特休幾天", deps=deps)
        assert r.answer == RAG_OK.text and "查詢失敗" not in r.markdown and r.error is None
        assert calls["chat"] == [] and r.mode is None and r.proposals == []


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
