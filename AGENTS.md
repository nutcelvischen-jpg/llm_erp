# AGENTS.md — 給 AI 開發代理（Sonnet / Claude Code）的專案守則

> 你正在開發「地端 LLM × ERP」PoC。完整規格在 `SPEC.md`，任務清單在 `TASKS.md`。
> **一次只做一個任務，做完跑驗收指令，通過才進下一個。**

## 專案目標（PoC 範圍）
在一台 MacBook Pro M3 Max 48 GB 上，示範三個案例：
1. 老闆用自然語言問財務／銷售數字（Text-to-SQL）
2. 問合約／SOP／法規，回答附頁碼出處（RAG）
3. 每週自動產生呆滯庫存／缺料預警（排程 Agent）

## 架構（PoC 版）
```
瀏覽器 → http://localhost:8000（自建單頁網頁 backend/app/web/index.html，由 FastAPI 提供）
   └─▶ backend FastAPI (host :8000：GET / 網頁、POST /api/chat)
          ├─▶ catalog 模板查詢（LLM 只做意圖辨識與看結果回覆）
          ├─▶ LM Studio (host :1234)  主模型 + embedding
          ├─▶ PostgreSQL (Docker :5432)  erp schema(假資料) + app schema(稽核/快取)
          ├─▶ Qdrant (Docker :6333)  文件向量(dense + sparse BM25)
          └─▶ reranker (backend 內 CPU, bge-reranker-v2-m3)
```
- **backend 跑在 host（不進 Docker）**：避免 arm64 torch 映像問題，且直接打 `localhost:1234`。
- Docker 只放 postgres、qdrant。介面是自建單頁網頁（不使用 Open WebUI / Streamlit / Next.js）。

## 硬性規則
1. **語言**：Python 3.12，套件管理用 `uv`。所有指令寫進 `Makefile`。
2. **不要改 TASKS.md 的任務順序**。若任務無法完成，在 `PROGRESS.md` 寫下原因與你嘗試過的方法，停下來。
3. **每個任務結束必須**：
   - 跑該任務的「驗收」指令，貼出輸出到 `PROGRESS.md`
   - `git add -A && git commit -m "T<編號>: <任務名>"`
4. **禁止事項**
   - 不要把 LLM 產生的 SQL 直接執行，一律經過 `sql_guard.validate()`
   - **LLM 不得決定要執行的 SQL 字串（模板優先）**：預設由程式寫死的參數化模板執行；日期、名稱比對、欄位／排序白名單都由程式處理；值一律用 `:name` 綁定參數，不用字串拼接。只有管理員開啟 `ALLOW_AI_FALLBACK` 時才可走 Text-to-SQL，且回答必須標示「AI 即時產生」
   - LLM 回覆中的數字必須能在查詢結果或程式算出的 facts 中找到；找不到就改用固定句型，不得顯示
   - 不要在程式碼寫死 API key、密碼；全部讀 `.env`
   - 不要安裝 TASKS.md 未列出的大型框架（LangChain、LlamaIndex 等）；本專案刻意用薄封裝
   - 不要修改 `erp` schema 的表結構來「讓測試通過」；改查詢或 View
   - 不要自行升級／降級 `pyproject.toml` 已鎖定的版本
   - 前端網頁不得引用外部 CDN（地端環境可能沒有網路；需要的函式庫請放進 `backend/app/web/vendor/`）；後端回傳的文字一律用 `textContent` 或跳脫後插入，禁止 `innerHTML` 直接塞入使用者或模型產生的內容
5. **錯誤處理**：對外部服務（LM Studio、Qdrant、Postgres）的呼叫都要有 timeout 與明確錯誤訊息。
6. **繁體中文**：所有面向使用者的文字、prompt、欄位中文名稱使用台灣用語。
7. **測試**：`pytest` 需在 10 秒內跑完單元測試；需要真實 LLM 的測試標記 `@pytest.mark.llm`，預設跳過（`make test-llm` 才跑）。

## 目錄結構（最終）
```
local_llm/
├── SPEC.md  AGENTS.md  TASKS.md  PROGRESS.md
├── Makefile  docker-compose.yml  .env.example  pyproject.toml
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── config.py          # pydantic-settings
│   │   ├── llm.py             # LM Studio 客戶端(chat/embedding)
│   │   ├── reranker.py
│   │   ├── db.py              # SQLAlchemy engine
│   │   ├── sql_guard.py
│   │   ├── text2sql.py        # AI 產生 SQL（兜底，預設關閉）
│   │   ├── catalog/           # 模板優先：base.py periods.py entities.py registry.py intent.py answer.py runner.py
│   │   │   ├── templates/     # sales.py receivable.py inventory.py purchasing.py
│   │   ├── rag/
│   │   │   ├── parse.py  chunk.py  ingest.py  retrieve.py  answer.py
│   │   ├── agent/
│   │   │   ├── router.py  graph.py  prompts.py
│   │   ├── api/
│   │   │   ├── chat.py  admin.py
│   │   ├── web/
│   │   │   ├── index.html       # 自建單頁網頁（原生 HTML/CSS/JS）
│   │   ├── audit.py
│   │   └── jobs/
│   │       ├── dead_stock.py  scheduler.py  line_push.py
│   └── tests/
├── data/
│   ├── seed/            # 假資料產生器與 CSV
│   ├── docs/            # 測試用 PDF
│   └── golden/          # 黃金問答集
├── sql/
│   ├── 001_erp_schema.sql  002_app_schema.sql  003_views.sql  schema_doc.md
└── scripts/
    ├── smoke_lmstudio.py  seed_db.py  ingest_docs.py  eval_text2sql.py  eval_rag.py
```

## 固定參數（不要改）
| 項目 | 值 |
|---|---|
| LM Studio URL | `http://localhost:1234/v1` |
| 主模型 id | `.env` 的 `LLM_MODEL`（預設 `qwen3.6-35b-a3b`）|
| Embedding 模型 id | `.env` 的 `EMBED_MODEL`（預設 `text-embedding-bge-m3`）|
| Embedding 維度 | 1024 |
| Qdrant collection | `erp_docs` |
| Postgres DB | `erp_poc`，schema `erp`（業務資料）、`app`（系統資料）|
| backend port | 8000 |
| 時區 | Asia/Taipei |
| 關閉 Qwen 思考 | 每次 chat 呼叫都帶 `extra_body={"reasoning_effort": "none"}`；`/no_think`、`enable_thinking` 無效；思考內容在 `reasoning_content` 欄位，答案在 `content` |
