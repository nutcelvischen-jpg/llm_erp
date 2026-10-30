"""診斷延遲：13 秒花在「處理 prompt（prefill）」還是「產生答案（decode）」，以及 LM Studio 有沒有重用相同開頭的快取。

用法：uv run python scripts/diag_latency.py
需要 LM Studio 開著；若已執行 make load-examples，會用真實的 few-shot 範例組 prompt。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import llm, text2sql
from backend.app.agent import prompts

Q1, Q2 = "今年營收最高的 3 個客戶", "目前逾期超過 60 天的應收帳款有哪些客戶？"


def timed(label: str, system: str | None, user: str, max_tokens: int) -> llm.ChatResult:
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    r = llm.chat(msgs, temperature=0, max_tokens=max_tokens)
    print(f"  {label:<34} prompt {r.prompt_tokens:>5} tok　產出 {r.completion_tokens:>4} tok　{r.latency_ms / 1000:6.2f} 秒")
    return r


def system_for(question: str) -> str:
    try:
        examples = text2sql.pick_examples(question, k=4)
    except Exception:  # noqa: BLE001  沒載入範例也能診斷
        examples = []
    return prompts.build_sql_system(examples)


print("暖機…")
llm.chat([{"role": "user", "content": "OK"}], max_tokens=5)

print("\n① 產出速度（極短 prompt，要求寫 200 字）")
d = timed("短 prompt 產生約 200 字", None, "請用繁體中文寫一段約 200 字的台中市介紹。", 300)
decode_rate = d.completion_tokens / (d.latency_ms / 1000)
print(f"  → 約 {decode_rate:.0f} tok/s")

print("\n② 處理 prompt 的時間（正式 prompt，只產 1 個 token）")
s1, s2 = system_for(Q1), system_for(Q2)
a = timed("正式 prompt（問題 1）", s1, Q1, 1)
b = timed("完全相同的請求再送一次", s1, Q1, 1)
c = timed("相同 system、不同使用者問題", s1, Q2, 1)
e = timed("不同範例（模擬問題 2 的 system）", s2, Q2, 1)
prefill_rate = a.prompt_tokens / (a.latency_ms / 1000)
print(f"  → 約 {prefill_rate:.0f} tok/s")

print("\n③ 推估")
sql_tokens = 200
print(f"  正式問題 ≈ 處理 prompt {a.latency_ms / 1000:.1f} 秒 + 產生 SQL（約 {sql_tokens} tok）{sql_tokens / decode_rate:.1f} 秒 "
      f"= {a.latency_ms / 1000 + sql_tokens / decode_rate:.1f} 秒")
print(f"  system 開頭相同時（快取命中）可省：{(a.latency_ms - c.latency_ms) / 1000:.1f} 秒；完全相同請求可省：{(a.latency_ms - b.latency_ms) / 1000:.1f} 秒")
if c.latency_ms < a.latency_ms * 0.5:
    print("  → LM Studio 有重用相同開頭的快取：把固定內容放前面、會變的內容（範例、問題）放後面，就能大幅縮短。")
elif e.latency_ms < a.latency_ms * 0.5:
    print("  → 只有「開頭相同的部分」被快取：可再把 prompt 拆成固定在前、變動在後。")
else:
    print("  → 看不出快取效果：延遲主要靠縮短 prompt（精簡 schema 說明、減少範例）或避免重複送出長 prompt。")
