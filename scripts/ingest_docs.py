"""把資料夾內的 PDF 索引進 Qdrant：python scripts/ingest_docs.py data/docs [--force] [--recreate]"""
import argparse

from qdrant_client import QdrantClient

from backend.app import llm
from backend.app.config import settings
from backend.app.rag.ingest import ingest_folder

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--force", action="store_true", help="忽略 mtime，全部重建")
ap.add_argument("--recreate", action="store_true", help="刪除並重建 collection")
a = ap.parse_args()


def show(i, n, name, written):
    print(f"[{i}/{n}] " + ("跳過（未變更） " if written is None else f"{written:3} 塊  ") + name)


s = ingest_folder(QdrantClient(url=settings.qdrant_url), a.folder, llm.embed, a.force, a.recreate, show)
print(f"\n完成：本次寫入 {s['written']} 塊，跳過 {s['skipped']} 份；collection {settings.qdrant_collection} "
      f"共 {s['points']} 筆；耗時 {s['seconds']:.0f} 秒")
