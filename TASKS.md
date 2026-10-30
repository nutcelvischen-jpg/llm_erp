# TASKS.md — 開發任務清單（最小任務拆分）

> 規則：按編號順序執行。每個任務有「驗收」指令，通過才 commit 並進下一個。
> 預估：共 32 個任務，熟練的 AI 代理約 3–5 個工作天。
> 「人工」標記 = 需要 Elvis 本人在 Mac 上操作（LM Studio GUI、下載模型），代理只需寫好腳本並說明。

---

## Phase 0：環境與骨架

### T01 建立 repo 骨架
**目標**：建立目錄、git、uv 專案、基本設定檔。
**步驟**
1. 在 `local_llm/` 執行 `git init`（若尚未）。
2. 建立 AGENTS.md「目錄結構」中的所有資料夾（空資料夾放 `.gitkeep`）。
3. 建立 `pyproject.toml`：
```toml
[project]
name = "erp-llm-poc"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic-settings>=2.4",
  "openai>=1.50",
  "httpx>=0.27",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.2",
  "sqlglot>=25.0",
  "qdrant-client[fastembed]>=1.11",
  "docling>=2.0",
  "sentence-transformers>=3.0",
  "apscheduler>=3.10",
  "faker>=28.0",
  "pandas>=2.2",
  "python-multipart>=0.0.9",
  "tenacity>=9.0",
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6"]
[tool.pytest.ini_options]
testpaths = ["backend/tests"]
markers = ["llm: 需要真實 LM Studio 的測試", "db: 需要 Postgres 的測試"]
addopts = "-m 'not llm and not db'"
[tool.ruff]
line-length = 100
```
4. 建立 `.gitignore`：`.venv/ __pycache__/ .env data/docs/*.pdf data/seed/*.csv *.pyc .pytest_cache/ .ruff_cache/ models/`
5. 建立 `.env.example`：
```env
# LM Studio
LLM_BASE_URL=http://localhost:1234/v1
LLM_API_KEY=lm-studio
LLM_MODEL=qwen3.6-35b-a3b
EMBED_MODEL=text-embedding-bge-m3
EMBED_DIM=1024
LLM_TIMEOUT=120

# Postgres
PG_DSN=postgresql+psycopg://erp:erp@localhost:5432/erp_poc

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=erp_docs

# Reranker
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_TOP_N=5

# App
APP_PORT=8000
APP_TZ=Asia/Taipei
LOG_LEVEL=INFO

# LINE (選配)
LINE_CHANNEL_ACCESS_TOKEN=
LINE_TARGET_ID=
```
6. 建立 `Makefile`（Tab 縮排）：
```makefile
.PHONY: setup up down logs dev test test-llm test-db seed ingest eval-sql eval-rag lint

setup:
	uv venv --python 3.12
	uv pip install -e ".[dev]"
	cp -n .env.example .env || true

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

dev:
	uv run uvicorn backend.app.main:app --reload --port 8000

test:
	uv run pytest -q

test-llm:
	uv run pytest -q -m llm

test-db:
	uv run pytest -q -m db

seed:
	uv run python scripts/seed_db.py

ingest:
	uv run python scripts/ingest_docs.py data/docs

eval-sql:
	uv run python scripts/eval_text2sql.py

eval-rag:
	uv run python scripts/eval_rag.py

lint:
	uv run ruff check backend scripts
```
7. 建立空的 `PROGRESS.md`，標題 `# 開發進度`。
8. `backend/__init__.py`、`backend/app/__init__.py`、`backend/app/rag/__init__.py`、`backend/app/agent/__init__.py`、`backend/app/api/__init__.py`、`backend/app/jobs/__init__.py`、`backend/tests/__init__.py` 建空檔。

**驗收**
```bash
make setup && uv run python -c "import fastapi, sqlglot, qdrant_client, docling; print('ok')"
```
輸出 `ok`。

---

### T02 docker-compose（postgres + qdrant）
**目標**：一鍵啟動周邊服務。（原本含 Open WebUI，已於改採自建網頁時移除。）
**步驟**：建立 `docker-compose.yml`：
```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: erp_pg
    environment:
      POSTGRES_USER: erp
      POSTGRES_PASSWORD: erp
      POSTGRES_DB: erp_poc
      TZ: Asia/Taipei
    ports: ["5432:5432"]
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./sql:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U erp -d erp_poc"]
      interval: 5s
      timeout: 3s
      retries: 20

  qdrant:
    image: qdrant/qdrant:latest
    container_name: erp_qdrant
    ports: ["6333:6333", "6334:6334"]
    volumes:
      - qdrant_data:/qdrant/storage


volumes:
  pgdata:
  qdrant_data:
```
注意：`./sql` 掛到 initdb 目錄，所以 **T05–T07 的 SQL 檔會在第一次啟動時自動執行**；若已啟動過，要 `docker compose down -v` 再 `up` 才會重跑。

**驗收**
```bash
make up && sleep 10 && docker compose ps && curl -s localhost:6333/collections && docker exec erp_pg psql -U erp -d erp_poc -c "select 1"
```
三個容器 `running`，Qdrant 回 JSON，psql 回 `1`。

---

### T03 LM Studio 設定與煙霧測試（人工 + 腳本）
**目標**：確認主模型與 embedding 可透過 OpenAI API 呼叫。
**人工步驟（寫進 `docs/LMSTUDIO_SETUP.md` 給 Elvis）**
1. LM Studio → Discover 下載：
   - `Qwen3.6-35B-A3B`（MLX，4bit）
   - `bge-m3`（GGUF，embedding）
2. Developer 分頁 → Start Server（port 1234）→ 勾選「Serve on local network」不需要；勾選「Just-in-Time Model Loading」。
3. 載入兩個模型；Context Length 設 32768；在模型設定關閉「Auto unload」。
4. 終端機執行 `sudo sysctl iogpu.wired_limit_mb=40000`。
5. 記下模型 id（`curl localhost:1234/v1/models`），填進 `.env` 的 `LLM_MODEL`、`EMBED_MODEL`。

**腳本步驟**：建立 `scripts/smoke_lmstudio.py`：
```python
"""檢查 LM Studio chat 與 embedding 是否正常。"""
import os, sys, time
from dotenv import load_dotenv  # 若未安裝: uv pip install python-dotenv 並加入 pyproject
from openai import OpenAI

load_dotenv()
client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])

models = [m.id for m in client.models.list().data]
print("models:", models)
for key in ("LLM_MODEL", "EMBED_MODEL"):
    if os.environ[key] not in models:
        sys.exit(f"[FAIL] {key}={os.environ[key]} 不在 LM Studio 模型清單中")

t = time.time()
r = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "用一句話介紹台中。只回答，不要思考過程。"}],
    max_tokens=100, temperature=0,
)
dt = time.time() - t
txt = r.choices[0].message.content
tps = (r.usage.completion_tokens or 0) / dt if dt else 0
print(f"chat ok ({dt:.1f}s, {tps:.0f} tok/s):", txt.strip()[:80])
if tps < 15:
    print("[WARN] 速度低於 15 tok/s，檢查是否用 MLX 版本與 GPU 記憶體上限")

e = client.embeddings.create(model=os.environ["EMBED_MODEL"], input=["應收帳款", "合約罰款"])
dim = len(e.data[0].embedding)
print("embedding ok, dim =", dim)
if dim != int(os.environ.get("EMBED_DIM", 1024)):
    sys.exit(f"[FAIL] embedding 維度 {dim} != EMBED_DIM")
print("ALL PASS")
```
將 `python-dotenv>=1.0` 加入 pyproject dependencies。

**驗收**：`uv run python scripts/smoke_lmstudio.py` 輸出 `ALL PASS`。

---

### T04 backend 骨架：config + health
**目標**：FastAPI 啟動，`/health` 回報三個依賴狀態。
**步驟**
1. `backend/app/config.py`：
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "lm-studio"
    llm_model: str
    embed_model: str
    embed_dim: int = 1024
    llm_timeout: int = 120
    pg_dsn: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "erp_docs"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_n: int = 5
    app_port: int = 8000
    app_tz: str = "Asia/Taipei"
    log_level: str = "INFO"
    line_channel_access_token: str = ""
    line_target_id: str = ""

settings = Settings()
```
2. `backend/app/db.py`：
```python
from sqlalchemy import create_engine, text
from .config import settings

engine = create_engine(settings.pg_dsn, pool_pre_ping=True, pool_size=5, future=True)

def ping() -> bool:
    with engine.connect() as c:
        return c.execute(text("select 1")).scalar() == 1
```
3. `backend/app/main.py`：
```python
import logging
from fastapi import FastAPI
from .config import settings
from . import db

logging.basicConfig(level=settings.log_level)
app = FastAPI(title="ERP LLM PoC")

