from pathlib import Path

import pytest
import yaml

from backend.app.sql_guard import validate

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = yaml.safe_load((ROOT / "data" / "golden" / "text2sql.yaml").read_text(encoding="utf-8"))
EXAMPLES = yaml.safe_load((ROOT / "data" / "seed" / "sql_examples.yaml").read_text(encoding="utf-8"))
CHECK_KEYS = {"rows_match", "contains", "refusal", "row_count", "row_count_gt"}


def test_thirty_unique_questions_with_sequential_ids():
    assert [q["id"] for q in GOLDEN] == [f"Q{i:02d}" for i in range(1, 31)]
    assert len({q["question"] for q in GOLDEN}) == 30


def test_each_question_has_exactly_one_check():
    for q in GOLDEN:
        assert len(CHECK_KEYS & set(q)) == 1, f"{q['id']} 必須剛好有一種檢查：{sorted(set(q))}"


def test_golden_questions_are_not_copies_of_few_shot_examples():
    """黃金題用來測泛化；若題目與範例逐字相同，就變成在考背誦。"""
    assert not {q["question"] for q in GOLDEN} & {e["question"] for e in EXAMPLES}


def test_refusal_questions_present_and_categories_cover_all_views():
    assert sum(1 for q in GOLDEN if q.get("refusal")) >= 4
    assert {"營收", "毛利", "應收", "庫存", "採購", "婉拒"} <= {q["category"] for q in GOLDEN}


@pytest.mark.parametrize("q", [q for q in GOLDEN if "rows_match" in q], ids=lambda q: q["id"])
def test_reference_sql_passes_guard(q):
    assert validate(q["rows_match"]).ok


@pytest.mark.db
@pytest.mark.parametrize("q", [q for q in GOLDEN if "rows_match" in q], ids=lambda q: q["id"])
def test_reference_sql_returns_rows_on_real_database(q):
    from backend.app import text2sql

    _, rows = text2sql._execute(q["rows_match"])
    assert rows and all(c is not None for c in rows[0]), f"{q['id']} 參考 SQL 沒有結果或含空值，題目對這份資料無效"
