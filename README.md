# 地端 LLM × ERP PoC

在一台 MacBook Pro（M3 Max 48 GB）上，**不把任何資料送出公司**，用中文：

1. **問 ERP 數字**：「今年毛利跟去年同期比怎樣？哪個客戶掉最多？」→ 結論、表格、圖表、SQL
2. **問合約／SOP／規章**：「鴻遠機械的合約，延遲交貨罰款怎麼算？」→ 條列回答＋檔名與頁碼
3. **每週主動預警**：每週一 08:00 產生呆滯庫存與缺料清單（可選擇推播到 LINE）

規格見 `SPEC.md`，開發守則見 `AGENTS.md`，任務與實作紀錄見 `TASKS.md`、`PROGRESS.md`。

---

## 10 分鐘從零到 Demo

前提：模型已下載（第一次下載主模型約 20 GB、reranker 約 2.2 GB、Docling 版面模型約 1 GB，需要網路）。

### 0. 需要的軟體
- macOS（Apple Silicon）、[LM Studio](https://lmstudio.ai)、Docker Desktop、[uv](https://docs.astral.sh/uv/)、`make`

### 1. LM Studio（人工，一次性；詳見 `docs/LMSTUDIO_SETUP.md`）
1. Explore 下載 **Qwen3.6-35B-A3B（MLX 4bit）** 與 **bge-m3（GGUF）**。
2. Settings › Local Model API › Local API server 切到 **Running**，port **1234**。
3. 終端機：`sudo sysctl iogpu.wired_limit_mb=40000`（重開機後要重打）。
4. `curl localhost:1234/v1/models` 確認模型 id。

### 2. 專案
```bash
make setup                 # 建 .venv、安裝依賴、複製 .env.example → .env
# 編輯 .env：LLM_MODEL / EMBED_MODEL 填上一步看到的 id（本機為 qwen/qwen3.6-35b-a3b、text-embedding-bge-m3）
make llm-up                # 讓聊天與 embedding 兩個模型同時常駐（重要，否則每題多 12 秒）
uv run python scripts/smoke_lmstudio.py   # 看到 ALL PASS

make up                    # Postgres + Qdrant（Docker）
make seed                  # 產生 2 年假 ERP 資料（以今天為基準；SEED_TODAY=YYYY-MM-DD 可固定）
make load-examples         # Text-to-SQL few-shot 範例（21 組）
make ingest                # 20 份示範 PDF → Qdrant（約 1 分鐘，355 塊）
make dev                   # http://localhost:8000
```

### 3. 四個頁面

| 網址 | 頁面 | 給誰用 |
|---|---|---|
| `/dashboard` | **儀表板**：今年營收／毛利與去年同期、逾期應收、呆滯庫存、缺料、供應商準時率 7 張指標卡＋3 張圖；點「看明細」進報表、「用問的」到問答 | 老闆、主管每天看一眼 |
| `/reports` | **報表**：16 支既定程式依銷售／應收／庫存／採購分類，下拉選單選條件後查詢；可排序、下載 CSV、列印；網址會記住條件（可加書籤）。**不經過 AI** | 習慣傳統 ERP 操作的同仁 |
| `/` | **問答**：用中文問數字與文件；數字結果可「在報表中開啟」改條件 | 臨時問題、數字＋合約一起看 |
| `/about` | **系統介紹**：能做什麼、怎麼運作、為什麼可信、資料不外流、可查的報表與文件清單、限制與常見問題，含即時系統狀態 | 第一次使用、Demo 開場 |

三個入口執行的是同一批既定程式，數字一致。截圖：`docs/screenshots/page_*.png`。

### 4. Demo
- 開 http://localhost:8000，點 6 個範例問題。講稿、預期畫面與備援見 **`docs/DEMO_SCRIPT.md`**。
- 連續追問的情境劇（圖表＋合約／規章＋兩者合併判斷）見 **`docs/DEMO_STORIES.md`**。
- 網頁操作：左側欄（新對話、本次問題、對話紀錄）、輸入框旁「💡 範例」、每題下方「接著問」與複製／下載 CSV／重新查詢。
- Demo 前先把 6 題預跑一次暖機（第一次查文件要載入 reranker，約 10 秒；之後 3–9 秒）。
- 每週預警手動觸發：`curl -s -X POST localhost:8000/admin/jobs/dead_stock/run`

### 5. 驗證
```bash
curl -s localhost:8000/health        # "ok": true，且沒有 warnings
make test                            # 單元測試（約 2 秒）
make test-db && make test-llm        # 需要 Docker 與 LM Studio
make eval-sql                        # 數字查詢 30 題黃金題（既定程式；--engine ai 可比較 AI 寫 SQL）
make eval-intent                     # 意圖辨識 40 題（模板 ≥95%、參數 ≥90%、不支援誤判 0）
make eval-rag                        # RAG 30 題（命中 ≥85%、答案 ≥80%、拒答全對）
uv run --with playwright python scripts/check_frontend.py   # 網頁 148 項瀏覽器檢查
```

---

## 架構

```
瀏覽器 ──▶ FastAPI :8000（host，不進 Docker）
            │  GET / 問答、/dashboard 儀表板、/reports 報表、/about 系統介紹（原生 HTML/JS，無外部 CDN）
            │  POST /api/chat、/api/feedback；GET /api/dashboard、/api/reports/catalog、POST /api/reports/run；/admin/*
            │  （儀表板與報表直接執行既定程式，不經過 LLM）
            ▼
        agent.run_agent
          ├─ router：LLM 分類 sql / docs / both / chat ＋ 關鍵字保底；依對話改寫問題
          ├─ sql  ─▶ catalog（既定程式）：LLM 辨識「模板＋參數」→ 程式驗證參數（期間、名稱比對、白名單）
          │          → 寫死的參數化 SQL（必經 sql_guard）→ 唯讀帳號 llm_reader 執行（10 秒逾時）
          │          → LLM 看結果與程式算的 facts 寫結論（數字檢查，不過就用固定句型）
          │          沒有明確命中 → 列出最接近的既定程式讓使用者確認；不支援 → 婉拒並記錄
          ├─ docs ─▶ Qdrant 混合檢索（bge-m3 dense ＋ jieba BM25 → RRF）→ reranker（CPU）
          │          → LLM 依片段回答並標 [來源 n]
          ├─ both ─▶ 兩支並行 → 合併結論（數字檢查）
          └─ chat ─▶ 一般回覆（不得出現公司數字）
            │
            └─ audit：每題寫入 app.audit_log
        APScheduler：每週一 08:00 呆滯／缺料預警 → app.notifications（→ LINE，選配）

LM Studio :1234（host）    Qwen3.6-35B-A3B（聊天）＋ bge-m3（embedding），兩者常駐
PostgreSQL :5432（Docker） erp schema（假 ERP 資料＋4 個中文 View）、app schema（稽核、回饋、通知、範例）
Qdrant :6333（Docker）     collection erp_docs：dense 1024 維 ＋ sparse bm25
```

主要程式：`backend/app/agent/`（路由、主流程、prompt）、`text2sql.py`、`sql_guard.py`、`rag/`（解析、切塊、索引、檢索、回答）、`numcheck.py`、`jobs/`（預警、排程、LINE）、`api/`、`web/index.html`。

---

## 已知限制

| 項目 | 現況 |
|---|---|
| 數字查詢範圍 | 只能回答 16 個既定程式涵蓋的問題（`backend/app/catalog/templates/`）；其他問題會列出最接近的程式讓使用者確認，或婉拒並記錄到 `app.unmatched_questions`，需由人新增模板。AI 不寫 SQL（`text2sql` 只保留給 `eval_text2sql.py --engine ai` 比較）。 |
| 數字檢查 | 確認回覆中的每個數字出現在結果、程式算出的 facts 或查詢條件中，**無法確認數字對應到正確欄位或正負號**（例：把缺口說成建議量）。已用「欄位=值」格式降低此風險，但不是保證；檢查不過就改用固定句型。 |
| 文件回答 | 嚴格字串比對的正確率 88–92%，失敗多為「答對但沒照抄原文」。只支援有文字層的 PDF（Docling 關閉 OCR，掃描檔不行）。 |
| 路由 | 含「幾／多少」的純文件問題會被升為 both，多查一次 SQL（約 +2 秒，不影響答案）。 |
| 權限 | 沒有登入、沒有使用者權限；`/admin/*` 無驗證。`make dev` 只綁 127.0.0.1，對外開放前必須先加驗證。 |
| 並行 | 主模型以 parallel 1 載入，同一時間只適合一人使用。 |
| 資料 | 假資料以 seed 當天為基準，重新 seed 數字會變（劇情不變）。 |
| 預警訊息 | LLM 摘要 ≤150 字，後面由程式附完整料號明細，整則會超過 150 字。 |
| LINE | 未設定；設定方式見 `docs/LINE_SETUP.md`。推播內容會經過 LINE 伺服器（資料離開內網）。 |

---

## 如何換模型

所有模型 id 都在 `.env`，程式不寫死。

- **換聊天模型**：LM Studio 下載新模型 → `.env` 的 `LLM_MODEL` 改成 `curl localhost:1234/v1/models` 的 id → `make llm-up` → 重跑 `make test-llm`、`make eval-sql`、`make eval-rag` 比較正確率與延遲。
  - Qwen3.6 用 `reasoning_effort: "none"` 關閉思考（`llm.py`）。換成其他模型時，確認此參數不會報錯，以及回覆不含思考內容（`strip_think` 會移除 `<think>` 區塊）。
- **換 embedding 模型**：改 `EMBED_MODEL`、`EMBED_DIM`，然後**必須重建向量**：`uv run python scripts/ingest_docs.py data/docs --recreate` 與 `make load-examples`。
- **換 reranker**：改 `RERANK_MODEL`（sentence-transformers CrossEncoder 相容的 HuggingFace 模型），第一次使用會下載。
- 注意：`AGENTS.md` 的「固定參數」（URL、維度、collection 名稱等）是本 PoC 的約定，正式導入時再一起調整。

## 如何接真實 ERP

系統只透過 **4 個中文 View** 讀資料（`v_銷售明細`、`v_應收帳款`、`v_庫存狀況`、`v_採購明細`，定義在 `sql/003_views.sql`）。接真實 ERP 的原則是**把 View 指到客戶資料，程式不動**：

1. **資料來源**
   - 客戶 ERP 是 PostgreSQL：在客戶庫（或唯讀副本）建同名、同欄位的 View，`.env` 的 `PG_DSN_READONLY` 指過去。
   - 客戶 ERP 是 SQL Server／Oracle 等：建議以 ETL／CDC 每晚同步到本機 Postgres 的 `erp` schema（守門員以 PostgreSQL 語法解析，直接連其他資料庫需改 `sql_guard` 的方言）。
2. **欄位對照**：每個 View 輸出相同的中文欄位名與意義（例如「銷售金額」是否含稅、「取消」單如何排除）。對照不清楚的地方寫進 `sql/schema_doc.md`，它會原封不動放進 prompt。
3. **權限**：建立只對 4 個 View 有 SELECT 權限的唯讀帳號（參考 `sql/003_views.sql` 的 `llm_reader`），不要給原始表權限。
4. **既定程式與黃金題**：依客戶的常見問題調整或新增 `backend/app/catalog/templates/` 的模板（SQL 寫死、值用綁定參數、每個模板 ≥5 句範例說法），定期把 `app.unmatched_questions` 裡常見的問題做成新模板；改寫 `data/golden/text2sql.yaml`、`intents.yaml`、`template_map.yaml` → `make eval-sql`、`make eval-intent` 達標才上線。
5. **文件**：把客戶的合約、SOP、規章 PDF 放進資料夾 → `uv run python scripts/ingest_docs.py <資料夾>`（或 `POST /admin/ingest`，路徑須在 `data/` 底下）；依客戶文件出 RAG 黃金題 → `make eval-rag`。
6. **預警規則**：`backend/app/jobs/dead_stock.py` 的呆滯天數（180）、缺料與建議採購量公式依客戶的採購政策調整。
