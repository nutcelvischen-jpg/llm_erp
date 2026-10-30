from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, BadRequestError

from backend.app import llm


def fake_chat_response(content="OK", pt=5, ct=2):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
    )


def bad_request():
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    return BadRequestError("bad", response=httpx.Response(400, request=req), body=None)


# ---------- strip_think ----------
@pytest.mark.parametrize(("raw", "expected"), [
    ("<think>推理\n過程</think>\n\n答案", "答案"),
    ("\n\n台中是一座城市。\n", "台中是一座城市。"),
    ("<think>想到一半被截斷", ""),
    ("前面的思考內容</think>答案", "答案"),
    ("<think>a</think>甲<think>b</think>乙", "甲乙"),
    ("", ""),
])
def test_strip_think(raw, expected):
    assert llm.strip_think(raw) == expected


# ---------- extract_json ----------
def test_extract_json_plain():
    assert llm.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced_block():
    assert llm.extract_json('好的：\n```json\n{"sql": "select 1"}\n```\n以上') == {"sql": "select 1"}


def test_extract_json_text_around():
    assert llm.extract_json('結果如下 {"x": "y"} 完畢') == {"x": "y"}


def test_extract_json_nested_and_braces_in_string():
    obj = llm.extract_json('前言 {"a": {"b": [1, {"c": 2}]}, "s": "含}大括號{"} 後記')
    assert obj == {"a": {"b": [1, {"c": 2}]}, "s": "含}大括號{"}


def test_extract_json_ignores_think_block():
    assert llm.extract_json('<think>先想 {"wrong": 1}</think>{"right": 2}') == {"right": 2}


@pytest.mark.parametrize("raw", ["完全沒有 JSON", "[1, 2, 3]", "{壞掉的 json", ""])
def test_extract_json_failure(raw):
    with pytest.raises(ValueError, match="JSON"):
        llm.extract_json(raw)


# ---------- chat（以假的 _create 取代網路呼叫）----------
def test_chat_disables_thinking_by_default(monkeypatch):
    seen = {}

    def fake_create(**kw):
        seen.update(kw)
        return fake_chat_response("\n\n你好\n")

    monkeypatch.setattr(llm, "_create", fake_create)
    res = llm.chat([{"role": "user", "content": "hi"}])
    assert seen["extra_body"] == {"reasoning_effort": "none"}
    assert "response_format" not in seen
    assert res.text == "你好"
    assert (res.prompt_tokens, res.completion_tokens) == (5, 2)
    assert res.latency_ms >= 0


def test_chat_think_true_omits_reasoning_effort(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "_create", lambda **kw: seen.update(kw) or fake_chat_response())
    llm.chat([{"role": "user", "content": "hi"}], think=True)
    assert "extra_body" not in seen


def test_chat_json_mode_falls_back_when_unsupported(monkeypatch):
    monkeypatch.setattr(llm, "_json_mode_ok", True)
    calls = []

    def fake_create(**kw):
        calls.append(dict(kw))
        if "response_format" in kw:
            raise bad_request()
        return fake_chat_response('{"ok": true}')

    monkeypatch.setattr(llm, "_create", fake_create)
    res = llm.chat([{"role": "user", "content": "x"}], json_mode=True)
    assert res.text == '{"ok": true}'
    assert len(calls) == 2 and "response_format" not in calls[1]
    assert llm._json_mode_ok is False
    llm.chat([{"role": "user", "content": "x"}], json_mode=True)  # 之後不再嘗試 json_object
    assert len(calls) == 3 and "response_format" not in calls[2]


def test_chat_connection_error_becomes_llmerror(monkeypatch):
    def boom(**_):
        raise APIConnectionError(request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(llm, "_create", boom)
    with pytest.raises(llm.LLMError, match="LM Studio"):
        llm.chat([{"role": "user", "content": "x"}])


def test_chat_bad_request_without_json_mode_is_llmerror(monkeypatch):
    def boom(**_):
        raise bad_request()

    monkeypatch.setattr(llm, "_create", boom)
    with pytest.raises(llm.LLMError, match="400"):
        llm.chat([{"role": "user", "content": "x"}])


# ---------- chat_json ----------
def test_chat_json_retries_once_then_succeeds(monkeypatch):
    outputs = iter([fake_chat_response("抱歉，我不確定"), fake_chat_response('{"sql": "select 1"}')])
    seen = []

    def fake_create(**kw):
        seen.append(kw["messages"])
        return next(outputs)

    monkeypatch.setattr(llm, "_create", fake_create)
    assert llm.chat_json([{"role": "user", "content": "q"}], '{"sql": str}') == {"sql": "select 1"}
    assert len(seen) == 2
    assert seen[0][0]["role"] == "system" and '{"sql": str}' in seen[0][0]["content"]
    assert "無法解析" in seen[1][-1]["content"]


def test_chat_json_merges_into_existing_system_message(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "_create", lambda **kw: seen.append(kw["messages"]) or fake_chat_response("{}"))
    llm.chat_json([{"role": "system", "content": "你是助理"}, {"role": "user", "content": "q"}], "{}")
    assert [m["role"] for m in seen[0]] == ["system", "user"]  # 不會多出第二則 system
    assert seen[0][0]["content"].startswith("你是助理")


def test_chat_json_gives_up_after_two_failures(monkeypatch):
    monkeypatch.setattr(llm, "_create", lambda **_: fake_chat_response("還是沒有 JSON"))
    with pytest.raises(llm.LLMError, match="JSON"):
        llm.chat_json([{"role": "user", "content": "q"}], "{}")


# ---------- embed ----------
def test_embed_batches_and_keeps_order(monkeypatch):
    sizes = []

    def fake_embed(**kw):
        batch = kw["input"]
        sizes.append(len(batch))
        data = [SimpleNamespace(index=i, embedding=[float(t)]) for i, t in enumerate(batch)]
        return SimpleNamespace(data=list(reversed(data)))  # 故意亂序，驗證有依 index 排序

    monkeypatch.setattr(llm, "_embed_create", fake_embed)
    out = llm.embed([str(i) for i in range(70)])
    assert sizes == [32, 32, 6]
    assert out == [[float(i)] for i in range(70)]


def test_embed_empty():
    assert llm.embed([]) == []


# ---------- 真實 LM Studio（make test-llm）----------
@pytest.mark.llm
def test_real_chat_fast_without_thinking():
    res = llm.chat([{"role": "user", "content": "請只回答 OK 兩個字母"}], max_tokens=50, temperature=0)
    assert "OK" in res.text
    assert res.completion_tokens < 30  # 沒有思考 token
    assert res.latency_ms < 15000


@pytest.mark.llm
def test_real_chat_json():
    obj = llm.chat_json(
        [{"role": "user", "content": "台中是哪個國家的城市？"}], '{"country": "國家名稱", "city": "城市"}'
    )
    assert {"country", "city"} <= set(obj)


@pytest.mark.llm
def test_real_embed_dim():
    vecs = llm.embed(["應收帳款", "合約罰款"])
    assert len(vecs) == 2 and len(vecs[0]) == llm.settings.embed_dim
