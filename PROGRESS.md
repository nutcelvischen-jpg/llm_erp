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

## T16 文件解析 ✅ （commit b5107f7）
- `backend/app/rag/parse.py`：`parse_pdf()` 用 Docling（關閉 OCR、開表格結構）→ `Block(doc_id, file_name, page, heading_path, kind, text)`；轉換邏輯 `blocks_from_docling()` 不依賴 docling，可用假文件單測（5 項）。
- 驗收：`pytest -m db backend/tests/test_rag_parse.py` 通過（鴻遠機械合約：有表格 Block、「0.3%」在第 2 頁，約 6.5 秒）。`scripts/parse_demo.py` 可檢視解析結果。
- 實測：附件價格表、聯絡窗口各成獨立 table Block，標題（如「第十七條（其他）」「附件一 產品價格表」）正確帶入 heading_path。
- 備註：同頁同標題下的簽署欄等短行會合併進同一個 text Block；T17 切塊時處理。

## T17 切塊 ✅ （commit 7893782）
- `backend/app/rag/chunk.py`：`chunk_blocks()`（文字約 600 字、重疊 80；表格整張一塊，>1500 字按列切並重複表頭；前綴 `【檔名 › 標題路徑】`；`doc_type` 由檔名前綴判斷）。`make test` 242 passed。
- 實測 20 份 PDF → **355 塊**（表格 110 塊）；字數 min/median/max = 48/147/803；解析加切塊共 34 秒。T18 驗收門檻（>200）足夠。
- 與 TASKS.md 的差異：不跨 Block 合併（Block 已按標題與頁分隔，頁碼引用才準）；只略超過目標長度（≤680 字）的文字不切。

## T18 建立索引 ✅
- `backend/app/rag/ingest.py` + `scripts/ingest_docs.py`：collection `erp_docs`（dense bge-m3 1024 維 + sparse bm25）；已索引且 mtime 未變則跳過；`--force` / `--recreate`；`jieba>=0.42` 已加入 pyproject。
- 驗收：`make ingest` 後 collection 共 **355 筆**（>200）；重跑時 17 份顯示「跳過（未變更）」。
- 與 TASKS.md 的差異：sparse 不用 fastembed `Qdrant/bm25`（需從 HuggingFace 下載且不斷詞），改為 jieba 斷詞 → crc32 token id → BM25 TF 權重，IDF 由 Qdrant（Modifier.IDF）計算。
- 待確認：某次重跑有 3 份（SOP_費用報支、SOP_進料驗收、規格書_BRG-6205-2RS）未被跳過而重寫，最終筆數仍為 355；原因未明（可能是前次執行中斷）。再跑一次 `make ingest` 若全數跳過即無問題。

## T18 修正 ✅
- 重跑時固定有 3 份被重寫：原因是浮點 mtime 經 Qdrant 存取精度對不上。改存整數奈秒 `mtime_ns`。驗收：`make test` 249 passed；`make ingest` 第一次寫入 355 塊，第二次「寫入 0 塊，跳過 20 份」。
- 之後的任務改交由 Claude Code 依 TASKS.md 自動進行（從 T19 開始）。

## T19 混合檢索 ✅
- `backend/app/rag/retrieve.py`：`candidates()`（dense + bm25 各 top_k → Qdrant `FusionQuery(RRF)`）、`retrieve()`（再經 reranker 取 top_n）；`doc_type` payload filter；Qdrant／embedding 失敗丟 `RetrieveError`（含明確訊息），reranker 失敗時記 warning 並退回 RRF 順序。client／embed／rerank 可注入。
- `backend/tests/test_rag_retrieve.py`：8 個單元測試（Qdrant `:memory:` + 假 embedding／reranker）+ 2 個 `@llm`。
- 驗收：`make test` 257 passed；`make test-llm` 17 passed。
- 與 TASKS.md 的差異（Elvis 同意）：原測試 query「延遲交貨罰款怎麼算」未指名客戶，而 5 份銷售合約違約金比率各不同（鴻遠 0.3%、台陽 0.5%、力發 0.2%、新祥 0.4%、明誠每週 1.5%），rerank 後 5 份第五條分數 0.918–0.956 幾乎並列、第一名是明誠，無正當方法固定排出鴻遠。改為「鴻遠機械的合約，延遲交貨罰款怎麼算？」→ 第一筆即鴻遠第五條（0.995）。TASKS.md 已同步註記。
- 實測：未指名時前 5 名正是 5 份銷售合約的違約金條款，採購合約扣款條款排 6–8，檢索本身正確。
- 注意：reranker 冷啟動第一次 20 筆約 6.6–9.6 秒，之後 1.1–1.7 秒（片段較長，max_length 512）；Demo 前需暖機。