@app.get("/health")
def health():
    out = {"postgres": False, "qdrant": False, "lmstudio": False}
    try: out["postgres"] = db.ping()
    except Exception as e: out["postgres_error"] = str(e)[:200]
    try:
        import httpx
        out["qdrant"] = httpx.get(f"{settings.qdrant_url}/collections", timeout=3).status_code == 200
    except Exception as e: out["qdrant_error"] = str(e)[:200]
    try:
        import httpx
        out["lmstudio"] = httpx.get(f"{settings.llm_base_url}/models", timeout=3).status_code == 200
    except Exception as e: out["lmstudio_error"] = str(e)[:200]
    out["ok"] = all(out[k] for k in ("postgres", "qdrant", "lmstudio"))
    return out
```
**驗收**：`make dev &` 後 `curl -s localhost:8000/health` 回 `"ok": true`。

---

## Phase 1：假 ERP 資料

### T05 ERP schema
**目標**：建立一家「台中精密零件公司」的 ERP 核心表。
**步驟**：建立 `sql/001_erp_schema.sql`：
```sql
CREATE SCHEMA IF NOT EXISTS erp;
SET search_path TO erp;

CREATE TABLE customers (
  customer_id   SERIAL PRIMARY KEY,
  customer_code VARCHAR(20) UNIQUE NOT NULL,
  name          VARCHAR(100) NOT NULL,
  industry      VARCHAR(50),
  region        VARCHAR(20),          -- 北部/中部/南部/海外
  sales_rep     VARCHAR(50),          -- 負責業務
  credit_limit  NUMERIC(14,2) DEFAULT 0,
  created_at    DATE NOT NULL
);

CREATE TABLE suppliers (
  supplier_id   SERIAL PRIMARY KEY,
  supplier_code VARCHAR(20) UNIQUE NOT NULL,
  name          VARCHAR(100) NOT NULL,
  lead_time_days INT DEFAULT 14
);

CREATE TABLE products (
  product_id    SERIAL PRIMARY KEY,
  sku           VARCHAR(30) UNIQUE NOT NULL,
  name          VARCHAR(100) NOT NULL,
  category      VARCHAR(50),          -- 軸承/齒輪/墊片/扣件/客製件
  unit          VARCHAR(10) DEFAULT 'PCS',
  std_cost      NUMERIC(12,2) NOT NULL,
  list_price    NUMERIC(12,2) NOT NULL,
  safety_stock  INT DEFAULT 0,
  supplier_id   INT REFERENCES suppliers(supplier_id),
  is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE sales_orders (
  so_id         SERIAL PRIMARY KEY,
  so_no         VARCHAR(20) UNIQUE NOT NULL,
  customer_id   INT NOT NULL REFERENCES customers(customer_id),
  order_date    DATE NOT NULL,
  ship_date     DATE,
  status        VARCHAR(20) NOT NULL  -- 待出貨/已出貨/已結案/取消
);

CREATE TABLE sales_order_lines (
  line_id       SERIAL PRIMARY KEY,
  so_id         INT NOT NULL REFERENCES sales_orders(so_id),
  product_id    INT NOT NULL REFERENCES products(product_id),
  qty           INT NOT NULL,
  unit_price    NUMERIC(12,2) NOT NULL,
  unit_cost     NUMERIC(12,2) NOT NULL
);

CREATE TABLE purchase_orders (
  po_id         SERIAL PRIMARY KEY,
  po_no         VARCHAR(20) UNIQUE NOT NULL,
  supplier_id   INT NOT NULL REFERENCES suppliers(supplier_id),
  order_date    DATE NOT NULL,
  expected_date DATE,
  received_date DATE,
  status        VARCHAR(20) NOT NULL  -- 待交貨/已收貨/取消
);

CREATE TABLE purchase_order_lines (
  line_id       SERIAL PRIMARY KEY,
  po_id         INT NOT NULL REFERENCES purchase_orders(po_id),
  product_id    INT NOT NULL REFERENCES products(product_id),
  qty           INT NOT NULL,
  unit_cost     NUMERIC(12,2) NOT NULL
);

CREATE TABLE inventory (
  product_id    INT PRIMARY KEY REFERENCES products(product_id),
  on_hand       INT NOT NULL DEFAULT 0,
  last_movement DATE
);

CREATE TABLE invoices (
  invoice_id    SERIAL PRIMARY KEY,
  invoice_no    VARCHAR(20) UNIQUE NOT NULL,
  so_id         INT REFERENCES sales_orders(so_id),
  customer_id   INT NOT NULL REFERENCES customers(customer_id),
  invoice_date  DATE NOT NULL,
  due_date      DATE NOT NULL,
  amount        NUMERIC(14,2) NOT NULL,
  paid_amount   NUMERIC(14,2) NOT NULL DEFAULT 0,
  paid_date     DATE
);

CREATE INDEX ON sales_orders(order_date);
CREATE INDEX ON sales_order_lines(so_id);
CREATE INDEX ON invoices(customer_id, due_date);
```
**驗收**
```bash
docker compose down -v && make up && sleep 10 && docker exec erp_pg psql -U erp -d erp_poc -c "\dt erp.*"
```
列出 9 張表。

---

### T06 app schema（稽核、快取、通知）
**步驟**：建立 `sql/002_app_schema.sql`：
```sql
CREATE SCHEMA IF NOT EXISTS app;
SET search_path TO app;

CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  session_id  VARCHAR(64),
  user_id     VARCHAR(64) DEFAULT 'demo',
  route       VARCHAR(20),            -- sql/docs/both/chat
  question    TEXT NOT NULL,
  sql_text    TEXT,
  sql_ok      BOOLEAN,
  sql_rows    INT,
  doc_sources JSONB,
  answer      TEXT,
  latency_ms  INT,
  prompt_tokens INT,
  completion_tokens INT,
  error       TEXT
);

CREATE TABLE sql_examples (            -- Text-to-SQL few-shot
  id          SERIAL PRIMARY KEY,
  question    TEXT NOT NULL,
  sql_text    TEXT NOT NULL,
  tags        TEXT[],
  embedding   REAL[]                   -- 1024 維，PoC 用陣列即可
);

CREATE TABLE notifications (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  job_name    VARCHAR(50),
  channel     VARCHAR(20),             -- line/console
  payload     TEXT,
  sent        BOOLEAN DEFAULT FALSE
);

CREATE TABLE feedback (
  id          BIGSERIAL PRIMARY KEY,
  audit_id    BIGINT REFERENCES audit_log(id),
  score       SMALLINT,                -- 1 讚 / -1 倒讚
  comment     TEXT,
  ts          TIMESTAMPTZ DEFAULT now()
);
```
**驗收**：重建後 `\dt app.*` 列出 4 張表。

---

### T07 假資料產生器
**目標**：產生 2 年（2024-11 ～ 2026-10）有「故事」的資料，讓 Demo 案例有東西可講。
**必須植入的劇情**（Demo 時要講得出來）
- 客戶 `C008 鴻遠機械`：2025 年營收前三，2026 年 6 月起訂單驟減（-40%）。
- 料號 `BRG-6205-2RS` 等 12 個料號：180 天以上無異動（呆滯）。
- 料號 `GEAR-M2-40T`：目前庫存 < 未來 3 週待出貨量（缺料）。
- 客戶 `C015 台陽科技`：有 3 張逾期 60 天以上未收發票。
- 2026 年 Q3 整體毛利率比 2025 年 Q3 低 3 個百分點（原料成本上漲）。

**步驟**：建立 `data/seed/generate.py`（用 Faker + 固定 seed=42，輸出 CSV 到 `data/seed/out/`）與 `scripts/seed_db.py`（用 pandas 讀 CSV → `to_sql` 進 `erp` schema，先 `TRUNCATE ... CASCADE`）。
規模：客戶 40、供應商 10、產品 120、銷售訂單 6,000、採購單 800、發票 5,500。
在 `generate.py` 最後加 `assert_story()`，用 pandas 檢查上面 5 個劇情都成立，不成立就 `raise`。

**驗收**
```bash
make seed && docker exec erp_pg psql -U erp -d erp_poc -c "select count(*) from erp.sales_orders" -c "select name from erp.customers where customer_code='C008'"
```
訂單數 ≈ 6000；回 `鴻遠機械`；`generate.py` 的 `assert_story()` 無錯誤。

---

### T08 唯讀 View 與 schema 說明文件
**目標**：給 LLM 看的是中文欄位 View，不是原始表。
**步驟**
1. `sql/003_views.sql`（在 `erp` schema 下建立，並建立唯讀角色）：
```sql
SET search_path TO erp;

