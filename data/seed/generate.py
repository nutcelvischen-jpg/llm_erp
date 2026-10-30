"""假 ERP 資料產生器：台中精密零件公司，約 2 年交易資料，內含 5 個 Demo 劇情。

用法：uv run python data/seed/generate.py
  → 產生資料、驗證 5 個劇情、輸出 CSV 到 data/seed/out/
日期一律相對於「今天」計算（可用環境變數 SEED_TODAY=YYYY-MM-DD 覆寫），
固定亂數種子 42，同一天重跑結果相同。

劇情（assert_story 會逐一驗證）：
  1. C008 鴻遠機械：去年營收前三，近 150 天訂單量驟減約 40%，今年累計營收跌幅（金額）全公司最大
  2. 12 個呆滯料號（含 BRG-6205-2RS）：200 天以上無異動且仍有庫存
  3. GEAR-M2-40T 等 3 個料號：庫存 + 在途 < 待出貨量（缺料）
  4. C015 台陽科技：恰好 3 張逾期 60 天以上未收發票（另有 C031 一張，讓清單不只一人）
  5. 2026 Q3 毛利率比 2025 Q3 低 3 個百分點（原料成本上漲）
"""
from __future__ import annotations

import os
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED = 42
OUT = Path(__file__).parent / "out"
TODAY = (
    date.fromisoformat(os.environ["SEED_TODAY"])
    if os.environ.get("SEED_TODAY")
    else date.today()
)
START = TODAY - timedelta(days=730)
DROP_START = TODAY - timedelta(days=150)  # C008 訂單驟減起點（約 6 月）
DEAD_DAYS = 200  # 呆滯料號距今天數下限
N_CUSTOMERS, N_SALES_ORDERS, N_PURCHASE_ORDERS = 40, 6000, 800

SALES_REPS = ["陳怡君", "林建宏", "黃雅婷", "張志豪", "李佩珊", "王俊傑"]
INDUSTRIES = ["機械製造", "汽車零組件", "自行車", "電子設備", "工具機", "金屬加工", "食品機械", "醫療器材"]
SUPPLIERS = [  # (名稱, 交期天數)
    ("大成鋼鐵", 14), ("中鋼軸承材料", 14), ("永信金屬", 21), ("宏達齒輪材料", 21),
    ("精密熱處理", 28), ("順發五金", 10), ("台灣精工扣件", 10), ("億豐表面處理", 14),
    ("嘉聯模具", 30), ("東和包材", 7),
]
CAT_SUPPLIERS = {"軸承": [1, 2, 3], "齒輪": [4, 5], "墊片": [6, 7], "扣件": [6, 7, 8], "客製件": [9, 10]}
CAT_W = {"軸承": 3, "齒輪": 2, "墊片": 3, "扣件": 3, "客製件": 1}
SO_QTY = {"軸承": (20, 300), "齒輪": (10, 120), "墊片": (200, 3000), "扣件": (200, 3000), "客製件": (1, 20)}
PO_QTY = {"軸承": (200, 1000), "齒輪": (100, 500), "墊片": (2000, 10000), "扣件": (2000, 10000), "客製件": (10, 100)}
SAFETY = {"軸承": (80, 300), "齒輪": (40, 150), "墊片": (500, 2000), "扣件": (500, 2000), "客製件": (5, 30)}
# 缺料劇情：sku -> (補幾張待出貨單, 每張數量下限, 上限, 庫存占待出貨比例)
SHORT = {
    "GEAR-M2-40T": (8, 100, 150, 0.35),
    "BRG-6204-2RS": (6, 120, 200, 0.55),
    "FST-M8x30-HEX": (5, 1500, 2500, 0.5),
}
Q3_YEARS = (2025, 2026)


def weekdays(a: date, b: date) -> list[date]:
    days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    return [d for d in days if d.weekday() < 5]


def cost_factor(d: date) -> float:
    """原料成本隨時間緩升（2 年約 +3%）。"""
    return 1 + 0.00004 * (d - START).days


