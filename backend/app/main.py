import logging
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import admin, chat
from .config import settings

logging.basicConfig(level=settings.log_level)
app = FastAPI(title="ERP LLM PoC")
app.include_router(chat.router)
app.include_router(admin.router)

WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    # no-store：開發時改了 index.html，重新整理就會看到
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


def _http_ok(url: str) -> bool:
    return httpx.get(url, timeout=3).status_code == 200


def _lmstudio_states() -> dict[str, str] | None:
    """LM Studio 的 REST API（/api/v0/models）可得知每個模型是否已載入；取不到就回 None（不影響健康檢查）。"""
    root = settings.llm_base_url.rstrip("/").removesuffix("/v1")
    try:
        r = httpx.get(f"{root}/api/v0/models", timeout=3)
        if r.status_code != 200:
            return None
        return {m["id"]: m.get("state", "") for m in r.json().get("data", [])}
    except Exception:  # noqa: BLE001
        return None


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
    states = _lmstudio_states() if out["lmstudio"] else None
    if states is not None:
        out["lmstudio_loaded"] = sorted(k for k, v in states.items() if v == "loaded")
        missing = [m for m in (settings.llm_model, settings.embed_model) if states.get(m) != "loaded"]
        if missing:  # 只是警告，不影響 ok；模型沒常駐時，每次切換模型都會多花十幾秒
            out["warnings"] = [f"模型未常駐：{'、'.join(missing)}。LM Studio 會在模型之間互相卸載，延遲可能高達十多秒；請執行 make llm-up"]
    return out
