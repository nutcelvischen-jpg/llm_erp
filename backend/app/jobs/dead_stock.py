"""T27 呆滯庫存與缺料預警（每週排程）。

1. 呆滯：v_庫存狀況 中 未異動天數 >= 180 且 現有庫存 > 0。
2. 缺料：現有庫存 + 在途數量 < 待出貨數量，或 現有庫存 < 安全庫存。
   缺口 = max(待出貨數量 − 現有庫存 − 在途數量, 0)；建議採購量 = 缺口 + 安全庫存。
3. LLM 把重點寫成 ≤150 字摘要（數字檢查不過、超長或漏了缺料料號 → 改用固定句型），
   程式再附上完整料號明細，存進 app.notifications。

用法：uv run python -m backend.app.jobs.dead_stock [--save]   （預設 dry run，只印出訊息）
"""
from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from .. import numcheck

log = logging.getLogger(__name__)

JOB_NAME = "dead_stock"
IDLE_DAYS = 180
SUMMARY_MAX = 150
TOP_DEAD = 3

DEAD_SQL = text("""
SELECT "料號", "品名", "現有庫存", ROUND("庫存金額", 0) AS "庫存金額", "未異動天數"
FROM erp."v_庫存狀況"
WHERE "未異動天數" >= :idle AND "現有庫存" > 0
ORDER BY "庫存金額" DESC, "料號"
""")

SHORTAGE_SQL = text("""
SELECT "料號", "品名", "現有庫存", "在途數量", "待出貨數量", "安全庫存",
       GREATEST("待出貨數量" - "現有庫存" - "在途數量", 0) AS "缺口",
       GREATEST("待出貨數量" - "現有庫存" - "在途數量", 0) + "安全庫存" AS "建議採購量",
       "供應商", "供應商交期天數"
FROM erp."v_庫存狀況"
WHERE "現有庫存" + "在途數量" < "待出貨數量" OR "現有庫存" < "安全庫存"
ORDER BY "缺口" DESC, "料號"
""")

SUMMARY_SYSTEM = """你是公司的庫存預警小幫手，要把每週的呆滯庫存與缺料資料寫成一則給老闆看的 LINE 訊息。

規則：
1. 繁體中文（台灣用語），全文不超過 120 字，純文字，不要 Markdown、不要條列符號、不要表情符號。
2. 必須提到：呆滯項數與庫存金額合計、金額最高的呆滯料號、每一個缺料料號與其建議採購量。
3. 只能使用「資料」中提供的數字與格式化字串，照原樣引用，不可自行計算、換算或四捨五入。
4. 不推測原因，不加問候語，不寫日期與標題（系統會自動加上「【庫存預警 月/日】」）。
"""


@dataclass
class Report:
    today: date
    dead: list[dict] = field(default_factory=list)
    shortage: list[dict] = field(default_factory=list)

    @property
    def dead_total(self) -> float:
        return sum(r["庫存金額"] for r in self.dead)


def _plain(v):
    return float(v) if isinstance(v, Decimal) else v


def collect(engine=None, today: date | None = None, idle_days: int = IDLE_DAYS) -> Report:
    if engine is None:
        from ..db import engine_ro as engine
    with engine.connect() as c:
        c.execute(text("SET LOCAL statement_timeout = '10s'"))
        dead = [{k: _plain(v) for k, v in r.items()} for r in c.execute(DEAD_SQL, {"idle": idle_days}).mappings()]
        short = [{k: _plain(v) for k, v in r.items()} for r in c.execute(SHORTAGE_SQL).mappings()]
    return Report(today or date.today(), dead, short)


def wan(v: float) -> str:
    """金額轉「萬」，一位小數。"""
    return f"{v / 1e4:,.1f} 萬"


def facts_text(rep: Report) -> str:
    lines = [f"日期：{rep.today:%m/%d}",
             f"呆滯（{IDLE_DAYS} 天以上未異動）項數：{len(rep.dead)}；庫存金額合計：{wan(rep.dead_total)}元"]
    for r in rep.dead[:TOP_DEAD]:
        lines.append(f"呆滯：{r['料號']} {r['品名']}，庫存金額 {wan(r['庫存金額'])}元，{r['未異動天數']} 天未異動")
    lines.append(f"缺料項數：{len(rep.shortage)}")
    for r in rep.shortage:
        lines.append(f"缺料：{r['料號']} {r['品名']}，缺口 {r['缺口']:,}，建議採購 {r['建議採購量']:,}，"
                     f"供應商 {r['供應商']}（交期 {r['供應商交期天數']} 天）")
    return "\n".join(lines)


