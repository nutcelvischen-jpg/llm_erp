"""所有既定查詢程式（模板）。新增模板：寫在 templates/ 下，再加進這裡。"""
from __future__ import annotations

from .base import QueryTemplate
from .templates import inventory, purchasing, receivable, sales

TEMPLATES: dict[str, QueryTemplate] = {
    t.id: t for mod in (sales, receivable, inventory, purchasing) for t in mod.TEMPLATES
}
