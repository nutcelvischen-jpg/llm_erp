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

## T20 RAG 回答 ✅
- `backend/app/rag/answer.py`：`answer(question, hits) -> RagAnswer(text, sources, prompt_tokens, completion_tokens, latency_ms, error)`；`Source(file_name, page, heading, snippet)`。prompt（`agent/prompts.py` 的 `RAG_SYSTEM`）：只依片段、不足時回「依現有文件查無相關資料。」、句末 `[來源 n]`、條列 ≤200 字、數字照原文、指名對象只用該對象文件。片段以 `<片段 n 檔案=… 頁=… 標題=…>` 包裹（去掉切塊前綴）。
- 後處理：只保留被引用的來源，並把回答中的編號重編成來源清單的順序（避免 [來源 3] 對不到）；不存在的編號刪除；沒標來源時保留前 2 筆。
- 與 TASKS.md 的差異：① 沒標來源且回答是「查無」時不附來源（附了反而誤導）；② 沒有片段時不呼叫 LLM，直接回「查無」；③ LLM 失敗時回 `error` 與提示文字，不拋例外（供 T23 組裝）。
- 驗收：`make test` 269 passed；`make test-llm` 18 passed。實際回答：鴻遠機械第五條，「0.3%」「10% 上限」，唯一來源 `銷售合約_鴻遠機械.pdf` 第 2 頁，約 1–2 秒（不含 rerank）。

## T21 RAG 評估腳本 ✅
- `scripts/make_rag_golden.py` → `data/golden/rag.yaml`（30 題）：由 `facts.yaml` 以固定 seed 抽題，20 份文件各 1 題、再加 5 題（避免挑簡單題），`expect_contains` 直接用 facts 的 `phrase`；另 5 題拒答（年終獎金、員工旅遊補助、退休金提撥、育嬰留停、遠端工作），已對全部 355 塊確認關鍵字不存在。
- `backend/app/eval_checks.py` 新增 `normalize_text`／`rag_contains`／`rag_refused`：只消除排版差異（PDF 部首字、全形、空白、破折號、臺／台、×／x），數字與用字仍須相同；單元測試含「0.35% 不算 0.3%」「500,000 不算 5,000,000」。
- `scripts/eval_rag.py`（`make eval-rag`）：先暖機 reranker；統計檢索命中（expect_file 在 top_n）、答案正確（expect_contains 全部出現）、拒答正確（含「查無」）、延遲；未達標結束碼 1；報告 `data/golden/report_rag_<日期>.md`（失敗題附檢索結果與完整回答）。
- 調整 T20：模型有 3/25 題答完後又另起一段補「依現有文件查無相關資料。」。修 prompt（能回答就不要加）＋後處理（已有引用時刪掉結尾單獨的拒答段）＋2 個單元測試。
- **驗收**（`make eval-rag`）：檢索命中 **25/25 = 100%**、答案正確 **21/25 = 84%**、拒答 **5/5**，平均 2.9 秒、P95 3.9 秒 → 達標。`make test` 274 passed。
- 注意：
  - 答案正確率有波動：修正前一輪是 23/25 = 92%，修正後是 21/25 = 84%（temperature 0.1），離 80% 門檻只差 1 題。
  - 4 題失敗**都是答對但沒照抄原文用字**：R02 答「30 日內驗證成效」但 phrase 是「追蹤」；R04 答「每人每餐上限為 1,000 元」但 phrase 是「每人每餐 1,000 元以內」；R07 答「超過 3 日」但 phrase 是「逾 3 日」；R22 答「每年事假可請 14 日」但 phrase 是「每年 14 日」。依規定沒有改題目或放寬比對。若要更穩，可在 prompt 要求「照原文引用關鍵句」，或把 phrase 改為只放關鍵數值（需 Elvis 決定）。
  - R11（永信金屬）回答混入另一份合約的 20 公斤條款，prompt 第 6 條（只用指名對象的片段）不一定被遵守；T23 可考慮依問題中的客戶／供應商名稱過濾片段。
  - reranker 冷啟動第一次 20 筆約 6–7 秒。

## T21 追加：RAG prompt 要求照原文引用 ✅
- `RAG_SYSTEM` 第 5 條改為「關鍵內容照片段原文用字逐字引用（例：原文『逾 3 日』不要改寫成『超過 3 天』）」。
- `make eval-rag` 兩輪：檢索 25/25、答案 **22/25 = 88%**、**23/25 = 92%**（原 84%）、拒答 5/5；平均 2.8–3.2 秒。
- 仍會失敗的：R02（答「30 日內驗證成效」，phrase「追蹤」）、R22（答「事假每年可請 14 日」，phrase「每年 14 日」）、偶發 R01（答「三層」，phrase「3 層」）。

