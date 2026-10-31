from types import SimpleNamespace

import pytest

from backend.app import eval_checks as ec


def ans(rows=None, error=None, total=None):
    rows = rows or []
    return SimpleNamespace(rows=rows, error=error, row_count=len(rows) if total is None else total)


# ---------- 數字容差 ----------
@pytest.mark.parametrize(("a", "b", "ok"), [
    # 參考值是整數：只容許四捨五入誤差
    (11979390, 11979390, True), (11979390.4, 11979390, True), (11979391, 11979390, False),
    (11979392, 11979390, False), (3, 3, True), (4, 3, False), (3.4, 3, True), (0.5, 0.0, True), (0.7, 0.0, False),
    (-935593, -935593.0, True), (-935000, -935593, False),
    # 參考值有小數：答案若四捨五入成整數容許 ±0.55；答案也帶小數則只容許 ±0.055
    (25.6, 25.6, True), (25.58, 25.6, True), (25.65, 25.6, True), (26, 25.6, True),
    (25.0, 25.6, False), (25.5, 25.6, False), (25.9, 25.6, False), (24.9, 25.6, False),
])
def test_approx_equal(a, b, ok):
    assert ec.approx_equal(a, b) is ok


def test_cell_matches_types():
    assert ec.cell_matches("鴻遠機械", " 鴻遠機械 ") and not ec.cell_matches("鴻遠機械", "華發實業")
    assert ec.cell_matches(None, None) and not ec.cell_matches(None, 0) and not ec.cell_matches(0, None)
    assert ec.cell_matches("2026-10-12", "2026-10-12") and not ec.cell_matches("2026-10-12", "2026-10-13")
    assert not ec.cell_matches(1, True)  # 布林不當數字
    assert not ec.cell_matches(5, "5")  # 型別不同不算相等（避免誤判）


# ---------- rows_match ----------
REF = [["華發實業", 11979390], ["鴻遠機械", 9869353], ["億達企業", 3783773]]


def test_rows_match_allows_extra_columns_and_any_order():
    shuffled = [["億達企業", 3783773, 12], ["華發實業", 11979390, 99], ["鴻遠機械", 9869353, 50]]
    assert ec.rows_match(REF, shuffled, 3) == (True, "")


def test_rows_match_detects_wrong_value_or_missing_row():
    wrong = [["華發實業", 11979390], ["鴻遠機械", 1], ["億達企業", 3783773]]
    ok, why = ec.rows_match(REF, wrong, 3)
    assert not ok and "鴻遠機械" in why
    ok, why = ec.rows_match(REF, REF[:2], 2)
    assert not ok and "列數不符" in why


def test_rows_match_uses_total_not_truncated_rows():
    ok, why = ec.rows_match(REF, REF, ans_total=300)  # 回傳被截斷到 200 列，但實際有 300 列
    assert not ok and "300" in why


def test_rows_match_any_count_allows_more_rows():
    extra = REF + [["其他公司", 5]]
    assert not ec.rows_match(REF, extra, 4)[0]
    assert ec.rows_match(REF, extra, 4, same_count=False)[0]


def test_rows_match_does_not_reuse_one_answer_row_for_two_refs():
    ref = [["甲", 10], ["甲", 10]]
    assert not ec.rows_match(ref, [["甲", 10]], 1, same_count=False)[0]


def test_rows_match_empty_reference_is_a_bad_golden_question():
    ok, why = ec.rows_match([], [["x"]], 1)
    assert not ok and "黃金題" in why


# ---------- contains ----------
def test_contains_values():
    rows = [["台陽科技", 3, 100759], ["精興金屬", 1, 60828]]
    assert ec.contains_values(["台陽科技", "精興金屬"], rows)[0]
    ok, why = ec.contains_values(["台陽科技", "不存在"], rows)
    assert not ok and "不存在" in why


# ---------- evaluate ----------
def test_refusal_passes_on_error_without_rows():
    assert ec.evaluate({"refusal": True}, ans(error="這個問題無法用目前的 ERP 資料回答：…"))[0]
    assert ec.evaluate({"refusal": True}, ans(error="嘗試 3 次仍無法產生可執行的 SQL：只允許 SELECT"))[0]  # 寫入指令被守門員擋下


def test_refusal_fails_when_data_returned_or_no_error():
    ok, why = ec.evaluate({"refusal": True}, ans(rows=[[1]]))
    assert not ok and "回傳了資料" in why
    ok, why = ec.evaluate({"refusal": True}, ans())
    assert not ok and "沒有產生任何錯誤" in why


def test_error_fails_normal_checks():
    ok, why = ec.evaluate({"row_count_gt": 0}, ans(error="LM Studio 沒開"))
    assert not ok and "查詢失敗" in why


def test_row_count_checks():
    assert ec.evaluate({"row_count": 3}, ans(rows=[[1]] * 3))[0]
    assert not ec.evaluate({"row_count": 3}, ans(rows=[[1]] * 2))[0]
    assert ec.evaluate({"row_count_gt": 0}, ans(rows=[[1]]))[0]
    assert not ec.evaluate({"row_count_gt": 0}, ans())[0]


def test_evaluate_rows_match_with_reference_and_any_count():
    assert ec.evaluate({"rows_match": "x"}, ans(rows=REF), ref_rows=REF)[0]
    assert not ec.evaluate({"rows_match": "x"}, ans(rows=REF + [["多"]]), ref_rows=REF)[0]
    assert ec.evaluate({"rows_match": "x", "any_count": True}, ans(rows=REF + [["多"]]), ref_rows=REF)[0]


def test_evaluate_contains():
    assert ec.evaluate({"contains": ["甲"]}, ans(rows=[["甲"]]))[0]
    assert not ec.evaluate({"contains": ["乙"]}, ans(rows=[["甲"]]))[0]


# ---------- RAG ----------
from backend.app.eval_checks import normalize_text, rag_contains, rag_refused  # noqa: E402


def test_normalize_text_layout_only():
    assert normalize_text("月結 30 天") == normalize_text("月結30天")
    assert normalize_text("HRC 58–62") == normalize_text("HRC 58-62") == normalize_text("HRC 58～62")
    assert normalize_text("新臺幣 5,000,000 元") == normalize_text("新台幣5,000,000元")
    assert normalize_text("M8 × 1.25") == normalize_text("M8x1.25")
    assert normalize_text("０．３％") == normalize_text("0.3%")
    assert normalize_text("⼩時") == "小時"


def test_rag_contains_is_strict_on_values():
    assert rag_contains("- 每逾一日 0.3%，上限 10% [來源 1]", ["0.3%", "10%"]) == (True, "")
    ok, why = rag_contains("每逾一日 0.35%", ["0.3%", "10%"])
    assert not ok and "10%" in why
    assert not rag_contains("新臺幣 500,000 元", ["新臺幣 5,000,000 元"])[0]
    assert not rag_contains("月結 3 天", ["月結 30 天"])[0]


def test_rag_refused():
    assert rag_refused("依現有文件查無相關資料。")
    assert not rag_refused("年終獎金 2 個月")
    assert not rag_refused(None)
