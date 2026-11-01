"""文件原文預覽：GET /api/docs/page（某一頁的圖片）、GET /api/docs/file（下載原始 PDF）。

檔名只接受 data/ 底下真的存在的 PDF（pdfview.pdf_path 白名單比對），不會讀到其他路徑。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from ..rag import pdfview

router = APIRouter(prefix="/api/docs")


def _path(file: str):
    path = pdfview.pdf_path(file)
    if not path:
        raise HTTPException(404, "找不到這份文件")
    return path


@router.get("/page")
def page(file: str = Query(..., max_length=200), page: int = Query(..., ge=1, le=999)) -> Response:
    path = _path(file)
    total = pdfview.page_count(path)
    if page > total:
        raise HTTPException(404, f"這份文件只有 {total} 頁")
    return Response(pdfview.render_png(path, page), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=600", "X-Page-Count": str(total)})


@router.get("/file")
def file(name: str = Query(..., max_length=200)) -> FileResponse:
    path = _path(name)
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")
