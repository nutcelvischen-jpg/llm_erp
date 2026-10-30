from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError

from backend.app import llm, text2sql
from backend.app.agent import prompts

GOOD_SQL = 'SELECT "客戶名稱" FROM "v_銷售明細" GROUP BY 1'


class FakeOrig(Exception):
    def __init__(self, msg, sqlstate=None):
        super().__init__(msg)
        self.sqlstate = sqlstate


def db_error(msg, sqlstate="42703"):
    return DBAPIError("stmt", {}, FakeOrig(msg, sqlstate))


@pytest.fixture
def flow(monkeypatch):
    """假的 LLM 與資料庫：outputs 依序是 chat_json 的回傳（或要丟的例外）；回傳 (calls, executed)。"""
    calls, executed = [], []

    def setup(outputs, exec_results=None):
        outs, results = iter(outputs), iter(exec_results or [(["客戶名稱"], [["甲"], ["乙"]])])

        def fake_chat_json(messages, schema_hint, max_tokens=1024):
            calls.append([dict(m) for m in messages])
            o = next(outs)
            if isinstance(o, Exception):
                raise o
            return o

        def fake_execute(sql):
            executed.append(sql)
            r = next(results)
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(llm, "chat_json", fake_chat_json)
        monkeypatch.setattr(text2sql, "_execute", fake_execute)
        monkeypatch.setattr(text2sql, "pick_examples", lambda q, k=4, examples=None: [])
        return calls, executed

    return setup


# ---------- run()：成功與重試 ----------
def test_success_on_first_attempt_returns_guarded_sql(flow):
    calls, executed = flow([{"sql": GOOD_SQL, "explanation": "各客戶"}])
    ans = text2sql.run("有哪些客戶？")
    assert ans.error is None and ans.attempts == 1
    assert ans.columns == ["客戶名稱"] and ans.rows == [["甲"], ["乙"]] and ans.row_count == 2
    assert ans.explanation == "各客戶"
    assert executed[0].endswith("LIMIT 200") and ans.sql == executed[0]  # 執行的是守門員改寫後的 SQL
    assert calls[0][0]["role"] == "system" and calls[0][-1] == {"role": "user", "content": "有哪些客戶？"}


def test_guard_rejection_is_fed_back_and_retried(flow):
    calls, executed = flow([
        {"sql": "DELETE FROM erp.customers", "explanation": "x"},
        {"sql": GOOD_SQL, "explanation": "改好了"},
    ])
    ans = text2sql.run("刪掉客戶")
    assert ans.error is None and ans.attempts == 2 and len(executed) == 1
    feedback = calls[1][-1]["content"]
    assert calls[1][-1]["role"] == "user" and "安全檢查" in feedback and "只允許 SELECT" in feedback
    assert calls[1][-2]["role"] == "assistant"


def test_db_error_is_fed_back_and_retried(flow):
    calls, executed = flow(
        [{"sql": GOOD_SQL, "explanation": ""}, {"sql": GOOD_SQL, "explanation": ""}],
        [db_error('column "客戶" does not exist'), (["客戶名稱"], [["甲"]])],
    )
    ans = text2sql.run("q")
    assert ans.error is None and ans.attempts == 2 and len(executed) == 2
    assert "執行失敗" in calls[1][-1]["content"] and "does not exist" in calls[1][-1]["content"]


def test_gives_up_after_max_attempts(flow):
    bad = {"sql": "drop table x", "explanation": ""}
    calls, executed = flow([bad] * 5)
    ans = text2sql.run("q")
    assert ans.attempts == text2sql.MAX_ATTEMPTS == 3 and len(calls) == 3 and not executed
    assert ans.error and "3 次" in ans.error and ans.rows == []


def test_missing_sql_field_is_retried(flow):
    _, executed = flow([{"explanation": "忘了寫 sql"}, {"sql": GOOD_SQL}])
    ans = text2sql.run("q")
    assert ans.error is None and ans.attempts == 2 and len(executed) == 1


# ---------- run()：不會重試的情況 ----------
def test_empty_sql_means_cannot_answer(flow):
    _, executed = flow([{"sql": "", "explanation": "資料庫沒有員工薪資"}])
    ans = text2sql.run("員工薪水多少？")
    assert ans.attempts == 1 and not executed
    assert "無法" in ans.error and "薪資" in ans.error


def test_llm_error_returned_not_raised(flow):
    flow([llm.LLMError("無法連線 LM Studio")])
    ans = text2sql.run("q")
    assert ans.error == "無法連線 LM Studio" and ans.attempts == 1


