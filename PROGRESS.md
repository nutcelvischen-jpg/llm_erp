# 開發進度

| 任務 | 狀態 | 日期 | 備註 |
|---|---|---|---|
| T01 建立 repo 骨架 | ✅ 完成 | 2026-10-30 | Mac 與容器皆輸出 `ok` |
| T02 docker-compose | ✅ 完成 | 2026-10-30 | 3 容器 running；qdrant 回 JSON；psql 回 1 |
| T03 LM Studio 與煙霧測試 | ✅ 完成 | 2026-10-30 | ALL PASS；約 90–99 tok/s；dim 1024 |
| T04 backend 骨架 | ✅ 完成 | 2026-10-30 | /health 回 ok: true |
| T05 ERP schema | ✅ 完成 | 2026-10-30 | erp schema 9 張表；host 端 db.ping() 為 True |
| T06 app schema | ✅ 完成 | 2026-10-30 | app schema 4 張表 |
| T07 假資料產生器 | ✅ 完成 | 2026-10-30 | 6000 訂單；5 個劇情驗證通過 |
| T08 唯讀 View 與 schema 文件 | ✅ 完成 | 2026-10-30 | llm_reader 只能讀 4 個 View，寫入被拒 |
| T09 LLM 客戶端封裝 | ✅ 完成 | 2026-10-30 | 25 單元測試 + 3 真實 LLM 測試通過 |
| T10 Reranker | ✅ 完成 | 2026-10-30 | bge-reranker-v2-m3；罰款條款排第一；20 筆 0.25 秒 |
| T11 SQL 守門員 | ✅ 完成 | 2026-10-30 | 57 個測試；含 CTE 繞過防護 |
| T12 few-shot 範例庫 | ✅ 完成 | 2026-10-30 | 20 組範例；真實 DB 全數跑出結果；修正 search_path |
| T13 Text-to-SQL 主流程 | ✅ 完成 | 2026-10-30 | 守門員 + 唯讀執行 + 失敗回饋重試（最多 3 次）；真實 LLM 4 題通過 |
| T13b 聊天網頁（自建） | ✅ 完成 | 2026-10-30 | http://localhost:8000；162 單元測試 + 30 項瀏覽器檢查 |
| T13c 介面打磨（圖表與證據面板） | ✅ 完成 | 2026-10-30 | 兩欄版面、自動圖表、排序；164 單元測試 + 66 項瀏覽器檢查 |
| T14 Text-to-SQL 評估腳本 | ✅ 完成 | 2026-10-31 | 30 題黃金題 30/30 = 100%；平均 1.7 秒、P95 2.3 秒（修正前 13.5 秒：LM Studio 在聊天與 embedding 模型間互相卸載，現在兩者常駐） |

## T01 建立 repo 骨架
與 TASKS.md 的差異（版本與依賴未動）：
1. `pyproject.toml` 加 `[tool.setuptools.packages.find] include = ["backend*"]`，否則根目錄多個頂層資料夾會讓 setuptools 安裝失敗。
2. `Makefile` 的 `uv venv` 加 `--allow-existing`，讓 `make setup` 可重複執行。

## T02 docker-compose
驗收輸出：`docker compose ps` 三容器 Up（postgres、open-webui 為 healthy）；`curl localhost:6333/collections` 回 `{"result":{"collections":[]},...}`；psql 回 `1`。

## T03 LM Studio 與煙霧測試
- LM Studio 實際 port 為 **1234**；模型 id：`qwen/qwen3.6-35b-a3b`、`text-embedding-bge-m3`。
- 與 TASKS.md 的差異：`.env` / `.env.example` 的 `LLM_MODEL` 改為 `qwen/qwen3.6-35b-a3b`（LM Studio 的 id 含 `qwen/` 前綴）；`python-dotenv` 已加入 pyproject；`max_tokens` 由 100 改 300。
- **Qwen3.6 思考模式**：第一次煙霧測試回應為空，原因是思考吃掉 411 tokens。用 `scripts/diag_think.py` 實測：`/no_think` 與 `enable_thinking=false` 無效（仍思考 601 tokens、約 6.5 秒）；`extra_body={"reasoning_effort":"none"}` 有效（思考 0 tokens、0.4 秒）。已寫入 AGENTS.md 固定參數與 TASKS.md T09。
- 實測速度約 90–99 tok/s（MLX）。
- `sudo sysctl iogpu.wired_limit_mb=40000` 已在 Mac 執行（重開機後需重打）。

## T15 測試文件準備 ✅
- `make docs`（`scripts/make_docs.py` + `scripts/docgen/`）產生 20 份繁中 PDF 到 `data/docs/`：銷售合約 5（含鴻遠機械 C008、台陽科技 C015）、採購合約 5、SOP 5、規格書 3、人資規章 2；皆 3–5 頁，有頁碼。
- `data/docs/facts.yaml`：123 筆重點事實（檔名、頁碼、問題、答案），供 T20/T21 產生 RAG 測試題。
- 與 TASKS.md 的差異：改用 Playwright/Chromium HTML→PDF（內嵌 Noto Sans CJK TC），不用 reportlab。
- 注意：PDF 抽字會把部分中文轉成 Kangxi 部首字元（如「⼩」）、en dash 變 figure dash；比對與 T16 解析後的文字須先 NFKC 正規化並統一破折號。
