"""手動檢視 T16 解析結果：python scripts/parse_demo.py [pdf 檔名關鍵字]（預設鴻遠機械合約）。"""
import sys
import time
from pathlib import Path

from backend.app.rag.parse import parse_pdf

key = sys.argv[1] if len(sys.argv) > 1 else "銷售合約_鴻遠機械"
p = next(Path("data/docs").glob(f"*{key}*.pdf"))
t = time.time()
bl = parse_pdf(p)
print(f"{p.name}：{len(bl)} 個 Block，表格 {sum(b.kind == 'table' for b in bl)} 個，{time.time() - t:.1f} 秒\n")
for b in bl:
    print(f"[p{b.page}] {b.kind:5} {' > '.join(b.heading_path) or '(無標題)'}")
    print("   ", b.text[:90].replace("\n", " ⏎ "))
