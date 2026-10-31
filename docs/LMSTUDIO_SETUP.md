# LM Studio 設定（Mac，一次性）

## 1. 下載模型
- Explore → 搜尋 `qwen3.6 35b a3b` → 選 **MLX 4bit**（約 20 GB）
- Explore → 搜尋 `bge-m3` → 選 **GGUF**（約 0.6 GB，embedding 用）

## 2. 開 server
- Settings → **Local Model API** → Local API server 切到 **Running**
- Base URL 必須是 `http://localhost:1234/v1`（不是的話按 Edit port 改成 1234）
- **Just-in-time model loading** 保持開啟：API 第一次呼叫時會自動載入模型

## 3. Context length
- Settings → **Local Model Defaults** → Minimum AutoFit context length = `32768`

## 4. 提高 GPU 記憶體上限（重開機後失效，要重打）
```bash
sudo sysctl iogpu.wired_limit_mb=40000
```

## 5. 確認模型 id，填進 `.env`
```bash
curl localhost:1234/v1/models
```
本專案使用：
```env
LLM_MODEL=qwen/qwen3.6-35b-a3b
EMBED_MODEL=text-embedding-bge-m3
```

## 6. 煙霧測試
```bash
uv run python scripts/smoke_lmstudio.py
```
看到 `ALL PASS` 即完成。第一次會觸發模型載入，需等 30–90 秒；Demo 前請先跑一次暖機。

## 常見問題
| 症狀 | 處理 |
|---|---|
| `Connection refused` | Local Model API 開關沒開，或 port 不是 1234 |
| `[FAIL] LLM_MODEL=... 不在清單中` | 以 `curl localhost:1234/v1/models` 的 id 為準 |
| 速度 < 15 tok/s | 確認是 MLX 版本；確認已執行 sysctl；關掉其他吃記憶體的 App |
| 第一題特別慢 | JIT 載入模型，正常；Demo 前先 `make llm-up` 並問一題暖機 |
| 每題都慢（約 13 秒） | 兩個模型在互相卸載；執行 `make llm-up`，見上節 |

## 兩個模型必須同時常駐（重要）

**症狀**：每個問題都要 13 秒左右，連「員工薪資」這種馬上會被婉拒的問題也一樣慢。
**原因**：LM Studio 的 JIT 自動載入預設「只保留最後一個載入的模型」。我們每題都會呼叫兩個模型（embedding 挑範例、聊天模型產生 SQL），它們會互相卸載，於是每題都要重新載入聊天模型並重算整份 prompt。
**實測**：兩個模型常駐之後，30 題黃金題平均從 **13.5 秒降到 1.7 秒**（P95 2.3 秒），正確率不變（30/30）。

**解法**：用 `make llm-up` 手動載入兩個模型（手動載入的模型不會被自動卸載）：
```bash
make llm-up          # 先卸載全部，再載入 .env 的 LLM_MODEL 與 EMBED_MODEL，並列出狀態
~/.lmstudio/bin/lms ps   # 確認剛好兩個模型、沒有重複（identifier 不該出現 :2）
```
- 聊天模型以 context 32768、parallel 1 載入：我們的 prompt 約 3K token，32K 綽綽有餘；LM Studio 預設的 256K context 與 4 個平行槽位只會浪費記憶體，快取也分散在不同槽位。
- **重開機或重啟 LM Studio 後要重跑 `make llm-up`**。Demo 或評估（`make eval-sql`）之前先跑一次。
- 後端 `/health` 會在模型沒常駐時回傳 `warnings`（不影響 `ok`），提醒你執行 `make llm-up`。
- 如果之後有多人同時使用，再把 `--parallel` 調高；調高前請重跑 `make eval-sql` 確認延遲。
