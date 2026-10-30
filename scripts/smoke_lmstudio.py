"""檢查 LM Studio chat 與 embedding 是否正常。

用法：uv run python scripts/smoke_lmstudio.py
第一次執行會觸發 JIT 載入模型（約 20 GB），可能要等 30–90 秒。
"""
import os
import re
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
    timeout=float(os.environ.get("LLM_TIMEOUT", "120")) * 3,  # 首次載入模型較久
)


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


models = [m.id for m in client.models.list().data]
print("models:", models)
for key in ("LLM_MODEL", "EMBED_MODEL"):
    if os.environ[key] not in models:
        sys.exit(f"[FAIL] {key}={os.environ[key]} 不在 LM Studio 模型清單中")

t = time.time()
r = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "用一句話介紹台中。"}],
    max_tokens=300,
    temperature=0,
    # Qwen3.6 不吃 /no_think 與 enable_thinking；只有 reasoning_effort=none 能關閉思考
    extra_body={"reasoning_effort": "none"},
)
dt = time.time() - t
txt = strip_think(r.choices[0].message.content)
if not txt:
    sys.exit("[FAIL] chat 回應為空（可能思考內容用完 max_tokens）")
tps = (r.usage.completion_tokens or 0) / dt if dt else 0
print(f"chat ok ({dt:.1f}s, {tps:.0f} tok/s): {txt[:80]}")
if tps < 15:
    print("[WARN] 速度低於 15 tok/s；首次呼叫含模型載入時間，請再跑一次確認")

t = time.time()
e = client.embeddings.create(
    model=os.environ["EMBED_MODEL"], input=["應收帳款", "合約罰款"]
)
dim = len(e.data[0].embedding)
print(f"embedding ok ({time.time() - t:.1f}s), dim = {dim}")
if dim != int(os.environ.get("EMBED_DIM", "1024")):
    sys.exit(f"[FAIL] embedding 維度 {dim} != EMBED_DIM")
print("ALL PASS")
