import pytest
from fastapi.testclient import TestClient

from backend.app import text2sql
from backend.app.api import chat as chat_api
from backend.app.main import app

client = TestClient(app)
FIELDS = {"question", "sql", "explanation", "columns", "rows", "row_count", "attempts", "error", "latency_ms"}


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def setup(answer):
        monkeypatch.setattr(chat_api.text2sql, "run", lambda q: calls.append(q) or answer)
        return calls

    return setup


def ok_answer():
    return text2sql.SqlAnswer(sql="SELECT 1 LIMIT 200", explanation="各客戶營收", columns=["客戶", "營收"],
                              rows=[["甲", 100], ["乙", 50]], row_count=2, attempts=1)


# ---------- 網頁 ----------
def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "ERP 智慧助理" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_static_file_served():
    assert client.get("/static/index.html").status_code == 200


def test_index_has_no_external_cdn_and_no_innerhtml():
    html = client.get("/").text
    assert "http://" not in html and "https://" not in html  # 不得引用外部資源
    assert ".innerHTML" not in html and "insertAdjacentHTML" not in html and "document.write" not in html


# ---------- /api/chat ----------
def test_chat_returns_all_fields(fake_run):
    fake_run(ok_answer())
    r = client.post("/api/chat", json={"question": "各客戶營收？"})
    assert r.status_code == 200
    d = r.json()
    assert FIELDS <= set(d)
    assert d["rows"] == [["甲", 100], ["乙", 50]] and d["columns"] == ["客戶", "營收"]
    assert d["error"] is None and isinstance(d["latency_ms"], int) and d["latency_ms"] >= 0
    assert d["question"] == "各客戶營收？"


def test_chat_strips_question_before_running(fake_run):
    calls = fake_run(ok_answer())
    client.post("/api/chat", json={"question": "  今年營收  \n"})
    assert calls == ["今年營收"]


def test_business_error_is_http_200_with_error_field(fake_run):
    fake_run(text2sql.SqlAnswer(error="這個問題無法用目前的 ERP 資料回答：沒有薪資資料", attempts=1))
    r = client.post("/api/chat", json={"question": "員工薪水？"})
    assert r.status_code == 200
    d = r.json()
    assert "無法" in d["error"] and d["rows"] == [] and FIELDS <= set(d)


@pytest.mark.parametrize("payload", [
    {"question": ""}, {"question": "   "}, {"question": "字" * 501}, {}, {"question": None}, {"question": 123},
])
def test_invalid_question_is_422(fake_run, payload):
    calls = fake_run(ok_answer())
    assert client.post("/api/chat", json=payload).status_code == 422
    assert calls == []  # 不會呼叫 LLM


def test_boundary_lengths_are_accepted(fake_run):
    fake_run(ok_answer())
    assert client.post("/api/chat", json={"question": "字"}).status_code == 200
    assert client.post("/api/chat", json={"question": "字" * 500}).status_code == 200


def test_session_id_is_optional(fake_run):
    fake_run(ok_answer())
    assert client.post("/api/chat", json={"question": "q", "session_id": "abc"}).status_code == 200


# ---------- 真實 LLM + 資料庫 ----------
@pytest.mark.llm
@pytest.mark.db
def test_real_chat_top_customers():
    r = client.post("/api/chat", json={"question": "今年營收最高的 3 個客戶"})
    d = r.json()
    assert r.status_code == 200 and d["error"] is None, d["error"]
    assert d["row_count"] == 3 and len(d["columns"]) >= 2
