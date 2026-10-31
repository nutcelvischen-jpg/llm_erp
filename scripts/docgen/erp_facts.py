"""從假資料產生器取得「與 ERP 一致」的合約事實：客戶名稱、付款天數、信用額度、業務、價格係數、產品單價、供應商與交期。
隨機種子固定，所以結果與 make seed 灌進資料庫的資料一致。"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "seed"))
import generate  # noqa: E402


def load() -> dict:
    rng = random.Random(generate.SEED)
    products, _ = generate.make_products(rng)
    customers, _, terms, price_f = generate.make_customers(rng)
    by_code = {c["customer_code"]: {**c, "pay_days": terms[c["customer_id"]], "price_f": price_f[c["customer_id"]]} for c in customers}
    suppliers = [{"code": f"S{i:03d}", "name": n, "lead_days": lt} for i, (n, lt) in enumerate(generate.SUPPLIERS, start=1)]
    return {"customers": by_code, "products": {p["sku"]: p for p in products}, "suppliers": suppliers}