def make_products(rng: random.Random) -> tuple[list[dict], set[str]]:
    items: list[tuple[str, str, str, float]] = []
    for c in ["6200", "6201", "6202", "6203", "6204", "6205", "6206", "6207", "6208", "6209",
              "6300", "6301", "6302", "6303", "6304"]:
        for suf in ("2RS", "ZZ"):
            items.append((f"BRG-{c}-{suf}", f"深溝球軸承 {c}-{suf}", "軸承", rng.uniform(18, 190)))
    for m in (1.0, 1.5, 2.0, 2.5, 3.0):
        for t in (20, 30, 40, 50, 60):
            items.append((f"GEAR-M{m:g}-{t}T", f"正齒輪 模數{m:g} {t}齒", "齒輪",
                          30 + m * t * rng.uniform(2.5, 4)))
    for s in (3, 4, 5, 6, 8, 10, 12, 16, 20, 24):
        items.append((f"WSH-M{s}-FL", f"平墊圈 M{s}", "墊片", 0.6 + s * 0.25))
        items.append((f"WSH-M{s}-SP", f"彈簧墊圈 M{s}", "墊片", 0.7 + s * 0.27))
    for s in (4, 5, 6, 8, 10, 12):
        for ln in (10, 20, 30, 40, 50):
            items.append((f"FST-M{s}x{ln}-HEX", f"六角螺栓 M{s}x{ln}", "扣件", 0.8 + s * ln * 0.012))
    for i in range(1, 16):
        items.append((f"CUS-{i:03d}", f"客製件 {i:03d}", "客製件", rng.uniform(250, 3200)))

    products = []
    for i, (sku, name, cat, cost) in enumerate(items, start=1):
        cost = round(cost, 2)
        products.append({
            "product_id": i, "sku": sku, "name": name, "category": cat, "unit": "PCS",
            "std_cost": cost, "list_price": round(cost * rng.uniform(1.30, 1.48), 2),
            "safety_stock": rng.randint(*SAFETY[cat]),
            "supplier_id": rng.choice(CAT_SUPPLIERS[cat]), "is_active": True,
        })
    protected = {"BRG-6205-2RS", *SHORT}
    pool = [p["sku"] for p in products if p["sku"] not in protected]
    dead = {"BRG-6205-2RS", *rng.sample(pool, 11)}
    for p in products:
        if p["sku"] in dead:
            p["safety_stock"] = 20
    return products, dead


def make_customers(rng: random.Random) -> tuple[list[dict], list[float], dict[int, int], dict[int, float]]:
    first = list("宏立大永精億明勝華新正金順力信德達佳泰聯")
    second = list("成達昌興億發誠揚祥城")
    suffix = ["機械", "工業", "科技", "精密", "企業", "實業", "金屬", "自動化"]
    names: list[str] = []
    while len(names) < N_CUSTOMERS:
        n = rng.choice(first) + rng.choice(second) + rng.choice(suffix)
        if n not in names:
            names.append(n)
    rows, weights, terms, price_f = [], [], {}, {}
    regions, region_w = ["北部", "中部", "南部", "海外"], [0.3, 0.4, 0.2, 0.1]
    for i in range(1, N_CUSTOMERS + 1):
        name = names[i - 1]
        region = rng.choices(regions, region_w)[0]
        rep = rng.choice(SALES_REPS)
        w = rng.lognormvariate(0, 0.6)
        if i == 8:
            name, region, rep, w = "鴻遠機械", "中部", "陳怡君", 7.0
        elif i == 15:
            name, region, rep, w = "台陽科技", "北部", "林建宏", 1.5
        rows.append({
            "customer_id": i, "customer_code": f"C{i:03d}", "name": name,
            "industry": rng.choice(INDUSTRIES), "region": region, "sales_rep": rep,
            "credit_limit": rng.choice([500000, 1000000, 2000000, 3000000, 5000000]),
            "created_at": START - timedelta(days=rng.randint(30, 2000)),
        })
        weights.append(w)
        terms[i] = rng.choice([30, 45, 60])
        price_f[i] = rng.uniform(0.97, 1.03)
    return rows, weights, terms, price_f


