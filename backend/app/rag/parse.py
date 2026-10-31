"""T16 文件解析：PDF → 帶頁碼與標題階層的 Block 清單。

Docling 負責版面與表格；本檔把它的輸出轉成 Block。轉換邏輯（blocks_from_docling）
只依賴 iterate_items() 的介面，不 import docling，所以能用假文件做單元測試。
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SKIP_LABELS = {"page_header", "page_footer"}
TABLE_LABELS = {"table"}
HEADING_LABELS = {"section_header", "title"}


@dataclass
class Block:
    doc_id: str
    file_name: str
    page: int
    heading_path: list[str] = field(default_factory=list)
    kind: str = "text"  # text / table
    text: str = ""


def doc_id_of(file_name: str) -> str:
    return hashlib.sha1(file_name.encode("utf-8")).hexdigest()[:12]


def clean_text(s: str) -> str:
    """PDF 抽字常把中文換成部首／相容字元（如「⼩」「⾏」）。只正規化這些字元，
    不動全形標點（NFKC 會把「（」變成「(」，不要）；並把各種破折號統一為 en dash。"""
    out = []
    for ch in s:
        o = ord(ch)
        if 0x2E80 <= o <= 0x2FDF or 0xF900 <= o <= 0xFAFF or 0x2F800 <= o <= 0x2FA1F:
            ch = unicodedata.normalize("NFKC", ch)
        elif o in (0x2010, 0x2011, 0x2012, 0x2015, 0x2212):
            ch = "–"
        out.append(ch)
    return "".join(out).replace(" ", " ").strip()


def _label(item) -> str:
    lab = getattr(item, "label", "")
    return str(getattr(lab, "value", lab))


def _page(item) -> int | None:
    prov = getattr(item, "prov", None)
    return prov[0].page_no if prov else None


def blocks_from_docling(doc, file_name: str) -> list[Block]:
    """走訪 DoclingDocument，產生 Block。同頁、同標題路徑的連續文字合併為一個 Block；
    每個表格獨立一個 Block（Markdown 表格文字）。"""
    did = doc_id_of(file_name)
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    cur_page = 1

    def path() -> list[str]:
        return [t for _, t in stack]

    for item, _lvl in doc.iterate_items():
        label = _label(item)
        if label in SKIP_LABELS:
            continue
        page = _page(item) or cur_page
        cur_page = page

        if label in HEADING_LABELS:
            title = clean_text(getattr(item, "text", "") or "")
            if not title:
                continue
            level = 0 if label == "title" else int(getattr(item, "level", 1) or 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue

        if label in TABLE_LABELS:
            try:
                md = item.export_to_markdown(doc=doc)
            except TypeError:
                md = item.export_to_markdown()
            md = clean_text(md)
            if md:
                blocks.append(Block(did, file_name, page, path(), "table", md))
            continue

        text = clean_text(getattr(item, "text", "") or "")
        if not text:
            continue
        if label == "list_item":
            marker = getattr(item, "marker", "") or "-"
            text = f"{marker} {text}" if not text.startswith(marker) else text
        last = blocks[-1] if blocks else None
        if last and last.kind == "text" and last.page == page and last.heading_path == path():
            last.text += "\n" + text
        else:
            blocks.append(Block(did, file_name, page, path(), "text", text))
    return blocks


def _converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = False  # 我們的 PDF 都有文字層；關掉 OCR 較快，也少下載模型
    opts.do_table_structure = True
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


_CONVERTER = None


def parse_pdf(path: Path) -> list[Block]:
    global _CONVERTER
    path = Path(path)
    if _CONVERTER is None:
        _CONVERTER = _converter()
    result = _CONVERTER.convert(str(path))
    return blocks_from_docling(result.document, path.name)
