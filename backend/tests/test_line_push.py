import json
import logging

import httpx
import pytest

from backend.app.jobs import line_push


@pytest.fixture
def cfg(monkeypatch):
    def set_(token="tok", target="U123"):
        monkeypatch.setattr(line_push.settings, "line_channel_access_token", token)
        monkeypatch.setattr(line_push.settings, "line_target_id", target)
    return set_


def mock_client(status=200, exc=None):
    sent = []

    def handler(req):
        if exc:
            raise exc
        sent.append(req)
        return httpx.Response(status, json={"message": "bad"} if status != 200 else {})

    return httpx.Client(transport=httpx.MockTransport(handler)), sent


class FakeEngine:
    def __init__(self):
        self.executed = []

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))


@pytest.mark.parametrize("token, target", [("", ""), ("tok", ""), ("", "U1")])
def test_not_configured_skips(cfg, caplog, token, target):
    cfg(token, target)
    caplog.set_level(logging.INFO)
    client, sent = mock_client()
    assert line_push.push("hi", client) is False and sent == []
    assert "LINE 未設定，跳過" in caplog.text
    assert line_push.push_pending(client=client) == 0


def test_push_request_format(cfg):
    cfg()
    client, sent = mock_client()
    assert line_push.push("預警", client) is True
    req = sent[0]
    assert str(req.url) == line_push.PUSH_URL and req.headers["Authorization"] == "Bearer tok"
    assert json.loads(req.content) == {"to": "U123", "messages": [{"type": "text", "text": "預警"}]}


def test_push_truncates_long_message(cfg):
    cfg()
    client, sent = mock_client()
    line_push.push("字" * 6000, client)
    assert len(json.loads(sent[0].content)["messages"][0]["text"]) == line_push.MAX_CHARS


def test_push_http_error_and_network_error(cfg, caplog):
    cfg()
    assert line_push.push("x", mock_client(401)[0]) is False and "HTTP 401" in caplog.text
    assert line_push.push("x", mock_client(exc=httpx.ConnectError("no net"))[0]) is False
    assert "連線失敗" in caplog.text


def test_send_notification_marks_sent_only_on_success(cfg):
    cfg()
    eng = FakeEngine()
    assert line_push.send_notification(7, "m", eng, mock_client()[0]) is True
    assert "SET sent = true" in eng.executed[0][0] and eng.executed[0][1] == {"i": 7}
    eng2 = FakeEngine()
    assert line_push.send_notification(8, "m", eng2, mock_client(500)[0]) is False and eng2.executed == []