CREATE OR REPLACE VIEW v_銷售明細 AS
SELECT so.so_no AS 訂單編號, so.order_date AS 訂單日期, so.ship_date AS 出貨日期, so.status AS 訂單狀態,
       c.customer_code AS 客戶代號, c.name AS 客戶名稱, c.region AS 客戶區域, c.sales_rep AS 負責業務,
       p.sku AS 料號, p.name AS 品名, p.category AS 產品類別,
       l.qty AS 數量, l.unit_price AS 單價, l.unit_cost AS 單位成本,
       l.qty * l.unit_price AS 銷售金額,
       l.qty * (l.unit_price - l.unit_cost) AS 毛利
FROM sales_order_lines l
JOIN sales_orders so ON so.so_id = l.so_id
JOIN customers c ON c.customer_id = so.customer_id
JOIN products p ON p.product_id = l.product_id
WHERE so.status <> '取消';

CREATE OR REPLACE VIEW v_應收帳款 AS
SELECT i.invoice_no AS 發票號碼, c.customer_code AS 客戶代號, c.name AS 客戶名稱, c.sales_rep AS 負責業務,
       i.invoice_date AS 發票日期, i.due_date AS 到期日, i.amount AS 發票金額, i.paid_amount AS 已收金額,
       i.amount - i.paid_amount AS 未收金額,
       CASE WHEN i.amount - i.paid_amount > 0 AND i.due_date < CURRENT_DATE
            THEN CURRENT_DATE - i.due_date ELSE 0 END AS 逾期天數
FROM invoices i JOIN customers c ON c.customer_id = i.customer_id;

CREATE OR REPLACE VIEW v_庫存狀況 AS
SELECT p.sku AS 料號, p.name AS 品名, p.category AS 產品類別, p.unit AS 單位,
       inv.on_hand AS 現有庫存, p.safety_stock AS 安全庫存, p.std_cost AS 標準成本,
       inv.on_hand * p.std_cost AS 庫存金額,
       inv.last_movement AS 最後異動日, CURRENT_DATE - inv.last_movement AS 未異動天數,
       s.name AS 供應商, s.lead_time_days AS 供應商交期天數,
       COALESCE((SELECT SUM(l.qty) FROM sales_order_lines l JOIN sales_orders so ON so.so_id=l.so_id
                 WHERE l.product_id=p.product_id AND so.status='待出貨'),0) AS 待出貨數量,
       COALESCE((SELECT SUM(l.qty) FROM purchase_order_lines l JOIN purchase_orders po ON po.po_id=l.po_id
                 WHERE l.product_id=p.product_id AND po.status='待交貨'),0) AS 在途數量
FROM products p
JOIN inventory inv ON inv.product_id = p.product_id
LEFT JOIN suppliers s ON s.supplier_id = p.supplier_id
WHERE p.is_active;

CREATE OR REPLACE VIEW v_採購明細 AS
SELECT po.po_no AS 採購單號, po.order_date AS 採購日期, po.expected_date AS 預計到貨日, po.received_date AS 實際到貨日,
       po.status AS 採購狀態, s.name AS 供應商, p.sku AS 料號, p.name AS 品名, l.qty AS 數量, l.unit_cost AS 單位成本,
       l.qty * l.unit_cost AS 採購金額
FROM purchase_order_lines l
JOIN purchase_orders po ON po.po_id = l.po_id
JOIN suppliers s ON s.supplier_id = po.supplier_id
JOIN products p ON p.product_id = l.product_id;

-- 唯讀角色給 LLM 查詢用
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='llm_reader') THEN
    CREATE ROLE llm_reader LOGIN PASSWORD 'llm_reader';
  END IF;
END $$;
GRANT USAGE ON SCHEMA erp TO llm_reader;
GRANT SELECT ON v_銷售明細, v_應收帳款, v_庫存狀況, v_採購明細 TO llm_reader;
```
2. `.env.example` 新增 `PG_DSN_READONLY=postgresql+psycopg://llm_reader:llm_reader@localhost:5432/erp_poc`，`config.py` 新增 `pg_dsn_readonly`。
3. 建立 `sql/schema_doc.md`：四個 View 的欄位、型別、中文說明、範例值、常見陷阱（例如「毛利率 = SUM(毛利)/SUM(銷售金額)，不要平均每列毛利率」「同期比較用 EXTRACT(YEAR/MONTH)」）。這份文件會原封不動放進 Text-to-SQL 的 system prompt，**寫清楚比寫短重要**。

**驗收**
```bash
docker compose down -v && make up && sleep 10 && make seed && \
docker exec erp_pg psql -U llm_reader -d erp_poc -c "select 客戶名稱, sum(銷售金額) from erp.v_銷售明細 group by 1 order by 2 desc limit 3" && \
docker exec erp_pg psql -U llm_reader -d erp_poc -c "delete from erp.customers" ; echo "(上一行應該 permission denied)"
```

---

## Phase 2：LLM 基礎元件

### T09 LLM 客戶端封裝
**目標**：`backend/app/llm.py` 提供 `chat()`、`chat_json()`、`embed()`，含 retry、timeout、token 統計、去除 Qwen 的 `<think>` 區塊。
**介面**
```python
from dataclasses import dataclass
@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int

def chat(messages: list[dict], temperature=0.1, max_tokens=1024, json_mode=False) -> ChatResult: ...
def chat_json(messages, schema_hint: str, max_tokens=1024) -> dict:  # 解析失敗自動重試 1 次並附上錯誤訊息
def embed(texts: list[str]) -> list[list[float]]:  # 批次 32 筆
def strip_think(text: str) -> str:  # 移除 <think>...</think>
```
**細節**
- 用 `openai` SDK，`timeout=settings.llm_timeout`，`tenacity` retry 2 次（只對連線錯誤）。
- Qwen3.6：每次 chat 呼叫預設帶 `extra_body={"reasoning_effort": "none"}`（已實測：思考 token 為 0、延遲約 0.4 秒；`/no_think` 與 `chat_template_kwargs.enable_thinking` 皆無效）。`chat()` 提供 `think: bool = False` 參數，為 True 時才不帶此參數。仍以 `strip_think` 與去除前後空白（content 開頭可能有 `\n\n`）防呆。
- `chat_json`：用 `response_format={"type":"json_object"}`；若 LM Studio 不支援則退回 prompt 要求「只輸出 JSON」並以正則抓第一個 `{...}`。

**測試** `backend/tests/test_llm.py`
- 單元（不需 LLM）：`strip_think` 三個案例；`chat_json` 的 JSON 擷取函式對 ```json 區塊```、前後有文字、巢狀 `{}` 三種輸入。
- `@pytest.mark.llm`：`chat([{"role":"user","content":"回答 OK"}])` 包含 `OK`；`embed(["a","b"])` 長度 2、維度 1024。

**驗收**：`make test` 通過；`make test-llm` 通過。

---

### T10 Reranker
**目標**：`backend/app/reranker.py`，CPU 載入 `bge-reranker-v2-m3`，提供 `rerank(query, docs: list[str], top_n) -> list[tuple[int, float]]`（回傳原索引與分數，分數高到低）。
**細節**
- 用 `sentence_transformers.CrossEncoder`，lazy load（第一次呼叫才載入），模組層級單例。
- 第一次下載模型約 2.2 GB，寫在 PROGRESS.md 提醒。
- 20 對文件在 M3 Max CPU 應 < 2 秒；超過 3 秒記 log warning。

**測試**：`@pytest.mark.llm`（因為要下載模型）：query「合約延遲交貨罰款」，docs 三段（一段談罰款、一段談付款條件、一段談公司簡介），罰款段排第一。

**驗收**：`make test-llm` 通過。

---

## Phase 3：Text-to-SQL

### T11 SQL 守門員 `sql_guard.py`
**目標**：LLM 產生的 SQL 一律經過驗證、改寫，才可執行。
**規則**
1. 用 `sqlglot.parse_one(sql, read="postgres")`；解析失敗 → 拒絕。
2. 只允許單一 `SELECT`（含 CTE）；出現 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/COPY/CREATE、分號後第二句 → 拒絕。
3. 只允許引用白名單 View：`v_銷售明細, v_應收帳款, v_庫存狀況, v_採購明細`（可帶 `erp.` 前綴）；其他表名 → 拒絕。
4. 禁止 `pg_` 開頭的函式與 `information_schema`。
5. 若最外層沒有 `LIMIT` → 自動加 `LIMIT 200`；若有且 > 1000 → 改成 1000。
6. 回傳 `GuardResult(ok: bool, sql: str, reason: str)`。

**測試** `backend/tests/test_sql_guard.py`（至少 10 案例）：合法查詢加 LIMIT；含 DELETE 拒絕；兩句拒絕；引用 `erp.customers` 拒絕；CTE 合法；LIMIT 5000 被壓到 1000；`select * from v_庫存狀況; drop table x` 拒絕；中文欄位與 View 名稱正確解析。

