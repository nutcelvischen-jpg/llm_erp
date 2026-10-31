"""T22 意圖路由：問題 → sql / docs / both / chat，並依對話脈絡改寫成獨立問題。

LLM 判斷之外有關鍵字保底：含文件詞 → 至少 docs；含數字詞 → 至少 sql；兩者都有 → both。
LLM 結果與規則取聯集（sql + docs = both；有其他類別時 chat 讓位）。LLM 失敗時只用規則。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from . import prompts

log = logging.getLogger(__name__)

Kind = Literal["sql", "docs", "both", "chat"]
KINDS = ("sql", "docs", "both", "chat")
DOC_WORDS = ("合約", "SOP", "規定", "辦法", "條款", "規格")
SQL_WORDS = ("多少", "幾", "排名", "金額", "庫存", "逾期", "營收")
MAX_TURNS = 6
MAX_TURN_CHARS = 300


@dataclass
class Route:
    kind: Kind
    rewritten: str
    source: str = "llm"  # llm / rules / llm+rules


def rule_kinds(text: str) -> set[str]:
    t = (text or "").upper()
    out = set()
    if any(w.upper() in t for w in DOC_WORDS):
        out.add("docs")
    if any(w in t for w in SQL_WORDS):
        out.add("sql")
    return out


def merge(kinds: set[str]) -> Kind:
    if "both" in kinds or {"sql", "docs"} <= kinds:
        return "both"
    for k in ("sql", "docs"):
        if k in kinds:
            return k
    return "chat"


def format_history(history: list[dict] | None) -> str:
    turns = [h for h in (history or []) if h.get("role") in ("user", "assistant") and h.get("content")]
    turns = turns[-MAX_TURNS * 2:]
    lines = []
    for h in turns:
        who = "使用者" if h["role"] == "user" else "助理"
        c = str(h["content"]).strip().replace("\n", " ")
        lines.append(f"{who}：{c[:MAX_TURN_CHARS]}")
    return "\n".join(lines)


def build_messages(question: str, history: list[dict] | None) -> list[dict]:
    hist = format_history(history)
    user = f"前文：\n{hist}\n\n最新一句話：{question}" if hist else f"前文：（無）\n\n最新一句話：{question}"
    return [{"role": "system", "content": prompts.ROUTER_SYSTEM}, {"role": "user", "content": user}]


def _default_chat_json(messages: list[dict]) -> dict:
    from .. import llm

    return llm.chat_json(messages, prompts.ROUTER_JSON_HINT, max_tokens=300)


def route(question: str, history: list[dict] | None = None, *, chat_json: Callable | None = None) -> Route:
    question = question.strip()
    chat_json = chat_json or _default_chat_json
    try:
        out = chat_json(build_messages(question, history))
    except Exception as e:  # noqa: BLE001 — LLM 失敗時退回關鍵字規則
        log.warning("路由 LLM 失敗，改用關鍵字規則：%s", e)
        return Route(merge(rule_kinds(question)), question, "rules")
    kind = str(out.get("kind", "")).strip().lower()
    rewritten = str(out.get("rewritten") or "").strip() or question
    if kind not in KINDS:
        log.warning("路由 LLM 回傳不合法的 kind=%r，改用關鍵字規則", kind)
        return Route(merge(rule_kinds(question) | rule_kinds(rewritten)), rewritten, "rules")
    rules = rule_kinds(question) | rule_kinds(rewritten)
    final = merge({kind} | rules)
    return Route(final, rewritten, "llm" if final == kind else "llm+rules")
