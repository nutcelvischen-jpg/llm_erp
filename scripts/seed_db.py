"""產生假 ERP 資料、驗證 5 個劇情，並灌入 Postgres 的 erp schema。

用法：make seed   （等同 uv run python scripts/seed_db.py）
會先 TRUNCATE 全部 erp 資料表再重灌，可重複執行。
"""
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "seed"))

import generate

from backend.app.db import engine

ORDER = [
    "customers", "suppliers", "products", "sales_orders", "sales_order_lines",
    "purchase_orders", "purchase_order_lines", "inventory", "invoices",
]
SERIAL_PK = {
    "customers": "customer_id", "suppliers": "supplier_id", "products": "product_id",
    "sales_orders": "so_id", "sales_order_lines": "line_id", "purchase_orders": "po_id",
    "purchase_order_lines": "line_id", "invoices": "invoice_id",
}


def main() -> None:
    tables = generate.finalize(generate.build())
    info = generate.assert_story(tables)
    generate.write_csv(tables)
    print("劇情驗證通過：", info["筆數"])

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(f"erp.{n}" for n in ORDER) + " RESTART IDENTITY CASCADE"))
        for name in ORDER:
            tables[name].to_sql(name, conn, schema="erp", if_exists="append", index=False,
                                method="multi", chunksize=1000)
            print(f"  {name}: {len(tables[name])} 筆")
        for name, pk in SERIAL_PK.items():  # 讓序列接在最大 id 之後
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('erp.{name}', '{pk}'), "
                f"(SELECT MAX({pk}) FROM erp.{name}))"))
    print("完成。")


if __name__ == "__main__":
    main()