## T22 意圖路由 ✅
- `backend/app/agent/router.py`：`route(question, history) -> Route(kind, rewritten, source)`；`ROUTER_SYSTEM`（`agent/prompts.py`）列四類定義各 5 例句與改寫規則；history 取最後 6 輪、每則截 300 字。
- 關鍵字保底照規格：文件詞（合約／SOP／規定／辦法／條款／規格）→ docs；數字詞（多少／幾／排名／金額／庫存／逾期／營收）→ sql；與 LLM 結果取聯集（sql+docs=both；有其他類時 chat 讓位）。規則同時套用原句與改寫後的句子。LLM 失敗或回傳不合法 kind 時只用規則。
- 驗收：`make test` 287 passed（規則 5 案例 + 合併、失敗退回等）；`make test-llm` 21 passed（sql、docs、「那去年呢」改寫成「鴻遠機械去年營收」）。
- 觀察：規格的數字詞很寬，「特休幾天」「事假一年可以請幾天」「GEAR-M2-40T 的最低訂購量是多少」LLM 判 docs，但被規則升為 both（會多跑一次 SQL，約 +2 秒）。照規格保留；T23 的 both 合併時 SQL 查無資料就只用文件回答。若要收斂，可把「幾／多少」改為只在沒有文件詞時才觸發（需 Elvis 決定）。

## T23 Agent 主流程 ✅
- `backend/app/agent/graph.py`：`run_agent(question, history, session_id) -> AgentResult(markdown, route, answer, rewritten, sql, columns, rows, row_count, sources, latency_ms, tokens, warning, error, audit_id)`。route → sql／docs／both（`ThreadPoolExecutor` 並行）／chat → Markdown（結論／數據表 ≤20 列／`<details>` SQL／來源）→ `audit.write`。外部呼叫集中在 `Deps`，單元測試全用假的。
- **與 TASKS.md 的差異（重要）**：
  1. sql 分支規格是 `catalog.answer_question`，但 T14b–T14f 依 Elvis 決定暫不做，改接 `text2sql.run`（必經 sql_guard、唯讀角色）；回答與 `warning` 一律標示「AI 即時產生的查詢，請查核 SQL 與結果」。這與 AGENTS.md「模板優先、AI SQL 須管理員開 ALLOW_AI_FALLBACK」不一致（目前 `/api/chat` 原本就是 text2sql）；做完 catalog 後只需替換 `graph._default_sql`。
  2. `audit.write` 屬 T24，但 T23 測試要檢查 audit_log，先在 `backend/app/audit.py` 實作 `write()`（失敗只記 log、回 None）；`list_recent`／`add_feedback` 留給 T24。
- 數字檢查 `backend/app/numcheck.py`：回覆中的數字須能在查詢結果、文件回答或問題中找到（容許千分位、依小數位四捨五入、萬／億換算；年份與 ≤31 小整數例外）。用在 sql 的查詢說明（不過→「查詢結果如下表（共 N 列）」）、both 的綜合結論（不過→固定組合：查詢說明＋文件回答）、chat（出現任何數字→固定自我介紹）。
- both：text2sql 婉拒（「無法用 ERP 資料回答」，例如路由規則把「特休幾天」升為 both）視為不適用、不顯示失敗；只有真正故障才顯示「這部分查詢失敗：…」。MERGE_SYSTEM 規定數字以查詢結果為準（修正「文件查無逾期金額」的矛盾句）。
- 驗收：`make test` 303 passed；`make test-llm` 22 passed（三題 Demo：營收前三→sql 表格、鴻遠罰款→docs 0.3%／10% 附來源、台陽逾期＋暫停出貨→both「5 張逾期 244,593 元…逾期超過 60 日得暫停出貨 [來源 1]」；audit_log +3 列）。延遲：sql 2.3 秒、both 5.6 秒、docs 首次 11.7 秒（reranker 冷啟動）。