**驗收**：`make test` 通過。

---

### T12 Few-shot 範例庫
**目標**：20 組「問題 → SQL」種子範例，存進 `app.sql_examples` 並向量化，查詢時挑最相近 4 組。
**步驟**
1. 建立 `data/seed/sql_examples.yaml`，20 組，涵蓋：本月／上月／今年累計、同期比較、Top N 客戶、毛利率、逾期應收、呆滯庫存、缺料、業務業績、產品類別占比、供應商交期達成率。每組 SQL 必須先在 psql 跑過確認正確。
2. `scripts/load_sql_examples.py`：讀 YAML → `embed(question)` → upsert 到 `app.sql_examples`。
3. `backend/app/text2sql.py` 內 `pick_examples(question, k=4)`：取出全部範例 embedding，用 numpy cosine 計算（PoC 規模 < 100 筆不需向量庫）。
4. `Makefile` 加 `load-examples` target。

**驗收**：`make load-examples` 後 `select count(*) from app.sql_examples` = 20；`pick_examples("哪個客戶欠最多錢")` 第一筆是逾期應收相關。

---

### T13 Text-to-SQL 主流程
**目標**：`text2sql.run(question) -> SqlAnswer`。
**流程**
```
question
 → pick_examples(4)
 → system prompt = schema_doc.md + 規則 + 今天日期 + few-shot
 → chat_json → {"sql": "...", "explanation": "..."}
 → sql_guard.validate
 → 失敗：把錯誤回饋給 LLM 重生一次（最多 2 次）
 → 用 pg_dsn_readonly 執行，statement_timeout=10s
 → 結果 (columns, rows ≤200) + sql + explanation
```
**Prompt 規則（寫進 prompts.py）**
- 只能用四個 View；欄位名稱用中文原名並加雙引號。
- 日期一律相對「今天 = {today}」計算；「本月」= 當月 1 日至今。
- 金額欄位 `ROUND(..., 0)`。
- 排序後要 LIMIT。
- 只輸出 JSON。

**回傳結構**
```python
@dataclass
class SqlAnswer:
    sql: str; explanation: str; columns: list[str]; rows: list[list]; row_count: int
    attempts: int; error: str | None
```
**測試**：`@pytest.mark.llm @pytest.mark.db`：三題——「今年營收最高的 3 個客戶」「目前逾期超過 60 天的應收有哪些客戶」「哪些料號超過 180 天沒異動」，皆 `error is None` 且 `row_count > 0`，第三題結果包含 `BRG-6205-2RS`。

**驗收**：`make test-llm` 通過。

---

### T13b 聊天網頁（自建單頁，讓介面提早可用）
**決策**：介面採「自建單頁網頁」，由 FastAPI 直接提供；單一 HTML 檔 + 原生 JavaScript，不需要 Node 建置。不使用 Open WebUI、Streamlit、Next.js。
**目標**：在瀏覽器（http://localhost:8000）用中文問商業問題，看到說明、表格與可展開的 SQL。此時只接 Text-to-SQL；RAG 與 Agent 路由在 T22–T25 再接上；圖表與視覺打磨在 T13c。
**步驟**
1. `backend/app/api/chat.py`（`APIRouter`，在 `main.py` 以 `app.include_router` 掛上）：
   - `POST /api/chat`，body `{"question": str, "session_id": str | null}`。`question` 去除前後空白後長度需為 1–500，否則 HTTP 422。
   - 用一般 `def` 端點（FastAPI 會放進 threadpool），呼叫 `text2sql.run(question)`，回傳 JSON：`{"question","explanation","sql","columns","rows","row_count","attempts","error","latency_ms"}`（rows 最多 200 列）。`error` 非空時仍回 HTTP 200（錯誤是業務結果，不是伺服器故障）。
2. `main.py`：用 `StaticFiles` 把 `backend/app/web/` 掛在 `/static`；`GET /` 以 `FileResponse` 回傳 `backend/app/web/index.html`。
3. `backend/app/web/index.html`（單一檔案，原生 HTML/CSS/JS，**不得引用外部 CDN**）：
   - 版面：上方標題「ERP 智慧助理」；中間是對話串；下方是輸入框（Enter 送出、Shift+Enter 換行）與送出鈕。對話串為空時，顯示 6 個範例問題按鈕（點一下即送出）：
     1. 哪個客戶今年的營收比去年同期掉最多？
     2. 目前逾期超過 60 天的應收帳款有哪些客戶？
     3. 哪些料號超過 180 天沒有異動？壓了多少庫存金額？
     4. 依目前待出貨的訂單，哪些料號會缺料？建議採購多少？
     5. 今年的毛利率比去年同期好還是差？
     6. 各供應商的準時交貨率
   - 送出後顯示「思考中…」與已經過的秒數；失敗（HTTP 錯誤、逾時、`error` 非空）顯示紅色提示框，內容為錯誤訊息。
   - 回答卡片：一句說明（`explanation`）、表格（最多顯示 20 列；數字加千分位；`null` 顯示 `-`；超過 20 列時加註「僅顯示前 20 列，共 N 列」）、可展開的「查詢的 SQL」區塊與「複製 SQL」按鈕、小字「耗時 X.X 秒・嘗試 N 次」。
   - 安全：所有後端傳來的文字一律用 `textContent` 或 DOM API 建立節點，**禁止用 `innerHTML` 插入**使用者或模型產生的內容。
   - 狀態只放在記憶體變數，不使用 localStorage。
4. 移除 Open WebUI：`docker-compose.yml` 已刪除該服務；Mac 上執行 `docker compose up -d --remove-orphans` 停掉舊容器，`docker volume rm local_llm_webui_data` 清掉資料卷。`make dev` 維持綁 127.0.0.1；之後要給同網段的人看 Demo，才手動加 `--host 0.0.0.0`。

**測試**
- 單元（FastAPI `TestClient`，`text2sql.run` 以 monkeypatch 換成假的）：`GET /` 回 200 且含「ERP 智慧助理」；`POST /api/chat` 回傳含上述全部欄位；空字串與超過 500 字回 422；`error` 非空時仍為 200 且 JSON 帶 `error`；`latency_ms` 為整數。
- 前端檢查（選配，`scripts/check_frontend.py`，需 playwright）：開頁面、攔截 `/api/chat` 回傳假資料，驗證表格列數、超過 20 列的提示、錯誤框、SQL 展開；回傳內容含 `<img src=x onerror=...>` 與 `<script>` 時**不會被執行**。
- `@pytest.mark.llm @pytest.mark.db`：真實問「今年營收最高的 3 個客戶」，`row_count == 3`。

**驗收**：`make dev` 後開啟 http://localhost:8000，點範例問題或輸入「今年營收最高的三個客戶」，15 秒內看到說明、表格與可展開的 SQL。

---

### T13c 介面打磨：圖表與證據面板（已完成）
**目標**：讓 Demo 畫面更有說服力。仍是單一 HTML 檔，圖表函式庫放 `backend/app/web/vendor/`（`npm pack echarts` 取得 `echarts.min.js`，連同 LICENSE、NOTICE；不得引用 CDN）。
**實作內容**
1. 寬螢幕（≥1000px）左右兩欄：左側對話（卡片只放說明與 5 列預覽）、右側「分析結果」面板，由上而下顯示圖表、完整資料表（最多 200 列）、SQL（預設展開）。點舊的回答卡片可切換面板內容。窄螢幕自動改為單欄，圖表、表格、SQL 放進卡片內。
2. 自動圖表：1 個標籤欄 + 1–3 個數值欄、2–40 列才畫。月份／日期／季度畫折線，其餘畫長條，類別超過 8 個改橫條；「年＋季」合併成 2025Q3；數值量級差超過 20 倍用雙 Y 軸；含文字欄、只有 1 列、第一欄是一般數字（代碼）時不畫圖。座標軸數字以「萬／億」顯示。
3. 品牌可客製：檔案開頭的 `CONFIG.brand`（名稱、標語、主色、圖表色盤）與 `CONFIG.examples`（範例問題），改一處即可。
4. 細節：處理中面板顯示骨架畫面、表格欄位標題可點擊排序（升冪／降冪／還原，空值永遠在最後）、按鈕皆有 aria-label、圖表 tooltip 對文字做 HTML 跳脫。
5. 👍／👎 回饋按鈕：目前只切換畫面狀態；寫入 `app.feedback` 在 T25。
**驗證**：`python3 scripts/check_frontend.py [截圖資料夾]`（66 項真實瀏覽器檢查，含圖表 tooltip 的 XSS）。
**驗收**：問「最近 6 個月每個月的營收趨勢」自動出折線圖；問「今年營收最高的 3 個客戶」出長條圖；右側面板同時顯示圖表、表格與 SQL。

