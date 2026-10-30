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
