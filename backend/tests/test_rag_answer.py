import pytest

from backend.app.llm import ChatResult, LLMError
from backend.app.rag.answer import (NO_ANSWER, answer, attach_sources, build_messages, cited_numbers,
                                    format_context, to_source)
from backend.app.rag.retrieve import Hit


def H(i, text, file="銷售合約_甲.pdf", page=2, heading=("第五條",)):
    return Hit(f"c{i}", 1.0, f"【{file} › {' › '.join(heading)}】\n{text}", file, page, list(heading), "合約")


HITS = [H(1, "每逾一日按 0.3% 計付違約金，上限 10%。"), H(2, "付款條件月結 30 天。", page=3),
        H(3, "特休依年資給予。", file="人資_請假.pdf", page=1, heading=("特休",))]


class FakeChat:
    def __init__(self, text):
        self.text, self.calls = text, []

    def __call__(self, messages):
        self.calls.append(messages)
        return ChatResult(self.text, 100, 20, 300)


def test_format_context_wraps_and_strips_prefix():
    ctx = format_context(HITS[:2])
    assert '<片段 1 檔案="銷售合約_甲.pdf" 頁="2" 標題="第五條">' in ctx
    assert '<片段 2 檔案="銷售合約_甲.pdf" 頁="3"' in ctx
    assert "【" not in ctx and "0.3%" in ctx


def test_build_messages_has_rules_and_question():
    m = build_messages("違約金？", HITS)
    assert "[來源 n]" in m[0]["content"] and "查無相關資料" in m[0]["content"]
    assert m[1]["content"].endswith("問題：違約金？")


def test_cited_numbers_formats():
    assert cited_numbers("a[來源 2]b[來源1, 3]c[來源 2、4][來源 1]") == [2, 1, 3, 4]
    assert cited_numbers("沒有引用") == []


def test_attach_sources_keeps_only_cited_and_renumbers():
    text, src = attach_sources("- 0.3% [來源 1]\n- 月結 30 天 [來源 2]", HITS)
    assert [s.page for s in src] == [2, 3]
    text, src = attach_sources("- 特休 [來源 3]\n- 違約金 [來源 1][來源 3]", HITS)
    assert [s.file_name for s in src] == ["人資_請假.pdf", "銷售合約_甲.pdf"]
    assert text == "- 特休 [來源 1]\n- 違約金 [來源 2][來源 1]"


def test_attach_sources_drops_invalid_numbers():
    text, src = attach_sources("A [來源 9]。B [來源 2]", HITS)
    assert text == "A 。B [來源 1]" and [s.page for s in src] == [3]


def test_attach_sources_no_citation_keeps_first_two():
    text, src = attach_sources("違約金 0.3%。", HITS)
    assert len(src) == 2 and src[0].page == 2


def test_attach_sources_refusal_has_no_sources():
    assert attach_sources(NO_ANSWER, HITS) == (NO_ANSWER, [])


def test_to_source_snippet():
    s = to_source(H(1, "字" * 300))
    assert s.heading == "第五條" and len(s.snippet) == 121 and s.snippet.endswith("…")
    assert not s.snippet.startswith("【")


def test_answer_happy_path():
    fake = FakeChat("- 每逾一日 0.3%，上限 10% [來源 1]")
    r = answer("違約金怎麼算", HITS, chat=fake)
    assert r.text.endswith("[來源 1]") and r.error is None
    assert len(r.sources) == 1 and r.sources[0].page == 2
    assert (r.prompt_tokens, r.completion_tokens, r.latency_ms) == (100, 20, 300)


def test_answer_without_hits_does_not_call_llm():
    r = answer("q", [], chat=lambda m: pytest.fail("不該呼叫 LLM"))
    assert r.text == NO_ANSWER and r.sources == []


def test_answer_llm_error_returns_message():
    def boom(_):
        raise LLMError("LLM 回應逾時")

    r = answer("q", HITS, chat=boom)
    assert r.error == "LLM 回應逾時" and "暫時無法產生" in r.text


def test_answer_empty_llm_output_is_refusal():
    r = answer("q", HITS, chat=FakeChat(""))
    assert r.text == NO_ANSWER and r.sources == []


# ---------- 真實服務 ----------
@pytest.mark.llm
def test_real_penalty_answer():
    from backend.app.rag.retrieve import retrieve

    q = "跟鴻遠機械的合約，延遲交貨罰款怎麼算？"
    r = answer(q, retrieve(q))
    print("\n", r.text, r.sources)
    assert r.error is None
    assert "0.3%" in r.text and "10%" in r.text
    assert r.sources
    assert any(s.file_name == "銷售合約_鴻遠機械.pdf" and s.page == 2 for s in r.sources)
    assert all(s.file_name == "銷售合約_鴻遠機械.pdf" for s in r.sources)