def fixed_summary(rep: Report) -> str:
    head = f"【庫存預警 {rep.today:%m/%d}】"
    if rep.dead:
        top = rep.dead[0]
        dead = (f"呆滯（{IDLE_DAYS} 天未異動）{len(rep.dead)} 項，壓 {wan(rep.dead_total)}元，"
                f"最多 {top['料號']} {wan(top['庫存金額'])}元。")
    else:
        dead = "無呆滯料號。"
    if rep.shortage:
        items = [f"{r['料號']} 建議採購 {r['建議採購量']:,}" for r in rep.shortage[:3]]
        more = f"等 {len(rep.shortage)} 項" if len(rep.shortage) > 3 else ""
        short = f"缺料 {len(rep.shortage)} 項：" + "、".join(items) + more + "。"
    else:
        short = "無缺料。"
    return head + dead + short


def details_text(rep: Report) -> str:
    out = []
    if rep.dead:
        out.append(f"呆滯料號（{len(rep.dead)}）：" + "、".join(r["料號"] for r in rep.dead))
    if rep.shortage:
        out.append("缺料明細：" + "；".join(
            f"{r['料號']} 缺 {r['缺口']:,}，建議採購 {r['建議採購量']:,}（{r['供應商']}，交期 {r['供應商交期天數']} 天）"
            for r in rep.shortage))
    return "\n".join(out)


def check_summary(summary: str, rep: Report) -> list[str]:
    """回傳不合格原因；空清單表示可用。"""
    problems = []
    if not summary:
        return ["空白"]
    if len(summary) > SUMMARY_MAX:
        problems.append(f"超過 {SUMMARY_MAX} 字（{len(summary)}）")
    missing = [r["料號"] for r in rep.shortage if r["料號"] not in summary]
    if missing:
        problems.append(f"漏了缺料料號 {missing}")
    rows = [list(r.values()) for r in rep.dead + rep.shortage]
    bad = numcheck.unsupported_numbers(summary, [facts_text(rep)], rows)
    if bad:
        problems.append(f"未獲支持的數字 {bad}")
    return problems


def _default_chat(messages: list[dict]):
    from .. import llm

    return llm.chat(messages, temperature=0.1, max_tokens=400)


def summarize(rep: Report, chat: Callable | None = None) -> tuple[str, str]:
    """回傳 (摘要, 來源 llm|fixed)。"""
    chat = chat or _default_chat
    try:
        r = chat([{"role": "system", "content": SUMMARY_SYSTEM},
                  {"role": "user", "content": f"資料：\n{facts_text(rep)}"}])
        text_ = " ".join(r.text.split())
    except Exception as e:  # noqa: BLE001
        log.warning("LLM 摘要失敗，改用固定句型：%s", e)
        return fixed_summary(rep), "fixed"
    if text_ and not text_.startswith("【"):
        text_ = f"【庫存預警 {rep.today:%m/%d}】{text_}"
    problems = check_summary(text_, rep)
    if problems:
        log.warning("LLM 摘要不合格（%s），改用固定句型：%r", "；".join(problems), text_)
        return fixed_summary(rep), "fixed"
    return text_, "llm"


def compose(summary: str, rep: Report) -> str:
    details = details_text(rep)
    return f"{summary}\n\n{details}" if details else summary


def save_notification(message: str, channel: str, engine=None) -> int:
    if engine is None:
        from ..db import engine
    with engine.begin() as c:
        return int(c.execute(text(
            "INSERT INTO app.notifications (job_name, channel, payload, sent) VALUES (:j, :c, :p, false) RETURNING id"),
            {"j": JOB_NAME, "c": channel, "p": message}).scalar_one())


def _channel() -> str:
    from ..config import settings

    return "line" if settings.line_channel_access_token and settings.line_target_id else "console"


def run(dry_run: bool = True, *, report: Report | None = None, chat: Callable | None = None,
        save: Callable | None = None) -> str:
    """產生預警訊息並回傳。dry_run=False 時寫入 app.notifications。"""
    rep = report or collect()
    summary, source = summarize(rep, chat)
    message = compose(summary, rep)
    log.info("庫存預警：呆滯 %d 項、缺料 %d 項，摘要來源 %s", len(rep.dead), len(rep.shortage), source)
    if not dry_run:
        nid = (save or save_notification)(message, _channel())
        log.info("已寫入 app.notifications id=%s", nid)
    return message


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="呆滯庫存與缺料預警")
    ap.add_argument("--save", action="store_true", help="寫入 app.notifications（預設只印出，不寫入）")
    print(run(dry_run=not ap.parse_args().save))
