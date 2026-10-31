import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import settings

client = TestClient(main.app)


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._p = status, payload or {}

    def json(self):
        return self._p


@pytest.fixture
def fake_net(monkeypatch):
    monkeypatch.setattr(main.db, "ping", lambda: True)

    def setup(states, v0_status=200):
        def fake_get(url, timeout=3):
            if url.endswith("/api/v0/models"):
                return Resp(v0_status, {"data": [{"id": k, "state": v} for k, v in states.items()]})
            return Resp(200)  # /collections 與 /v1/models

        monkeypatch.setattr(main.httpx, "get", fake_get)

    return setup


def test_health_no_warning_when_both_models_loaded(fake_net):
    fake_net({settings.llm_model: "loaded", settings.embed_model: "loaded", "other": "not-loaded"})
    d = client.get("/health").json()
    assert d["ok"] is True and "warnings" not in d
    assert sorted(d["lmstudio_loaded"]) == sorted([settings.llm_model, settings.embed_model])


def test_health_warns_when_embedding_model_not_resident(fake_net):
    fake_net({settings.llm_model: "loaded", settings.embed_model: "not-loaded"})
    d = client.get("/health").json()
    assert d["ok"] is True  # 只是警告，不影響整體健康
    assert settings.embed_model in d["warnings"][0] and "make llm-up" in d["warnings"][0]
    assert settings.llm_model not in d["warnings"][0]


def test_health_warns_for_both_when_nothing_loaded(fake_net):
    fake_net({})
    w = client.get("/health").json()["warnings"][0]
    assert settings.llm_model in w and settings.embed_model in w


def test_health_ignores_missing_rest_api(fake_net):
    fake_net({}, v0_status=404)  # 較舊的 LM Studio 沒有 /api/v0
    d = client.get("/health").json()
    assert d["ok"] is True and "warnings" not in d and "lmstudio_loaded" not in d
