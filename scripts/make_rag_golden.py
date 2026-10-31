"""由 data/docs/facts.yaml 產生 RAG 黃金題 data/golden/rag.yaml（固定 seed，可重現）。

25 題可回答：20 份文件各隨機抽 1 筆事實，再從剩下的事實隨機抽 5 筆；expect_contains 用 facts 的 phrase。
5 題拒答：文件中確定沒有的主題（已對全部 355 塊確認關鍵字不存在），期望回答含「查無」。
用法：uv run python scripts/make_rag_golden.py
"""
import random
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "docs" / "facts.yaml"
OUT = ROOT / "data" / "golden" / "rag.yaml"
SEED = 21

REFUSALS = [
    "公司的年終獎金發幾個月？",
    "員工旅遊每人補助多少錢？",
    "公司幫員工提撥的退休金比例是多少？",
    "育嬰留職停薪要怎麼申請？",
    "遠端工作每週最多可以幾天？",
]


def build() -> list[dict]:
    facts = yaml.safe_load(FACTS.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    by_file: dict[str, list[dict]] = {}
    for f in facts:
        by_file.setdefault(f["file"], []).append(f)
    picked = [rng.choice(by_file[name]) for name in sorted(by_file)]
    rest = [f for f in facts if f not in picked]
    picked += rng.sample(rest, 5)
    out = []
    for i, f in enumerate(picked, 1):
        out.append({"id": f"R{i:02d}", "question": f["question"], "expect_file": f["file"],
                    "expect_page": f["page"], "expect_contains": list(f["phrase"]), "answer": f["answer"]})
    for j, q in enumerate(REFUSALS, len(out) + 1):
        out.append({"id": f"R{j:02d}", "question": q, "refusal": True, "expect_contains": ["查無"]})
    return out


if __name__ == "__main__":
    qs = build()
    header = "# 由 scripts/make_rag_golden.py 產生，請勿手改；要調整請改腳本後重新產生。\n"
    OUT.write_text(header + yaml.safe_dump(qs, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"寫入 {OUT.relative_to(ROOT)}：{len(qs)} 題（拒答 {sum(1 for q in qs if q.get('refusal'))} 題）")