---

### T14 Text-to-SQL 評估腳本（已完成）
**目標**：量化 Text-to-SQL 的正確率與延遲；之後每次改 prompt、範例或 `schema_doc.md` 都要重跑，確認沒有退步。
**內容**
- `data/golden/text2sql.yaml`：30 題（營收、毛利、客戶、業績、訂單、產品、應收、庫存、採購各類，另有 4 題「應該婉拒」：薪資、競爭對手、天氣、要求修改資料）。題目措辭刻意跟 `sql_examples.yaml` 的範例不同，測的是泛化能力。
- 每題一種檢查：`rows_match`（附**參考 SQL**，評估時才在資料庫執行，所以題目不會隨日期過期；容許答案多帶欄位、順序不同，數字只容許四捨五入誤差）、`contains`、`row_count`、`row_count_gt`、`refusal`。
- `backend/app/eval_checks.py`：比對邏輯（純函式，有單元測試）。數字容差依精度判斷：參考值為整數只容許 ±0.5，毛利率這類小數只容許 ±0.055（答案四捨五入成整數則 ±0.55），避免少算一筆也被判對。
- `scripts/eval_text2sql.py`：`make eval-sql` 跑全部；`--only Q01,Q05`、`--category 應收`、`--threshold 0.8`（低於門檻結束碼為 1）。輸出每題結果與耗時、總正確率、各類別統計、平均與 P95 延遲、平均嘗試次數，報告存 `data/golden/report_text2sql_<日期>.md`（失敗題會附上產生的 SQL 與參考 SQL）。
- 測試：`test_eval_checks.py`、`test_golden_set.py`（含需要資料庫的「所有參考 SQL 都有結果」）。
**規則**：沒達標時，補 few-shot 範例或 `schema_doc.md`，**不要改黃金題**。（例外：若參考 SQL 對這份資料沒有結果，表示題目本身無效，才可修題。）
**驗收**：`make eval-sql` 正確率 ≥ 80%。

---

### 架構調整說明：模板優先（T14b–T14f，插在 T14 與 T15 之間）
**決策**：為了降低 SQL 的不確定性，改為「模板優先」。LLM 只做兩件事：① 辨識意圖並填參數、② 看結果寫回覆；**要執行的 SQL 一律由程式寫死（參數化模板）**。
```
問題 → ① LLM 辨識「模板＋參數」→ ② 程式驗證參數（日期、名稱比對由程式算）→ ③ 執行寫死的 SQL（值一律用綁定參數）→ ④ LLM 看結果回覆（數字須能在結果中找到）
```
- 沒命中任何模板：預設婉拒並推薦相近問題，同時記錄下來供日後做成新模板；管理員可用 `ALLOW_AI_FALLBACK=true` 開啟 AI 兜底（走 T13 的 Text-to-SQL，回答必須明顯標示「AI 即時產生，請查核」）。
- T11 守門員、T12 範例、T13 Text-to-SQL、T14 評估都保留：守門員仍檢查每一句模板 SQL；範例變成意圖辨識的素材；Text-to-SQL 是兜底；黃金題用來驗證模板與意圖。
- **已驗證的技術細節（請照做）**：
  1. 守門員會把 `:name` 改寫成 `%(name)s`，SQLAlchemy 再跳脫成 `%%` 導致語法錯誤。解法：`validate()` 回傳前用 `re.sub(r"%\((\w+)\)s", r":\1", sql)` 還原。
  2. `LIMIT :top_n` 會被守門員當成非常數 LIMIT 壓成 1000。解法：`top_n` 等已驗證的整數**直接寫成常數**（`LIMIT 5`），不要用綁定參數。
  3. 可選條件寫成 `(CAST(:customer AS text) IS NULL OR "客戶名稱" = :customer)`，傳入 `None` 就不篩選。
  4. 字串、日期、數字等「值」一律用 `:name` 綁定；只有欄位名稱、排序方向這類「結構」可由程式從**白名單對照表**插入，絕不插入使用者或 LLM 提供的字串。

---

### T14b 查詢目錄骨架：資料結構、期間解析、實體比對
**目標**：模板式查詢的共用基礎（不含任何具體模板）。檔案放 `backend/app/catalog/`：`__init__.py`、`base.py`、`periods.py`、`entities.py`。
**步驟**
1. `base.py`：
```python
@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Literal["period", "enum", "int", "entity"]
    label: str                                    # 中文名稱，用於提示與反問
    required: bool = False
    default: Any = None
    choices: dict[str, list[str]] | None = None   # enum：{標準值: [同義詞…]}，標準值同時是白名單對照表的 key
    entity: Literal["customer", "supplier", "sku", "rep"] | None = None
    min: int | None = None
    max: int | None = None

@dataclass
class BuiltQuery:
    sql: str            # 只含 :name 綁定參數；已通過 sql_guard.validate
    binds: dict

@dataclass
class QueryTemplate:
    id: str
    title: str                                    # 例如「營收排名」
    description: str                              # 給 LLM 看的一句話說明
    examples: list[str]                           # 意圖辨識用的範例說法（至少 5 句，措辭多樣）
    params: list[ParamSpec]
    build: Callable[[dict], BuiltQuery]           # 純函式：已驗證的參數 → SQL 與綁定參數
    facts: Callable[[list[str], list[list]], dict]  # 程式算出的事實（總額、第一名、占比…），供回覆引用
    summary: Callable[[dict], str]                # 固定句型摘要（LLM 失敗或數字檢查不過時使用）
```
2. `sql_guard.py` 小修：`validate()` 回傳前，把 `%(name)s` 還原成 `:name`（見上方技術細節 1），並補測試：綁定參數可通過、保留名稱、LIKE 的 `%` 不受影響、`LIMIT 5` 常數保留。
3. `periods.py`：`resolve_period(code: str, today: date) -> Period(date_from, date_to, label)`（`date_to` 為**不含**的上界）。代碼：
   - `this_month`、`last_month`、`this_quarter`、`last_quarter`、`this_year`、`last_year`
   - `ytd`（今年 1/1 到今天）、`last_n_days:N`、`last_n_months:N`（含本月；從 N−1 個月前的 1 日起）、`all`
   - `quarter:<this_year|last_year|YYYY>:<1-4>`、`month:<this_year|last_year|YYYY>:<1-12>`
   - 另提供 `compare_periods(kind, today)`：`yoy_ytd`（今年累計 vs 去年同期，2/29 要處理）、`mom`（本月累計 vs 上月同期）、`qoq`。
   - `label` 為中文說明，例如「2026 年（今年）」「2026 年 Q3」。不合法的代碼丟 `ValueError`。
4. `entities.py`：`EntityIndex(providers)`，`providers` 是 `{kind: () -> list[str]}`（正式版從資料庫讀客戶／供應商／料號／業務名單；測試時注入假名單）。`match(kind, text) -> Match(status, value, options)`：
   - 正規化：NFKC、去空白、料號不分大小寫、比對時忽略「股份有限公司／有限公司／公司」。
   - `exact`（完全相同）→ `fuzzy`（唯一的包含關係，或 difflib 相似度 ≥ 0.75 且與第二名差 ≥ 0.1）→ `ambiguous`（多個接近，`options` 最多 5 個）→ `none`。
**測試**（純單元，不需服務）：`test_periods.py` 以固定的 `today`（2026-10-30、2026-03-31、2024-02-29、2026-01-01）逐一驗證每種代碼的起訖與跨年、閏年；`test_entities.py`：完全相同、省略「公司」、唯一包含、模糊、不明確、查無、料號大小寫。
**驗收**：`make test` 通過。

---

