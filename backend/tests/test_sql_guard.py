import re
from pathlib import Path

import pytest

from backend.app.sql_guard import ALLOWED_VIEWS, GuardResult, validate

ROOT = Path(__file__).resolve().parents[2]


def ok(sql: str) -> str:
    r = validate(sql)
    assert r.ok, f"應通過卻被拒絕：{r.reason}\n{sql}"
    return r.sql


def rejected(sql: str) -> str:
    r = validate(sql)
    assert not r.ok, f"應被拒絕卻通過：{r.sql}"
    assert r.reason
    return r.reason


# ---------- 合法查詢 ----------
def test_simple_select_gets_default_limit():
    assert ok('select 料號 from v_庫存狀況').endswith("LIMIT 200")


def test_chinese_quoted_identifiers_survive_rewrite():
    out = ok('SELECT "客戶名稱", SUM("銷售金額") AS "營收" FROM "v_銷售明細" GROUP BY 1 ORDER BY 2 DESC')
    assert '"客戶名稱"' in out and '"v_銷售明細"' in out and '"營收"' in out
    assert ok(out) == out  # 冪等：重跑結果不變


def test_unquoted_chinese_view_and_erp_prefix():
    ok("select 料號 from v_庫存狀況")
    ok('select 1 from erp."v_銷售明細"')
    ok("select 1 from erp.v_應收帳款")


@pytest.mark.parametrize("view", sorted(ALLOWED_VIEWS))
def test_every_whitelisted_view_is_allowed(view):
    ok(f'select * from "{view}"')


def test_cte_and_union_are_allowed():
    ok("with a as (select 料號 from v_庫存狀況), b as (select * from a) select * from b")
    out = ok("select 料號 from v_庫存狀況 union select 料號 from v_庫存狀況")
    assert out.endswith("LIMIT 200")


def test_postgres_date_functions_are_allowed():
    ok("""select date_trunc('month', current_date), extract(year from "訂單日期"),
          "訂單日期" <= current_date - interval '1 year' from "v_銷售明細" """)


def test_trailing_semicolon_and_comments_are_stripped():
    out = ok("select 料號 /* 註解 */ from v_庫存狀況 -- 尾註解\n;")
    assert "/*" not in out and "--" not in out and not out.endswith(";")


# ---------- LIMIT 處理 ----------
def test_existing_small_limit_is_kept_with_offset():
    assert ok("select 料號 from v_庫存狀況 limit 5 offset 3").endswith("LIMIT 5 OFFSET 3")


def test_large_limit_is_capped_at_1000():
    assert ok("select 料號 from v_庫存狀況 limit 5000").endswith("LIMIT 1000")


def test_non_constant_limit_is_capped():
    assert ok("select 料號 from v_庫存狀況 limit all").endswith("LIMIT 1000")


# ---------- 必須拒絕 ----------
@pytest.mark.parametrize("sql", [
    "delete from erp.customers",
    "update erp.customers set name='x'",
    "insert into erp.customers(name) values ('x')",
    "drop table erp.customers",
    "truncate erp.customers",
    "alter table erp.customers add column x int",
    "create table x as select 1",
    "grant all on schema erp to public",
    "copy erp.customers to '/tmp/x'",
    "set statement_timeout = 0",
    "explain analyze select 1 from v_庫存狀況",
    "vacuum erp.customers",
])
def test_non_select_statements_rejected(sql):
    rejected(sql)


def test_multiple_statements_rejected():
    assert "單一" in rejected("select 1 from v_庫存狀況; drop table x")
    rejected("select 1 from v_庫存狀況; select 2 from v_庫存狀況")


@pytest.mark.parametrize("sql", [
    "select * from erp.customers",
    "select * from customers",
    "select * from public.v_庫存狀況",
    "select * from other_db.erp.v_庫存狀況",
    "select * from v_庫存狀況 where 1 = (select count(*) from erp.customers)",
    "select * from v_庫存狀況 a join erp.suppliers b on true",
    "with x as (select * from erp.customers) select * from x",
    "select 料號 from v_庫存狀況 union select name from erp.customers",
])
def test_non_whitelisted_tables_rejected_anywhere_in_query(sql):
    rejected(sql)


@pytest.mark.parametrize("sql", [
    "select * from pg_catalog.pg_tables",
    "select * from pg_tables",
    "select * from information_schema.tables",
    "select pg_sleep(5) from v_庫存狀況",
    "select pg_read_file('/etc/passwd') from v_庫存狀況",
    "select current_setting('is_superuser') from v_庫存狀況",
    "select set_config('x','y',false) from v_庫存狀況",
    "select lo_import('/etc/passwd') from v_庫存狀況",
])
def test_system_catalog_and_dangerous_functions_rejected(sql):
    rejected(sql)


@pytest.mark.parametrize("sql", [
    "select * into newtbl from v_庫存狀況",
    "select * from v_庫存狀況 for update",
    "select * from generate_series(1, 100000000)",
    "select * from v_庫存狀況 fetch first 5 rows only",
])
def test_into_locking_table_functions_fetch_rejected(sql):
    rejected(sql)


# ---------- CTE 作用域繞過 ----------
def test_cte_shadowing_real_table_rejected():
    rejected("with customers as (select * from customers) select * from customers")


def test_cte_referencing_later_cte_rejected():
    rejected("with a as (select * from b), b as (select 1 as x) select * from a")


def test_recursive_and_nested_with_rejected():
    assert "RECURSIVE" in rejected(
        "with recursive t as (select 1 as n union all select n+1 from t where n < 5) select * from t")
    assert "巢狀" in rejected("select * from (with x as (select 1) select * from x) q")


# ---------- 輸入異常 ----------
@pytest.mark.parametrize("sql", ["", "   ", "\n", "selec from", "select from where", "select * from"])
def test_empty_and_garbage_rejected(sql):
    rejected(sql)


def test_result_type_and_original_sql_kept_on_rejection():
    r = validate("delete from erp.customers")
    assert isinstance(r, GuardResult) and r.ok is False
    assert r.sql == "delete from erp.customers"


# ---------- 與 schema_doc.md 一致 ----------
def test_all_sql_examples_in_schema_doc_pass():
    doc = (ROOT / "sql" / "schema_doc.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```sql\n(.*?)```", doc, flags=re.DOTALL)
    assert len(blocks) >= 3
    for b in blocks:
        ok(b)