def build() -> dict[str, pd.DataFrame]:
    rng = random.Random(SEED)
    suppliers = [{"supplier_id": i, "supplier_code": f"S{i:03d}", "name": n, "lead_time_days": lt}
                 for i, (n, lt) in enumerate(SUPPLIERS, start=1)]
    lead = {s["supplier_id"]: s["lead_time_days"] for s in suppliers}
    products, dead = make_products(rng)
    pid = {p["sku"]: p["product_id"] for p in products}
    prod = {p["product_id"]: p for p in products}
    dead_ids = {pid[s] for s in dead}
    short_ids = {pid[s] for s in SHORT}
    customers, cust_w, terms, price_f = make_customers(rng)

    # ---------- 銷售訂單 ----------
    wd = weekdays(START, TODAY)
    orders: list[dict] = []
    while len(orders) < N_SALES_ORDERS:
        d, c = rng.choice(wd), rng.choices(range(1, N_CUSTOMERS + 1), cust_w)[0]
        if c == 8 and d >= DROP_START and rng.random() < 0.4:
            continue
        orders.append({"order_date": d, "customer_id": c})
    orders.sort(key=lambda o: o["order_date"])
    per_day: dict[date, int] = {}
    for i, o in enumerate(orders, start=1):
        d = o["order_date"]
        per_day[d] = per_day.get(d, 0) + 1
        o["so_id"], o["so_no"] = i, f"SO{d:%Y%m%d}-{per_day[d]:03d}"
        age = (TODAY - d).days
        ship: date | None
        if rng.random() < 0.02:
            status, ship = "取消", None
        elif age <= 21 and rng.random() < 0.7:
            status, ship = "待出貨", None
        elif age <= 21:
            status, ship = "已出貨", min(TODAY, d + timedelta(days=rng.randint(1, 4)))
        elif age <= 60:
            status, ship = rng.choice(["已出貨", "已結案"]), d + timedelta(days=rng.randint(1, 5))
        else:
            status, ship = "已結案", d + timedelta(days=rng.randint(1, 5))
        o["status"], o["ship_date"] = status, ship

    all_w = [CAT_W[p["category"]] * rng.lognormvariate(0, 0.5) for p in products]
    ids_all = [p["product_id"] for p in products]
    live = [(i, w) for i, w in zip(ids_all, all_w, strict=True) if i not in dead_ids]
    sale_cut = TODAY - timedelta(days=DEAD_DAYS + 6)

    def pick_products(d: date, k: int) -> list[int]:
        if d > sale_cut:
            ids, ws = zip(*live, strict=True)
        else:
            ids, ws = ids_all, all_w
        return list(dict.fromkeys(rng.choices(ids, ws, k=k)))

    lines: list[dict] = []
    for o in orders:
        d, cf = o["order_date"], cost_factor(o["order_date"])
        for p_id in pick_products(d, rng.choices([1, 2, 3, 4], [0.3, 0.35, 0.25, 0.1])[0]):
            p = prod[p_id]
            lines.append({
                "so_id": o["so_id"], "product_id": p_id,
                "qty": rng.randint(*SO_QTY[p["category"]]),
                "unit_price": round(p["list_price"] * rng.uniform(0.93, 1.02) * price_f[o["customer_id"]], 2),
                "unit_cost": round(p["std_cost"] * cf * rng.uniform(0.985, 1.015), 2),
            })

    # 劇情 3：替缺料料號補幾張待出貨訂單
    pending = [o for o in orders if o["status"] == "待出貨"]
    for sku, (n, lo, hi, _) in SHORT.items():
        for o in rng.sample(pending, n):
            existing = [ln for ln in lines if ln["so_id"] == o["so_id"] and ln["product_id"] == pid[sku]]
            q = rng.randint(lo, hi)
            if existing:
                existing[0]["qty"] += q
            else:
                p = prod[pid[sku]]
                lines.append({
                    "so_id": o["so_id"], "product_id": pid[sku], "qty": q,
                    "unit_price": round(p["list_price"] * rng.uniform(0.95, 1.0), 2),
                    "unit_cost": round(p["std_cost"] * cost_factor(o["order_date"]), 2),
                })

    # 劇情 5：校準 2026 Q3 毛利率 = 2025 Q3 - 3 個百分點
    odate = {o["so_id"]: o["order_date"] for o in orders}
    ostat = {o["so_id"]: o["status"] for o in orders}

    def q3(y: int) -> list[dict]:
        return [ln for ln in lines if ostat[ln["so_id"]] != "取消"
                and odate[ln["so_id"]].year == y and odate[ln["so_id"]].month in (7, 8, 9)]

    def sums(ls: list[dict]) -> tuple[float, float]:
        return (sum(ln["qty"] * ln["unit_price"] for ln in ls),
                sum(ln["qty"] * ln["unit_cost"] for ln in ls))

    s25, c25 = sums(q3(Q3_YEARS[0]))
    s26, c26 = sums(q3(Q3_YEARS[1]))
    m25 = 1 - c25 / s25
    scale = s26 * (1 - (m25 - 0.03)) / c26
    for ln in q3(Q3_YEARS[1]):
        ln["unit_cost"] = round(ln["unit_cost"] * scale, 2)
    for i, ln in enumerate(lines, start=1):
        ln["line_id"] = i

    pending_ids = {o["so_id"] for o in pending}
    pend_qty: dict[int, int] = {}
    for ln in lines:
        if ln["so_id"] in pending_ids:
            pend_qty[ln["product_id"]] = pend_qty.get(ln["product_id"], 0) + ln["qty"]

    # ---------- 採購單 ----------
    sup_products: dict[int, list[int]] = {}
    for p in products:
        sup_products.setdefault(p["supplier_id"], []).append(p["product_id"])
    pos: list[dict] = []
    po_lines: list[dict] = []

    def add_po(d: date, sid: int, forced_status: str | None = None, only: list[int] | None = None) -> None:
        expected = d + timedelta(days=lead[sid])
        if forced_status:
            status = forced_status
        elif rng.random() < 0.02:
            status = "取消"
        elif expected > TODAY:
            status = "待交貨"
        else:
            status = "已收貨"
        received = None
        if status == "已收貨":
            received = min(TODAY, max(d + timedelta(days=3), expected + timedelta(days=round(rng.gauss(1.5, 2.5)))))
        cand = only or sup_products[sid]
        po_cut = TODAY - timedelta(days=DEAD_DAYS + lead[sid] + 10)
        cand = [c for c in cand if not (c in dead_ids and d > po_cut)
                and not (status == "待交貨" and c in short_ids)]
        if not cand:
            return
        po_id = len(pos) + 1
        pos.append({"po_id": po_id, "po_no": f"PO{d:%Y%m%d}-{po_id:04d}", "supplier_id": sid,
                    "order_date": d, "expected_date": expected, "received_date": received, "status": status})
        for p_id in rng.sample(cand, min(len(cand), rng.randint(1, 4))):
            p = prod[p_id]
            po_lines.append({"po_id": po_id, "product_id": p_id,
                             "qty": rng.randint(*PO_QTY[p["category"]]),
                             "unit_cost": round(p["std_cost"] * cost_factor(d) * rng.uniform(0.97, 1.03), 2)})

    for d in sorted(rng.choices(wd, k=N_PURCHASE_ORDERS)):
        add_po(d, rng.randint(1, len(SUPPLIERS)))

    # 確保非呆滯料號 150 天內都有異動
    def last_events() -> dict[int, date]:
        ev: dict[int, date] = {}
        ship = {o["so_id"]: o["ship_date"] for o in orders if o["status"] in ("已出貨", "已結案")}
        for ln in lines:
            if ln["so_id"] in ship:
                ev[ln["product_id"]] = max(ev.get(ln["product_id"], date.min), ship[ln["so_id"]])
        recv = {p["po_id"]: p["received_date"] for p in pos if p["status"] == "已收貨"}
        for pl in po_lines:
            if pl["po_id"] in recv:
                ev[pl["product_id"]] = max(ev.get(pl["product_id"], date.min), recv[pl["po_id"]])
        return ev

    ev = last_events()
    for p in products:
        if p["product_id"] not in dead_ids and ev.get(p["product_id"], date.min) < TODAY - timedelta(days=150):
            add_po(TODAY - timedelta(days=rng.randint(45, 100)) - timedelta(days=lead[p["supplier_id"]]),
                   p["supplier_id"], forced_status="已收貨", only=[p["product_id"]])
    ev = last_events()

    transit: dict[int, int] = {}
    pending_po = {p["po_id"] for p in pos if p["status"] == "待交貨"}
    for pl in po_lines:
        if pl["po_id"] in pending_po:
            transit[pl["product_id"]] = transit.get(pl["product_id"], 0) + pl["qty"]
    for i, pl in enumerate(po_lines, start=1):
        pl["line_id"] = i

    # ---------- 庫存 ----------
    inventory = []
    for p in products:
        i = p["product_id"]
        pend = pend_qty.get(i, 0)
        if i in dead_ids:
            on_hand = rng.randint(150, 1200)
        elif i in short_ids:
            frac = next(v[3] for k, v in SHORT.items() if pid[k] == i)
            on_hand = max(0, min(int(pend * frac), pend - transit.get(i, 0) - 1))
        else:
            on_hand = pend + int(p["safety_stock"] * rng.uniform(1.1, 2.5)) + transit.get(i, 0) // 2
        last = ev.get(i)
        if i in dead_ids and (last is None or (TODAY - last).days < DEAD_DAYS):
            last = TODAY - timedelta(days=rng.randint(DEAD_DAYS + 10, 420))
        inventory.append({"product_id": i, "on_hand": on_hand, "last_movement": last})

    # ---------- 發票 ----------
    ship_orders = sorted((o for o in orders if o["status"] in ("已出貨", "已結案")),
                         key=lambda o: o["ship_date"])
    amount_by_so: dict[int, float] = {}
    for ln in lines:
        amount_by_so[ln["so_id"]] = amount_by_so.get(ln["so_id"], 0) + ln["qty"] * ln["unit_price"]
    invoices: list[dict] = []
    for n, o in enumerate(ship_orders, start=1):
        inv_d = o["ship_date"]
        due = inv_d + timedelta(days=terms[o["customer_id"]])
        amount = round(amount_by_so[o["so_id"]] * 1.05, 2)
        over = (TODAY - due).days
        paid, paid_d = 0.0, None
        r = rng.random()
        if over > 60 or (over > 0 and r < 0.70):
            paid, paid_d = amount, min(TODAY, due + timedelta(days=rng.randint(-3, min(25, max(over, 0)))))
        elif over > 0 and r < 0.85:
            paid = round(amount * rng.uniform(0.3, 0.7), 0)
        elif over <= 0 and r < 0.25:
            paid, paid_d = amount, min(TODAY, inv_d + timedelta(days=rng.randint(5, 30)))
        invoices.append({"invoice_id": n, "invoice_no": f"INV{inv_d:%Y%m}-{n:05d}", "so_id": o["so_id"],
                         "customer_id": o["customer_id"], "invoice_date": inv_d, "due_date": due,
                         "amount": amount, "paid_amount": paid, "paid_date": paid_d})

    # 劇情 4：C015 恰好 3 張逾期 > 60 天未收；C031 一張
    def force_unpaid(cid: int, lo: int, hi: int, n: int) -> None:
        cand = [v for v in invoices if v["customer_id"] == cid and lo <= (TODAY - v["due_date"]).days <= hi]
        for v in rng.sample(cand, n):
            v["paid_amount"], v["paid_date"] = 0.0, None

    force_unpaid(15, 65, 150, 3)
    force_unpaid(31, 62, 95, 1)

    return {
        "customers": pd.DataFrame(customers), "suppliers": pd.DataFrame(suppliers),
        "products": pd.DataFrame(products), "sales_orders": pd.DataFrame(orders).drop(columns=[]),
        "sales_order_lines": pd.DataFrame(lines), "purchase_orders": pd.DataFrame(pos),
        "purchase_order_lines": pd.DataFrame(po_lines), "inventory": pd.DataFrame(inventory),
        "invoices": pd.DataFrame(invoices),
    }


