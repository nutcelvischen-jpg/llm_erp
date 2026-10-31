from datetime import date

import pytest

from backend.app.jobs import dead_stock as ds
from backend.app.llm import ChatResult


def report():
    dead = [{"料號": "CUS-008", "品名": "客製件 008", "現有庫存": 1080, "庫存金額": 2044440.0, "未異動天數": 222},
            {"料號": "BRG-6205-2RS", "品名": "深溝球軸承", "現有庫存": 1164, "庫存金額": 64730.0, "未異動天數": 202}]
    short = [{"料號": "GEAR-M2-40T", "品名": "正齒輪", "現有庫存": 349, "在途數量": 0, "待出貨數量": 998,
              "安全庫存": 113, "缺口": 649, "建議採購量": 762, "供應商": "精密熱處理", "供應商交期天數": 28}]
    return ds.Report(date(2026, 10, 31), dead, short)


def chat_returning(text):
    calls = []

    def f(msgs):
        calls.append(msgs)
        return ChatResult(text, 1, 1, 1)

    f.calls = calls
    return f


def test_facts_and_fixed_summary():
    rep = report()
    assert rep.dead_total == 2109170.0
    f = ds.facts_text(rep)
    assert "庫存金額合計：210.9 萬元" in f and "GEAR-M2-40T 正齒輪，缺口 649，建議採購 762" in f
    s = ds.fixed_summary(rep)
    assert s.startswith("【庫存預警 10/31】") and "2 項，壓 210.9 萬元" in s and "GEAR-M2-40T 建議採購 762" in s
    assert len(s) <= ds.SUMMARY_MAX


def test_fixed_summary_empty_and_many():
    empty = ds.Report(date(2026, 10, 31))
    assert "無呆滯料號" in ds.fixed_summary(empty) and "無缺料" in ds.fixed_summary(empty)
    assert ds.compose(ds.fixed_summary(empty), empty) == ds.fixed_summary(empty)
    many = report()
    many.shortage = [dict(many.shortage[0], 料號=f"P{i}") for i in range(6)]
    assert "等 6 項" in ds.fixed_summary(many)


def test_details_list_every_sku():
    d = ds.details_text(report())
    assert "呆滯料號（2）：CUS-008、BRG-6205-2RS" in d
    assert "GEAR-M2-40T 缺 649，建議採購 762（精密熱處理，交期 28 天）" in d


def test_llm_summary_accepted():
    chat = chat_returning("呆滯 2 項合計 210.9 萬元，最高 CUS-008 204.4 萬元。缺料 GEAR-M2-40T 建議採購 762。")
    s, src = ds.summarize(report(), chat)
    assert src == "llm" and s.startswith("【庫存預警 10/31】呆滯 2 項")
    assert "GEAR-M2-40T" in chat.calls[0][1]["content"]


@pytest.mark.parametrize("text", [
    "呆滯 2 項合計 300 萬元。缺料 GEAR-M2-40T 建議採購 762。",   # 編造數字
    "呆滯 2 項合計 210.9 萬元。",                                # 漏了缺料料號
    "缺料 GEAR-M2-40T 建議採購 762。" + "呆滯" * 80,             # 太長
    "",
])
def test_bad_llm_summary_falls_back(text):
    s, src = ds.summarize(report(), chat_returning(text))
    assert src == "fixed" and s == ds.fixed_summary(report())


def test_llm_error_falls_back():
    def boom(_):
        raise RuntimeError("down")

    assert ds.summarize(report(), boom)[1] == "fixed"


def test_run_dry_and_save():
    saved = []
    chat = chat_returning("bad 999")
    msg = ds.run(True, report=report(), chat=chat, save=lambda m, c: saved.append(m) or 1)
    assert saved == [] and "BRG-6205-2RS" in msg and "GEAR-M2-40T" in msg
    msg2 = ds.run(False, report=report(), chat=chat, save=lambda m, c: saved.append((m, c)) or 1)
    assert saved == [(msg2, ds._channel())]


# ---------- 真實資料庫 + LLM ----------
@pytest.mark.llm
@pytest.mark.db
def test_real_message_contains_key_skus():
    msg = ds.run(dry_run=True)
    print("\n" + msg)
    assert "BRG-6205-2RS" in msg and "GEAR-M2-40T" in msg
    assert len(msg.split("\n\n")[0]) <= ds.SUMMARY_MAX
