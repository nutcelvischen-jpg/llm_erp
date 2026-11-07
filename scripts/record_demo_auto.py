"""自動操作 llm_erp：錄製示範影片並截取關鍵畫面。

執行：uv run --with playwright python scripts/record_demo_auto.py
需先 make up、make llm-up、make dev（/health 回 ok: true）。
輸出：data/demo_recordings/（已在 .gitignore 之外請自行決定是否提交）
"""
import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "demo_recordings"
VIDEO_DIR = OUT_DIR / "raw_video"
BASE_URL = "http://localhost:8000"

SCENARIOS = [
    {"id": "02_margin_drop", "q": "今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？",
     "desc": "毛利同期比較與掉單分析", "show_sql": True},
    {"id": "03_revenue_trend", "q": "鴻遠機械最近 12 個月每個月的營收",
     "desc": "月營收折線圖", "show_sql": False},
    {"id": "04_contract_merging", "q": "鴻遠機械今年營收多少？依鴻遠機械的合約，今年拿得到折讓嗎？",
     "desc": "數字與合約合併判定（ERP + RAG）", "show_sql": False},
    {"id": "05_dead_stock", "q": "哪些料號超過 180 天沒動？壓了多少錢？",
     "desc": "呆滯庫存天數與金額診斷", "show_sql": True},
    {"id": "06_shortage_alert", "q": "依目前待出貨訂單，哪些料號會缺料？建議採購多少？",
     "desc": "缺料預警與採購建議表", "show_sql": False},
    {"id": "07_ar_aging", "q": "應收帳款的帳齡分佈",
     "desc": "帳齡分佈長條圖", "show_sql": False},
]


def wait_answer(page, timeout=90000):
    """等「思考中」出現再等它消失；中途若出現反問／確認卡，由截圖呈現，不自動點選。"""
    try:
        page.wait_for_selector(".pending", timeout=5000)
    except Exception:
        pass  # 回答極快時可能來不及看到
    page.wait_for_function("!document.querySelector('.pending')", timeout=timeout)


def open_sql(page):
    """展開右側面板裡的 SQL（<details>），並捲到可見處。"""
    d = page.locator("#panel details").filter(has_text="SQL")
    if d.count() == 0:
        return False
    d = d.last
    if d.evaluate("el => !el.open"):
        d.locator("summary").first.click()
    page.wait_for_timeout(600)
    d.scroll_into_view_if_needed()
    return True


def run_demo():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(VIDEO_DIR, ignore_errors=True)
    VIDEO_DIR.mkdir(parents=True)
    failed = []
    timeline = {}  # 各段相對於影片開頭的秒數，給 make_demo_video.py 對齊旁白用

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,  # 高畫質截圖；影片仍為 1440x900
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1440, "height": 900},
        )
        t0 = time.monotonic()
        page = context.new_page()
        now = lambda: round(time.monotonic() - t0, 2)

        print("=== 步驟 0：首頁儀表板 ===")
        page.goto(f"{BASE_URL}/")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT_DIR / "01_dashboard.png"))
        print("已截圖：01_dashboard.png")
        timeline["01_dashboard"] = {"start": 0.0, "ready": now()}

        print("=== 步驟 1：進入問答頁面 ===")
        page.goto(f"{BASE_URL}/chat")
        page.wait_for_timeout(2000)

        for s in SCENARIOS:
            print(f"\n提問：{s['q']}（{s['desc']}）")
            try:
                page.fill("#input", s["q"])
                page.wait_for_timeout(400)
                page.press("#input", "Enter")
                sent = now()
                wait_answer(page)
                page.wait_for_timeout(2500)  # 等圖表動畫
                if s["show_sql"] and not open_sql(page):
                    print("  （此題沒有 SQL 區塊，略過展開）")
                page.screenshot(path=str(OUT_DIR / f"{s['id']}.png"))
                timeline[s["id"]] = {"start": round(sent - 1.2, 2), "sent": sent, "ready": now()}
                print(f"已截圖：{s['id']}.png")
            except Exception as e:  # 單題失敗不中斷整段錄影
                failed.append(s["id"])
                print(f"  [失敗] {s['id']}：{str(e)[:120]}")
                page.screenshot(path=str(OUT_DIR / f"{s['id']}_FAILED.png"))
            page.wait_for_timeout(1500)

        timeline["_end"] = now()
        video = page.video
        page.close()
        context.close()  # 關閉後影片才會寫完
        browser.close()

        if video:
            target = OUT_DIR / "llm_erp_demo.webm"
            shutil.move(video.path(), str(target))
            print(f"\n示範影片錄製完成：{target}")

    (OUT_DIR / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    shutil.rmtree(VIDEO_DIR, ignore_errors=True)
    if failed:
        print("未成功的題目：", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    run_demo()
