"""文件原文預覽：把 PDF 某一頁畫成圖片，並找出引用片段在頁面上的位置（給前端畫外框與螢光）。

座標一律換成相對頁面的比例（0～1，原點在左上），前端用百分比疊在圖片上，跟圖片解析度無關。
找不到位置時回傳 None，前端仍可顯示整頁，不影響回答本身。
"""
from __future__ import annotations

import io
import re
import threading
from functools import lru_cache
from pathlib import Path

from ..agent.followups import DOCS_ROOT

RENDER_SCALE = 2.0
MIN_SEG = 4            # 少於 4 個字的片段（表格裡的數字、項次）容易對到別處，不拿來定位
HIT_SCORE = 0.5        # 句子的雙字詞有一半以上出現在回答裡，就當成「回答用到的句子」
HIT_FALLBACK = 0.25    # 沒有句子過門檻時，最相關的那句至少要有這個分數才標
_SPLIT = re.compile(r"(?<=[。；！？!?;])|\n|\|")
_DROP = re.compile(r"[\s#*`>\-—–:：|]+")
_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)
_lock = threading.Lock()   # pdfium 不是 thread-safe，FastAPI 同步端點跑在多執行緒裡


def pdf_path(file_name: str) -> Path | None:
    """只接受 data/ 底下真的存在的 PDF 檔名（白名單比對，不拼接路徑）。"""
    name = Path(file_name).name
    if not name.lower().endswith(".pdf"):
        return None
    for p in DOCS_ROOT.rglob("*.pdf"):
        if p.name == name:
            return p
    return None


def page_count(path: Path) -> int:
    return _page_count(str(path), path.stat().st_mtime)


@lru_cache(maxsize=64)
def _page_count(path: str, _mtime: float) -> int:
    import pypdfium2 as pdfium

    with _lock:
        pdf = pdfium.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()


def render_png(path: Path, page: int) -> bytes:
    """第 page 頁（從 1 起算）的灰階 PNG。灰階讓前端的螢光色更明顯，檔案也小一半。"""
    return _render(str(path), path.stat().st_mtime, page)


@lru_cache(maxsize=48)
def _render(path: str, _mtime: float, page: int) -> bytes:
    import pypdfium2 as pdfium

    with _lock:
        pdf = pdfium.PdfDocument(path)
        try:
            img = pdf[page - 1].render(scale=RENDER_SCALE).to_pil().convert("L")
        finally:
            pdf.close()
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- 定位
def _bigrams(s: str) -> set[str]:
    s = _PUNCT.sub("", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def segments(body: str) -> list[str]:
    """把片段切成句子／表格儲存格；去掉 markdown 記號後太短的不要。"""
    out = []
    for part in _SPLIT.split(body):
        part = part.strip()
        if len(_DROP.sub("", part)) >= MIN_SEG:
            out.append(part)
    return out


def hit_segments(segs: list[str], answer: str) -> set[int]:
    """回答實際用到的句子（依雙字詞重疊比例）。"""
    ans = _bigrams(answer)
    if not ans:
        return set()
    scores = []
    for s in segs:
        b = _bigrams(s)
        scores.append(len(b & ans) / len(b) if b else 0.0)
    hits = {i for i, sc in enumerate(scores) if sc >= HIT_SCORE}
    if not hits and scores and max(scores) >= HIT_FALLBACK:
        hits = {scores.index(max(scores))}
    return hits


def _find(norm: str, needle: str, start: int) -> int:
    """先從上一段之後找（片段順序與頁面順序一致），找不到再全頁找。"""
    i = norm.find(needle, start)
    return i if i >= 0 else norm.find(needle)


def _line_rects(boxes: list[tuple[float, float, float, float]]) -> list[list[float]]:
    """字元框（left, bottom, right, top）依行合併成矩形。"""
    rects: list[list[float]] = []
    for l, b, r, t in boxes:
        if r <= l or t <= b:
            continue
        cur = rects[-1] if rects else None
        # 垂直方向重疊超過較矮者的一半就算同一行（數字、標點的字框比中文字矮）
        overlap = min(t, cur[3]) - max(b, cur[1]) if cur else 0
        if cur and overlap > 0.5 * min(t - b, cur[3] - cur[1]) and l >= cur[0] - 2:
            cur[0], cur[1], cur[2], cur[3] = min(cur[0], l), min(cur[1], b), max(cur[2], r), max(cur[3], t)
        else:
            rects.append([l, b, r, t])
    return rects


def locate_text(chars: list[tuple[str, tuple[float, float, float, float]]], width: float, height: float,
                body: str, heading: str, answer: str) -> list[dict]:
    """純函式（方便測試）：chars 是頁面上每個字與它的框（PDF 座標，原點左下）。
    回傳 [{"kind": "region"|"hit", "x", "y", "w", "h"}]，比例座標、原點左上。"""
    keep = [(c, box) for c, box in chars if c.strip()]
    norm = "".join(c for c, _ in keep)
    segs = segments(body)
    hits = hit_segments(segs, answer)
    region: list[list[float]] = []
    hit_rects: list[list[float]] = []
    pos = 0
    if heading:
        h = _DROP.sub("", heading)
        i = norm.find(h) if len(h) >= MIN_SEG else -1
        if i >= 0:
            region += _line_rects([b for _, b in keep[i:i + len(h)]])
            pos = i + len(h)
    for n, seg in enumerate(segs):
        needle = "".join(seg.split())
        i = _find(norm, needle, pos)
        if i < 0:
            continue
        pos = i + len(needle)
        rects = _line_rects([b for _, b in keep[i:pos]])
        region += rects
        if n in hits:
            hit_rects += rects
    if not region:
        return []

    def rel(r: list[float], kind: str) -> dict:
        l, b, rr, t = r
        return {"kind": kind, "x": round(l / width, 4), "y": round((height - t) / height, 4),
                "w": round((rr - l) / width, 4), "h": round((t - b) / height, 4)}

    frame = [min(r[0] for r in region), min(r[1] for r in region), max(r[2] for r in region), max(r[3] for r in region)]
    return [rel(frame, "region")] + [rel(r, "hit") for r in hit_rects]


def locate(file_name: str, page: int, body: str, heading: str, answer: str) -> dict | None:
    """回傳 {"ratio": 頁高/頁寬, "pages": 總頁數, "boxes": [...]}；找不到檔案或頁數不對時回傳 None。"""
    path = pdf_path(file_name)
    if not path:
        return None
    import pypdfium2 as pdfium

    with _lock:
        pdf = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page <= len(pdf):
                return None
            total = len(pdf)
            pg = pdf[page - 1]
            width, height = pg.get_size()
            tp = pg.get_textpage()
            text = tp.get_text_range()
            chars = [(text[i] if i < len(text) else "", tp.get_charbox(i)) for i in range(tp.count_chars())]
        finally:
            pdf.close()
    return {"ratio": round(height / width, 4), "pages": total,
            "boxes": locate_text(chars, width, height, body, heading, answer)}
