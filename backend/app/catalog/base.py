"""查詢模板的共用資料結構。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..sql_guard import validate


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Literal["period", "enum", "int", "entity"]
    label: str                                    # 中文名稱，用於提示與反問
    required: bool = False
    default: Any = None
    choices: dict[str, list[str]] | None = None   # enum：{標準值: [同義詞…]}；標準值同時是白名單對照表的 key
    entity: Literal["customer", "supplier", "sku", "rep"] | None = None
    min: int | None = None
    max: int | None = None


@dataclass
class BuiltQuery:
    sql: str            # 只含 :name 綁定參數；已通過 sql_guard.validate
    binds: dict


@dataclass
class QueryTemplate:
    id: str
    title: str                                    # 例如「營收排名」
    description: str                              # 給 LLM 看的一句話說明
    examples: list[str]                           # 意圖辨識用的範例說法（≥ 5 句，措辭多樣）
    params: list[ParamSpec]
    build: Callable[[dict], BuiltQuery]           # 純函式：已驗證的參數 → SQL 與綁定參數
    facts: Callable[[list[str], list[list]], dict]  # 程式算出的事實（總額、第一名、占比…）
    summary: Callable[[dict], str]                # 固定句型摘要（LLM 失敗或數字檢查不過時使用）
    columns: Callable[[dict], list[str]] = field(default=lambda p: [])  # 結果欄位（給使用者確認時預覽）


class TemplateError(ValueError):
    """模板 SQL 未通過守門員（程式錯誤，不是使用者錯誤）。"""


def guarded(sql: str, binds: dict) -> BuiltQuery:
    """模板 SQL 也必須通過守門員；回傳已標準化（補 LIMIT）的 SQL。"""
    g = validate(sql)
    if not g.ok:
        raise TemplateError(f"模板 SQL 未通過守門員：{g.reason}")
    return BuiltQuery(g.sql, binds)
