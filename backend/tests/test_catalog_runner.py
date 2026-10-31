"""T14f runner：意圖 → 執行既定程式 → 回覆（假的辨識／執行／LLM）。"""
from datetime import date

from backend.app.catalog import runner
from backend.app.catalog.intent import Intent, Proposal
from backend.app.llm import ChatResult

TODAY = date(2026, 10, 31)


def deps(intent=None, rows=None, exc=None, chat_text="今年營收第一名是華發實業，11,979,390 元。"):
    calls = {"execute": [], "confirm": []}

    def execute(q):
        calls["execute"].append(q)
        if exc:
            raise exc
        return ["客戶名稱", "營收"], rows if rows is not None else [["華發實業", 11979390], ["鴻遠機械", 9869353]]

    def confirm(tid, params, today):
        calls["confirm"].append((tid, params))
        return Intent("template", tid, {"dimension": "客戶", "metric": "營收", "period": "this_year", "top_n": 5,
                                        "order": "desc", "_today": today}, ["排名對象：客戶"])

    d = runner.Deps(recognize=lambda q, t: intent, confirm=confirm, execute=execute,
                    chat=lambda m: ChatResult(chat_text, 1, 1, 1))
    return d, calls


TEMPLATE = Intent("template", "sales_rank", {"dimension": "客戶", "metric": "營收", "period": "this_year", "top_n": 5,
                                             "order": "desc", "_today": TODAY},
                  ["排名對象：客戶", "期間：2026 年（今年）", "筆數：5"], notes=["已將「華發」視為「華發實業」"])


def test_template_executes_with_binds_and_llm_answer():
    d, calls = deps(TEMPLATE)
    a = runner.answer_question("今年營收前五名客戶", TODAY, deps=d)
    assert a.mode == "template" and a.template_title == "銷售排名" and a.row_count == 2
    assert ":date_from" in a.sql and a.binds == {"date_from": "2026-01-01", "date_to": "2026-11-01"}
    assert a.answer_source == "llm" and a.answer.startswith("今年營收第一名") and a.notes == TEMPLATE.notes
    assert calls["execute"][0].binds["date_from"] == date(2026, 1, 1)  # 執行時仍是 date，不是字串


def test_invented_number_uses_fixed_summary():
    d, _ = deps(TEMPLATE, chat_text="華發實業營收 2,000 萬元")
    a = runner.answer_question("q", TODAY, deps=d)
    assert a.answer_source == "fixed" and "華發實業" in a.answer and "2,000" not in a.answer


def test_clarify_confirm_no_match_do_not_execute():
    d, calls = deps(Intent("clarify", "sales_total", message="請問是哪一個？", options=["華發實業", "華發精密"]))
    a = runner.answer_question("q", TODAY, deps=d)
    assert (a.mode, a.options, a.template_title) == ("clarify", ["華發實業", "華發精密"], "銷售合計")
    prop = Proposal("sales_rank", "銷售排名", "d", {"dimension": "客戶", "_today": TODAY}, ["排名對象：客戶"],
                    ["客戶名稱", "營收"], ["指標不支援「毛利率」，改用「營收」"])
    d, calls2 = deps(Intent("confirm", message="您是要查下列其中一個嗎？", proposals=[prop]))
    a = runner.answer_question("q", TODAY, deps=d)
    assert a.mode == "confirm" and a.proposals[0]["params"] == {"dimension": "客戶"}   # 不含 _today
    assert a.proposals[0]["notes"] == prop.notes and a.proposals[0]["columns"] == ["客戶名稱", "營收"]
    d, calls3 = deps(Intent("no_match", message="沒有對應", candidates=[{"template_id": "ar_aging"},
                                                                        {"template_id": "sales_rank"}]))
    a = runner.answer_question("q", TODAY, deps=d)
    assert a.mode == "no_match" and a.suggestions == ["應收帳款的帳齡分佈", "今年營收前五名的客戶"]
    assert calls["execute"] == calls2["execute"] == calls3["execute"] == []


def test_choice_goes_through_confirm_revalidation():
    d, calls = deps(intent=None)
    a = runner.answer_question("今年哪個客戶最賺", TODAY, choice={"template_id": "sales_rank", "params": {"top_n": "5"}},
                               deps=d)
    assert calls["confirm"] == [("sales_rank", {"top_n": "5"})] and a.mode == "template"


def test_execute_error_returns_error_mode():
    d, _ = deps(TEMPLATE, exc=RuntimeError("canceling statement due to statement timeout\nDETAIL"))
    a = runner.answer_question("q", TODAY, deps=d)
    assert a.mode == "error" and a.error == "查詢失敗：canceling statement due to statement timeout"
    assert a.sql and a.rows == []


def test_empty_result_uses_fixed_without_llm():
    d, _ = deps(TEMPLATE, rows=[], chat_text="不該用到")
    a = runner.answer_question("q", TODAY, deps=d)
    assert a.answer == "查無符合條件的資料。" and a.answer_source == "fixed"
