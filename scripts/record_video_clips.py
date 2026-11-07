"""錄製系統操作畫面（給介紹影片用）：用真實瀏覽器操作並錄成 webm，另存每段的事件時間。

用法（需 make dev 正在執行、兩個模型已常駐）：
  .venv/bin/python scripts/record_video_clips.py            # 錄全部
  .venv/bin/python scripts/record_video_clips.py chat_sql   # 只錄指定的段
輸出：data/video/clips/<名稱>.webm 與 data/video/clips/clips.json（不進 git）
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000/"
OUT = Path(__file__).resolve().parents[1] / "data" / "video" / "clips"
W, H = 1600, 900

# 讓錄影看得到「滑鼠」：無頭瀏覽器預設不畫游標。點擊時有一圈漣漪。
CURSOR_JS = """
(() => {
  const mk = () => {
    const c = document.createElement('div');
    c.id = '__cur';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-4px 0 0 -4px;z-index:2147483647;pointer-events:none;transition:transform .06s linear';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l14 8-6 1.8L8.2 18z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      r.style.cssText = `position:fixed;left:${e.clientX-18}px;top:${e.clientY-18}px;width:36px;height:36px;border-radius:50%;border:3px solid #c8ff00;z-index:2147483646;pointer-events:none;transition:all .45s ease-out;opacity:.95`;
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(2.2)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState !== 'loading') mk(); else addEventListener('DOMContentLoaded', mk);
})();
"""

Q_SQL = "今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？"
Q_DOC = "鴻遠機械的合約，延遲交貨罰款怎麼算？"
Q_STOCK = "哪些料號超過 180 天沒動？壓了多少錢？"


def glide(pg, x, y, steps=28):
    pg.mouse.move(x, y, steps=steps)


def ask(pg, q, ev, t0, tag):
    box = pg.locator("#input").bounding_box()
    glide(pg, box["x"] + 80, box["y"] + box["height"] / 2)
    pg.mouse.down(); pg.mouse.up()
    pg.wait_for_timeout(400)
    ev[f"{tag}_type_start"] = time.time() - t0
    pg.type("#input", q, delay=70)
    pg.wait_for_timeout(500)
    ev[f"{tag}_send"] = time.time() - t0
    pg.press("#input", "Enter")
    pg.wait_for_timeout(400)
    pg.wait_for_function("!document.querySelector('.pending')", timeout=90000)
    ev[f"{tag}_answer"] = time.time() - t0
    pg.wait_for_timeout(1800)


def clip_dashboard(pg, ev, t0):
    pg.goto(BASE)
    pg.wait_for_selector(".tile", timeout=30000)
    pg.wait_for_timeout(1500)
    ev["ready"] = time.time() - t0
    tiles = pg.locator(".tile")
    n = min(tiles.count(), 4)
    for i in range(n):  # 滑過前幾張指標卡
        b = tiles.nth(i).bounding_box()
        glide(pg, b["x"] + b["width"] * 0.55, b["y"] + b["height"] * 0.5)
        pg.wait_for_timeout(700)
    pg.mouse.wheel(0, 520)  # 往下看圖表
    pg.wait_for_timeout(1800)
    pg.mouse.wheel(0, -520)
    pg.wait_for_timeout(800)
    ev["end"] = time.time() - t0


def clip_chat_sql(pg, ev, t0):
    pg.goto(BASE + "chat")
    pg.wait_for_selector("#input", timeout=30000)
    pg.wait_for_timeout(1200)
    ev["ready"] = time.time() - t0
    ask(pg, Q_SQL, ev, t0, "q")
    sql = pg.locator("#thread details").filter(has_text="SQL").last  # 展開 SQL，展示可稽核
    if sql.count():
        b = sql.locator("summary").first.bounding_box()
        if b:
            glide(pg, b["x"] + 40, b["y"] + 8); pg.mouse.down(); pg.mouse.up()
            pg.wait_for_timeout(1200)
            # 把右側面板捲到底，讓完整的 SQL 區塊進入畫面並停留（介紹影片要拍清楚 SQL）
            pg.locator("#panel").evaluate("el => el.scrollTo({top: el.scrollHeight, behavior: 'smooth'})")
            pg.wait_for_timeout(3800)
    ev["end"] = time.time() - t0


def clip_chat_doc(pg, ev, t0):
    pg.goto(BASE + "chat")
    pg.wait_for_selector("#input", timeout=30000)
    pg.wait_for_timeout(1200)
    ev["ready"] = time.time() - t0
    ask(pg, Q_DOC, ev, t0, "q")
    pg.locator("details.sources summary").last.scroll_into_view_if_needed()
    s = pg.locator("details.sources summary").last.bounding_box()
    glide(pg, s["x"] + 30, s["y"] + 8); pg.mouse.down(); pg.mouse.up()
    pg.wait_for_timeout(1500)
    ev["sources_open"] = time.time() - t0
    btn = pg.locator("details.sources button.tool").last
    b = btn.bounding_box()
    glide(pg, b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    pg.wait_for_timeout(500)
    ev["viewer_click"] = time.time() - t0
    pg.mouse.down(); pg.mouse.up()
    pg.wait_for_timeout(3500)  # 原頁與螢光框
    ev["end"] = time.time() - t0


def clip_chat_stock(pg, ev, t0):
    pg.goto(BASE + "chat")
    pg.wait_for_selector("#input", timeout=30000)
    pg.wait_for_timeout(1200)
    ev["ready"] = time.time() - t0
    ask(pg, Q_STOCK, ev, t0, "q")
    pg.wait_for_timeout(1500)
    ev["end"] = time.time() - t0


CLIPS = {"dashboard": clip_dashboard, "chat_sql": clip_chat_sql, "chat_doc": clip_chat_doc, "chat_stock": clip_chat_stock}


def main():
    want = sys.argv[1:] or list(CLIPS)
    if bad := [k for k in want if k not in CLIPS]:
        sys.exit(f"沒有這段：{bad}；可選 {list(CLIPS)}")
    try:
        urllib.request.urlopen(BASE + "health", timeout=5)
    except OSError:
        sys.exit(f"連不到 {BASE}，請先在另一個終端機執行 make dev")
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "clips.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name in want:
            ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                record_video_dir=str(OUT / "_tmp"), record_video_size={"width": W, "height": H})
            ctx.add_init_script(CURSOR_JS)
            pg = ctx.new_page()
            t0, ev = time.time(), {}
            print(f"錄製 {name} …", flush=True)
            try:
                CLIPS[name](pg, ev, t0)
            finally:
                path = pg.video.path()
                ctx.close()
            dst = OUT / f"{name}.webm"
            Path(path).replace(dst)
            meta[name] = {k: round(v, 2) for k, v in ev.items()}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            print(f"  → {dst.name}  {meta[name]}")
        b.close()
    (OUT / "_tmp").rmdir() if (OUT / "_tmp").exists() and not any((OUT / "_tmp").iterdir()) else None
    print(f"\n完成，檔案在 {OUT}")


main()
