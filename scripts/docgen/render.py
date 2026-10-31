"""文件 DSL 與 PDF 渲染：用 HTML/CSS 排版，再由 Chromium 列印成 PDF（內嵌字型，文字可擷取、有頁碼）。"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

COMPANY = "台中精密零件股份有限公司"
DEMO_NOTE = "【示範資料】虛構文件，僅供系統展示"

CSS = """
body { font-family: "Noto Sans CJK TC", "Noto Sans CJK HK", sans-serif; font-size: 10.5pt; line-height: 1.8; color: #111; margin: 0; }
h1 { font-size: 19pt; text-align: center; margin: 0 0 5mm; letter-spacing: .04em; }
h2 { font-size: 12.5pt; margin: 6mm 0 1.5mm; padding-left: 3mm; border-left: 4px solid #0f4c81; break-after: avoid; }
h3 { font-size: 11pt; margin: 4mm 0 1mm; color: #0f4c81; break-after: avoid; }
p { margin: 1.4mm 0; text-align: justify; }
ul, ol { margin: 1.4mm 0; padding-left: 6mm; }
li { margin: .6mm 0; }
table { border-collapse: collapse; width: 100%; margin: 2.5mm 0; }
th, td { border: .5pt solid #555; padding: 1.5mm 2.2mm; font-size: 9.8pt; vertical-align: top; line-height: 1.55; }
th { background: #e8eef6; font-weight: 700; text-align: left; }
tr { break-inside: avoid; }
caption { caption-side: top; text-align: left; font-weight: 700; padding: 0 0 1mm; font-size: 10pt; }
table.kv th { width: 26%; }
.note { border: .5pt solid #b58900; background: #fff8e1; padding: 2mm 3mm; margin: 3mm 0; font-size: 9.8pt; break-inside: avoid; }
.sign { margin-top: 10mm; break-inside: avoid; }
.sign td { height: 22mm; border: .5pt solid #555; }
.pb { break-before: page; }
"""

HEADER = '<div style="width:100%;font-size:8px;font-family:\'Noto Sans CJK TC\',sans-serif;color:#555;padding:0 20mm;display:flex;justify-content:space-between;"><span>{company}</span><span>{title}</span></div>'
FOOTER = '<div style="width:100%;font-size:8px;font-family:\'Noto Sans CJK TC\',sans-serif;color:#555;padding:0 20mm;display:flex;justify-content:space-between;"><span>{note}</span><span>第 <span class="pageNumber"></span> 頁／共 <span class="totalPages"></span> 頁</span></div>'


@dataclass
class Doc:
    filename: str           # 不含副檔名；開頭決定 doc_type（銷售合約_／採購合約_／SOP_／規格書_／人資_）
    doc_type: str           # 合約／SOP／規格／人資
    title: str
    header: str             # 頁首右側的短標題
    blocks: list = field(default_factory=list)
    facts: list = field(default_factory=list)   # {"q","a","phrase"}：phrase 必須出現在 PDF 文字中，頁碼會自動找出


def H1(t): return ("h1", t)
def H2(t): return ("h2", t)
def H3(t): return ("h3", t)
def P(t): return ("p", t)
def UL(items): return ("ul", list(items))
def OL(items): return ("ol", list(items))
def NOTE(t): return ("note", t)
def BREAK(): return ("break",)
def KV(rows): return ("kv", rows)
def TABLE(headers, rows, caption=None): return ("table", headers, rows, caption)
def SIGN(left, right): return ("sign", left, right)


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def inline(s) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(s))


def block_html(b) -> str:
    k = b[0]
    if k in ("h1", "h2", "h3"):
        return f"<{k}>{inline(b[1])}</{k}>"
    if k == "p":
        return f"<p>{inline(b[1])}</p>"
    if k in ("ul", "ol"):
        return f"<{k}>" + "".join(f"<li>{inline(i)}</li>" for i in b[1]) + f"</{k}>"
    if k == "note":
        return f'<div class="note">{inline(b[1])}</div>'
    if k == "break":
        return '<div class="pb"></div>'
    if k == "kv":
        return '<table class="kv">' + "".join(f"<tr><th>{inline(a)}</th><td>{inline(v)}</td></tr>" for a, v in b[1]) + "</table>"
    if k == "table":
        _, headers, rows, caption = b
        cap = f"<caption>{inline(caption)}</caption>" if caption else ""
        head = "<thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in headers) + "</tr></thead>"
        body = "<tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody>"
        return f"<table>{cap}{head}{body}</table>"
    if k == "sign":
        def cell(lines):
            return "<td>" + "<br>".join(inline(x) for x in lines) + "</td>"
        return f'<table class="sign"><tr>{cell(b[1])}{cell(b[2])}</tr></table>'
    raise ValueError(k)


def doc_html(doc: Doc) -> str:
    body = "".join(block_html(b) for b in doc.blocks)
    return f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8"><title>{esc(doc.title)}</title><style>{CSS}</style></head><body>{body}</body></html>'


def render_pdfs(docs: list[Doc], outdir: Path) -> None:
    from playwright.sync_api import sync_playwright

    outdir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for d in docs:
            page.set_content(doc_html(d), wait_until="load")
            page.pdf(
                path=str(outdir / f"{d.filename}.pdf"), format="A4", print_background=True,
                display_header_footer=True,
                header_template=HEADER.format(company=esc(COMPANY), title=esc(d.header)),
                footer_template=FOOTER.format(note=esc(DEMO_NOTE)),
                margin={"top": "24mm", "bottom": "22mm", "left": "20mm", "right": "20mm"},
            )
        browser.close()
