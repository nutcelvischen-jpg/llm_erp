"""產生 20 份繁中測試 PDF 到 data/docs/，並驗證頁數、文字可擷取、重點句的頁碼，輸出 data/docs/facts.yaml。

用法：python3 scripts/make_docs.py      （需要 playwright + chromium；Mac 上可用 uv run --with playwright …）
這些是虛構的示範文件，內容與 ERP 假資料一致（客戶、付款天數、信用額度、單價、供應商交期）。
"""
import re
import unicodedata
import sys
from pathlib import Path

import yaml
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docgen import erp_facts, hr, purchase, sales, sop, specs  # noqa: E402
from docgen.render import render_pdfs  # noqa: E402

OUT = ROOT / "data" / "docs"
MIN_PAGES, MAX_PAGES = 3, 8


def squeeze(s: str) -> str:
    return re.sub(r"[\u2010-\u2015\u2212]", "-", re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)))


def main() -> None:
    erp = erp_facts.load()
    docs = sales.all_sales(erp) + purchase.all_purchase(erp) + sop.all_sop(erp) + specs.all_specs(erp) + hr.all_hr(erp)
    assert len(docs) == 20, f"應為 20 份，實際 {len(docs)}"
    for old in OUT.glob("*.pdf"):
        old.unlink()
    render_pdfs(docs, OUT)

    facts_out, problems = [], []
    for d in docs:
        pages = [squeeze(p.extract_text() or "") for p in PdfReader(OUT / f"{d.filename}.pdf").pages]
        n = len(pages)
        print(f"  {n} 頁  {d.filename}")
        if not MIN_PAGES <= n <= MAX_PAGES:
            problems.append(f"{d.filename}：{n} 頁，應在 {MIN_PAGES}–{MAX_PAGES} 頁")
        for f in d.facts:
            hit = [next((i + 1 for i, t in enumerate(pages) if squeeze(ph) in t), None) for ph in f["phrase"]]
            if None in hit:
                problems.append(f"{d.filename}：找不到重點句 {f['phrase']}")
                continue
            facts_out.append({"file": f"{d.filename}.pdf", "doc_type": d.doc_type, "page": hit[0], "question": f["q"], "answer": f["a"], "phrase": f["phrase"]})
    (OUT / "facts.yaml").write_text(yaml.safe_dump(facts_out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    types = {}
    for d in docs:
        types[d.doc_type] = types.get(d.doc_type, 0) + 1
    print(f"共 {len(docs)} 份 {types}；重點事實 {len(facts_out)} 筆 → data/docs/facts.yaml")
    if problems:
        print("\n[問題]\n  " + "\n  ".join(problems))
        sys.exit(1)


if __name__ == "__main__":
    main()