### T14c 查詢模板（16 個）與黃金題對照
**目標**：把日常問題做成寫死的模板。檔案：`backend/app/catalog/templates/`（`sales.py`、`receivable.py`、`inventory.py`、`purchasing.py`）與 `backend/app/catalog/registry.py`（`TEMPLATES: dict[str, QueryTemplate]`）。
**通用規則**
- 只用四個 View；值一律綁定參數；`top_n` 等整數寫成常數；維度、指標、排序方向由白名單對照表決定（例如 `DIMENSIONS = {"客戶": '"客戶名稱"', "產品類別": '"產品類別"', …}`）。
- 金額 `ROUND(…, 0)`、比率 `ROUND(100.0 * … , 1)`；日期區間用 `>= :date_from AND < :date_to`。
- 每個模板都要有：≥ 5 句 `examples`、`facts()`、`summary()`，並通過 `sql_guard.validate`。
**16 個模板**
| id | 用途 | 主要參數（括號為預設值）|
|---|---|---|
| `sales_rank` | 排名：客戶／產品／料號／產品類別／業務／區域 × 營收／毛利／毛利率／數量／訂單數／營收占比 | dimension、metric（營收）、period（this_year）、top_n（5，上限 50）、order（desc）|
| `sales_total` | 合計：一次回傳 營收、毛利、毛利率(%)、訂單數 | period（this_year）、customer?、category?、rep?、region? |
| `sales_trend` | 趨勢（也可取最高／最低的月份） | grain（月／季）、period（last_n_months:6）、customer?、order（time／desc／asc）、top_n? |
| `sales_compare` | 同期比較 | compare（yoy_ytd／mom／qoq）、metric、dimension（整體／客戶／產品類別／業務／區域）、top_n（10）、order（下滑最多／成長最多）|
| `sales_largest_orders` | 金額最大的訂單 | period、top_n（5）|
| `ar_summary` | 應收合計：未收總額、未收張數、客戶數 | customer?、overdue_gt?（不填＝全部未收；0＝已逾期；30＝逾期超過 30 天）|
| `ar_by_customer` | 欠款／逾期客戶清單 | overdue_gt?、top_n（10）、order |
| `ar_invoices` | 某客戶的逾期發票明細 | customer（必填）、overdue_gt（0）|
| `ar_aging` | 帳齡分佈（1–30、31–60、61 天以上） | — |
| `stock_dead` | 呆滯料號明細與庫存金額 | idle_days（180）、top_n（50）|
| `stock_dead_total` | 呆滯庫存合計：料號數、庫存金額 | idle_days（180）|
| `stock_shortage` | 缺料與建議採購量 | — |
| `stock_lookup` | 單一料號的庫存、安全庫存、最後異動日、供應商 | sku（必填）|
| `stock_rank` | 庫存排名 | metric（庫存金額）、top_n（10）、order |
| `supplier_ontime` | 供應商準時交貨率 | order（最低）、top_n（10）|
| `purchase_summary` | 採購金額合計或依供應商彙總 | period、status（全部有效／待交貨／已收貨）、group（無／供應商）|

**黃金題對照**：建立 `data/golden/template_map.yaml`，把 T14 的 26 題資料型問題對應到「模板＋參數」（婉拒題不需要）：
`Q01 sales_rank{客戶,營收,this_year,5}`、`Q02 sales_total{this_year}`、`Q03 sales_total{this_month}`、`Q04 sales_total{last_year}`、`Q05 sales_total{this_year, customer:華發實業}`、`Q06 sales_total{last_year, customer:鴻遠機械}`、`Q07 sales_rank{產品類別,毛利率,this_year,50}`、`Q08 sales_rank{業務,營收,this_year,1}`、`Q09 sales_trend{月,this_year,order:desc,top_n:1}`、`Q10 sales_rank{區域,營收占比,this_year,50}`、`Q11 sales_largest_orders{this_year,1}`、`Q12 sales_rank{料號,數量,this_year,3}`、`Q13 sales_total{quarter:last_year:3}`、`Q14 ar_summary{}`、`Q15 ar_summary{overdue_gt:30}`、`Q16 ar_summary{customer:台陽科技}`、`Q17 ar_summary{customer:精興金屬, overdue_gt:0}`、`Q18 ar_by_customer{overdue_gt:0, top_n:50}`、`Q19 ar_by_customer{overdue_gt:60, top_n:50}`、`Q20 stock_rank{庫存金額,5}`、`Q21 stock_shortage{}`、`Q22 stock_dead_total{}`、`Q23 stock_lookup{BRG-6205-2RS}`、`Q24 supplier_ontime{最低,1}`、`Q25 purchase_summary{this_year,全部有效}`、`Q26 purchase_summary{all,待交貨}`。
**測試**
- 單元：每個模板 `build()` 產生的 SQL 通過守門員；參數缺漏／越界的行為；SQL 中**不含**任何使用者提供的字串（用含單引號與分號的參數驗證只出現在 binds）。
- `@pytest.mark.db`：每個模板用預設參數跑真實資料庫皆有結果；**`test_template_map.py`：26 題各自執行對應模板，結果須通過 T14 的 `eval_checks.rows_match`（與參考 SQL 比對）或 `contains`**，這證明模板本身與 AI 產生 SQL 的標準答案一致。
- `facts()` 與 `summary()`：以範例資料驗證每個模板都能產生非空、不含 `None` 的摘要。
**驗收**：`make test`、`make test-db` 通過（含 26 題對照）。

---

### T14d 意圖辨識器
**目標**：問題 → 模板＋參數，或反問，或未命中。檔案：`backend/app/catalog/intent.py`；新增 `sql/004_catalog.sql`（`app.unmatched_questions`：id、ts、question、candidates jsonb）。
**流程 `recognize(question, today) -> Intent`**
1. **候選**：啟動時對所有模板的 `examples` 做 embedding（存記憶體）；問題的 embedding 與各模板取最大餘弦相似度，取前 5 名。最高分低於 `INTENT_MIN_SIM`（預設 0.35，於評估時校準）直接判未命中，**不呼叫 LLM**。
2. **LLM（`llm.chat_json`，溫度 0、關閉思考）**：prompt 含今天日期、5 個候選的 id／title／description／參數規格（列出標準值）。規則：不確定就回 `{"template_id": null}`；期間一律輸出代碼，**不要自己算日期**；客戶、供應商、料號照使用者說法原樣填入（由程式比對）。輸出 `{"template_id": "...", "params": {...}}`。
3. **程式驗證 `normalize_params`**：template_id 不在候選→未命中；enum 接受標準值或同義詞，不合法用預設值（必填則反問）；int 夾在 [min, max]；period 以語法驗證，失敗用預設；entity 用 `EntityIndex`（exact／fuzzy 自動替換並記錄「已將『華發』視為『華發實業』」；ambiguous 反問並列出選項；none 反問「找不到…」並推薦相近名稱）；未知參數丟棄；缺必填→反問。
4. **回傳** `Intent(kind: template|clarify|no_match, template_id, params, params_readable: list[str], message, options, candidates)`。`params_readable` 例如 `["維度：客戶", "指標：營收", "期間：2026 年（今年）", "前 5 名"]`。未命中時寫入 `app.unmatched_questions`。LLM 失敗時回 `no_match` 並附「AI 暫時無法使用」。
**意圖黃金集**：`data/golden/intents.yaml`，40 題（16 個模板各至少 2 題，措辭與 `examples` 不同，含 8 題「不支援」：薪資、天氣、競爭對手、修改資料、文件問題等）；`scripts/eval_intents.py`（`make eval-intent`）輸出：模板正確率、參數正確率、不支援題的誤判率。**門檻**：模板 ≥ 95%、參數 ≥ 90%、不支援題誤判 0。
**測試**：以假的 embedding／LLM 驗證：候選排序、低於門檻不呼叫 LLM、不存在的 template_id、同義詞、夾值、實體的四種狀態、缺必填反問、未知參數、LLM 例外。真實測試 `@llm @db` 跑意圖黃金集。
**驗收**：`make eval-intent` 達門檻。

---

### T14e 結果回覆（LLM 看結果、不可編造數字）
**目標**：`backend/app/catalog/answer.py`：`summarize(question, template, params_readable, columns, rows, facts) -> AnswerText(text, source)`。
**規則**
- `facts` 由模板的 `facts()` 以**程式**算出（總額、第一名與占比、最高／最低月份、變化金額與百分比、件數…），數值連同預先格式化的字串一起給 LLM；LLM 不做任何運算。
- LLM prompt：問題、查詢說明、結果表（最多 20 列）、facts。要求：繁體中文、2–3 句、先給結論；**只能使用 facts 與表格中出現的數字**；不推測原因；不提 SQL。
- **數字檢查** `numbers_supported(text, rows, facts) -> (ok, 未獲支持的數字)`：擷取回覆中的數字（含千分位、小數、`%`、`萬`、`億`），與「結果與 facts 的所有數值（含萬／億換算，容許四捨五入）」比對；允許的例外：年份與月份（來自期間說明或結果日期）、排名序數（不超過 top_n 與列數）。**檢查不過，或 LLM 失敗，就改用模板的 `summary()` 固定句型**，並標記 `source="fixed"`；絕不顯示未經檢查的數字。
**測試**：數字擷取的邊界（`1,234.5`、`12.3%`、`1,198 萬`、中文數字不當數字）；支援／不支援的判斷；16 個模板的 `summary()` 皆可產生；LLM 失敗時退回固定句型；真實測試 `@llm`：3 個模板的回覆都通過數字檢查。
**驗收**：`make test`、`make test-llm` 通過。

---

