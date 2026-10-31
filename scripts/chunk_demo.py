"""解析全部 data/docs PDF 並切塊，印出統計（用來預估 T18 的索引筆數）。"""
import statistics
import time
from pathlib import Path

from backend.app.rag.chunk import chunk_blocks
from backend.app.rag.parse import parse_pdf

t = time.time()
allc = []
for p in sorted(Path("data/docs").glob("*.pdf")):
    cs = chunk_blocks(parse_pdf(p))
    allc += cs
    print(f"{p.name:34} {len(cs):3} 塊（表格 {sum(c.kind == 'table' for c in cs)}）")
L = [len(c.text) for c in allc]
print(f"\n共 {len(allc)} 塊；字數 min/median/max = {min(L)}/{int(statistics.median(L))}/{max(L)}；"
      f"表格塊 {sum(c.kind == 'table' for c in allc)}；耗時 {time.time() - t:.0f} 秒")
