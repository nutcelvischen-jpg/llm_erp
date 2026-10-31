import pytest
from fastapi.testclient import TestClient

from backend.app.agent.graph import AgentResult
from backend.app.api import chat as chat_api
from backend.app.main import app

client = TestClient(app)
FIELDS = {"question", "sql", "explanation", "columns", "rows", "row_count", "attempts", "error", "latency_ms",
          "route", "sources", "audit_id", "answer", "markdown", "warning", "rewritten", "mode", "template_id",
          "template_title", "params_readable", "binds", "answer_source", "options", "proposals", "suggestions", "notes"}


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def setup(result):
        def run(question, history, session_id, choice=None):
            calls.append({"question": question, "history": history, "session_id": session_id, "choice": choice})
            return result
        monkeypatch.setattr(chat_api.graph, "run_agent", run)
        return calls

    return setup


def ok_answer():
    return AgentResult(markdown="各客戶營收", route="sql", answer="各客戶營收", rewritten="各客戶營收？",
                       sql="SELECT 1 LIMIT 200", columns=["客戶", "營收"], rows=[["甲", 100], ["乙", 50]],
                       row_count=2, attempts=1, latency_ms=1200, audit_id=7, mode="template",
                       template_id="sales_rank", template_title="銷售排名", params_readable=["排名對象：客戶"],
                       binds={"date_from": "2026-01-01"}, answer_source="llm")


def docs_answer():
    return AgentResult(markdown="- 0.3% [來源 1]", route="docs", answer="- 0.3% [來源 1]",
                       sources=[{"file_name": "銷售合約_鴻遠機械.pdf", "page": 2, "heading": "第五條",
                                 "snippet": "每逾一日…"}], audit_id=8, latency_ms=900)


# ---------- 網頁 ----------
def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "ERP 智慧助理" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_static_file_served():
    assert client.get("/static/index.html").status_code == 200


def test_vendored_echarts_is_served_locally():
    r = client.get("/static/vendor/echarts.min.js")
    assert r.status_code == 200 and len(r.content) > 500_000
    assert "/static/vendor/echarts.min.js" in client.get("/").text  # 網頁引用的是本機檔


def test_echarts_license_files_shipped():
    assert client.get("/static/vendor/LICENSE").status_code == 200
    assert "Apache" in client.get("/static/vendor/LICENSE").text


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
    assert d["question"] == "各客戶營收？" and d["route"] == "sql" and d["audit_id"] == 7
    assert d["answer"] == d["explanation"] == "各客戶營收" and d["attempts"] == 1 and d["warning"] is None
    assert d["mode"] == "template" and d["template_title"] == "銷售排名" and d["binds"] == {"date_from": "2026-01-01"}


def test_chat_strips_question_before_running(fake_run):
    calls = fake_run(ok_answer())
    client.post("/api/chat", json={"question": "  今年營收  \n"})
    assert calls[0]["question"] == "今年營收"


def test_business_error_is_http_200_with_error_field(fake_run):
    fake_run(AgentResult(markdown="", route="sql", error="這個問題無法用目前的 ERP 資料回答：沒有薪資資料"))
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


def test_docs_route_returns_sources(fake_run):
    fake_run(docs_answer())
    d = client.post("/api/chat", json={"question": "鴻遠罰款"}).json()
    assert d["route"] == "docs" and d["sources"][0]["page"] == 2 and d["rows"] == [] and d["audit_id"] == 8


def test_history_and_session_passed_and_trimmed(fake_run):
    calls = fake_run(ok_answer())
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(20)]
    hist.append({"role": "user", "content": "   "})
    r = client.post("/api/chat", json={"question": "那去年呢", "session_id": "s1", "history": hist})
    assert r.status_code == 200
    got = calls[0]["history"]
    assert len(got) == 12 and got[0] == {"role": "user", "content": "m8"} and got[-1]["content"] == "m19"
    assert calls[0]["session_id"] == "s1"


@pytest.mark.parametrize("hist", [[{"role": "system", "content": "x"}], [{"role": "user"}], "abc"])
def test_invalid_history_is_422(fake_run, hist):
    fake_run(ok_answer())
    assert client.post("/api/chat", json={"question": "q", "history": hist}).status_code == 422


def test_choice_is_passed_to_agent(fake_run):
    calls = fake_run(ok_answer())
    body = {"question": "今年哪個客戶最賺", "choice": {"template_id": "sales_rank", "params": {"dimension": "客戶"}}}
    assert client.post("/api/chat", json=body).status_code == 200
    assert calls[0]["choice"] == {"template_id": "sales_rank", "params": {"dimension": "客戶"}}
    assert client.post("/api/chat", json={"question": "q", "choice": {"params": {}}}).status_code == 422


# ---------- /api/feedback ----------
def test_feedback_ok(monkeypatch):
    calls = []
    monkeypatch.setattr(chat_api.audit, "add_feedback", lambda a, s, c: calls.append((a, s, c)) or 99)
    r = client.post("/api/feedback", json={"audit_id": 7, "score": -1, "comment": "數字不對"})
    assert r.status_code == 200 and r.json() == {"ok": True, "id": 99} and calls == [(7, -1, "數字不對")]


def test_feedback_failure_is_503(monkeypatch):
    monkeypatch.setattr(chat_api.audit, "add_feedback", lambda *a: None)
    r = client.post("/api/feedback", json={"audit_id": 7, "score": 1})
    assert r.status_code == 503 and "回饋寫入失敗" in r.json()["detail"]


@pytest.mark.parametrize("payload", [{"audit_id": 7, "score": 2}, {"audit_id": 0, "score": 1}, {"score": 1},
                                     {"audit_id": 7, "score": 1, "comment": "字" * 1001}])
def test_feedback_invalid_is_422(monkeypatch, payload):
    monkeypatch.setattr(chat_api.audit, "add_feedback", lambda *a: pytest.fail("不該寫入"))
    assert client.post("/api/feedback", json=payload).status_code == 422


# ---------- 真實 LLM + 資料庫 ----------
@pytest.mark.llm
@pytest.mark.db
@pytest.mark.parametrize("q, route", [
    ("今年營收最高的 3 個客戶", "sql"),
    ("鴻遠機械的合約，延遲交貨罰款怎麼算？", "docs"),
    ("台陽科技逾期的應收有多少？依合約逾期多久可以暫停出貨？", "both"),
])
def test_real_demo_questions(q, route):
    d = client.post("/api/chat", json={"question": q, "session_id": "pytest"}).json()
    assert d["route"] == route and d["error"] is None, d["error"]
    assert d["answer"] and d["audit_id"]
    if route in ("sql", "both"):
        assert d["row_count"] >= 1 and d["sql"] and d["mode"] == "template" and d["template_title"]
    if route == "sql":
        assert d["row_count"] == 3
    if route in ("docs", "both"):
        assert d["sources"]
    r = client.post("/api/feedback", json={"audit_id": d["audit_id"], "score": 1})
    assert r.status_code == 200 and r.json()["ok"]
