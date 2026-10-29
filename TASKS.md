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

### T02 docker-compose（postgres + qdrant + open-webui）
**目標**：一鍵啟動周邊服務。
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

  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: erp_webui
    ports: ["3000:8080"]
    environment:
      OPENAI_API_BASE_URL: http://host.docker.internal:8000/v1
      OPENAI_API_KEY: poc
      ENABLE_OLLAMA_API: "false"
      WEBUI_AUTH: "false"
      DEFAULT_LOCALE: zh-TW
    extra_hosts: ["host.docker.internal:host-gateway"]
    volumes:
      - webui_data:/app/backend/data

volumes:
  pgdata:
  qdrant_data:
  webui_data:
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
- Qwen 系列：在 system prompt 結尾加 `/no_think`，並仍以 `strip_think` 防呆。
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

### T14 Text-to-SQL 評估腳本
**目標**：量化正確率，之後每次改 prompt 都要跑。
**步驟**
1. `data/golden/text2sql.yaml`：30 題，每題含 `question`、`check`（三選一：`row_count_gt: N` / `contains: 值` / `sql_equals_result_of: <參考SQL>`，第三種是執行參考 SQL 比對結果集）。
2. `scripts/eval_text2sql.py`：逐題跑 `text2sql.run`，輸出表格（題目、通過、嘗試次數、耗時）與總分，寫到 `data/golden/report_text2sql_<日期>.md`。

**驗收**：`make eval-sql` 正確率 ≥ 80%（達不到就回 T12 補範例、T08 補 schema_doc，不要改測試）。

---

## Phase 4：文件 RAG

### T15 測試文件準備
**目標**：20 份繁中 PDF 放進 `data/docs/`，由代理**自行生成**（不要抓網路檔案）。
**步驟**：寫 `data/docs/make_docs.py`，用 `reportlab`（加進 dev 依賴）或 `docx → pdf` 產生：
- 5 份客戶銷售合約（含交期、延遲罰款條款「每日按未交貨金額 0.3%，上限 10%」、付款條件、保固），客戶名稱對應 ERP 的 C001–C005。
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
 ├ sql  → text2sql.run → summarize_table(LLM 把表格寫成 3 句結論，附上要點數字)
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

### T25 OpenAI 相容端點 `api/openai_compat.py`
**目標**：讓 Open WebUI 當成一般模型使用。
**端點**
- `GET /v1/models` → `[{"id":"erp-assistant","object":"model"}]`
- `POST /v1/chat/completions`：取 `messages` 最後一則 user 為 question，其餘為 history；`session_id` 取 header `X-Session-Id` 或 hash(前 3 則訊息)。
  - `stream=false`：回標準 ChatCompletion JSON。
  - `stream=true`：SSE，先送「🔎 正在分析問題…」等進度 chunk（route 後送「📊 查詢 ERP…」或「📄 搜尋文件…」），最後把完整 markdown 一次送出，再送 `[DONE]`。（PoC 不做 token 級串流，避免複雜度。）
- `POST /v1/feedback` `{audit_id, score, comment}`。
**測試**：用 `httpx` 打 `/v1/models` 與 `stream=false` 的 chat（`@llm @db`）。

**驗收**：`curl localhost:8000/v1/models` 正確；Open WebUI（http://localhost:3000）模型下拉出現 `erp-assistant`，問「今年營收最高的三個客戶」得到表格與 SQL。

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
- 在 Open WebUI 設定 `erp-assistant` 模型的「建議提示」（Prompt Suggestions）6 題：
  1. 今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？
  2. 哪些客戶的應收逾期超過 60 天？金額多少？
  3. 鴻遠機械的合約，延遲交貨罰款怎麼算？
  4. 哪些料號超過 180 天沒動？壓了多少錢？
  5. 依目前待出貨訂單，哪些料號會缺料？建議採購多少？
  6. 員工加班費怎麼計算？依據哪份規章？
- 寫 `docs/DEMO_SCRIPT.md`：15 分鐘 Demo 流程、每題預期畫面、講稿重點、常見失敗的備援（例如先暖機、預跑一次）。
**驗收**：6 題在 Open WebUI 全部正確回答，每題 < 15 秒；截圖存 `docs/screenshots/`。

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
| Open WebUI 看不到模型 | 打不到 host | 確認 `host.docker.internal` 與 backend 綁 `0.0.0.0` |
| 回答超過 30 秒 | 模型沒用 MLX／記憶體不足 swap | 檢查 LM Studio 引擎、`iogpu.wired_limit_mb` |
| psql 中文 View 名稱報錯 | 沒加雙引號 | SQL 中 View 與欄位一律 `"v_銷售明細"` |
