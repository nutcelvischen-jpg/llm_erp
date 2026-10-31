"""把資料夾內的 PDF 索引進 Qdrant：python scripts/ingest_docs.py data/docs [--force] [--recreate]"""
import argparse
import time
from pathlib import Path

from qdrant_client import QdrantClient

from backend.app import llm
from backend.app.config import settings
from backend.app.rag.ingest import ensure_collection, ingest_pdf

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--force", action="store_true", help="忽略 mtime，全部重建")
ap.add_argument("--recreate", action="store_true", help="刪除並重建 collection")
a = ap.parse_args()

client = QdrantClient(url=settings.qdrant_url)
name = ensure_collection(client, recreate=a.recreate)
pdfs = sorted(Path(a.folder).glob("*.pdf"))
t0, total, skipped = time.time(), 0, 0
for i, p in enumerate(pdfs, 1):
    t = time.time()
    n = ingest_pdf(client, p, llm.embed, force=a.force or a.recreate, name=name)
    if n is None:
        skipped += 1
        print(f"[{i}/{len(pdfs)}] 跳過（未變更） {p.name}")
    else:
        total += n
        print(f"[{i}/{len(pdfs)}] {n:3} 塊  {time.time() - t:4.1f}s  {p.name}")
cnt = client.count(name, exact=True).count
print(f"\n完成：本次寫入 {total} 塊，跳過 {skipped} 份；collection {name} 共 {cnt} 筆；耗時 {time.time() - t0:.0f} 秒")
