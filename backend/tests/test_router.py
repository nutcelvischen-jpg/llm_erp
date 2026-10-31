import pytest

from backend.app.agent.router import build_messages, format_history, merge, route, rule_kinds


def fake(kind, rewritten=""):
    calls = []

    def f(messages):
        calls.append(messages)
        return {"kind": kind, "rewritten": rewritten}

    f.calls = calls
    return f


# ---------- 規則保底（5 案例）----------
@pytest.mark.parametrize("q, expect", [
    ("鴻遠機械的合約，延遲交貨罰款怎麼算？", {"docs"}),
    ("今年營收最高的三個客戶", {"sql"}),
    ("依合約條款，台陽科技逾期的發票要怎麼處理？", {"docs", "sql"}),
    ("出貨檢驗 sop 的抽樣方式", {"docs"}),
    ("你好", set()),
])
def test_rule_kinds(q, expect):
    assert rule_kinds(q) == expect


def test_merge():
    assert merge({"sql", "docs"}) == "both"
    assert merge({"chat", "docs"}) == "docs"
    assert merge({"both"}) == "both"
    assert merge({"chat"}) == "chat" and merge(set()) == "chat"


def test_llm_result_kept_when_rules_agree():
    r = route("今年營收最高的三個客戶", chat_json=fake("sql", "今年營收最高的三個客戶"))
    assert (r.kind, r.source) == ("sql", "llm")


def test_union_with_rules():
    r = route("鴻遠機械的合約付款條件，以及今年營收多少？", chat_json=fake("docs"))
    assert (r.kind, r.source) == ("both", "llm+rules")
    r = route("加班費辦法", chat_json=fake("chat"))
    assert r.kind == "docs"


def test_rules_apply_to_rewritten_too():
    r = route("那去年呢", [{"role": "user", "content": "鴻遠機械今年營收"}], chat_json=fake("chat", "鴻遠機械去年營收"))
    assert r.kind == "sql" and r.rewritten == "鴻遠機械去年營收"


def test_both_returns_split_parts():
    def f(msgs):
        return {"kind": "both", "rewritten": "q", "sql_part": " 台陽逾期多少？ ", "docs_part": "台陽合約多久停止出貨？"}
    r = route("台陽逾期多少？依合約多久可暫停出貨？", chat_json=f)
    assert (r.kind, r.sql_part, r.docs_part) == ("both", "台陽逾期多少？", "台陽合約多久停止出貨？")
    r = route("今年營收", chat_json=lambda m: {"kind": "sql", "rewritten": "今年營收", "sql_part": "x"})
    assert r.sql_part == "" and r.docs_part == ""


def test_empty_rewritten_falls_back_to_question():
    assert route("你好", chat_json=fake("chat", "")).rewritten == "你好"


def test_invalid_kind_uses_rules():
    r = route("合約條款", chat_json=fake("weather"))
    assert (r.kind, r.source) == ("docs", "rules")


def test_llm_failure_uses_rules():
    def boom(_):
        raise RuntimeError("down")

    r = route("今年營收多少", chat_json=boom)
    assert (r.kind, r.rewritten, r.source) == ("sql", "今年營收多少", "rules")


def test_history_is_trimmed_and_formatted():
    hist = [{"role": "user", "content": f"q{i}"} for i in range(20)] + [{"role": "system", "content": "x"}]
    text = format_history(hist)
    assert text.count("\n") == 11 and text.startswith("使用者：q8") and "x" not in text
    assert "前文：（無）" in build_messages("你好", None)[1]["content"]
    assert "助理：答" in build_messages("那去年呢", [{"role": "assistant", "content": "答"}])[1]["content"]


# ---------- 真實 LLM ----------
@pytest.mark.llm
def test_real_sql():
    assert route("今年營收最高的三個客戶").kind == "sql"


@pytest.mark.llm
def test_real_docs():
    assert route("鴻遠機械的合約，延遲交貨罰款怎麼算？").kind == "docs"


@pytest.mark.llm
def test_real_followup_rewrite():
    hist = [{"role": "user", "content": "鴻遠機械今年營收多少？"},
            {"role": "assistant", "content": "鴻遠機械今年營收為 1,234 萬元。"}]
    r = route("那去年呢", hist)
    print("\n", r)
    assert r.kind == "sql" and "鴻遠" in r.rewritten and "去年" in r.rewritten
