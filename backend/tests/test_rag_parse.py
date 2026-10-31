from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from backend.app.rag.parse import Block, blocks_from_docling, clean_text, doc_id_of


class FakeDoc:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return [(i, 0) for i in self._items]


def it(label, text="", page=1, level=1, md=None, marker=None):
    o = NS(label=NS(value=label), text=text, prov=[NS(page_no=page)], level=level)
    if marker:
        o.marker = marker
    if md is not None:
        o.export_to_markdown = lambda doc=None: md
    return o


def test_clean_text_fixes_radicals_keeps_fullwidth():
    assert clean_text("每箱淨重不⾜ 20 公⽄（含包材）") == "每箱淨重不足 20 公斤（含包材）"
    assert clean_text("HRC 58‒62") == "HRC 58–62"
    assert clean_text("⼩時") == "小時"


def test_doc_id_stable_12():
    assert doc_id_of("a.pdf") == doc_id_of("a.pdf") and len(doc_id_of("a.pdf")) == 12


def test_heading_path_and_merge():
    doc = FakeDoc([
        it("title", "銷售合約", 1),
        it("section_header", "第二條 交期", 1, level=1),
        it("text", "交期為 30 日。", 1),
        it("text", "逾期處理如下。", 1),
        it("section_header", "2.1 違約金", 2, level=2),
        it("text", "每逾一日按 0.3%。", 2),
        it("page_footer", "第 2 頁", 2),
        it("section_header", "第三條 付款", 3, level=1),
        it("text", "月結 30 天。", 3),
    ])
    bl = blocks_from_docling(doc, "x.pdf")
    assert [b.page for b in bl] == [1, 2, 3]
    assert bl[0].heading_path == ["銷售合約", "第二條 交期"]
    assert bl[0].text == "交期為 30 日。\n逾期處理如下。"
    assert bl[1].heading_path == ["銷售合約", "第二條 交期", "2.1 違約金"]
    assert "0.3%" in bl[1].text and "第 2 頁" not in bl[1].text
    assert bl[2].heading_path == ["銷售合約", "第三條 付款"]


def test_table_block():
    doc = FakeDoc([it("section_header", "費率", 2), it("table", page=2, md="| 項目 | 值 |\n|---|---|\n| 違約金 | 0.3% |")])
    bl = blocks_from_docling(doc, "x.pdf")
    assert len(bl) == 1 and bl[0].kind == "table" and bl[0].page == 2 and "0.3%" in bl[0].text
    assert bl[0].heading_path == ["費率"]


def test_list_item_marker():
    bl = blocks_from_docling(FakeDoc([it("list_item", "第一項", 1, marker="1.")]), "x.pdf")
    assert bl[0].text == "1. 第一項"


@pytest.mark.db  # 需要 Docling 模型（首次會下載），故與 DB 測試同組，不拖慢 make test
def test_parse_real_contract():
    from backend.app.rag.parse import parse_pdf

    p = Path(__file__).resolve().parents[2] / "data" / "docs" / "銷售合約_鴻遠機械.pdf"
    bl = parse_pdf(p)
    assert all(isinstance(b, Block) for b in bl)
    assert any(b.kind == "table" for b in bl)
    hit = [b for b in bl if "0.3%" in b.text]
    assert hit and hit[0].page == 2
    assert all(b.page >= 1 and b.doc_id == doc_id_of(p.name) for b in bl)
