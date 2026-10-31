"""T14d 意圖辨識（假的 embedding／LLM／名單）。"""
from datetime import date

import pytest

from backend.app.catalog import intent as I
from backend.app.catalog.entities import EntityIndex
from backend.app.catalog.registry import TEMPLATES

TODAY = date(2026, 10, 31)
ENT = EntityIndex({"customer": lambda: ["華發實業", "華發精密", "鴻遠機械", "台陽科技"],
                   "sku": lambda: ["BRG-6205-2RS", "GEAR-M2-40T"], "rep": lambda: ["王小明"],
                   "supplier": lambda: ["大成鋼鐵"]})


class FakeExamples:
    def __init__(self, top):
        self._top = top

    def top(self, q, k=5):
        return self._top[:k]


def deps(llm_out=None, top=None, exc=None):
    logged, calls = [], []

    def chat_json(msgs):
        calls.append(msgs)
        if exc:
            raise exc
        return llm_out

    d = I.Deps(embed=lambda t: [[0.0]], chat_json=chat_json, entities=ENT,
               log_unmatched=lambda q, k, c: logged.append((q, k, c)),
               examples=FakeExamples(top or [("sales_rank", 0.8), ("sales_total", 0.6), ("sales_compare", 0.5)]))
    return d, logged, calls


def rec(q, **kw):
    d, logged, calls = deps(**kw)
    return I.recognize(q, TODAY, d), logged, calls


# ---------- 候選與門檻 ----------
def test_low_similarity_skips_llm():
    it, logged, calls = rec("明天天氣", top=[("sales_rank", 0.2)])
    assert it.kind == "no_match" and calls == [] and logged[0][1] == "no_match"


def test_candidates_sorted_and_in_prompt():
    it, _, calls = rec("今年營收前五名客戶", llm_out={"status": "match", "template_id": "sales_rank",
                                                  "params": {"dimension": "客戶", "top_n": 5}})
    assert [c["template_id"] for c in it.candidates] == ["sales_rank", "sales_total", "sales_compare"]
    prompt = calls[0][0]["content"]
    assert "id: sales_rank" in prompt and "id: stock_dead" not in prompt and "2026-10-31" in prompt


def test_example_index_ranks_by_max_similarity():
    vec = {"a": [1, 0], "b": [0, 1], "q": [0.9, 0.1]}
    templates = {"x": TEMPLATES["sales_rank"], "y": TEMPLATES["ar_aging"]}
    idx = I.ExampleIndex(lambda ts: [vec["a"] if "營收" in t else vec["q"] if t == "Q" else vec["b"] for t in ts],
                         templates)
    top = idx.top("Q")
    assert top[0][0] == "sales_rank" and top[0][1] > top[1][1]


# ---------- match ----------
def test_match_with_synonyms_and_clamp():
    it, _, _ = rec("q", llm_out={"status": "match", "template_id": "sales_rank",
                                 "params": {"dimension": "顧客", "metric": "業績", "top_n": 999, "order": "最高",
                                            "period": "last_year", "bogus": "x"}})
    assert it.kind == "template" and it.template_id == "sales_rank"
    p = it.params
    assert (p["dimension"], p["metric"], p["top_n"], p["order"], p["period"]) == ("客戶", "營收", 50, "desc", "last_year")
    assert "bogus" not in p
    assert it.params_readable == ["排名對象：客戶", "指標：營收", "期間：2025 年（去年）", "筆數：50", "排序：由高到低"]


def test_unsupported_param_value_goes_to_confirm_not_execute():
    it, logged, _ = rec("各業務員毛利率跟去年比", top=[("sales_compare", 0.8)], llm_out={
        "status": "match", "template_id": "sales_compare", "params": {"metric": "毛利率", "dimension": "業務"}})
    assert it.kind == "confirm" and len(it.proposals) == 1
    p = it.proposals[0]
    assert p.template_id == "sales_compare" and p.params["metric"] == "營收"
    assert p.notes == ["指標不支援「毛利率」，改用「營收」"] and logged[0][1] == "confirm"


def test_unrecognized_period_goes_to_confirm():
    it, _, _ = rec("q", llm_out={"status": "match", "template_id": "sales_rank",
                                 "params": {"period": "2026-01-01~2026-03-31"}})
    assert it.kind == "confirm" and "期間「2026-01-01~2026-03-31」無法辨識，改用「2026 年（今年）」" in it.proposals[0].notes


def test_omitted_params_use_defaults_and_execute():
    it, _, _ = rec("q", llm_out={"status": "match", "template_id": "sales_rank", "params": {}})
    assert it.kind == "template" and it.params["metric"] == "營收" and it.notes == []


def test_template_not_in_candidates_is_not_executed():
    it, logged, _ = rec("q", llm_out={"status": "match", "template_id": "stock_dead", "params": {}})
    assert it.kind == "no_match" and logged


# ---------- entity ----------
def test_entity_fuzzy_replaced_with_note():
    it, _, _ = rec("q", top=[("sales_total", 0.8)],
                   llm_out={"status": "match", "template_id": "sales_total", "params": {"customer": "鴻遠"}})
    assert it.kind == "template" and it.params["customer"] == "鴻遠機械"
    assert "已將「鴻遠」視為「鴻遠機械」" in it.notes and "客戶：鴻遠機械" in it.params_readable


