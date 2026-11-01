import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import admin, chat, docview, reports
from .config import settings
from .jobs import scheduler

logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="ERP LLM PoC", lifespan=lifespan)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(docview.router)

WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _page(name: str) -> FileResponse:
    # no-store：開發時改了網頁，重新整理就會看到
    return FileResponse(WEB_DIR / name, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def home(request: Request):
    # 首頁是儀表板；舊的「/?q=問題」連結轉到問答頁
    if request.query_params.get("q"):
        return RedirectResponse(f"/chat?{request.url.query}", status_code=307)
    return _page("dashboard.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return _page("dashboard.html")


@app.get("/chat", include_in_schema=False)
def chat_page():
    return _page("index.html")


@app.get("/reports", include_in_schema=False)
def reports_page():
    return _page("reports.html")


@app.get("/about", include_in_schema=False)
def about_page():
    return _page("about.html")


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