### T14f 整合：`catalog.answer_question`、API 與網頁
**目標**：把 T14b–T14e 串起來，並接上 `/api/chat` 與網頁。
**步驟**
1. `backend/app/catalog/runner.py`：`answer_question(question, today=None) -> CatalogAnswer`。流程：`recognize` →（clarify／no_match 直接回傳）→ 執行模板（`engine_ro`、`text(sql)` 加綁定參數、逾時 10 秒）→ `summarize`。欄位：`mode`（template／ai_sql／clarify／no_match／error）、`template_id`、`template_title`、`params_readable`、`columns`、`rows`、`row_count`、`sql`（含 `:name`）、`binds`、`answer`、`answer_source`、`options`、`suggestions`、`warning`、`error`、`latency_ms`。
2. 未命中：`ALLOW_AI_FALLBACK=false`（預設，新增到 `.env.example` 與 `config.py`）時，回覆「這類問題目前還不支援」並附 3 個最相近的範例問題；為 `true` 時改走 `text2sql.run`，`mode="ai_sql"`、`warning="AI 即時產生的查詢，請查核 SQL 與結果"`。（管理員在頁面切換開關留到 T26。）
3. `/api/chat` 改呼叫 `answer_question`；回傳保留舊欄位（`explanation` 放 `answer`），新增上述欄位。
4. 網頁：卡片上方顯示「標準查詢：營收排名」徽章與 `params_readable` 標籤；`mode=ai_sql` 顯示醒目的黃色警示；`clarify` 以按鈕呈現 `options`（點選後以「原問題（指：選項）」重新送出）；`no_match` 顯示建議問題按鈕（點選即送出）；SQL 區塊同時顯示綁定參數。更新 `scripts/check_frontend.py` 對應檢查。
5. `scripts/eval_text2sql.py` 新增 `--engine template|ai`（預設 template）：template 模式呼叫 `answer_question`，用同一份 30 題黃金題驗證。
**測試**：單元（假的 recognize／LLM）涵蓋 template、clarify、no_match、兜底開關、錯誤；API 欄位；網頁檢查；真實測試跑三個 Demo 問題。
**驗收**：`make eval-sql`（template 模式）資料型 26 題 ≥ 95%、4 題婉拒題全部為 no_match；再用 `--engine ai` 跑一次，兩份報告並列比較正確率、平均延遲與嘗試次數。

---

### T15 測試文件準備
**目標**：20 份繁中 PDF 放進 `data/docs/`，由代理**自行生成**（不要抓網路檔案）。
**步驟**：寫 `data/docs/make_docs.py`，用 `reportlab`（加進 dev 依賴）或 `docx → pdf` 產生：
- 5 份客戶銷售合約（含交期、延遲罰款條款「每日按未交貨金額 0.3%，上限 10%」、付款條件、保固），客戶名稱必須對應 ERP 的客戶：**鴻遠機械（C008）、台陽科技（C015）**，其餘三份取 ERP 的 C001–C003（T20 的測試會問「鴻遠機械的合約」，所以鴻遠機械那份必須存在，且含「延遲交貨每日按未交貨金額 0.3%，上限 10%」條款）。
- 5 份供應商採購合約。
- 5 份內部 SOP（請假、報支、驗收、客訴處理、出貨檢驗）。
- 3 份產品規格書（含表格）。
- 2 份人資規章（加班費計算、特休天數表）。
每份 3–8 頁，要有標題階層與頁碼，**至少 3 份含表格**。中文字型用系統 `PingFang.ttc` 或 Noto Sans CJK TC。

**驗收**：`ls data/docs/*.pdf | wc -l` = 20；隨機開一份確認中文正常、有頁碼。

---

### T16 文件解析 `rag/parse.py`
**目標**：PDF → 帶頁碼與標題階層的區塊清單。
**介面**
```python
@dataclass
class Block:
    doc_id: str; file_name: str; page: int; heading_path: list[str]; kind: str  # text/table
    text: str
def parse_pdf(path: Path) -> list[Block]
```
**細節**：用 `docling.document_converter.DocumentConverter`；表格輸出為 Markdown 表格文字；`heading_path` 由最近的 H1/H2/H3 組成；`doc_id` = 檔名 sha1 前 12 碼。
**測試**：解析 T15 其中一份合約，有 ≥ 1 個 `kind=="table"` 的 Block，且某 Block `text` 包含「0.3%」且 `page` 正確。

**驗收**：`make test-db`（這組測試標 `db` 以免拖慢單元測試）通過。

---

### T17 切塊 `rag/chunk.py`
**目標**：Block → Chunk（300–800 tokens，保留上下文）。
**規則**
- 以 heading 為邊界；同一 heading 下的文字累積到約 600 中文字切一塊，重疊 80 字。
- 表格不切，整張表一塊；若超過 1500 字則按列切並重複表頭。
- 每塊前綴 `【{file_name} › {heading_path 以 › 串接}】`，提升檢索命中。
- `Chunk` 欄位：`chunk_id`（doc_id + 序號）、`doc_id`、`file_name`、`page`、`heading_path`、`text`、`kind`、`doc_type`（合約/SOP/規格/人資，由檔名前綴判斷）。
**測試**：純單元測試，構造 Block 清單驗證切塊數量、重疊、表格不被切。

**驗收**：`make test` 通過。

---

### T18 建立索引 `rag/ingest.py` + `scripts/ingest_docs.py`
**目標**：Chunk → Qdrant（dense bge-m3 + sparse BM25）。
**步驟**
1. collection `erp_docs`：`vectors_config={"dense": VectorParams(size=1024, distance=COSINE)}`，`sparse_vectors_config={"bm25": SparseVectorParams(modifier=IDF)}`。
2. dense 用 `llm.embed()`；sparse 用 `fastembed.SparseTextEmbedding("Qdrant/bm25")`，但 **中文要先斷詞**：加 `jieba>=0.42` 依賴，對 text 做 `" ".join(jieba.cut(text))` 再餵 BM25（dense 用原文）。
3. payload = Chunk 所有欄位。
4. `ingest_docs.py <資料夾>`：掃描 PDF → 以 doc_id 判斷是否已索引（已索引且檔案 mtime 未變則跳過）→ 批次 upsert 64 筆。
5. 顯示進度與總計。

**驗收**：`make ingest` 完成；`curl -s localhost:6333/collections/erp_docs | jq .result.points_count` > 200。

---

### T19 混合檢索 `rag/retrieve.py`
**介面**
```python
@dataclass
class Hit: chunk_id: str; score: float; text: str; file_name: str; page: int; heading_path: list[str]; doc_type: str
def retrieve(query: str, top_k=20, top_n=5, doc_type: str | None = None) -> list[Hit]
```
**流程**：Qdrant `query_points` 用 `prefetch` 同時查 dense 與 bm25 各 top_k → `FusionQuery(RRF)` → 取 top_k → `reranker.rerank` → top_n。`doc_type` 有值時加 payload filter。
**測試** `@pytest.mark.llm`：query「延遲交貨罰款怎麼算」top_n 第一筆 `file_name` 是銷售合約且 text 含「0.3%」；query「特休幾天」第一筆 doc_type = 人資。

**驗收**：`make test-llm` 通過。

---

### T20 RAG 回答 `rag/answer.py`
**介面**：`answer(question, hits) -> RagAnswer(text, sources: list[Source])`，`Source(file_name, page, heading, snippet)`。
**Prompt 規則**
- 只能根據提供的片段回答；片段不足以回答時明確說「依現有文件查無相關資料」，不得編造。
- 每個事實句末標 `[來源 n]`，n 對應片段編號。
- 回答用繁體中文、條列、不超過 200 字（數字與條款要精確引用）。
- 片段用 `<片段 n 檔案=... 頁=...>` 包裹。
**後處理**：解析回答中的 `[來源 n]`，只保留被引用的 Source；若 LLM 沒標任何來源，保留前 2 筆。
**測試** `@pytest.mark.llm`：「跟鴻遠機械的合約，延遲交貨罰款怎麼算？」回答含 `0.3%` 與 `10%`，sources 非空且 page 正確。

**驗收**：`make test-llm` 通過。

---

### T21 RAG 評估腳本
**步驟**：`data/golden/rag.yaml` 30 題（含 5 題「文件中沒有的問題」，期望回答含「查無」）；每題 `expect_contains: [...]`、`expect_file: 檔名片段`。`scripts/eval_rag.py` 計算：檢索命中率（expect_file 是否在 top_n）、答案正確率、拒答正確率。
**驗收**：`make eval-rag` 檢索命中 ≥ 85%、答案正確 ≥ 80%、5 題拒答全部正確。

---

## Phase 5：Agent 與 API

