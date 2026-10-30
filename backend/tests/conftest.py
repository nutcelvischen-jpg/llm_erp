"""沒有 .env 時（例如 CI），補上讓 Settings 能載入的最小環境變數。有 .env 就完全不動。"""
import os
from pathlib import Path

if not Path(".env").exists():
    os.environ.setdefault("LLM_MODEL", "test-model")
    os.environ.setdefault("EMBED_MODEL", "test-embed")
    os.environ.setdefault("PG_DSN", "postgresql+psycopg://erp:erp@localhost:5432/erp_poc")
