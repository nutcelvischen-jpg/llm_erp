"""模板共用工具：期間綁定、可選條件、白名單取值、數字格式。

規則：值一律用 :name 綁定；欄位名稱、排序方向等「結構」只能從白名單對照表取出。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..periods import Period, compare_periods, resolve_period

DIR = {"desc": "DESC", "asc": "ASC"}
ORDER_CHOICES = {"desc": ["由高到低", "最高", "最多", "最大", "前幾名", "降冪", "top"],
                 "asc": ["由低到高", "最低", "最少", "最小", "後幾名", "升冪", "bottom"]}
REGIONS = {"北部": ["北區", "台北", "北"], "中部": ["中區", "台中", "中"], "南部": ["南區", "高雄", "南"],
           "海外": ["國外", "外銷", "海外客戶"]}
CATEGORIES = {"軸承": ["bearing", "BRG"], "齒輪": ["gear", "GEAR"], "墊片": ["墊圈", "華司", "WSH"],
              "扣件": ["螺栓", "螺絲", "FST"], "客製件": ["客製", "CUS"]}


def today_of(p: dict) -> date:
    return p.get("_today") or date.today()


def period(p: dict, key: str = "period") -> Period:
    return resolve_period(p[key], today_of(p))


def period_binds(p: dict, key: str = "period") -> dict:
    per = period(p, key)
    return {"date_from": per.date_from, "date_to": per.date_to}


def compare_binds(p: dict, key: str = "compare") -> dict:
    cur, prev = compare_periods(p[key], today_of(p))
    return {"cur_from": cur.date_from, "cur_to": cur.date_to, "prev_from": prev.date_from, "prev_to": prev.date_to}


def opt_eq(column: str, name: str) -> str:
    """可選條件：參數為 None 時不篩選。column 必須是程式寫死的欄位。"""
    return f"(CAST(:{name} AS TEXT) IS NULL OR {column} = :{name})"


def pick(table: dict[str, Any], key: str) -> Any:
    """從白名單對照表取值；不在表中就丟錯（normalize_params 應已擋下）。"""
    if key not in table:
        raise ValueError(f"不在白名單中：{key!r}")
    return table[key]


def top(p: dict, key: str = "top_n", default: int = 10, hi: int = 50) -> int:
    """已驗證的整數直接寫成常數（守門員會把非常數 LIMIT 壓成 1000）。"""
    v = p.get(key)
    return max(1, min(int(default if v is None else v), hi))


# ---------- 數字格式 ----------
def money(v) -> str:
    return "-" if v is None else f"{round(float(v)):,} 元"


def num(v) -> str:
    if v is None:
        return "-"
    f = float(v)
    return f"{int(f):,}" if f.is_integer() else f"{f:,.1f}"


def pct(v) -> str:
    return "-" if v is None else f"{float(v):.1f}%"


def col(columns: list[str], rows: list[list], name: str) -> list:
    i = columns.index(name)
    return [r[i] for r in rows]


def first(columns: list[str], rows: list[list]) -> dict:
    return dict(zip(columns, rows[0])) if rows else {}


def fmt(column: str, v) -> str:
    """依欄位名稱決定格式：比率 → %、金額 → 元、其他 → 千分位。"""
    if v is None:
        return "-"
    if not isinstance(v, int | float):
        return str(v)
    if any(k in column for k in ("率", "%", "占比")):
        return pct(v)
    if any(k in column for k in ("營收", "毛利", "金額", "總額", "本期", "比較期", "增減")) and "數" not in column:
        return money(v)
    return num(v)
