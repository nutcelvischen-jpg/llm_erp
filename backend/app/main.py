import logging

import httpx
from fastapi import FastAPI

from . import db
from .config import settings

logging.basicConfig(level=settings.log_level)
app = FastAPI(title="ERP LLM PoC")


def _http_ok(url: str) -> bool:
    return httpx.get(url, timeout=3).status_code == 200


@app.get("/health")
def health():
    out: dict = {"postgres": False, "qdrant": False, "lmstudio": False}
    try:
        out["postgres"] = db.ping()
    except Exception as e:  # noqa: BLE001
        out["postgres_error"] = str(e)[:200]
    try:
        out["qdrant"] = _http_ok(f"{settings.qdrant_url}/collections")
    except Exception as e:  # noqa: BLE001
        out["qdrant_error"] = str(e)[:200]
    try:
        out["lmstudio"] = _http_ok(f"{settings.llm_base_url}/models")
    except Exception as e:  # noqa: BLE001
        out["lmstudio_error"] = str(e)[:200]
    out["ok"] = all(out[k] for k in ("postgres", "qdrant", "lmstudio"))
    return out
