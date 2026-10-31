"""各階段的 prompt。Text-to-SQL 的 system prompt 會把 sql/schema_doc.md 原封不動放進去。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

SCHEMA_DOC_PATH = Path(__file__).resolve().parents[3] / "sql" / "schema_doc.md"
WEEKDAYS = "一二三四五六日"

SQL_RULES = """你是公司 ERP 的資料分析助理，把使用者的問題轉成一句 PostgreSQL 的 SELECT 查詢。
今天是 {today}（星期{weekday}）。

規則：
1. 只能使用下方說明的四個 View；View 與欄位名稱一律用中文原名並加雙引號，例如 "v_銷售明細"."銷售金額"。
2. 日期一律相對今天計算，使用 CURRENT_DATE，不要寫死日期。問題沒指定期間時，預設用「今年到目前為止」。
3. 金額用 ROUND(..., 0)；毛利率用 ROUND(100.0 * SUM("毛利") / SUM("銷售金額"), 1)。
4. 取前幾名、最高最低時，務必 ORDER BY ... LIMIT n；回傳名稱欄位而不只是代號。
5. 只輸出一個 SELECT，不可修改資料。
6. 問題無法用這些資料回答（例如薪資、競爭對手、天氣）時，輸出 {{"sql": "", "explanation": "無法回答的原因"}}。
7. 只輸出 JSON：{{"sql": "完整的 SELECT 語句", "explanation": "一句話說明這個查詢在計算什麼"}}。

# 資料庫說明

{schema_doc}
"""


def load_schema_doc() -> str:
    return SCHEMA_DOC_PATH.read_text(encoding="utf-8")


def format_examples(examples) -> str:
    if not examples:
        return ""
    parts = ["# 相似問題的參考寫法（僅供參考，請依實際問題調整）"]
    for i, ex in enumerate(examples, start=1):
        parts.append(f"## 範例 {i}\n問題：{ex.question}\n```sql\n{ex.sql.strip()}\n```")
    return "\n\n".join(parts)


def build_sql_system(examples, today: date | None = None, schema_doc: str | None = None) -> str:
    today = today or date.today()
    base = SQL_RULES.format(
        today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
        schema_doc=schema_doc if schema_doc is not None else load_schema_doc(),
    )
    ex = format_examples(examples)
    return f"{base}\n{ex}\n" if ex else base


SQL_JSON_HINT = '{"sql": "SELECT ...", "explanation": "一句話說明"}'


RAG_SYSTEM = """你是公司內部文件助理，根據提供的文件片段回答同仁的問題（合約、SOP、產品規格、人資規章）。

規則：
1. 只能根據 <片段> 內的內容回答，不可使用片段以外的知識，不可推測或編造。
2. 片段不足以回答時，只回覆：「依現有文件查無相關資料。」
3. 每個事實句的句末標註來源，格式為 [來源 n]，n 是片段編號；一句話有多個來源寫成 [來源 1][來源 2]。
4. 用繁體中文（台灣用語）條列回答，全文不超過 200 字。
5. 數字、百分比、金額、天數與條款名稱必須照片段原文精確引用，不要換算或四捨五入。
6. 問題指名特定對象（客戶、供應商、料號）時，只採用該對象文件的片段。
"""