def test_entity_ambiguous_clarifies_with_options():
    it, _, _ = rec("q", top=[("sales_total", 0.8)],
                   llm_out={"status": "match", "template_id": "sales_total", "params": {"customer": "華發"}})
    assert it.kind == "clarify" and set(it.options) == {"華發實業", "華發精密"} and "華發" in it.message


def test_entity_not_found_clarifies():
    it, _, _ = rec("q", top=[("sales_total", 0.8)],
                   llm_out={"status": "match", "template_id": "sales_total", "params": {"customer": "大同電子"}})
    assert it.kind == "clarify" and "找不到客戶「大同電子」" in it.message


def test_missing_required_param_clarifies():
    it, _, _ = rec("q", top=[("stock_lookup", 0.8)],
                   llm_out={"status": "match", "template_id": "stock_lookup", "params": {}})
    assert it.kind == "clarify" and it.message == "請問要查哪個料號？"


# ---------- confirm（沒有明確命中） ----------
def test_unsure_lists_closest_programs():
    it, logged, _ = rec("今年哪個客戶最賺", llm_out={
        "status": "unsure", "template_id": None,
        "alternatives": [{"template_id": "sales_rank", "params": {"dimension": "客戶", "metric": "毛利"}},
                         {"template_id": "sales_compare", "params": {"dimension": "客戶"}},
                         {"template_id": "sales_rank", "params": {}},          # 重複
                         {"template_id": "stock_dead", "params": {}}]})        # 不在候選
    assert it.kind == "confirm" and it.message == I.CONFIRM_MSG
    assert [p.template_id for p in it.proposals] == ["sales_rank", "sales_compare"]
    p = it.proposals[0]
    assert p.title == "銷售排名" and "指標：毛利" in p.params_readable and p.columns == ["客戶名稱", "毛利"]
    assert logged[0][1] == "confirm" and logged[0][2][0]["template_id"] == "sales_rank"


def test_unsure_proposals_needing_clarification_are_dropped():
    it, logged, _ = rec("q", top=[("ar_invoices", 0.7)], llm_out={
        "status": "unsure", "alternatives": [{"template_id": "ar_invoices", "params": {}}]})
    assert it.kind == "no_match" and logged[0][1] == "no_match"


def test_unsupported_and_llm_failure():
    it, logged, _ = rec("員工薪資", llm_out={"status": "unsupported", "template_id": None})
    assert it.kind == "no_match" and it.proposals == [] and logged
    it, _, _ = rec("q", exc=RuntimeError("down"))
    assert it.kind == "no_match" and "AI 暫時無法使用" in it.message


def test_confirm_revalidates_client_params():
    it = I.confirm("sales_rank", {"dimension": "客戶", "top_n": "100", "order": "desc; DROP", "_today": "x"},
                   TODAY, ENT)
    assert it.kind == "template" and it.params["top_n"] == 50 and it.params["order"] == "desc"
    assert it.params["_today"] == TODAY
    assert I.confirm("no_such", {}, TODAY, ENT).kind == "no_match"
    assert I.confirm("ar_invoices", {}, TODAY, ENT).kind == "clarify"


def test_overdue_readable():
    t = TEMPLATES["ar_summary"]
    assert I.readable(t, {"customer": "台陽科技", "overdue_gt": 0}, TODAY) == ["客戶：台陽科技", "已逾期"]
    assert I.readable(t, {"overdue_gt": 60}, TODAY) == ["逾期超過 60 天"]


def test_data_part_only_adds_note_to_prompt():
    _, _, calls = rec("q", llm_out={"status": "unsupported"})
    assert "文件系統另外回答" not in calls[0][0]["content"]
    d, _, calls = deps(llm_out={"status": "unsupported"})
    I.recognize("台陽逾期多少？依合約多久可暫停出貨？", TODAY, d, data_part_only=True)
    assert "文件系統另外回答" in calls[0][0]["content"]


def test_catalog_prompt_lists_param_specs():
    text = I.format_catalog(["sales_rank", "stock_lookup"])
    assert "dimension（排名對象，標準值：客戶／產品／料號／產品類別／業務／區域，預設 客戶）" in text
    assert "sku（料號，料號名稱（照原話），必填）" in text
    assert "結果欄位（預設參數）：客戶名稱、營收" in text


# ---------- 真實 LLM＋資料庫（意圖黃金集的子集；完整 40 題用 make eval-intent）----------
REAL = [("今年到目前為止，業績貢獻最大的五家客戶是哪些？", "template", "sales_rank"),
        ("鴻遠機械已經過了付款期限還沒付的帳款有多少？", "template", "ar_summary"),
        ("GEAR-M2-40T 現在倉庫裡有多少？", "template", "stock_lookup"),
        ("業務部門的平均月薪是多少？", "no_match", None),
        ("鴻遠機械合約的付款條件是什麼？", "no_match", None)]


@pytest.mark.llm
@pytest.mark.db
@pytest.mark.parametrize("q, kind, tid", REAL)
def test_real_recognize(monkeypatch, q, kind, tid):
    monkeypatch.setattr(I, "log_unmatched", lambda *a: None)
    it = I.recognize(q)
    assert (it.kind, it.template_id) == (kind, tid), it


@pytest.mark.llm
@pytest.mark.db
def test_real_unsupported_metric_is_not_executed(monkeypatch):
    monkeypatch.setattr(I, "log_unmatched", lambda *a: None)
    it = I.recognize("各業務員今年的毛利率跟去年比")
    executed_wrong_metric = it.kind == "template" and it.params.get("metric") != "毛利率"
    assert not executed_wrong_metric and it.kind in ("confirm", "template"), it
