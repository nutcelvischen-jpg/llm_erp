"""現場示範劇本（docs/DEMO_STORIES.md）：在真實瀏覽器依序提問並截圖，順便確認每題的答案與耗時。

用法（需 make dev 正在執行）：
  uv run --with playwright python scripts/demo_stories.py [劇本編號 ...] [--out 資料夾]
例：uv run --with playwright python scripts/demo_stories.py          # 全部 7 個劇本
    uv run --with playwright python scripts/demo_stories.py 1 3      # 只跑劇本 1、3
截圖預設存到 data/demo_shots/（不進 git）。
"""
import argparse
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

S = {
 "1": ["鴻遠機械最近 12 個月每個月的營收", "鴻遠機械的合約，年度採購多少可以拿到折讓？", "鴻遠機械今年營收多少？依鴻遠機械的合約，今年拿得到折讓嗎？"],
 "2": ["最近 18 個月每個月的毛利率", "哪個客戶今年的營收比去年同期掉最多"],
 "3": ["應收帳款的帳齡分佈", "台陽科技有哪些發票逾期", "依合約，台陽科技逾期多久我們可以暫停出貨？信用額度多少？"],
 "4": ["依目前待出貨訂單，哪些料號會缺料？建議採購多少？", "各供應商的準時交貨率", "精密熱處理依合約標準交期幾天？延遲交貨我們可以怎麼扣款？", "GEAR-M2-40T 的材質與硬度是什麼？"],
 "5": ["客戶反映 6205-2RS 軸承異音，A 級客訴要多久內提出暫時對策？要用什麼報告回覆？", "6205-2RS 軸承的內外環硬度規格是多少？", "BRG-6205-2RS 目前庫存多少"],
 "6": ["我月薪 48,000，請事假 1 天要扣多少薪水？", "平日加班前兩小時的加班費倍率是多少？"],
 "7": ["各業務員今年的毛利率跟去年比", "各業務員的薪水是多少"],
}
ap = argparse.ArgumentParser(description="現場示範劇本：依序提問並截圖")
ap.add_argument("stories", nargs="*", metavar="劇本編號", help=f"可選 {'、'.join(S)}；不填跑全部")
ap.add_argument("--url", default="http://localhost:8000/", help="伺服器位址（問答頁在 /chat）")
ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "demo_shots"), help="截圖資料夾")
args = ap.parse_args()
if bad := [k for k in args.stories if k not in S]:
    ap.error(f"沒有劇本 {'、'.join(bad)}，可選 {'、'.join(S)}")
only = args.stories or list(S)
BASE = args.url.rstrip("/") + "/"
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
try:
    urllib.request.urlopen(BASE + "health", timeout=5)
except OSError:
    sys.exit(f"連不到 {BASE}，請先在另一個終端機執行 make dev")

slow = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for k in only:
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "chat")
        print(f"\n劇本 {k}")
        for i, q in enumerate(S[k], 1):
            t = time.time()
            pg.fill("#input", q); pg.press("#input", "Enter")
            pg.wait_for_timeout(300)
            pg.wait_for_function("!document.querySelector('.pending')", timeout=90000)
            dt = time.time() - t
            pg.wait_for_timeout(1500)
            card = pg.locator("#thread .card").last
            txt = card.inner_text().replace("\n", " ")[:220]
            chart = "［圖表］" if pg.locator("#panel .chart").count() else ""
            print(f"  {i}. {q}（{dt:.1f} 秒）{chart}\n     {txt[:160]}")
            if dt > 15:
                slow.append(f"劇本 {k} 第 {i} 題 {dt:.1f} 秒")
            pg.screenshot(path=str(out / f"story{k}_{i}.png"))
        pg.close()
    b.close()
print(f"\n截圖已存到 {out}")
if slow:
    print("超過 15 秒（可能沒暖機）：" + "；".join(slow))
