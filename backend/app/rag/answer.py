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


def answer(question: str, hits: list[Hit], *, chat: Callable | None = None) -> RagAnswer:
    if not hits:
        return RagAnswer(NO_ANSWER)
    chat = chat or _default_chat
    try:
        res = chat(build_messages(question, hits))
    except Exception as e:
        log.warning("RAG 回答失敗：%s", e)
        return RagAnswer(f"文件回答暫時無法產生：{e}", [to_source(h) for h in hits[:FALLBACK_SOURCES]],
                         error=str(e))
    text = (res.text or "").strip() or NO_ANSWER
    text, sources = attach_sources(text, hits)
    return RagAnswer(text, sources, res.prompt_tokens, res.completion_tokens, res.latency_ms)
