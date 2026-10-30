"""LM Studio（OpenAI 相容 API）客戶端封裝：chat / chat_json / embed。

重點：
- Qwen3.6 預設會長篇思考；每次 chat 都帶 reasoning_effort="none" 關閉（已實測有效，
  `/no_think`、`enable_thinking` 都無效）。需要思考時傳 think=True。
- 連線錯誤自動重試 2 次；逾時不重試；所有失敗統一丟 LLMError，訊息可直接顯示給使用者。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    OpenAI,
)
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from .config import settings

log = logging.getLogger(__name__)

EMBED_BATCH = 32
_client = OpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    timeout=settings.llm_timeout,
    max_retries=0,  # 重試交給 tenacity，避免重複
)
_json_mode_ok = True  # LM Studio 若不支援 response_format=json_object，第一次失敗後就不再嘗試


class LLMError(RuntimeError):
    """LLM 呼叫失敗（連線、逾時、伺服器回傳錯誤、無法解析 JSON）。"""


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def _is_retryable(e: BaseException) -> bool:
    return isinstance(e, APIConnectionError) and not isinstance(e, APITimeoutError)


_retry = retry(
    retry=retry_if_exception(_is_retryable), stop=stop_after_attempt(3), wait=wait_fixed(1), reraise=True
)


@_retry
def _create(**kwargs):
    return _client.chat.completions.create(**kwargs)


@_retry
def _embed_create(**kwargs):
    return _client.embeddings.create(**kwargs)


def _wrap(e: Exception) -> LLMError:
    if isinstance(e, APITimeoutError):
        return LLMError(f"LLM 回應逾時（>{settings.llm_timeout} 秒）")
    if isinstance(e, APIConnectionError):
        return LLMError(f"無法連線 LM Studio（{settings.llm_base_url}），請確認 Local API server 為 Running")
    if isinstance(e, APIStatusError):
        return LLMError(f"LLM 伺服器回傳錯誤 {e.status_code}：{str(e)[:200]}")
    return LLMError(f"LLM 呼叫失敗：{e}")


def strip_think(text: str) -> str:
    """移除 <think>...</think>（含未閉合、只剩結尾標籤的情況），並去除前後空白。"""
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "<think>" in text:  # 被截斷，沒有結尾
        text = text.split("<think>")[0]
    elif "</think>" in text:  # 只剩結尾標籤
        text = text.split("</think>")[-1]
    return text.strip()


def extract_json(text: str) -> dict:
    """從模型輸出中取出第一個 JSON 物件：支援 ```json 區塊、前後有說明文字、巢狀大括號。"""
    text = strip_think(text)
    candidates = [m.group(1) for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)]
    candidates.append(text)
    decoder = json.JSONDecoder()
    for cand in candidates:
        for m in re.finditer(r"\{", cand):
            try:
                obj, _ = decoder.raw_decode(cand[m.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    raise ValueError(f"找不到有效的 JSON 物件：{text[:120]!r}")


def chat(
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 1024,
    json_mode: bool = False,
    think: bool = False,
) -> ChatResult:
    global _json_mode_ok
    kwargs: dict = {
        "model": settings.llm_model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }
    if not think:
        kwargs["extra_body"] = {"reasoning_effort": "none"}
    use_json = json_mode and _json_mode_ok
    if use_json:
        kwargs["response_format"] = {"type": "json_object"}

    t0 = time.perf_counter()
    try:
        try:
            r = _create(**kwargs)
        except BadRequestError:
            if not use_json:
                raise
            log.warning("LM Studio 不支援 response_format=json_object，改用 prompt 約束 JSON")
            _json_mode_ok = False
            kwargs.pop("response_format")
            r = _create(**kwargs)
    except Exception as e:
        raise _wrap(e) from e
    ms = int((time.perf_counter() - t0) * 1000)

    choice = r.choices[0]
    text = strip_think(choice.message.content or "")
    if not text:
        log.warning("LLM 回應為空（finish_reason=%s）；若 think=True，請調高 max_tokens", choice.finish_reason)
    usage = r.usage
    return ChatResult(
        text=text,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=ms,
    )


def chat_json(messages: list[dict], schema_hint: str, max_tokens: int = 1024) -> dict:
    """要求模型只輸出 JSON；解析失敗會把錯誤回饋給模型重試 1 次，仍失敗丟 LLMError。"""
    instruction = f"只輸出一個 JSON 物件，不要任何其他文字或程式碼區塊標記。格式：{schema_hint}"
    msgs = [dict(m) for m in messages]
    if msgs and msgs[0]["role"] == "system":
        msgs[0]["content"] = f"{msgs[0]['content']}\n\n{instruction}"
    else:
        msgs.insert(0, {"role": "system", "content": instruction})

    res = chat(msgs, temperature=0, max_tokens=max_tokens, json_mode=True)
    try:
        return extract_json(res.text)
    except ValueError as e:
        log.warning("第一次 JSON 解析失敗，重試：%s", e)
        retry_msgs = [
            *msgs,
            {"role": "assistant", "content": res.text or "(空)"},
            {"role": "user", "content": f"上一次輸出無法解析為 JSON（{e}）。請只輸出符合格式的 JSON 物件。"},
        ]
        res2 = chat(retry_msgs, temperature=0, max_tokens=max_tokens, json_mode=True)
        try:
            return extract_json(res2.text)
        except ValueError as e2:
            raise LLMError(f"模型兩次都沒有輸出有效 JSON：{e2}") from e2


def embed(texts: list[str]) -> list[list[float]]:
    """批次產生向量（每批 32 筆），回傳順序與輸入一致。"""
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        try:
            r = _embed_create(model=settings.embed_model, input=batch)
        except Exception as e:
            raise _wrap(e) from e
        out.extend(d.embedding for d in sorted(r.data, key=lambda d: d.index))
    return out
