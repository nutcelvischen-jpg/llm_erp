"""意圖辨識評估：逐題跑 data/golden/intents.yaml，統計模板正確率、參數正確率、不支援題誤判。

用法：make eval-intent   或   uv run python scripts/eval_intents.py --only I01,I05
門檻（未達標結束碼為 1）：模板 ≥ 95%、參數 ≥ 90%、不支援題誤判 0。報告：data/golden/report_intents_<日期>.md
"""
import argparse
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.catalog import intent as I
from backend.app.catalog.entities import default_index
from backend.app.catalog.periods import resolve_period
from backend.app.catalog.registry import TEMPLATES
from backend.app.config import settings

GOLDEN = ROOT / "data" / "golden" / "intents.yaml"
MIN_TEMPLATE, MIN_PARAMS = 0.95, 0.90


def same_param(t, name, got, want, today) -> bool:
    spec = next(s for s in t.params if s.name == name)
    if spec.kind == "period":
        try:
            a, b = resolve_period(got, today), resolve_period(want, today)
        except ValueError:
            return False
        return (a.date_from, a.date_to) == (b.date_from, b.date_to)
    if spec.kind == "entity":
        want = default_index().match(spec.entity, str(want)).value if want is not None else None
    return got == want


def run_one(q, today):
    t0 = time.perf_counter()
    it = I.recognize(q["question"], today)
    secs = time.perf_counter() - t0
    r = {**q, "kind": it.kind, "got": it.template_id, "seconds": secs, "readable": it.params_readable,
         "message": it.message, "proposals": [p.template_id for p in it.proposals]}
    if q.get("unsupported"):
        r["ok_template"] = it.kind == "no_match"
        r["why"] = "" if r["ok_template"] else f"應判不支援，卻得到 {it.kind} {it.template_id or r['proposals']}"
        return r
    r["ok_template"] = it.kind == "template" and it.template_id == q["template"]
    if not r["ok_template"]:
        r["ok_params"] = False
        r["why"] = f"得到 {it.kind} {it.template_id or ''} {r['proposals'] or ''} {it.message}".strip()
        return r
    t = TEMPLATES[q["template"]]
    bad = [f"{k}={it.params.get(k)!r}（應為 {v!r}）" for k, v in (q.get("params") or {}).items()
           if not same_param(t, k, it.params.get(k), v, today)]
    r["ok_params"] = not bad
    r["why"] = "參數錯誤：" + "；".join(bad) if bad else ""
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    qs = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    if a.only:
        qs = [q for q in qs if q["id"] in set(a.only.split(","))]
    today = date.today()
    I.log_unmatched = lambda *args, **kw: None  # 評估不寫入 unmatched_questions
    res = []
    for q in qs:
        r = run_one(q, today)
        res.append(r)
        mark = "✓" if r["ok_template"] and r.get("ok_params", True) else "✗"
        print(f"{mark} {r['id']} {r['kind']:9} {r['seconds']:4.1f}s {q['question']}")
        if mark == "✗":
            print(f"      → {r['why']}")
    sup = [r for r in res if not r.get("unsupported")]
    uns = [r for r in res if r.get("unsupported")]
    t_ok = sum(r["ok_template"] for r in sup)
    p_ok = sum(r.get("ok_params", False) for r in sup)
    mis = sum(not r["ok_template"] for r in uns)
    secs = [r["seconds"] for r in res]
    t_rate = t_ok / len(sup) if sup else 1
    p_rate = p_ok / len(sup) if sup else 1
    line = (f"模板 {t_ok}/{len(sup)} = {t_rate:.0%}　參數 {p_ok}/{len(sup)} = {p_rate:.0%}　"
            f"不支援誤判 {mis}/{len(uns)}　平均 {statistics.mean(secs):.1f}s　最慢 {max(secs):.1f}s")
    print("\n" + line)
    ok = t_rate >= MIN_TEMPLATE and p_rate >= MIN_PARAMS and mis == 0
    out = ROOT / "data" / "golden" / f"report_intents_{today}.md"
    lines = [f"# 意圖辨識評估報告 {today}", "", f"- 模型：`{settings.llm_model}`；門檻：模板 ≥ 95%、參數 ≥ 90%、不支援誤判 0",
             f"- **{line}**", f"- 結果：{'✅ 達標' if ok else '❌ 未達標'}", "",
             "| ID | 結果 | 類型 | 秒 | 問題 | 參數／說明 |", "|---|---|---|---|---|---|"]
    for r in res:
        good = r["ok_template"] and r.get("ok_params", True)
        detail = "、".join(r["readable"]) if good and r["readable"] else r.get("why", "")
        lines.append(f"| {r['id']} | {'✅' if good else '❌'} | {r['kind']} | {r['seconds']:.1f} | {r['question']} | {detail} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"報告：{out.relative_to(ROOT)}")
    if not ok:
        print("[未達標] 請補模板 examples、描述或同義詞，不要改黃金題。")
        return 1
    print("[達標]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
