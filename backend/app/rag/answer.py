"""T20 RAG 回答：檢索片段 → LLM 依片段作答並標 [來源 n] → 只保留被引用的來源。"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..agent import prompts
from .retrieve import Hit

log = logging.getLogger(__name__)

NO_ANSWER = "依現有文件查無相關資料。"
FALLBACK_SOURCES = 2
SNIPPET_LEN = 120
MAX_TOKENS = 600
_PREFIX = re.compile(r"^【[^】]*】\s*")
_CITE = re.compile(r"\[來源\s*([\d\s,，、]+)\]")


@dataclass
class Source:
    file_name: str
    page: int
    heading: str
    snippet: str
    view: dict | None = None   # 原文預覽：頁面比例與外框／螢光位置（pdfview.locate），找不到為 None


@dataclass
class RagAnswer:
    text: str
    sources: list[Source] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    error: str | None = None


def body_of(hit: Hit) -> str:
    """去掉切塊時加的【檔名 › 標題】前綴。"""
    return _PREFIX.sub("", hit.text, count=1).strip()


def format_context(hits: list[Hit]) -> str:
    parts = []
    for n, h in enumerate(hits, 1):
        heading = " › ".join(h.heading_path)
        parts.append(f'<片段 {n} 檔案="{h.file_name}" 頁="{h.page}" 標題="{heading}">\n{body_of(h)}\n</片段 {n}>')
    return "\n\n".join(parts)


def build_messages(question: str, hits: list[Hit]) -> list[dict]:
    return [
        {"role": "system", "content": prompts.RAG_SYSTEM},
        {"role": "user", "content": f"{format_context(hits)}\n\n問題：{question}"},
    ]


def to_source(hit: Hit) -> Source:
    body = re.sub(r"\s+", " ", body_of(hit))
    snippet = body if len(body) <= SNIPPET_LEN else body[:SNIPPET_LEN] + "…"
    return Source(hit.file_name, hit.page, " › ".join(hit.heading_path), snippet)


def cited_numbers(text: str) -> list[int]:
    """依出現順序回傳引用的片段編號（不重複）；支援 [來源 1]、[來源 1, 2]、[來源1、3]。"""
    out: list[int] = []
    for m in _CITE.finditer(text):
        for x in re.findall(r"\d+", m.group(1)):
            n = int(x)
            if n not in out:
                out.append(n)
    return out


def is_refusal(text: str) -> bool:
    return "查無" in text


def drop_trailing_refusal(text: str) -> str:
    """模型有時答完又在最後另起一段補「查無相關資料」；已有引用時刪掉這段，避免自相矛盾。"""
    paras = text.rstrip().split("\n")
    if len(paras) > 1 and paras[-1].strip() == NO_ANSWER and cited_numbers(text):
        return "\n".join(paras[:-1]).rstrip()
    return text


def attach_sources(text: str, hits: list[Hit]) -> tuple[str, list[Source]]:
    """只保留被引用的來源，並把回答中的編號改成新來源清單的編號；不存在的編號移除。
    沒有任何引用時：拒答不附來源，否則保留前 2 筆。"""
    valid = [n for n in cited_numbers(text) if 1 <= n <= len(hits)]
    if not valid:
        text = _CITE.sub("", text).strip()
        if is_refusal(text):
            return text, []
        return text, [to_source(h) for h in hits[:FALLBACK_SOURCES]]
    renum = {old: new for new, old in enumerate(valid, 1)}

    def repl(m: re.Match) -> str:
        ns = [renum[int(x)] for x in re.findall(r"\d+", m.group(1)) if int(x) in renum]
        return "".join(f"[來源 {n}]" for n in dict.fromkeys(ns))

    return _CITE.sub(repl, text).strip(), [to_source(hits[n - 1]) for n in valid]


def _default_chat(messages: list[dict]):
    from .. import llm

    return llm.chat(messages, temperature=0.1, max_tokens=MAX_TOKENS)


def answer(question: str, hits: list[Hit], *, chat: Callable | None = None,
           locate: Callable | None = None) -> RagAnswer:
    if not hits:
        return RagAnswer(NO_ANSWER)
    chat = chat or _default_chat
    try:
        res = chat(build_messages(question, hits))
    except Exception as e:  # noqa: BLE001 — 回答失敗不能拖垮整個請求
        log.warning("RAG 回答失敗：%s", e)
        return RagAnswer(f"文件回答暫時無法產生：{e}", [to_source(h) for h in hits[:FALLBACK_SOURCES]],
                         error=str(e))
    text = drop_trailing_refusal((res.text or "").strip()) or NO_ANSWER
    text, sources = attach_sources(text, hits)
    add_views(sources, hits, text, locate)
    return RagAnswer(text, sources, res.prompt_tokens, res.completion_tokens, res.latency_ms)


def _default_locate(file_name: str, page: int, body: str, heading: str, answer_text: str) -> dict | None:
    from . import pdfview

    return pdfview.locate(file_name, page, body, heading, answer_text)


def add_views(sources: list[Source], hits: list[Hit], answer_text: str, locate: Callable | None = None) -> None:
    """替每個來源找出它在 PDF 頁面上的位置；失敗只記 log，回答照常。"""
    locate = locate or _default_locate
    by_key = {}
    for h in hits:
        by_key.setdefault((h.file_name, h.page, to_source(h).snippet), h)
    for s in sources:
        h = by_key.get((s.file_name, s.page, s.snippet))
        if not h:
            continue
        try:
            s.view = locate(h.file_name, h.page, body_of(h), h.heading_path[-1] if h.heading_path else "", answer_text)
        except Exception as e:  # noqa: BLE001
            log.warning("原文定位失敗 %s 第 %s 頁：%s", h.file_name, h.page, e)
