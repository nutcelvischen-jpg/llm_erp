"""診斷：Qwen3.6 思考模式如何關閉。

用法：uv run python scripts/diag_think.py
比較三種呼叫方式的 content、思考長度、耗時。
"""
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key="x", timeout=300)
model = os.environ["LLM_MODEL"]
messages = [{"role": "user", "content": "用一句話介紹台中。"}]

cases = {
    "A 預設": {},
    "B enable_thinking=false": {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
    },
    "C reasoning_effort=none": {"extra_body": {"reasoning_effort": "none"}},
}

for name, kw in cases.items():
    t = time.time()
    try:
        r = client.chat.completions.create(
            model=model, messages=messages, max_tokens=1500, temperature=0, **kw
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] ERROR: {str(e)[:200]}")
        continue
    dt = time.time() - t
    msg = r.choices[0].message
    extra = msg.model_extra or {}
    reasoning = extra.get("reasoning_content") or extra.get("reasoning") or ""
    details = r.usage.completion_tokens_details
    rtok = getattr(details, "reasoning_tokens", None) if details else None
    print(
        f"[{name}] finish={r.choices[0].finish_reason} "
        f"completion={r.usage.completion_tokens} reasoning_tokens={rtok} "
        f"{dt:.1f}s ({r.usage.completion_tokens / dt:.0f} tok/s)"
    )
    print(f"    content={msg.content!r:.120}")
    print(f"    reasoning欄位長度={len(reasoning)}  欄位名稱={[k for k in extra]}")