### T22 意圖路由 `agent/router.py`
**介面**：`route(question, history) -> Route(kind: Literal["sql","docs","both","chat"], rewritten: str)`。
**細節**
- 用 `chat_json`，system prompt 列出四類定義與各 5 個例句；`rewritten` 是補上對話脈絡後的獨立問題（例如前一輪問「鴻遠機械今年營收」，這輪問「那去年呢」→ 改寫成「鴻遠機械去年營收」）。
- 保底規則：問題含「合約／SOP／規定／辦法／條款／規格」→ 至少 docs；含「多少／幾／排名／金額／庫存／逾期／營收」→ 至少 sql；兩者都有 → both。LLM 結果與規則衝突時取聯集。
**測試**：單元測試規則保底（不需 LLM）5 案例；`@llm` 3 案例。

**驗收**：`make test` 與 `make test-llm` 通過。

---

### T23 Agent 主流程 `agent/graph.py`
**目標**：`run_agent(question, history, session_id) -> AgentResult`，純 Python 狀態機（不用 LangGraph，減少依賴）。
**流程**
```
route
 ├ sql  → catalog.answer_question（模板優先；未命中時依 ALLOW_AI_FALLBACK 決定婉拒或走 text2sql.run；回覆已含數字檢查，不必再 summarize_table）
 ├ docs → retrieve → answer
 ├ both → 兩者並行(ThreadPoolExecutor) → 合併 prompt 產生最終回答
 └ chat → 一般回覆（system prompt 說明自己是公司 ERP 助理，不回答與公司無關的事）
 → 組裝 Markdown：結論 / 數據表(≤20 列，Markdown table) / SQL(折疊 <details>) / 來源列表
 → audit.write(...)
```
**AgentResult**：`markdown`, `route`, `sql`, `rows`, `sources`, `latency_ms`, `tokens`。
**錯誤處理**：任何一支失敗都要回「這部分查詢失敗：原因」而非 500，並記 audit `error`。

**測試** `@llm @db`：三個 Demo 問題各跑一次，`markdown` 非空、route 正確、audit_log 多三列。

**驗收**：`make test-llm` 通過。

---

### T24 稽核 `audit.py`
**介面**：`write(AuditRecord) -> id`、`list_recent(n)`、`add_feedback(audit_id, score, comment)`。
用 SQLAlchemy Core 寫入 `app.audit_log`；失敗只記 log 不拋錯（稽核不能拖垮回答）。
**驗收**：`make test-db` 通過（寫入後讀回）。

---

### T25 聊天 API 升級（`api/chat.py`）
**目標**：把 T13b 的 `POST /api/chat` 從只接 Text-to-SQL，升級為接上 Agent。
**變更**
- 後端由 `text2sql.run` 換成 `agent.run_agent(question, history, session_id)`；body 新增 `history`（前幾輪 `{role, content}`，最多 6 輪）。
- 回傳新增欄位：`route`（sql/docs/both/chat）、`sources`（文件來源：檔名、頁碼、片段）、`audit_id`、`answer`（綜合結論文字）。
- 新增 `POST /api/feedback`：body `{audit_id, score, comment}`，寫入 `app.feedback`；網頁的 👍／👎 改為真的呼叫它。
- 網頁：`sources` 顯示為可展開的來源列表（檔名＋頁碼＋片段）；`route` 為 docs 時不顯示表格。
**測試**：TestClient 驗證新增欄位與 `/api/feedback`；`@llm @db` 三個 Demo 問題各打一次。
**驗收**：網頁問「今年營收最高的三個客戶」與「鴻遠機械的合約，延遲交貨罰款怎麼算？」，前者出表格，後者出文字回答與來源。

---

### T26 管理端點 `api/admin.py`
- `GET /admin/audit?limit=50` 最近稽核
- `POST /admin/ingest` body `{"path": "data/docs"}` 觸發重建索引（背景執行）
- `GET /admin/stats` 今日問題數、平均延遲、各 route 數量、SQL 成功率
**驗收**：三個端點 curl 皆回 200 且資料合理。

---

## Phase 6：示範案例

### T27 呆滯庫存與缺料預警 `jobs/dead_stock.py`
**邏輯**（純 SQL + LLM 寫結論）
1. 呆滯：`v_庫存狀況` 中 `未異動天數 >= 180 AND 現有庫存 > 0`，列料號、品名、庫存金額，總計。
2. 缺料：`現有庫存 + 在途數量 < 待出貨數量 OR 現有庫存 < 安全庫存`，列料號、缺口、供應商、交期天數、建議採購量（= 缺口 + 安全庫存）。
3. 用 LLM 把兩張表寫成 ≤ 150 字的 LINE 訊息（含關鍵數字），存 `app.notifications`。
**介面**：`run(dry_run=True) -> str`（回傳訊息文字）。
**測試** `@llm @db`：訊息含 `BRG-6205-2RS` 與 `GEAR-M2-40T`。
**驗收**：`uv run python -m backend.app.jobs.dead_stock` 印出訊息。

---

### T28 排程器 `jobs/scheduler.py`
- APScheduler `BackgroundScheduler(timezone=settings.app_tz)`，每週一 08:00 跑 `dead_stock.run(dry_run=False)`；於 FastAPI `lifespan` 啟動。
- `POST /admin/jobs/dead_stock/run` 手動觸發（Demo 用）。
**驗收**：啟動 log 顯示下次執行時間；手動觸發後 `app.notifications` 多一列。

---

### T29 LINE 推播 `jobs/line_push.py`（選配，無 token 時自動跳過）
- 用 LINE Messaging API `POST https://api.line.me/v2/bot/message/push`，`to = LINE_TARGET_ID`。
- 成功把 `notifications.sent = true`。
- 寫 `docs/LINE_SETUP.md`：如何建 Messaging API channel、取得 token 與 userId/groupId。
**驗收**：無 token 時 log `LINE 未設定，跳過`；有 token 時手機收到訊息。

---

### T30 Demo 開場語與範例問題
- `backend/app/agent/prompts.py` 的 chat system prompt 加入公司簡介（台中精密零件公司、產品線、資料期間）。
- 更新 `backend/app/web/index.html` 的範例問題按鈕（`EXAMPLES` 常數）為下列 6 題（第 3、6 題為文件問題）：
  1. 今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？
  2. 哪些客戶的應收逾期超過 60 天？金額多少？
  3. 鴻遠機械的合約，延遲交貨罰款怎麼算？
  4. 哪些料號超過 180 天沒動？壓了多少錢？
  5. 依目前待出貨訂單，哪些料號會缺料？建議採購多少？
  6. 員工加班費怎麼計算？依據哪份規章？
- 寫 `docs/DEMO_SCRIPT.md`：15 分鐘 Demo 流程、每題預期畫面、講稿重點、常見失敗的備援（例如先暖機、預跑一次）。
**驗收**：6 題在網頁（http://localhost:8000）全部正確回答，每題 < 15 秒；截圖存 `docs/screenshots/`。

---

## Phase 7：驗收與交付

### T31 端到端驗收
1. `docker compose down -v && make up && make seed && make load-examples && make ingest`（從零重建）。
2. `make test && make test-db && make test-llm` 全綠。
3. `make eval-sql`、`make eval-rag` 達標。
4. 冷啟動後 6 題 Demo 全部通過。
把所有輸出貼到 `PROGRESS.md` 的「最終驗收」段。

### T32 交付文件
- `README.md`：10 分鐘從零到 Demo 的步驟（含 LM Studio 人工步驟）、架構圖、已知限制、如何換模型、如何接真實 ERP（把 View 指到客戶資料庫）。
- 更新 `SPEC.md` 的「PoC 實作狀態」段落：哪些案例已實作、量測到的延遲與正確率。

---

## 附錄：常見錯誤與處理

| 症狀 | 原因 | 處理 |
|---|---|---|
| LM Studio 回 404 model not found | `.env` 模型 id 與 `/v1/models` 不一致 | 以 `curl localhost:1234/v1/models` 為準 |
| 回答夾雜 `<think>` | Qwen 思考模式 | 確認 `/no_think` 與 `strip_think` |
| embedding 維度不是 1024 | 載到錯的 embedding 模型 | 換 bge-m3 |
| Text-to-SQL 用了原始表名 | schema_doc 沒強調 | 在 prompt 明列「只能用這四個 View」，guard 會擋 |
| 中文 BM25 全部零分 | 沒斷詞 | 確認 jieba 有套用在 ingest 與 query 兩端 |
| Docling 第一次很慢 | 下載版面模型 | 正常，約 1 GB，之後快取 |
| 網頁打不開或回 404 | backend 沒啟動或 port 被占用 | 確認 `make dev` 在跑，開 http://localhost:8000 |
| 回答超過 30 秒 | 模型沒用 MLX／記憶體不足 swap | 檢查 LM Studio 引擎、`iogpu.wired_limit_mb` |
| psql 中文 View 名稱報錯 | 沒加雙引號 | SQL 中 View 與欄位一律 `"v_銷售明細"` |