## T24 稽核 ✅
- `backend/app/audit.py`：`write(AuditRecord) -> id | None`（T23 已建）、`list_recent(n)`（新到舊，n 夾 1–500，`ts` 轉 ISO 字串，`doc_sources` 為 JSON）、`add_feedback(audit_id, score, comment)`（score 只收 1／-1，否則 ValueError；comment 去空白、截 1000 字）。所有資料庫失敗只記 log、回 None／空清單，不拋錯。
- 測試 `backend/tests/test_audit.py`：單元（連不上資料庫不拋錯、分數驗證）+ `db`（寫入後讀回、回饋寫入讀回、不存在的 audit_id、排序與夾值）。
- 驗收：`make test` 305 passed；`make test-db` 62 passed。
- 備註：db 測試會在 `app.audit_log` 留下 session_id 為 `pytest-…` 的列（T23 的真實測試是 `pytest`），T26 統計時可用 session_id 排除。

## T25 聊天 API 升級 ✅
- `POST /api/chat` 改呼叫 `agent.run_agent`；body 新增 `history`（`{role: user|assistant, content}`，保留最後 6 輪 = 12 則，空白略過，其他 role → 422）、`session_id` ≤64 字。回傳保留舊欄位（`explanation` = `answer`、`attempts` 為 text2sql 實際嘗試次數），新增 `route`、`rewritten`、`answer`、`markdown`、`sources`、`warning`、`audit_id`。
- `POST /api/feedback`：`{audit_id > 0, score: 1|-1, comment ≤1000}` → `audit.add_feedback`；寫入失敗（含 audit_id 不存在）回 503。
- 網頁：送出 `session_id`（頁面記憶體）與前幾輪對話；回答顯示多行文字、`sources` 可展開來源列表（檔名＋頁碼＋標題＋片段；寬螢幕面板預設展開）；`route` 為 docs／chat 時不顯示表格；sql 結果顯示黃色「AI 即時產生」警示；部分失敗時同時顯示回答與「這部分查詢失敗」；👍／👎 真的呼叫 `/api/feedback`（取消不送、失敗還原按鈕並提示）；有 SQL 才顯示嘗試次數。
- `scripts/check_frontend.py` 新增 19 項（共 85 項全過）：docs 無表格、來源展開與內容、session／history 傳送、回饋送出／取消／失敗、警示、部分失敗、寬螢幕來源面板、回答與來源的 XSS。執行方式：`uv run --with playwright python scripts/check_frontend.py`（playwright 不在專案依賴）。
- 驗收：`make test` 316 passed；`make test-llm` 24 passed（含三題 Demo 打真實 API 並送回饋）；真實瀏覽器開 http://localhost:8000：「今年營收最高的三個客戶」→ 表格（華發實業 11,979,390／鴻遠機械／億達企業）＋警示＋SQL，2.5 秒；「鴻遠機械的合約，延遲交貨罰款怎麼算？」→ 文字回答（0.3%、10% 上限）＋來源「銷售合約_鴻遠機械.pdf 第 2 頁 › 第五條」，10.4 秒（dev server 第一次載入 reranker）。
- 備註：`/health` 顯示 LM Studio 另外載入了 `phonon-40m-multilingual`，不是本專案的模型，會多占記憶體。

## T26 管理端點 ✅
- `backend/app/api/admin.py`（已掛進 `main.py`）：
  - `GET /admin/audit?limit=50`（1–500）→ `{count, items}`。
  - `POST /admin/ingest` body `{"path": "data/docs", "force": false}` → 202，背景執行緒重建索引；只允許專案 `data/` 底下存在的資料夾（其他 400）；執行中再送 409。另加 `GET /admin/ingest` 查進度與結果。索引迴圈搬到 `rag/ingest.ingest_folder()`，`scripts/ingest_docs.py` 改為共用（`make ingest` 輸出不變）。
  - `GET /admin/stats` → 今日（Asia/Taipei）問題數、平均延遲、各 route 數量、SQL 查詢數與成功率、錯誤數；預設排除 `session_id` 為 `pytest…` 的測試紀錄，`?include_tests=true` 才包含。
- 驗收（對執行中的 `make dev`）：三個端點皆 HTTP 200。audit 回最近紀錄；ingest 202 → 狀態 done（20 份全部跳過、355 筆）；stats `{"questions": 2, "avg_latency_ms": 6469, "by_route": {"docs": 1, "sql": 1}, "sql_success_rate": 1.0}`（含測試紀錄時 27 題）；`path: "../"` 回 400。`make test` 325 passed、`make test-db` 65 passed。
- 清理：T24 測試曾寫入 2 筆沒有 session_id 的測試紀錄（id 17、18，問題 q0／q1），已刪除，測試改帶 `pytest-` 前綴。
- **注意：管理端點沒有驗證**。`make dev` 只綁 127.0.0.1；若要用 `--host 0.0.0.0` 給同網段的人看 Demo，任何人都能觸發重建索引、讀稽核紀錄。
