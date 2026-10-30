"""Text-to-SQL 評估：逐題跑黃金問答集（data/golden/text2sql.yaml），統計正確率與延遲。

用法：
  make eval-sql                                   跑全部 30 題（需要 LM Studio 與資料庫）
  uv run python scripts/eval_text2sql.py --only Q01,Q05
  uv run python scripts/eval_text2sql.py --category 應收
  uv run python scripts/eval_text2sql.py --threshold 0.8   低於此正確率時結束碼為 1（預設 0.8）
報告輸出到 data/golden/report_text2sql_<日期>.md。改 prompt、範例或 schema_doc.md 之後都要重跑，確認沒有退步。
"""
import argparse
import math
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import eval_checks, text2sql
from backend.app.config import settings
from backend.app.db import engine

GOLDEN = ROOT / "data" / "golden" / "text2sql.yaml"


def load_questions(only: set[str] | None, category: str | None) -> list[dict]:
    qs = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    if only:
        qs = [q for q in qs if q["id"] in only]
    if category:
        qs = [q for q in qs if q["category"] == category]
    return qs


def run_one(q: dict) -> dict:
    ref_rows = None
    if "rows_match" in q:
        try:
            _, ref_rows = text2sql._execute(q["rows_match"])
        except Exception as e:  # noqa: BLE001
            return {**q, "ok": False, "why": f"參考 SQL 執行失敗：{str(e)[:150]}", "attempts": 0, "seconds": 0.0, "sql": "", "error": None}
    t0 = time.perf_counter()
    ans = text2sql.run(q["question"])
    seconds = time.perf_counter() - t0
    ok, why = eval_checks.evaluate(q, ans, ref_rows)
    return {**q, "ok": ok, "why": why, "attempts": ans.attempts, "seconds": seconds, "sql": ans.sql,
            "error": ans.error, "row_count": ans.row_count, "head": ans.rows[:3]}


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[max(0, math.ceil(0.95 * len(xs)) - 1)]


def write_report(results: list[dict], rate: float, path: Path) -> None:
    n = len(results)
    secs = [r["seconds"] for r in results]
    lines = [
        f"# Text-to-SQL 評估報告 {date.today()}",
        "",
        f"- 模型：`{settings.llm_model}`；embedding：`{settings.embed_model}`",
        f"- **正確率：{sum(r['ok'] for r in results)}/{n} = {rate:.0%}**",
        f"- 平均延遲 {statistics.mean(secs):.1f} 秒；P95 {p95(secs):.1f} 秒；最慢 {max(secs):.1f} 秒",
        f"- 平均嘗試次數 {statistics.mean(r['attempts'] for r in results):.2f}（1 表示一次就對）",
        "",
        "## 各類別",
        "",
        "| 類別 | 通過 | 題數 |",
        "|---|---|---|",
    ]
    for cat in dict.fromkeys(r["category"] for r in results):
        rs = [r for r in results if r["category"] == cat]
        lines.append(f"| {cat} | {sum(r['ok'] for r in rs)} | {len(rs)} |")
    lines += ["", "## 逐題結果", "", "| ID | 結果 | 嘗試 | 秒 | 問題 |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {'✅' if r['ok'] else '❌'} | {r['attempts']} | {r['seconds']:.1f} | {r['question']} |")
    failed = [r for r in results if not r["ok"]]
    if failed:
        lines += ["", "## 失敗題目細節", ""]
        for r in failed:
            lines += [f"### {r['id']} {r['question']}", f"- 原因：{r['why']}"]
            if r.get("error"):
                lines.append(f"- 系統訊息：{r['error']}")
            if r.get("head"):
                lines.append(f"- 前幾列：`{r['head']}`")
            if r.get("sql"):
                lines += ["- 產生的 SQL：", "```sql", r["sql"], "```"]
            if "rows_match" in r:
                lines += ["- 參考 SQL：", "```sql", r["rows_match"].strip(), "```"]
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只跑指定題號，逗號分隔，例如 Q01,Q05")
    ap.add_argument("--category")
    ap.add_argument("--threshold", type=float, default=0.8)
    args = ap.parse_args()

    qs = load_questions(set(args.only.split(",")) if args.only else None, args.category)
    if not qs:
        sys.exit("沒有符合條件的題目")
    with engine.connect() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM app.sql_examples")).scalar() == 0:
            print("[警告] app.sql_examples 是空的，請先執行 make load-examples，否則 few-shot 範例不會生效\n")

    results = []
    for q in qs:
        r = run_one(q)
        results.append(r)
        mark = "✓" if r["ok"] else "✗"
        print(f"{mark} {r['id']}  {r['attempts']}次 {r['seconds']:5.1f}s  {r['question']}")
        if not r["ok"]:
            print(f"      → {r['why']}")

    rate = sum(r["ok"] for r in results) / len(results)
    secs = [r["seconds"] for r in results]
    print(f"\n正確率 {sum(r['ok'] for r in results)}/{len(results)} = {rate:.0%}　"
          f"平均 {statistics.mean(secs):.1f}s　P95 {p95(secs):.1f}s　平均嘗試 {statistics.mean(r['attempts'] for r in results):.2f} 次")
    out = ROOT / "data" / "golden" / f"report_text2sql_{date.today()}.md"
    write_report(results, rate, out)
    print(f"報告：{out.relative_to(ROOT)}")
    if rate < args.threshold:
        print(f"[未達標] 低於門檻 {args.threshold:.0%}。請補 few-shot 範例或 schema_doc.md，不要改黃金題。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
