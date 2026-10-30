"""把 data/seed/sql_examples.yaml 的範例向量化並寫入 app.sql_examples（先清空再寫入，可重複執行）。

用法：make load-examples   （需要 LM Studio 開著；embedding 用 EMBED_MODEL）
"""
import sys
from pathlib import Path

import yaml
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import llm
from backend.app.config import settings
from backend.app.db import engine
from backend.app.sql_guard import validate


def main() -> None:
    examples = yaml.safe_load((ROOT / "data" / "seed" / "sql_examples.yaml").read_text(encoding="utf-8"))
    for ex in examples:
        r = validate(ex["sql"])
        if not r.ok:
            sys.exit(f"[FAIL] 範例未通過 SQL 守門員：{ex['question']}\n  原因：{r.reason}")

    vecs = llm.embed([ex["question"] for ex in examples])
    if len(vecs[0]) != settings.embed_dim:
        sys.exit(f"[FAIL] embedding 維度 {len(vecs[0])} != EMBED_DIM {settings.embed_dim}")

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE app.sql_examples RESTART IDENTITY"))
        for ex, v in zip(examples, vecs, strict=True):
            conn.execute(
                text("INSERT INTO app.sql_examples (question, sql_text, tags, embedding) "
                     "VALUES (:q, :s, :t, CAST(:e AS real[]))"),
                {"q": ex["question"], "s": ex["sql"].strip(), "t": ex.get("tags", []), "e": v},
            )
    print(f"已載入 {len(examples)} 組範例（向量維度 {len(vecs[0])}）")


if __name__ == "__main__":
    main()
