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
| 第一題特別慢 | JIT 載入模型，正常；Demo 前先暖機 |
