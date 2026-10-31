"""T14e 結果回覆：LLM 看「既定程式」的結果與程式算出的 facts 寫 2–3 句結論，不可編造數字。

數字檢查 numbers_supported()：回覆中的每個數字都必須出現在查詢結果、facts 或查詢條件（期間、筆數…）中，
容許千分位、依回覆的小數位數四捨五入、萬／億換算；名次序數不得超過結果列數或筆數。
檢查不過或 LLM 失敗 → 改用模板的固定句型 summary()，source="fixed"。絕不顯示未經檢查的數字。
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from numbers import Number
from typing import Literal

from ..numcheck import extract_numbers
from .base import QueryTemplate
from .templates.common import fmt

log = logging.getLogger(__name__)

TABLE_ROWS = 20


@dataclass
class AnswerText:
    text: str
    source: Literal["llm", "fixed"]
    unsupported: list[str] | None = None


SYSTEM = """你是公司 ERP 助理。系統已用「既定查詢程式」查好資料，請根據查詢結果與「程式算出的事實」用 2–3 句話回答使用者。

規則：
1. 繁體中文（台灣用語），第一句直接給結論。
2. 只能使用「事實」與「查詢結果」中出現的數字，照原樣引用（金額加千分位），不可自己計算、加總、換算或四捨五入。
3. 每個數字要取自正確的欄位（例如問建議採購量，就只能引用「建議採購量=」後面的值）。
4. 結果超過 3 列時，只點名最重要的前 3 項，其餘說「詳見表格」。
5. 不推測原因，不提 SQL、資料表或程式名稱。
"""


def _num_values(values: Iterable) -> list[float]:
    out: list[float] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, Number):
            out.append(float(v))
        elif isinstance(v, str):
            out += [x for x, _, _ in extract_numbers(v)]
    return out


def numbers_supported(text: str, rows: list[list], facts: dict, context: Iterable[str] = (),
                      max_rank: int = 0) -> tuple[bool, list[str]]:
    """回傳（是否全部有依據, 沒有依據的數字原文）。context：查詢條件文字（期間說明、筆數…）。"""
    allowed = _num_values(c for r in rows for c in r) + _num_values(facts.values()) + _num_values(context)
    max_rank = max(max_rank, len(rows))
    bad = []
    for v, dec, raw in extract_numbers(text):
        if v.is_integer() and 1 <= v <= max_rank and "萬" not in raw and "億" not in raw:
            continue  # 名次、筆數
        scale = 1e8 if "億" in raw else 1e4 if "萬" in raw else 1.0
        tol = 0.5 * scale * 10 ** (-dec) + 1e-9
        if not any(abs(abs(a) - v) <= tol for a in allowed):  # 負數以絕對值比對（回覆用「減少」表達方向）
            bad.append(raw)
    return not bad, bad


def _row_text(columns: list[str], rows: list[list]) -> str:
    return "\n".join(f"第 {i} 列：" + "；".join(f"{c}={'-' if v is None else v}" for c, v in zip(columns, r))
                     for i, r in enumerate(rows[:TABLE_ROWS], 1))


def facts_text(facts: dict) -> str:
    """數值連同預先格式化的字串一起給 LLM（LLM 不做任何運算）。"""
    lines = []
    for k, v in facts.items():
        if isinstance(v, int | float) and not isinstance(v, bool):
            # 「第一名數值」這類 key 看不出單位，改用 facts 裡的指標欄位名決定格式
            unit = facts.get("指標", k) if k.endswith("數值") else k
            lines.append(f"- {k}：{v}（格式化：{fmt(unit, v)}）")
        elif v is not None:
            lines.append(f"- {k}：{v}")
    return "\n".join(lines)


def build_messages(question: str, template: QueryTemplate, params_readable: list[str], columns: list[str],
                   rows: list[list], facts: dict) -> list[dict]:
    user = (f"問題：{question}\n\n# 查詢說明\n{template.title}：{template.description}\n"
            f"條件：{'；'.join(params_readable) or '無'}\n\n"
            f"# 程式算出的事實\n{facts_text(facts) or '（無）'}\n\n"
            f"# 查詢結果（共 {len(rows)} 列，以下最多 {TABLE_ROWS} 列）\n{_row_text(columns, rows) or '（沒有資料）'}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _default_chat(messages: list[dict]):
    from .. import llm

    return llm.chat(messages, temperature=0.1, max_tokens=400)


def summarize(question: str, template: QueryTemplate, params_readable: list[str], columns: list[str],
              rows: list[list], facts: dict, *, top_n: int = 0, chat: Callable | None = None) -> AnswerText:
    fixed = template.summary(facts)
    if not rows:
        return AnswerText(fixed, "fixed")
    try:
        r = (chat or _default_chat)(build_messages(question, template, params_readable, columns, rows, facts))
        text = (r.text or "").strip()
    except Exception as e:  # noqa: BLE001 — LLM 失敗就用固定句型
        log.warning("結果回覆 LLM 失敗，改用固定句型：%s", e)
        return AnswerText(fixed, "fixed")
    if not text:
        return AnswerText(fixed, "fixed")
    ok, bad = numbers_supported(text, rows, facts, params_readable, top_n)
    if not ok:
        log.warning("結果回覆含未獲支持的數字 %s，改用固定句型：%r", bad, text)
        return AnswerText(fixed, "fixed", bad)
    return AnswerText(text, "llm")
