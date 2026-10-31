"""T14e 結果回覆與數字檢查。"""
from datetime import date

import pytest

from backend.app.catalog.answer import build_messages, facts_text, numbers_supported, summarize
from backend.app.catalog.registry import TEMPLATES
from backend.app.llm import ChatResult, LLMError
from backend.app.numcheck import extract_numbers

COLS = ["客戶名稱", "營收"]
ROWS = [["華發實業", 11979390], ["鴻遠機械", 9869353], ["億達企業", 3783773]]
T = TEMPLATES["sales_rank"]
FACTS = T.facts(COLS, ROWS)
COND = ["排名對象：客戶", "指標：營收", "期間：2026 年（今年）", "筆數：3"]


def chat(text):
    calls = []

    def f(msgs):
        calls.append(msgs)
        return ChatResult(text, 1, 1, 1)
    f.calls = calls
    return f


# ---------- 數字擷取邊界 ----------
def test_extract_boundaries():
    got = [(v, d) for v, d, _ in extract_numbers("營收 1,234.5 元、毛利率 12.3%、約 1,198 萬，三家客戶")]
    assert got == [(1234.5, 1), (12.3, 1), (11980000.0, 0)]  # 中文數字「三」不當數字


# ---------- 支援／不支援 ----------
def test_supported_exact_rounded_and_units():
    assert numbers_supported("華發實業營收 11,979,390 元，約 1,198 萬", ROWS, FACTS, COND)[0]
    assert numbers_supported("華發實業營收約 1,197.9 萬元", ROWS, FACTS, COND)[0]


def test_unsupported_numbers_detected():
    ok, bad = numbers_supported("華發實業營收 12,000,000 元，成長 15%", ROWS, FACTS, COND)
    assert not ok and bad == ["12,000,000", "15"]


def test_years_and_ranks_only_from_context():
    assert numbers_supported("2026 年營收第 1 名是華發實業，前 3 名如表", ROWS, FACTS, COND)[0]
    ok, bad = numbers_supported("2019 年第 7 名", ROWS, FACTS, COND)   # 年份不在條件中、名次超過列數
    assert not ok and bad == ["2019", "7"]


def test_negative_matched_by_absolute_value():
    assert numbers_supported("減少 935,592 元", [["鴻遠機械", -935592]], {}, [])[0]


def test_dates_in_rows_allow_month_and_day():
    assert numbers_supported("最後異動日為 2026 年 3 月 31 日", [["BRG", "2026-03-31"]], {}, [])[0]


# ---------- prompt ----------
def test_prompt_has_facts_formatted_and_rows():
    m = build_messages("今年營收前三名", T, COND, COLS, ROWS, FACTS)
    u = m[1]["content"]
    assert "第一名數值：11979390（格式化：11,979,390 元）" in u and "第 2 列：客戶名稱=鴻遠機械；營收=9869353" in u
    assert "條件：排名對象：客戶；指標：營收" in u and "不可自己計算" in m[0]["content"]
    assert facts_text({"a": None}) == ""


# ---------- 回覆來源 ----------
def test_llm_answer_used_when_numbers_supported():
    a = summarize("今年營收前三名", T, COND, COLS, ROWS, FACTS, chat=chat("今年營收第一名是華發實業，11,979,390 元。"))
    assert a.source == "llm" and a.text.startswith("今年營收第一名")


def test_unsupported_number_falls_back_to_fixed():
    a = summarize("q", T, COND, COLS, ROWS, FACTS, chat=chat("華發實業營收 1,300 萬元。"))
    assert a.source == "fixed" and a.text == T.summary(FACTS) and a.unsupported == ["1,300 萬"]


def test_llm_failure_and_empty_falls_back():
    def boom(_):
        raise LLMError("逾時")
    assert summarize("q", T, COND, COLS, ROWS, FACTS, chat=boom).source == "fixed"
    assert summarize("q", T, COND, COLS, ROWS, FACTS, chat=chat("  ")).source == "fixed"


def test_markdown_table_in_llm_answer_removed():
    text = "今年營收第一名是華發實業。\n\n詳見下表：\n\n| 客戶名稱 | 營收 |\n| :--- | :--- |\n| 華發實業 | 11,979,390 |\n| 鴻遠"
    a = summarize("q", T, COND, COLS, ROWS, FACTS, chat=chat(text))
    assert a.source == "llm" and "|" not in a.text and a.text == "今年營收第一名是華發實業。\n\n詳見下表："


def test_no_rows_does_not_call_llm():
    a = summarize("q", T, COND, COLS, [], T.facts(COLS, []), chat=lambda m: pytest.fail("不該呼叫"))
    assert a.source == "fixed" and a.text == "查無符合條件的資料。"


def test_all_sixteen_fixed_summaries_via_fallback():
    from backend.tests.test_templates import SAMPLES
    for tid, t in TEMPLATES.items():
        cols, rows = SAMPLES[tid]
        a = summarize("q", t, [], cols, rows, t.facts(cols, rows), chat=chat("編造 987,654,321 元"))
        assert a.source == "fixed" and a.text and "None" not in a.text, tid


# ---------- 真實 LLM＋資料庫 ----------
@pytest.mark.llm
@pytest.mark.db
@pytest.mark.parametrize("tid, q, over", [
    ("sales_rank", "今年營收前三名的客戶", {"top_n": 3}),
    ("stock_dead", "哪些料號超過 180 天沒動？壓了多少錢？", {}),
    ("stock_shortage", "依目前待出貨訂單，哪些料號會缺料？建議採購多少？", {}),
])
def test_real_answers_pass_number_check(tid, q, over):
    from backend.app.catalog.intent import readable
    from backend.tests.test_templates import run

    t = TEMPLATES[tid]
    p = {**{s.name: s.default for s in t.params}, **over, "_today": date.today()}
    cols, rows = run(t, p)
    a = summarize(q, t, readable(t, p, date.today()), cols, rows, t.facts(cols, rows), top_n=p.get("top_n") or 0)
    print(f"\n[{tid}] {a.source}: {a.text}")
    assert a.source == "llm", a.unsupported
