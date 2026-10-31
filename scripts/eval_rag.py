"""RAG 評估：逐題跑 data/golden/rag.yaml（檢索 → 回答），統計檢索命中率、答案正確率、拒答正確率。

用法：
  make eval-rag                                   跑全部 30 題（需要 LM Studio、Qdrant，先 make ingest）
  uv run python scripts/eval_rag.py --only R01,R05
門檻（未達標結束碼為 1）：檢索命中 ≥ 85%、答案正確 ≥ 80%、拒答全部正確。
報告輸出到 data/golden/report_rag_<日期>.md。題目由 scripts/make_rag_golden.py 產生，不要為了過關改題目。
"""
import argparse
import math
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import eval_checks
from backend.app.config import settings
from backend.app.rag.answer import answer
from backend.app.rag.retrieve import retrieve

GOLDEN = ROOT / "data" / "golden" / "rag.yaml"
MIN_HIT, MIN_ANSWER = 0.85, 0.80


def run_one(q: dict) -> dict:
    t0 = time.perf_counter()
    try:
        hits = retrieve(q["question"])
    except Exception as e:  # noqa: BLE001
        return {**q, "hit": False, "ok": False, "why": f"檢索失敗：{e}", "seconds": time.perf_counter() - t0,
                "text": "", "files": [], "sources": []}
    t1 = time.perf_counter()
    ans = answer(q["question"], hits)
    t2 = time.perf_counter()
    files = [h.file_name for h in hits]
    if q.get("refusal"):
        hit, ok = None, eval_checks.rag_refused(ans.text)
        why = "" if ok else "應回答查無，卻給了答案"
    else:
        hit = q["expect_file"] in files
        ok, why = eval_checks.rag_contains(ans.text, q["expect_contains"])
        if ans.error:
            ok, why = False, f"LLM 失敗：{ans.error}"
    return {**q, "hit": hit, "ok": ok, "why": why, "seconds": t2 - t0, "retrieve_s": t1 - t0,
            "text": ans.text, "files": files, "sources": [f"{s.file_name} p{s.page}" for s in ans.sources]}


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[max(0, math.ceil(0.95 * len(xs)) - 1)]


def summarize(results: list[dict]) -> dict:
    ans = [r for r in results if not r.get("refusal")]
    ref = [r for r in results if r.get("refusal")]
    secs = [r["seconds"] for r in results]
    return {
        "hit": sum(r["hit"] for r in ans), "ok": sum(r["ok"] for r in ans), "n": len(ans),
        "ref_ok": sum(r["ok"] for r in ref), "ref_n": len(ref),
        "mean": statistics.mean(secs), "p95": p95(secs), "max": max(secs),
    }


def passed(s: dict) -> bool:
    return (s["n"] == 0 or (s["hit"] / s["n"] >= MIN_HIT and s["ok"] / s["n"] >= MIN_ANSWER)) \
        and s["ref_ok"] == s["ref_n"]


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.0%}" if b else "-"


def write_report(results: list[dict], s: dict, path: Path) -> None:
    lines = [
        f"# RAG 評估報告 {date.today()}",
        "",
        f"- 模型：`{settings.llm_model}`；embedding：`{settings.embed_model}`；reranker：`{settings.rerank_model}`",
        f"- **檢索命中：{pct(s['hit'], s['n'])}**（門檻 {MIN_HIT:.0%}；expect_file 是否在 top_n）",
        f"- **答案正確：{pct(s['ok'], s['n'])}**（門檻 {MIN_ANSWER:.0%}；expect_contains 全部出現）",
        f"- **拒答正確：{pct(s['ref_ok'], s['ref_n'])}**（須全部正確）",
        f"- 平均延遲 {s['mean']:.1f} 秒；P95 {s['p95']:.1f} 秒；最慢 {s['max']:.1f} 秒（含檢索、重排、回答）",
        f"- 結果：{'✅ 達標' if passed(s) else '❌ 未達標'}",
        "",
        "## 逐題結果",
        "",
        "| ID | 命中 | 答案 | 秒 | 問題 | 引用來源 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        hit = "-" if r["hit"] is None else ("✅" if r["hit"] else "❌")
        lines.append(f"| {r['id']} | {hit} | {'✅' if r['ok'] else '❌'} | {r['seconds']:.1f} | {r['question']} "
                     f"| {'、'.join(r['sources'])} |")
    failed = [r for r in results if not r["ok"] or r["hit"] is False]
    if failed:
        lines += ["", "## 失敗題目細節", ""]
        for r in failed:
            lines += [f"### {r['id']} {r['question']}"]
            if r.get("expect_file"):
                lines.append(f"- 期望文件：{r['expect_file']} 第 {r['expect_page']} 頁；期望含：{r['expect_contains']}")
                lines.append(f"- 標準答案：{r['answer']}")
            if r["why"]:
                lines.append(f"- 原因：{r['why']}")
            lines.append(f"- 檢索 top_n：{r['files']}")
            lines += ["- 回答：", "", "```", r["text"], "```", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只跑指定題號，逗號分隔，例如 R01,R05")
    args = ap.parse_args()
    qs = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    if args.only:
        qs = [q for q in qs if q["id"] in set(args.only.split(","))]
    if not qs:
        sys.exit("沒有符合條件的題目")

    retrieve("暖機")  # 先載入 reranker，避免第一題延遲失真
    results = []
    for q in qs:
        r = run_one(q)
        results.append(r)
        hit = " " if r["hit"] is None else ("命中" if r["hit"] else "未中")
        print(f"{'✓' if r['ok'] else '✗'} {r['id']} {hit} {r['seconds']:5.1f}s  {r['question']}")
        if not r["ok"]:
            print(f"      → {r['why']}｜{r['text'][:80]!r}")
        elif r["hit"] is False:
            print(f"      → 檢索未命中 {r['expect_file']}：{r['files']}")

    s = summarize(results)
    print(f"\n檢索命中 {pct(s['hit'], s['n'])}　答案正確 {pct(s['ok'], s['n'])}　拒答正確 {pct(s['ref_ok'], s['ref_n'])}"
          f"　平均 {s['mean']:.1f}s　P95 {s['p95']:.1f}s")
    out = ROOT / "data" / "golden" / f"report_rag_{date.today()}.md"
    write_report(results, s, out)
    print(f"報告：{out.relative_to(ROOT)}")
    if not passed(s):
        print(f"[未達標] 門檻：檢索命中 ≥ {MIN_HIT:.0%}、答案正確 ≥ {MIN_ANSWER:.0%}、拒答全部正確。不要改黃金題。")
        return 1
    print("[達標]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