COLUMNS = {
    "customers": ["customer_id", "customer_code", "name", "industry", "region", "sales_rep", "credit_limit", "created_at"],
    "suppliers": ["supplier_id", "supplier_code", "name", "lead_time_days"],
    "products": ["product_id", "sku", "name", "category", "unit", "std_cost", "list_price", "safety_stock", "supplier_id", "is_active"],
    "sales_orders": ["so_id", "so_no", "customer_id", "order_date", "ship_date", "status"],
    "sales_order_lines": ["line_id", "so_id", "product_id", "qty", "unit_price", "unit_cost"],
    "purchase_orders": ["po_id", "po_no", "supplier_id", "order_date", "expected_date", "received_date", "status"],
    "purchase_order_lines": ["line_id", "po_id", "product_id", "qty", "unit_cost"],
    "inventory": ["product_id", "on_hand", "last_movement"],
    "invoices": ["invoice_id", "invoice_no", "so_id", "customer_id", "invoice_date", "due_date", "amount", "paid_amount", "paid_date"],
}


def finalize(t: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """欄位順序對齊資料表；日期空值保持為 None。"""
    out = {}
    for name, cols in COLUMNS.items():
        df = t[name][cols].astype(object)
        out[name] = df.where(df.notna(), None)
    return out


def assert_story(t: dict[str, pd.DataFrame]) -> dict:
    so, sl = t["sales_orders"].copy(), t["sales_order_lines"].copy()
    so["order_date"] = pd.to_datetime(so["order_date"])
    ok = so[so["status"] != "取消"][["so_id", "customer_id", "order_date"]]
    ln = sl.merge(ok, on="so_id")
    for c in ("qty", "unit_price", "unit_cost"):
        ln[c] = ln[c].astype(float)
    ln["rev"] = ln["qty"] * ln["unit_price"]
    ln["gp"] = ln["qty"] * (ln["unit_price"] - ln["unit_cost"])
    info: dict = {}

    # 1. C008
    rev_last = ln[ln["order_date"].dt.year == TODAY.year - 1].groupby("customer_id")["rev"].sum()
    rank = list(rev_last.sort_values(ascending=False).index).index(8) + 1
    assert rank <= 3, f"劇情1：C008 去年營收排名 {rank}，應在前三"
    c8 = ok[ok["customer_id"] == 8]["order_date"]
    after = (c8 >= pd.Timestamp(DROP_START)).sum() / 150
    before = ((c8 < pd.Timestamp(DROP_START)) & (c8 >= pd.Timestamp(DROP_START - timedelta(days=300)))).sum() / 300
    ratio = after / before
    assert 0.45 <= ratio <= 0.75, f"劇情1：C008 近期訂單頻率比 {ratio:.2f}，應約 0.6"
    try:
        last_end = date(TODAY.year - 1, TODAY.month, TODAY.day)
    except ValueError:
        last_end = date(TODAY.year - 1, TODAY.month, 28)
    this = ln[(ln["order_date"] >= pd.Timestamp(date(TODAY.year, 1, 1)))].groupby("customer_id")["rev"].sum()
    prev = ln[(ln["order_date"] >= pd.Timestamp(date(TODAY.year - 1, 1, 1)))
              & (ln["order_date"] <= pd.Timestamp(last_end))].groupby("customer_id")["rev"].sum()
    diff = this.sub(prev, fill_value=0)
    assert diff.idxmin() == 8, f"劇情1：YTD 跌幅最大的是 C{diff.idxmin():03d}，不是 C008"
    pct = (diff / prev).dropna().sort_values()
    info["C008"] = f"去年營收第{rank}、訂單頻率比{ratio:.2f}、YTD跌{-diff[8] / 1e6:.2f}百萬(跌幅%排名第{list(pct.index).index(8) + 1})"

    # 2. 呆滯庫存
    inv = t["inventory"].copy()
    inv["days"] = (pd.Timestamp(TODAY) - pd.to_datetime(inv["last_movement"])).dt.days
    prods = t["products"].set_index("product_id")
    dead = inv[(inv["on_hand"].astype(int) > 0) & (inv["days"] >= 180)]
    dead_skus = set(prods.loc[dead["product_id"], "sku"])
    assert len(dead) == 12 and "BRG-6205-2RS" in dead_skus, f"劇情2：呆滯料號 {len(dead)} 個"
    info["呆滯"] = f"{len(dead)} 個，庫存金額 {(dead['on_hand'].astype(int) * prods.loc[dead['product_id'], 'std_cost'].astype(float).values).sum() / 1e4:.0f} 萬"

    # 3. 缺料
    pend_ids = set(so[so["status"] == "待出貨"]["so_id"])
    pend = sl[sl["so_id"].isin(pend_ids)].groupby("product_id")["qty"].sum()
    po, pl = t["purchase_orders"], t["purchase_order_lines"]
    transit = pl[pl["po_id"].isin(set(po[po["status"] == "待交貨"]["po_id"]))].groupby("product_id")["qty"].sum()
    s = inv.set_index("product_id")[["on_hand"]].astype(int).join(prods[["sku", "safety_stock"]])
    s["pend"], s["transit"] = pend, transit
    s = s.fillna({"pend": 0, "transit": 0})
    short = set(s[(s["on_hand"] + s["transit"] < s["pend"]) | (s["on_hand"] < s["safety_stock"].astype(int))]["sku"])
    assert short == set(SHORT), f"劇情3：缺料清單 {short}"
    g = s[s["sku"] == "GEAR-M2-40T"].iloc[0]
    info["缺料"] = f"{sorted(short)}；GEAR-M2-40T 庫存{int(g['on_hand'])} < 待出貨{int(g['pend'])}"

    # 4. 逾期應收
    iv = t["invoices"].copy()
    iv["over"] = (pd.Timestamp(TODAY) - pd.to_datetime(iv["due_date"])).dt.days
    iv["open"] = iv["amount"].astype(float) - iv["paid_amount"].astype(float)
    late = iv[(iv["open"] > 0) & (iv["over"] > 60)].groupby("customer_id").size()
    assert late.get(15, 0) == 3, f"劇情4：C015 逾期>60天發票 {late.get(15, 0)} 張"
    info["逾期"] = {f"C{k:03d}": int(v) for k, v in late.items()}

    # 5. 毛利率
    m = {y: ln[(ln["order_date"].dt.year == y) & ln["order_date"].dt.month.isin([7, 8, 9])] for y in Q3_YEARS}
    mg = {y: d["gp"].sum() / d["rev"].sum() for y, d in m.items()}
    gap = (mg[Q3_YEARS[0]] - mg[Q3_YEARS[1]]) * 100
    assert 2.7 <= gap <= 3.3, f"劇情5：Q3 毛利率差 {gap:.2f} 個百分點"
    info["毛利"] = f"2025Q3 {mg[2025]:.1%} → 2026Q3 {mg[2026]:.1%}（差 {gap:.1f} 點）"
    info["筆數"] = {k: len(v) for k, v in t.items()}
    return info


def write_csv(t: dict[str, pd.DataFrame]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in t.items():
        df.to_csv(OUT / f"{name}.csv", index=False)


def main() -> None:
    t = finalize(build())
    info = assert_story(t)
    write_csv(t)
    print(f"今天 = {TODAY}")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("assert_story 全部通過；CSV 已輸出到", OUT)


if __name__ == "__main__":
    main()
