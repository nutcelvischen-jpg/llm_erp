from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.rag import pdfview
from backend.app.rag.answer import Source, add_views

client = TestClient(app)
DOC = "銷售合約_鴻遠機械.pdf"
BODY = ("賣方未能於確認之交貨日期交貨者，每逾一日，按延遲交付部分貨款（未稅）之 0.3% 計付違約金，累計 金額以該部分貨款之 10% 為上限。\n"
        "延遲係因買方變更訂單、未提供必要資料或不可抗力所致者，不適用前項規定。")
ANSWER = "每逾一日按延遲交付部分貨款（未稅）的 0.3% 計付違約金，累計上限為該部分貨款的 10%[來源 1]。"


def chars(lines: list[str], width=600, height=800, top=700, size=10):
    """假頁面：每行一列字，每字寬 size。"""
    out = []
    for n, line in enumerate(lines):
        t = top - n * 20
        for i, c in enumerate(line):
            out.append((c, (50 + i * size, t - size, 50 + (i + 1) * size, t)))
        out.append(("\n", (0, 0, 0, 0)))
    return out


def test_locate_text_frames_region_and_highlights_used_sentence():
    page = chars(["第一條 定義", "第五條 延遲", "每逾一日罰千分之三。", "逾三十日得解約。", "第六條 驗收"])
    boxes = pdfview.locate_text(page, 600, 800, "每逾一日罰千分之三。\n逾三十日得解約。", "第五條 延遲", "每逾一日罰千分之三")
    region, *hits = boxes
    assert region["kind"] == "region" and all(b["kind"] == "hit" for b in hits)
    # 外框從標題那行到最後一句，不含前後的條文
    assert region["y"] == round((800 - 680) / 800, 4) and region["h"] == round((680 - 630) / 800, 4)
    assert len(hits) == 1 and hits[0]["y"] == round((800 - 660) / 800, 4)


def test_locate_text_ignores_whitespace_and_line_breaks():
    page = chars(["賣方延遲交貨者，每逾一日", "計付違約金。"])
    boxes = pdfview.locate_text(page, 600, 800, "賣方延遲交貨者，每逾 一日計付違約金。", "", "賣方延遲交貨每逾一日計付違約金")
    assert [b["kind"] for b in boxes] == ["region", "hit", "hit"]   # 跨兩行的一句話 → 兩行螢光


def test_locate_text_returns_empty_when_not_on_page():
    assert pdfview.locate_text(chars(["完全無關的內容"]), 600, 800, "找不到的句子在這裡", "", "x") == []


def test_hit_segments_needs_real_overlap():
    segs = pdfview.segments("每逾一日罰千分之三。驗收應於五日內完成。")
    assert pdfview.hit_segments(segs, "每逾一日罰千分之三") == {0}
    assert pdfview.hit_segments(segs, "今天天氣很好") == set()
    assert pdfview.segments("| 項目 | 5 |\n|---|---|\n| 違約金上限 | 10% |") == ["違約金上限"]


def test_pdf_path_is_whitelisted():
    assert pdfview.pdf_path(DOC).name == DOC
    for bad in ("../../.env", "/etc/passwd", "銷售合約_鴻遠機械", "不存在.pdf", "../data/docs/" + DOC + "x"):
        assert pdfview.pdf_path(bad) is None, bad
    assert pdfview.pdf_path("../../" + DOC).name == DOC   # 只取檔名，路徑部分被丟掉


def test_locate_real_pdf():
    v = pdfview.locate(DOC, 2, BODY, "第五條（延遲交貨之處理）", ANSWER)
    assert v["pages"] == 5 and 1.3 < v["ratio"] < 1.5
    kinds = [b["kind"] for b in v["boxes"]]
    assert kinds[0] == "region" and kinds.count("hit") == 2   # 0.3% 那句跨兩行
    assert all(0 <= b["x"] <= 1 and 0 <= b["y"] <= 1 for b in v["boxes"])
    assert pdfview.locate(DOC, 9, BODY, "", ANSWER) is None
    assert pdfview.locate("不存在.pdf", 1, BODY, "", ANSWER) is None


def test_add_views_matches_sources_to_hits_and_survives_errors():
    from backend.app.rag.retrieve import Hit

    h = Hit(chunk_id="c", score=1.0, text="【x › 第五條】" + BODY, file_name=DOC, page=2, heading_path=["第五條"])
    from backend.app.rag.answer import to_source
    src = [to_source(h), Source("別的.pdf", 1, "", "x")]
    calls = []
    add_views(src, [h], ANSWER, lambda *a: calls.append(a) or {"ratio": 1, "pages": 1, "boxes": []})
    assert calls == [(DOC, 2, BODY, "第五條", ANSWER)] and src[0].view and src[1].view is None

    def boom(*a):
        raise RuntimeError("壞掉")
    src = [to_source(h)]
    add_views(src, [h], ANSWER, boom)
    assert src[0].view is None


def test_page_endpoint():
    r = client.get("/api/docs/page", params={"file": DOC, "page": 2})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert r.headers["x-page-count"] == "5"
    assert client.get("/api/docs/page", params={"file": DOC, "page": 6}).status_code == 404
    assert client.get("/api/docs/page", params={"file": "../../.env", "page": 1}).status_code == 404
    assert client.get("/api/docs/page", params={"file": DOC, "page": 0}).status_code == 422


def test_file_endpoint():
    r = client.get("/api/docs/file", params={"name": DOC})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    assert client.get("/api/docs/file", params={"name": "../pyproject.toml"}).status_code == 404