def test_database_connection_error_is_not_retried(flow):
    calls, _ = flow([{"sql": GOOD_SQL}] * 3, [db_error("connection refused", sqlstate=None)])
    ans = text2sql.run("q")
    assert ans.attempts == 1 and len(calls) == 1 and "無法連線資料庫" in ans.error


def test_example_lookup_failure_does_not_break_query(flow, monkeypatch):
    flow([{"sql": GOOD_SQL}])

    def boom(q, k=4, examples=None):
        raise RuntimeError("app.sql_examples 不存在")

    monkeypatch.setattr(text2sql, "pick_examples", boom)
    assert text2sql.run("q").error is None


def test_rows_are_truncated_but_row_count_is_total(flow):
    big = [[i] for i in range(350)]
    flow([{"sql": GOOD_SQL}], [(["n"], big)])
    ans = text2sql.run("q")
    assert ans.row_count == 350 and len(ans.rows) == 200 == text2sql.MAX_ROWS


# ---------- 輔助函式 ----------
def test_jsonable_conversions():
    assert text2sql._jsonable(Decimal("12.00")) == 12 and isinstance(text2sql._jsonable(Decimal("12.00")), int)
    assert text2sql._jsonable(Decimal("12.5")) == 12.5
    assert text2sql._jsonable(date(2026, 10, 30)) == "2026-10-30"
    assert text2sql._jsonable(datetime(2026, 10, 30, 8, 5)) == "2026-10-30T08:05:00"
    assert text2sql._jsonable(None) is None and text2sql._jsonable("字") == "字"


@pytest.mark.parametrize(("src", "expected"), [
    ("select '12:30', x::int", "select '12:30', x::int"),  # 一般冒號與 :: 不動
    ("select ':a'", "select '\\:a'"),  # 看起來像綁定參數的才跳脫
    ("select 'a:b'", "select 'a:b'"),
])
def test_escape_colons(src, expected):
    assert text2sql._escape_colons(src) == expected


# ---------- prompt ----------
def test_system_prompt_contains_date_rules_schema_and_examples():
    ex = [text2sql.Example("今年營收最高的客戶", "SELECT 1 FROM \"v_銷售明細\"", [], None)]
    p = prompts.build_sql_system(ex, today=date(2026, 10, 30))
    assert "2026-10-30" in p and "星期五" in p
    assert "CURRENT_DATE" in p and "v_銷售明細" in p and "逾期天數" in p  # 規則 + schema_doc
    assert "今年營收最高的客戶" in p and "範例 1" in p
    assert '"sql"' in p  # 輸出格式說明
    assert "範例" not in prompts.build_sql_system([], today=date(2026, 10, 30)).split("# 資料庫說明")[0]


# ---------- 真實資料庫 ----------
@pytest.mark.db
def test_real_execute_handles_colons_percent_and_types():
    cols, rows = text2sql._execute(
        """SELECT '12:30' AS t, 'a:b' AS u, ':x' AS v, "料號", "現有庫存", "最後異動日"
           FROM "v_庫存狀況" WHERE "品名" LIKE '%軸承%' ORDER BY 4 LIMIT 2""")
    assert cols[:3] == ["t", "u", "v"]
    assert rows[0][:3] == ["12:30", "a:b", ":x"] and isinstance(rows[0][4], int)
    assert rows[0][5] is None or isinstance(rows[0][5], str)


@pytest.mark.db
def test_real_execute_is_readonly():
    with pytest.raises(DBAPIError):
        text2sql._execute("DELETE FROM erp.customers")


# ---------- 真實 LLM + 資料庫（建議先 make load-examples）----------
@pytest.mark.llm
@pytest.mark.db
def test_real_top_customers():
    ans = text2sql.run("今年營收最高的 3 個客戶")
    assert ans.error is None, ans.error
    assert ans.row_count == 3 and ans.rows


@pytest.mark.llm
@pytest.mark.db
def test_real_overdue_over_60_days():
    ans = text2sql.run("目前逾期超過 60 天的應收有哪些客戶")
    assert ans.error is None, ans.error
    assert "台陽科技" in json_text(ans)


@pytest.mark.llm
@pytest.mark.db
def test_real_dead_stock_includes_story_sku():
    ans = text2sql.run("哪些料號超過 180 天沒異動？")
    assert ans.error is None, ans.error
    assert "BRG-6205-2RS" in json_text(ans)


@pytest.mark.llm
@pytest.mark.db
def test_real_unanswerable_question_is_declined_not_guessed():
    ans = text2sql.run("我們員工的平均薪水是多少？")
    assert ans.error and not ans.rows


def json_text(ans) -> str:
    return str(ans.rows)
