"""T17 切塊：Block → Chunk。純函式，無外部依賴。

規則：以 heading 為邊界（Block 本身已按標題／頁分隔，不跨 Block 合併）；文字累積到約
TEXT_TARGET 字切一塊、重疊 OVERLAP 字；表格整張一塊，超過 TABLE_MAX 字則按列切並重複表頭；
每塊前綴 【檔名 › 標題路徑】。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parse import Block

TEXT_TARGET = 600
OVERLAP = 80
TABLE_MAX = 1500

_DOC_TYPES = (("銷售合約", "合約"), ("採購合約", "合約"), ("SOP", "SOP"), ("規格書", "規格"), ("人資", "人資"))
_SENT = re.compile(r"(?<=[。！？；!?;\n])")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    file_name: str
    page: int
    heading_path: list[str] = field(default_factory=list)
    text: str = ""
    kind: str = "text"
    doc_type: str = "其他"


def doc_type_of(file_name: str) -> str:
    for prefix, t in _DOC_TYPES:
        if file_name.startswith(prefix):
            return t
    return "其他"


def prefix_of(file_name: str, heading_path: list[str]) -> str:
    return "【" + " › ".join([file_name, *heading_path]) + "】"


def _units(text: str) -> list[str]:
    out: list[str] = []
    for s in _SENT.split(text):
        while len(s) > TEXT_TARGET:  # 沒有標點的超長句：硬切
            out.append(s[:TEXT_TARGET])
            s = s[TEXT_TARGET:]
        if s:
            out.append(s)
    return out


def split_text(text: str, target: int = TEXT_TARGET, overlap: int = OVERLAP) -> list[str]:
    """累積到約 target 字切一塊；下一塊以前一塊最後 overlap 字開頭。"""
    text = text.strip()
    if len(text) <= target + overlap:  # 稍微超過就不切，避免產生極短尾巴
        return [text] if text else []
    parts: list[str] = []
    buf, new = "", 0  # new = buf 內非重疊的新內容長度
    for u in _units(text):
        if buf and new and len(buf) + len(u) > target:
            parts.append(buf.strip())
            buf, new = buf[-overlap:], 0
        buf += u
        new += len(u)
    if new:
        parts.append(buf.strip())
    return parts


def split_table(md: str, limit: int = TABLE_MAX) -> list[str]:
    md = md.strip()
    if len(md) <= limit:
        return [md]
    lines = md.split("\n")
    head, rows = lines[:2], lines[2:]  # Markdown 表格：表頭列 + 分隔列
    if len(lines) < 3 or not set(lines[1].replace("|", "").strip()) <= set("-: "):
        head, rows = [], lines
    parts: list[str] = []
    cur: list[str] = []
    size = sum(len(x) + 1 for x in head)
    for r in rows:
        if cur and size + len(r) + 1 > limit:
            parts.append("\n".join(head + cur))
            cur, size = [], sum(len(x) + 1 for x in head)
        cur.append(r)
        size += len(r) + 1
    if cur:
        parts.append("\n".join(head + cur))
    return parts


def chunk_blocks(blocks: list[Block]) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq: dict[str, int] = {}
    for b in blocks:
        body = split_table(b.text) if b.kind == "table" else split_text(b.text)
        pre = prefix_of(b.file_name, b.heading_path)
        for piece in body:
            n = seq.get(b.doc_id, 0)
            seq[b.doc_id] = n + 1
            chunks.append(Chunk(f"{b.doc_id}-{n:03d}", b.doc_id, b.file_name, b.page, list(b.heading_path),
                                f"{pre}\n{piece}", b.kind, doc_type_of(b.file_name)))
    return chunks
