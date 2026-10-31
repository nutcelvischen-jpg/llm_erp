"""前端檢查：用 Playwright 開 backend/app/web/index.html，攔截 /api/chat 回傳假資料，驗證行為與安全性。

用法：python3 scripts/check_frontend.py [截圖資料夾]
（Playwright 不是專案依賴；需要時自行安裝：pip install playwright && playwright install chromium）
頁面以假網址 http://app.test/ 提供，不需要啟動後端。
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "backend" / "app" / "web" / "index.html").read_text(encoding="utf-8")
BASE = "http://app.test/"  # 瀏覽器不允許 file:// 頁面發 fetch，所以用假網址並以 route 提供頁面
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
passed: list[str] = []


def check(cond: bool, name: str) -> None:
    if not cond:
        raise AssertionError(f"[FAIL] {name}")
    passed.append(name)


def answer(**kw) -> dict:
    base = {"question": "q", "sql": "", "explanation": "", "columns": [], "rows": [], "row_count": 0,
            "attempts": 1, "error": None, "latency_ms": 2300}
    return {**base, **kw}


def mock(page, payload=None, status=200, delay_ms=0, abort=False):
    requests = []

    def handler(route):
        requests.append(json.loads(route.request.post_data or "{}"))
        if abort:
            return route.abort()
        if delay_ms:
            page.wait_for_timeout(delay_ms)
        return route.fulfill(status=status, content_type="application/json", body=json.dumps(payload or {}))

    page.route("**/api/chat", handler)
    return requests


WEB = ROOT / "backend" / "app" / "web"


def fresh(browser, width=800):
    """預設 800 寬（窄版：結果直接放在對話卡片內）；width>=1000 則是兩欄版面。"""
    page = browser.new_page(viewport={"width": width, "height": 800})
    page.route(BASE, lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=HTML))
    page.route("http://app.test/static/**", lambda r: r.fulfill(path=str(WEB / r.request.url.split("/static/")[1])))
    page.goto(BASE)
    return page


def shot(page, name):
    if SHOTS:
        page.wait_for_timeout(1300)  # 等圖表進場動畫播完
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


with sync_playwright() as p:
    browser = p.chromium.launch()

    # 1. 初始畫面與範例按鈕
    page = fresh(browser)
    check(page.title() == "ERP 智慧助理", "標題")
    check(page.locator(".chip").count() == 6, "6 個範例問題按鈕")
    shot(page, "1_welcome")

    # 2. 點範例 → 送出該問題；表格 20 列上限、千分位、null、數字靠右、SQL 預設收合
    rows = [[f"客戶{i}", 1234567 + i, None if i == 0 else 12.3456, 2025] for i in range(25)]
    reqs = mock(page, answer(explanation="今年各客戶營收", sql='SELECT 1 FROM "v_銷售明細" LIMIT 200',
                             columns=["客戶名稱", "營收", "毛利率", "年"], rows=rows, row_count=25))
    first = page.locator(".chip").first.inner_text()
    page.locator(".chip").first.click()
    page.wait_for_selector("table")
    check(reqs[0]["question"] == first, "點範例會送出該問題")
    check(page.locator("tbody tr").count() == 20, "表格最多顯示 20 列")
    check("僅顯示前 20 列，共 25 列" in page.locator(".note").inner_text(), "超過 20 列的提示")
    check(page.locator("tbody tr").nth(0).locator("td").nth(1).inner_text() == "1,234,567", "千分位")
    check(page.locator("tbody tr").nth(0).locator("td").nth(2).inner_text() == "-", "null 顯示 -")
    check(page.locator("tbody tr").nth(1).locator("td").nth(2).inner_text() == "12.35", "小數取 2 位")
    check(page.locator("tbody tr").nth(0).locator("td").nth(3).inner_text() == "2025", "年份不加千分位")
    check("num" in page.locator("tbody tr").nth(0).locator("td").nth(1).get_attribute("class"), "數字欄靠右")
    check(page.locator(".welcome").count() == 0, "送出後範例區消失")
    check(page.locator("details").get_attribute("open") is None, "SQL 預設收合")
    page.locator("summary").click()
    check(page.locator("details pre").is_visible() and "v_銷售明細" in page.locator("details pre").inner_text(), "SQL 可展開")
    check("耗時 2.3 秒・嘗試 1 次" in page.locator(".meta").inner_text(), "耗時與嘗試次數")
    check(page.locator("#input").is_enabled() and page.locator("#send").is_enabled(), "完成後輸入框恢復可用")
    shot(page, "2_result")

    # 3. 錯誤情境
    mock_err = answer(error="這個問題無法用目前的 ERP 資料回答：沒有薪資資料")
    page.unroute("**/api/chat")
    mock(page, mock_err)
    page.fill("#input", "員工薪水多少？")
    page.press("#input", "Enter")
    page.wait_for_selector(".error")
    check("沒有薪資資料" in page.locator(".error").last.inner_text(), "業務錯誤顯示紅色提示框")
    shot(page, "3_error")

    page.unroute("**/api/chat")
    mock(page, {"detail": "x"}, status=500)
    page.fill("#input", "測試 500")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.error').length >= 2")
    check("HTTP 500" in page.locator(".error").last.inner_text(), "HTTP 500 提示")

    page.unroute("**/api/chat")
    mock(page, abort=True)
    page.fill("#input", "測試斷線")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.error').length >= 3")
    check("無法連線" in page.locator(".error").last.inner_text(), "網路失敗提示")

    page.unroute("**/api/chat")
    mock(page, answer(explanation="沒資料", columns=["a"], rows=[], row_count=0))
    page.fill("#input", "空結果")
    page.press("#input", "Enter")
    page.wait_for_selector(".empty")
    check("沒有符合條件的資料" in page.locator(".empty").inner_text(), "空結果提示")
    page.close()

    # 4. 輸入行為：Enter 送出、Shift+Enter 換行、輸入法選字不送出、空白不送出
    page = fresh(browser)
    reqs = mock(page, answer(explanation="ok", columns=["a"], rows=[[1]], row_count=1))
    page.fill("#input", "第一行")
    page.press("#input", "Shift+Enter")
    check(len(reqs) == 0 and page.input_value("#input").endswith("\n"), "Shift+Enter 換行不送出")
    page.fill("#input", "選字中")
    page.evaluate("document.getElementById('input').dispatchEvent("
                  "new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true}))")
    page.wait_for_timeout(300)
    check(len(reqs) == 0, "輸入法選字時按 Enter 不送出")
    page.fill("#input", "   ")
    page.press("#input", "Enter")
    page.wait_for_timeout(300)
    check(len(reqs) == 0, "只有空白不送出")
    page.fill("#input", "正式送出")
    page.press("#input", "Enter")
    page.wait_for_selector("table")
    check(len(reqs) == 1 and reqs[0]["question"] == "正式送出", "Enter 送出")
    page.close()

    # 5. 處理中：顯示「思考中」、輸入框與按鈕停用
    page = fresh(browser)
    mock(page, answer(explanation="慢", columns=["a"], rows=[[1]], row_count=1), delay_ms=1500)
    page.fill("#input", "慢的查詢")
    page.press("#input", "Enter")
    page.wait_for_selector(".pending")
    check(page.locator("#input").is_disabled() and page.locator("#send").is_disabled(), "處理中停用輸入")
    check("思考中" in page.locator(".pending").inner_text(), "顯示思考中")
    shot(page, "5_pending")
    page.wait_for_selector("table")
    page.close()

    # 6. XSS：後端回傳的內容含惡意 HTML，必須只當文字顯示、不得執行
    page = fresh(browser)
    evil = '<img src=x onerror="window.__xss=1">'
    mock(page, answer(explanation=evil, sql=f"SELECT '{evil}'", columns=[evil], row_count=1,
                      rows=[[f"<script>window.__xss=2</script>{evil}"]]))
    page.fill("#input", '<img src=x onerror="window.__xss=3"><script>window.__xss=4</script>')
    page.press("#input", "Enter")
    page.wait_for_selector("table")
    page.wait_for_timeout(500)
    check(page.evaluate("window.__xss") is None, "惡意 HTML 不會被執行")
    check(page.locator("#thread img, #panel img, #thread script, #panel script").count() == 0, "對話區與面板沒有被注入的 img/script 元素")
    check(evil in page.locator(".explain").inner_text(), "說明文字原樣顯示為文字")
    check(evil in page.locator("th").first.inner_text(), "欄位名稱原樣顯示為文字")
    check("window.__xss=4" in page.locator(".msg-user").inner_text(), "使用者輸入原樣顯示為文字")
    page.close()


    # ================= T13c：寬螢幕兩欄版面、圖表、排序 =================
    TOP = answer(explanation="今年營收最高的客戶", sql='SELECT "客戶名稱" FROM "v_銷售明細" LIMIT 200',
                 columns=["客戶名稱", "營收"], rows=[["華發實業", 11979390], ["鴻遠機械", 9869353], ["億達企業", 3783773]], row_count=3)
    TREND = answer(explanation="近 6 個月營收", sql='SELECT 1 FROM "v_銷售明細" LIMIT 200', columns=["月份", "營收", "毛利率(%)"],
                   rows=[[f"2026-0{m}", 7000000 + m * 90000, 24 + m * 0.2] for m in range(5, 10)], row_count=5)

    def ask_and_wait(page, payload, question="測試", selector=".card.answer"):
        before = page.locator(selector).count()
        page.unroute("**/api/chat")
        mock(page, payload)
        page.fill("#input", question)
        page.press("#input", "Enter")
        page.wait_for_function(f"document.querySelectorAll('{selector}').length > {before}")
        page.wait_for_timeout(400)

    page = fresh(browser, width=1280)
    mock(page, TOP)
    page.fill("#input", "營收前三")
    page.press("#input", "Enter")
    page.wait_for_selector(".panel .chart canvas")
    check(page.locator("#layout.wide").count() == 1 and page.locator("#panel").is_visible(), "寬螢幕顯示右側面板")
    check(page.locator(".panel .chart").get_attribute("data-chart-type") == "bar", "客戶營收畫長條圖")
    check(page.locator(".panel table tbody tr").count() == 3, "面板有完整資料表")
    check(page.locator(".panel details").get_attribute("open") is not None and "v_銷售明細" in page.locator(".panel pre").inner_text(), "面板同時顯示 SQL")
    check(page.locator(".panel-head p").inner_text() == "營收前三", "面板標題顯示對應的問題")
    check(page.locator(".card.answer table tbody tr").count() == 3 and page.locator(".hintline").count() == 1, "對話卡片只放預覽與提示")
    check(page.locator(".card.answer .chart").count() == 0 and page.locator(".card.answer details").count() == 0, "對話卡片不重複放圖與 SQL")
    check(page.locator(".card.answer").first.get_attribute("class").count("active") == 1, "最新回答為選取狀態")
    shot(page, "6_wide_bar")

    ask_and_wait(page, TREND, "趨勢")
    check(page.locator(".panel .chart").get_attribute("data-chart-type") == "line", "月份資料畫折線圖")
    check(page.locator(".panel .chart").get_attribute("data-axes") == "2", "營收與毛利率量級差太多時用雙 Y 軸")
    check("active" in page.locator(".card.answer").nth(1).get_attribute("class") and "active" not in page.locator(".card.answer").nth(0).get_attribute("class"), "選取狀態移到最新回答")
    shot(page, "7_wide_line")
    page.locator(".card.answer").nth(0).click()
    page.wait_for_selector('.panel .chart[data-chart-type="bar"]')
    check("營收前三" in page.locator(".panel-head p").inner_text() and "active" in page.locator(".card.answer").nth(0).get_attribute("class"), "點舊回答可切換面板")

    # 排序：升冪 → 降冪 → 還原
    first = lambda: page.locator(".panel tbody tr").first.locator("td").first.inner_text()
    check(first() == "華發實業", "排序前為原順序")
    page.locator(".panel th button", has_text="營收").click()
    check(first() == "億達企業", "點欄位標題：數字升冪")
    page.locator(".panel th button", has_text="營收").click()
    check(first() == "華發實業", "再點一次：降冪")
    page.locator(".panel th button", has_text="營收").click()
    page.locator(".panel th button", has_text="客戶名稱").click()
    check(page.locator(".panel th .arrow").first.inner_text() == "▲", "排序箭頭")
    check(page.locator(".panel .chart canvas").count() == 1, "點卡片或排序不會讓圖表消失")

    # 回饋按鈕
    up, down = page.locator(".card.answer").nth(0).locator(".fb").nth(0), page.locator(".card.answer").nth(0).locator(".fb").nth(1)
    up.click()
    check(up.get_attribute("aria-pressed") == "true" and down.get_attribute("aria-pressed") == "false", "👍 可切換")
    down.click()
    check(up.get_attribute("aria-pressed") == "false" and down.get_attribute("aria-pressed") == "true", "👎 與 👍 互斥")

    # 各種圖表判斷
    YQ = answer(columns=["年", "季", "營收", "毛利率(%)"], row_count=4,
                rows=[[2025, 3, 23109297, 25.6], [2025, 4, 24500000, 25.9], [2026, 1, 22000000, 24.1], [2026, 2, 21800000, 23.8]])
    ask_and_wait(page, YQ, "季度")
    check(page.locator(".panel .chart").get_attribute("data-chart-type") == "line", "年+季合併成季度折線圖")
    check(page.locator(".panel tbody tr").first.locator("td").first.inner_text() == "2025", "年份不加千分位（面板）")

    CAT = answer(columns=["產品類別", "營收", "占比(%)"], row_count=3, rows=[["軸承", 40000000, 55.2], ["齒輪", 20000000, 27.6], ["扣件", 12000000, 17.2]])
    ask_and_wait(page, CAT, "占比")
    check(page.locator(".panel .chart").get_attribute("data-chart-type") == "bar" and page.locator(".panel .chart").get_attribute("data-axes") == "2", "營收與占比用雙軸長條圖")

    MANY = answer(columns=["客戶名稱", "差額"], row_count=12, rows=[[f"客戶{i}", -i * 1000] for i in range(12)])
    ask_and_wait(page, MANY, "很多列")
    check(page.locator(".panel .chart").get_attribute("data-chart-type") == "hbar", "類別超過 8 個改畫橫條圖")

    STOCK = answer(columns=["料號", "品名", "現有庫存", "庫存金額"], row_count=2, rows=[["BRG-1", "軸承", 100, 5000], ["BRG-2", "軸承", 200, 9000]])
    ask_and_wait(page, STOCK, "文字欄")
    check(page.locator(".panel .chart").count() == 0 and page.locator(".panel table").count() == 1, "含文字欄的結果不畫圖，只出表格")

    ask_and_wait(page, answer(columns=["客戶名稱", "營收"], rows=[["甲", 1]], row_count=1), "單列")
    check(page.locator(".panel .chart").count() == 0, "只有 1 列不畫圖")

    CODES = answer(columns=["代碼", "數量"], rows=[[101, 5], [102, 9], [103, 3]], row_count=3)
    ask_and_wait(page, CODES, "代碼")
    check(page.locator(".panel .chart").count() == 0, "第一欄是一般數字（代碼）不畫圖")

    ask_and_wait(page, answer(error="這個問題無法用目前的 ERP 資料回答：沒有薪資資料"), "薪水")
    check("沒有可顯示的結果" in page.locator(".panel").inner_text(), "錯誤回答的面板提示")

    # 寬 → 窄：面板收起，結果改放進卡片；再回到寬
    ask_and_wait(page, TOP, "營收前三 again")
    page.set_viewport_size({"width": 800, "height": 800})
    page.wait_for_timeout(500)
    check(not page.locator("#panel").is_visible() and page.locator("#layout.wide").count() == 0, "變窄後面板收起")
    check(page.locator(".card.answer").last.locator("table").count() == 1 and page.locator(".card.answer").last.locator(".chart canvas").count() == 1, "變窄後卡片內含圖與表")
    shot(page, "8_narrow_inline")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_selector(".panel .chart canvas")
    check(page.locator("#panel").is_visible() and page.locator(".card.answer").last.locator("table").count() == 1, "變寬後恢復兩欄")
    check(page.locator(".card.answer").last.locator(".chart").count() == 0, "變寬後卡片不重複圖表")

    # 處理中：面板顯示骨架畫面
    page.unroute("**/api/chat")
    mock(page, TOP, delay_ms=1200)
    page.fill("#input", "慢")
    page.press("#input", "Enter")
    page.wait_for_selector(".panel .skeleton")
    check(page.locator(".panel .skeleton").count() == 3, "寬螢幕處理中面板顯示骨架畫面")
    page.wait_for_selector(".panel .chart canvas")

    # 品牌設定
    check(page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--brand').trim()") == "#0f4c81", "品牌色來自 CONFIG")
    check(page.evaluate("document.getElementById('brandName').textContent") == page.evaluate("CONFIG.brand.name"), "名稱來自 CONFIG")
    page.close()

    # 圖表的 XSS：類別名稱與數列名稱含惡意 HTML，hover 出 tooltip 也不能執行
    page = fresh(browser, width=1280)
    evil = '<img src=x onerror="window.__xss=7">'
    mock(page, answer(columns=[evil, evil + "值"], row_count=3, rows=[[evil, 10], [evil + "2", 20], [evil + "3", 15]]))
    page.fill("#input", "惡意圖表")
    page.press("#input", "Enter")
    page.wait_for_selector(".panel .chart canvas")
    box = page.locator(".panel .chart").bounding_box()
    for fx in (0.25, 0.5, 0.75):
        page.mouse.move(box["x"] + box["width"] * fx, box["y"] + box["height"] * 0.6)
        page.wait_for_timeout(250)
    page.wait_for_timeout(400)
    check(page.evaluate("window.__xss") is None, "圖表 tooltip 的惡意 HTML 不會被執行")
    check(page.locator(".panel .chart img").count() == 0, "圖表內沒有被注入的 img")
    page.close()

    # both 但數字部分沒有執行查詢（只有文件回答）：不顯示空結果提示
    page = fresh(browser)
    mock(page, answer(route="both", answer="依合約逾期超過 60 日得暫停出貨 [來源 1]",
                      sources=[{"file_name": "銷售合約_台陽科技.pdf", "page": 3, "heading": "", "snippet": "60 日"}]))
    page.fill("#input", "台陽暫停出貨")
    page.press("#input", "Enter")
    page.wait_for_selector(".sources")
    card = page.locator(".card.answer").last
    check(card.locator(".empty").count() == 0 and card.locator("table").count() == 0, "both 沒執行查詢時不顯示空結果提示")
    page.close()

    # ================= T25：Agent 回答（route、來源、警示、回饋、對話脈絡）=================
    SRC = [{"file_name": "銷售合約_鴻遠機械.pdf", "page": 2, "heading": "第五條（延遲交貨之處理）", "snippet": "每逾一日…0.3%"},
           {"file_name": "銷售合約_鴻遠機械.pdf", "page": 3, "heading": "", "snippet": "採購預測"}]
    DOCS = answer(route="docs", answer="1. 每逾一日 0.3% [來源 1]\n2. 上限 10% [來源 1]", sources=SRC, audit_id=11, attempts=0)
    page = fresh(browser)
    reqs = mock(page, DOCS)
    fb = []
    page.route("**/api/feedback", lambda r: fb.append(json.loads(r.request.post_data)) or r.fulfill(
        status=200, content_type="application/json", body='{"ok": true, "id": 1}'))
    page.fill("#input", "鴻遠罰款")
    page.press("#input", "Enter")
    page.wait_for_selector(".sources")
    card = page.locator(".card.answer").last
    check(card.locator("table").count() == 0 and card.locator(".empty").count() == 0, "docs 回答不顯示表格與空結果提示")
    check("上限 10%" in card.locator(".explain").inner_text() and "long" in card.locator(".explain").get_attribute("class"), "docs 回答多行文字")
    check(card.locator(".sources").get_attribute("open") is None, "來源預設收合")
    card.locator(".sources summary").click()
    check(card.locator(".sources li").count() == 2 and "文件來源（2）" in card.locator(".sources summary").inner_text(), "來源列表可展開")
    check("銷售合約_鴻遠機械.pdf 第 2 頁 › 第五條（延遲交貨之處理）" in card.locator(".sources li").first.inner_text(), "來源顯示檔名、頁碼與標題")
    check("0.3%" in card.locator(".src-snippet").first.inner_text(), "來源顯示片段")
    check("嘗試" not in card.locator(".meta").inner_text(), "沒有 SQL 時不顯示嘗試次數")
    check(reqs[0]["session_id"] and reqs[0]["history"] == [], "第一題送出 session_id 與空的 history")
    shot(page, "9_docs_sources")

    card.locator(".fb").nth(1).click()
    page.wait_for_function("document.querySelector('.card.answer:last-child .fb-status')?.textContent === '已記錄回饋'")
    check(fb == [{"audit_id": 11, "score": -1}], "👎 呼叫 /api/feedback")
    card.locator(".fb").nth(1).click()
    page.wait_for_timeout(200)
    check(len(fb) == 1 and card.locator(".fb").nth(1).get_attribute("aria-pressed") == "false", "取消回饋不重複送出")

    page.unroute("**/api/chat")
    reqs = mock(page, answer(route="sql", answer="今年營收最高的 3 個客戶", sql="SELECT 1", columns=["客戶名稱", "營收"],
                             rows=[["甲", 3], ["乙", 2]], row_count=2, warning="AI 即時產生的查詢，請查核 SQL 與結果", audit_id=12))
    page.fill("#input", "那營收呢")
    page.press("#input", "Enter")
    page.wait_for_selector(".warning")
    check(reqs[0]["history"] == [{"role": "user", "content": "鴻遠罰款"}, {"role": "assistant", "content": DOCS["answer"]}], "第二題帶上前一輪對話")
    check(reqs[0]["session_id"] == page.evaluate("sessionId"), "同一頁面沿用 session_id")
    check("AI 即時產生" in page.locator(".warning").inner_text() and page.locator(".card.answer").last.locator("table").count() == 1, "sql 回答顯示黃色警示與表格")

    page.unroute("**/api/feedback")
    page.route("**/api/feedback", lambda r: r.fulfill(status=503, content_type="application/json", body='{"detail": "x"}'))
    last = page.locator(".card.answer").last
    last.locator(".fb").first.click()
    page.wait_for_function("document.querySelector('.card.answer:last-child .fb-status')?.textContent === '回饋送出失敗'")
    check(last.locator(".fb").first.get_attribute("aria-pressed") == "false", "回饋失敗時恢復按鈕狀態")

    page.unroute("**/api/chat")
    mock(page, answer(route="both", answer="依合約逾期 60 日可暫停出貨 [來源 1]", sources=SRC[:1],
                      error="數據查詢失敗：無法連線資料庫"))
    page.fill("#input", "部分失敗")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 3")
    page.wait_for_timeout(300)
    last = page.locator(".card.answer").last
    check("暫停出貨" in last.locator(".explain").inner_text() and "這部分查詢失敗" in last.locator(".error").inner_text(), "部分失敗：顯示回答與失敗提示")
    page.close()

    # 寬螢幕：docs 回答的面板顯示來源
    page = fresh(browser, width=1280)
    mock(page, DOCS)
    page.fill("#input", "鴻遠罰款")
    page.press("#input", "Enter")
    page.wait_for_selector(".panel .sources")
    check(page.locator(".panel .sources").get_attribute("open") is not None and page.locator(".panel .sources li").count() == 2, "寬螢幕面板顯示展開的來源")
    check(page.locator(".panel table").count() == 0 and page.locator(".panel .chart").count() == 0, "docs 面板沒有表格與圖表")
    shot(page, "10_wide_docs")
    page.close()

    # 來源與回答的 XSS
    page = fresh(browser)
    evil = '<img src=x onerror="window.__xss=9">'
    mock(page, answer(route="docs", answer=evil, sources=[{"file_name": evil, "page": 1, "heading": evil, "snippet": evil}],
                      warning=evil, error=evil))
    page.fill("#input", "惡意來源")
    page.press("#input", "Enter")
    page.wait_for_selector(".sources")
    page.locator(".sources summary").click()
    page.wait_for_timeout(300)
    check(page.evaluate("window.__xss") is None and page.locator("#thread img").count() == 0, "回答與來源的惡意 HTML 不會被執行")
    check(evil in page.locator(".sources li").first.inner_text(), "來源原樣顯示為文字")
    page.close()

    # ================= T14f：既定程式（標準查詢徽章、確認候選、反問、未命中）=================
    TPL = answer(route="sql", mode="template", template_id="sales_rank", template_title="銷售排名",
                 params_readable=["排名對象：客戶", "期間：2026 年（今年）", "筆數：3"], answer="今年營收第一名是華發實業。",
                 sql='SELECT "客戶名稱" FROM "v_銷售明細" WHERE "訂單日期" >= :date_from LIMIT 3',
                 binds={"date_from": "2026-01-01", "date_to": "2026-11-01"}, columns=["客戶名稱", "營收"],
                 rows=[["華發實業", 11979390], ["鴻遠機械", 9869353]], row_count=2, notes=["已將「華發」視為「華發實業」"])
    page = fresh(browser)
    mock(page, TPL)
    page.fill("#input", "今年營收前三")
    page.press("#input", "Enter")
    page.wait_for_selector(".badge")
    card = page.locator(".card.answer").last
    check(card.locator(".badge").inner_text() == "標準查詢：銷售排名", "標準查詢徽章")
    check(card.locator(".tag").count() == 3 and "期間：2026 年（今年）" in card.locator(".badges").inner_text(), "參數標籤")
    check("已將「華發」視為「華發實業」" in card.locator(".notes").first.inner_text(), "名稱替換提示")
    check(card.locator(".warning").count() == 0, "標準查詢不顯示 AI 警示")
    card.locator("summary", has_text="查詢的 SQL").click()
    check('-- :date_from = "2026-01-01"' in card.locator("pre").inner_text(), "SQL 區塊列出綁定參數")
    shot(page, "11_template")

    PROPS = [{"template_id": "sales_rank", "title": "銷售排名", "description": "依客戶排營收",
              "params": {"dimension": "客戶", "metric": "營收", "top_n": 5}, "params_readable": ["排名對象：客戶", "指標：營收"],
              "columns": ["客戶名稱", "營收"], "notes": []},
             {"template_id": "sales_compare", "title": "同期比較", "description": "今年 vs 去年同期",
              "params": {"metric": "營收", "dimension": "業務"}, "params_readable": ["指標：營收", "比較對象：業務"],
              "columns": ["對象", "本期營收", "比較期營收", "增減", "增減(%)"], "notes": ["指標不支援「毛利率」，改用「營收」"]}]
    page.unroute("**/api/chat")
    reqs = mock(page, answer(route="sql", mode="confirm", answer="找不到完全符合的既定查詢。您是要查下列其中一個嗎？", proposals=PROPS))
    page.fill("#input", "各業務毛利率跟去年比")
    page.press("#input", "Enter")
    page.wait_for_selector(".proposal")
    card = page.locator(".card.answer").nth(1)   # 固定索引：送出後 .last 會指到新的回答
    check(card.locator(".proposal").count() == 2 and card.locator("table").count() == 0, "確認模式列出候選、不顯示表格")
    check("結果欄位：對象、本期營收" in card.locator(".proposal").nth(1).inner_text(), "候選顯示結果欄位")
    check("⚠ 指標不支援「毛利率」" in card.locator(".proposal .warn").inner_text(), "候選顯示改用預設的提醒")
    check(card.locator(".error").count() == 0, "確認模式不是錯誤")
    shot(page, "12_confirm")
    page.unroute("**/api/chat")
    reqs = mock(page, TPL)
    card.locator(".proposal").nth(1).locator(".act").click()
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 3")
    check(reqs[0]["choice"] == {"template_id": "sales_compare", "params": {"metric": "營收", "dimension": "業務"}}, "點「執行這個」送出 choice 與參數")
    check(reqs[0]["question"] == "各業務毛利率跟去年比" and page.locator(".msg-user").last.inner_text() == "執行：同期比較", "沿用原問題並顯示執行哪個程式")
    check(card.locator(".act").first.is_disabled(), "點選後候選按鈕停用")

    page.unroute("**/api/chat")
    mock(page, answer(route="sql", mode="confirm", answer="找不到完全符合的既定查詢。", proposals=PROPS[:1]))
    page.fill("#input", "平均訂單金額")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 4")
    card = page.locator(".card.answer").last
    card.locator(".act.ghost", has_text="都不是").click()
    check("已記錄這個問題" in card.inner_text() and card.locator(".act").first.is_disabled(), "「都不是」顯示已記錄")

    page.unroute("**/api/chat")
    reqs = mock(page, answer(route="sql", mode="clarify", answer="「華發」對應到多個客戶，請問是哪一個？", options=["華發實業", "華發精密"]))
    page.fill("#input", "華發今年營收")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 5")
    page.unroute("**/api/chat")
    reqs = mock(page, TPL)
    page.locator(".card.answer").last.locator(".act", has_text="華發精密").click()
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 6")
    check(reqs[0]["question"] == "華發今年營收（指：華發精密）" and "choice" not in reqs[0], "反問選項以「原問題（指：選項）」重新送出")

    page.unroute("**/api/chat")
    mock(page, answer(route="sql", mode="no_match", answer="這類問題目前沒有對應的既定查詢。", suggestions=["今年營收前五名的客戶"]))
    page.fill("#input", "員工薪水")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 7")
    page.unroute("**/api/chat")
    reqs = mock(page, TPL)
    page.locator(".card.answer").last.locator(".act", has_text="今年營收前五名的客戶").click()
    page.wait_for_function("document.querySelectorAll('.card.answer').length >= 8")
    check(reqs[0]["question"] == "今年營收前五名的客戶", "未命中的建議問題可點選送出")
    page.close()

    # 確認候選與反問選項的 XSS
    page = fresh(browser)
    evil = '<img src=x onerror="window.__xss=11">'
    mock(page, answer(route="sql", mode="confirm", answer=evil, proposals=[{
        "template_id": evil, "title": evil, "description": evil, "params": {"x": evil}, "params_readable": [evil],
        "columns": [evil], "notes": [evil]}]))
    page.fill("#input", "惡意候選")
    page.press("#input", "Enter")
    page.wait_for_selector(".proposal")
    page.wait_for_timeout(300)
    check(page.evaluate("window.__xss") is None and page.locator("#thread img").count() == 0, "候選內容的惡意 HTML 不會被執行")
    check(evil in page.locator(".proposal h4").inner_text(), "候選標題原樣顯示為文字")
    page.close()

    # ================= 使用性：範例選單、接著問、回答操作、本次問題、對話紀錄、新對話 =================
    sent = []
    TBL = answer(route="sql", mode="template", template_id="ar_invoices", template_title="客戶逾期發票明細",
                 answer="台陽科技共有 2 張逾期發票。", columns=["發票號碼", "未收金額"], rows=[["INV-1", 1200], ["INV-\"2,", 30]],
                 row_count=2, sql="SELECT 1", audit_id=5,
                 followups=["依合約，台陽科技逾期多久我們可以暫停出貨？", "台陽科技有哪些發票逾期？", evil])

    def usability_handler(route):
        body = json.loads(route.request.post_data or "{}")
        sent.append(body)
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({**TBL, "question": body["question"]}))

    page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page.route(BASE, lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=HTML))
    page.route("http://app.test/static/**", lambda r: r.fulfill(path=str(WEB / r.request.url.split("/static/")[1])))
    page.route("**/api/chat", usability_handler)
    page.goto(BASE)
    check(page.locator(".sidebar").is_visible() and page.locator("#newBtn").is_visible(), "寬螢幕顯示左側欄與新對話")
    check(page.locator("#convos .side-empty").count() == 1, "沒有紀錄時顯示空狀態")
    page.click("#exBtn")
    check(page.locator("#examples").is_visible() and page.locator(".ex-group").count() == 5, "範例選單分 5 組")
    page.keyboard.press("Escape")
    check(page.locator("#examples").is_hidden(), "Esc 關閉範例選單")
    page.locator(".welcome .act").click()
    check(page.locator("#examples").is_visible(), "歡迎畫面的「看更多範例」打開選單")
    page.locator(".ex-item", has_text="台陽科技有哪些發票逾期").click()
    page.wait_for_selector(".card.answer")
    check(sent[-1]["question"] == "台陽科技有哪些發票逾期" and page.locator("#examples").is_hidden(), "點範例直接送出並關閉選單")
    card = page.locator(".card.answer").last
    nq = card.locator(".next-q").all_inner_texts()
    check(nq[0].startswith("依合約") and "台陽科技有哪些發票逾期？" not in nq, "接著問：顯示追問、問過的不再出現（忽略問號）")
    check(evil in nq and page.evaluate("window.__xss") is None, "接著問的惡意 HTML 原樣顯示為文字")
    check(card.locator(".fb").count() == 2 and card.locator(".tool").all_inner_texts() == ["複製", "下載 CSV", "在報表中開啟", "重新查詢"],
          "回答下方有複製、下載 CSV、在報表中開啟、重新查詢")
    check(card.locator("a.tool").get_attribute("href").startswith("/reports?t=ar_invoices"), "「在報表中開啟」連到同一支程式")
    with page.expect_download() as dl:
        card.locator(".tool", has_text="下載 CSV").click()
    raw = Path(dl.value.path()).read_text(encoding="utf-8")
    check(raw.startswith("\ufeff發票號碼,未收金額") and '"INV-""2,"' in raw and dl.value.suggested_filename.startswith("客戶逾期發票明細_"),
          "CSV 含 BOM、正確跳脫、以程式名稱命名")
    check(page.locator("#panel .section-h .tool", has_text="下載 CSV").count() == 1, "右側資料表也能下載 CSV")
    card.locator(".next-q").first.click()
    page.wait_for_function("document.querySelectorAll('.card.answer').length === 2")
    check(sent[-1]["question"].startswith("依合約") and len(sent[-1]["history"]) == 2, "點接著問送出並帶對話脈絡")
    check(page.locator("#toc .side-item").count() == 2 and "current" in page.locator("#toc .side-item").nth(1).get_attribute("class"), "本次對話列出 2 題、標示目前這題")
    page.locator("#toc .go").first.click()
    page.wait_for_timeout(300)
    check("active" in page.locator(".card.answer").first.get_attribute("class") and page.locator("#panel .panel-head p").inner_text() == "台陽科技有哪些發票逾期",
          "點本次對話的問題跳回該題並切換右側面板")
    page.locator(".card.answer").first.locator(".tool", has_text="重新查詢").click()
    page.wait_for_function("document.querySelectorAll('.card.answer').length === 3")
    check(sent[-1]["question"] == "台陽科技有哪些發票逾期", "重新查詢送出同一題")
    first_session = sent[-1]["session_id"]
    check(page.locator("#convos .side-item").count() == 1 and "3 題" in page.locator("#convos .d").inner_text(), "對話自動存進紀錄")
    page.click("#newBtn")
    check(page.locator(".welcome").count() == 1 and page.locator(".card").count() == 0 and page.locator("#toc .side-empty").count() == 1, "新對話回到歡迎畫面")
    page.locator(".chip").first.click()
    page.wait_for_selector(".card.answer")
    check(sent[-1]["history"] == [] and sent[-1]["session_id"] != first_session, "新對話不帶舊脈絡、換新的 session")
    check(page.locator("#convos .side-item").count() == 2, "紀錄有 2 段對話")
    page.reload()
    page.wait_for_selector("#convos .side-item")
    check(page.locator("#convos .side-item").count() == 2, "重新整理後紀錄還在")
    page.locator("#convos .go", has_text="台陽科技有哪些發票逾期").click()
    page.wait_for_timeout(300)
    check(page.locator(".card.answer").count() == 3 and page.locator(".welcome").count() == 0 and page.locator("#toc .side-item").count() == 3, "點紀錄回到那段對話")
    page.fill("#input", "接著問")
    page.press("#input", "Enter")
    page.wait_for_function("document.querySelectorAll('.card.answer').length === 4")
    check(sent[-1]["session_id"] == first_session and len(sent[-1]["history"]) == 6, "回到舊對話後沿用它的脈絡與 session")
    page.on("dialog", lambda d: d.accept())
    page.locator("#convos .side-item").first.hover()
    page.locator("#convos .del").first.click()
    check(page.locator("#convos .side-item").count() == 1 and page.locator(".welcome").count() == 1, "刪除目前的對話後回到新對話")
    page.set_viewport_size({"width": 900, "height": 800})
    page.wait_for_timeout(300)
    check(page.locator("#menuBtn").is_visible() and page.locator("#sidebar").bounding_box()["x"] < 0, "窄螢幕左側欄收起、顯示「☰ 紀錄」")
    page.click("#menuBtn")
    page.wait_for_timeout(300)
    check(page.locator("#sidebar").bounding_box()["x"] >= 0, "點「☰ 紀錄」打開抽屜")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check(page.locator("#sidebar").bounding_box()["x"] < 0, "Esc 關閉抽屜")
    page.close()

    # ================= 儀表板、報表、系統介紹（傳統介面）=================
    def page_for(name, routes, width=1440):
        pg = browser.new_page(viewport={"width": width, "height": 900})
        body = (WEB / name).read_text(encoding="utf-8")
        pg.route(BASE + name.removesuffix(".html") + "*", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=body))
        pg.route("http://app.test/static/**", lambda r: r.fulfill(path=str(WEB / r.request.url.split("/static/")[1])))
        for pattern, handler in routes.items():
            pg.route(pattern, handler)
        return pg

    def json_route(payload, status=200):
        return lambda r: r.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    DASH = {"as_of": "2026-10-31", "latency_ms": 210, "errors": [], "tiles": [
        {"key": "revenue", "title": "今年累計營收", "value": 83487889, "unit": "元", "sub": "去年同期 82,463,973 元，+1.2%", "tone": "ok",
         "report": {"template_id": "sales_compare", "params": {"compare": "yoy_ytd"}}, "ask": "今年營收跟去年同期比如何？"},
        {"key": "x", "title": evil, "value": 3, "unit": evil, "sub": evil, "tone": "danger",
         "report": {"template_id": "stock_shortage", "params": {}}, "ask": evil}],
        "charts": [{"key": "trend", "title": "營收趨勢", "columns": ["月份", "營收"], "rows": [["2026-09", 100], ["2026-10", 120]],
                    "report": {"template_id": "sales_trend", "params": {"grain": "月"}}}]}
    page = page_for("dashboard.html", {"**/api/dashboard": json_route(DASH)})
    page.goto(BASE + "dashboard")
    page.wait_for_selector(".tile")
    check(page.locator(".tile").count() == 2 and page.locator(".tile .value").first.inner_text().startswith("83,487,889"), "儀表板指標卡與千分位")
    check(page.locator(".topnav a[aria-current=page]").inner_text() == "儀表板" and page.locator(".topnav a").count() == 4, "導覽列標示目前頁面")
    check(page.locator(".tile").first.locator("a", has_text="看明細").get_attribute("href").startswith("/reports?t=sales_compare")
          and page.locator(".tile").first.locator("a", has_text="用問的").get_attribute("href").startswith("/?q="), "指標卡連到報表與問答")
    page.wait_for_timeout(400)
    check(page.locator(".chart-card .chart").count() == 1 and page.evaluate("window.__xss") is None and page.locator(".tile img").count() == 0,
          "儀表板圖表與 XSS 防護")
    page.close()
    page = page_for("dashboard.html", {"**/api/dashboard": json_route({"detail": "x"}, 500)})
    page.goto(BASE + "dashboard")
    page.wait_for_selector(".error")
    check("載入失敗" in page.locator(".error").inner_text(), "儀表板失敗提示")
    page.close()

    CAT = {"groups": [{"name": "應收帳款", "reports": [
        {"id": "ar_invoices", "title": "客戶逾期發票明細", "description": "某一個客戶的逾期發票", "example": "台陽科技有哪些發票逾期",
         "columns": ["發票號碼", "未收金額"], "params": [
            {"name": "customer", "label": "客戶", "kind": "entity", "required": True, "default": None, "min": None, "max": None,
             "options": [{"value": "台陽科技", "label": "台陽科技"}]},
            {"name": "overdue_gt", "label": "逾期超過天數", "kind": "enum", "required": False, "default": 0, "min": 0, "max": 3650,
             "options": [{"value": 0, "label": "已逾期"}, {"value": 60, "label": "逾期超過 60 天"}]}]},
        {"id": "ar_aging", "title": evil, "description": evil, "example": "應收帳款的帳齡分佈", "columns": [], "params": []}]}]}
    runs = []

    def run_handler(route):
        body = json.loads(route.request.post_data or "{}")
        runs.append(body)
        if not body["params"].get("customer") and body["template_id"] == "ar_invoices":
            return route.fulfill(status=400, content_type="application/json", body=json.dumps({"detail": "請問要查哪個客戶？"}))
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "template_id": body["template_id"], "template_title": "客戶逾期發票明細", "params_readable": ["客戶：台陽科技", "逾期超過 60 天"],
            "notes": [], "answer": "共 1 張，未收合計 100 元。", "columns": ["發票號碼", "未收金額"], "rows": [["INV-1", 100]], "row_count": 1,
            "sql": "SELECT 1", "binds": {"customer": "台陽科技"}, "latency_ms": 30, "followups": ["依合約，台陽科技逾期多久我們可以暫停出貨？"]}))

    page = page_for("reports.html", {"**/api/reports/catalog": json_route(CAT), "**/api/reports/run": run_handler}, width=1300)
    page.goto(BASE + "reports")
    page.wait_for_selector("#menu button")
    check(page.locator("#menu h3").inner_text() == "應收帳款" and page.locator("#menu button").count() == 2, "報表選單分組")
    check(page.evaluate("window.__xss") is None and page.locator("#menu img").count() == 0, "報表名稱的惡意 HTML 不會被執行")
    page.locator("#menu button", has_text="客戶逾期發票明細").click()
    check(page.locator("#f_customer").get_attribute("list") == "f_customer_list" and page.locator("#f_overdue_gt option").count() == 2, "條件表單：名稱可輸入篩選、下拉選項")
    page.click("#form button[type=submit]")
    page.wait_for_selector("#result .error")
    check("哪個客戶" in page.locator("#result .error").inner_text(), "必填沒填時顯示後端訊息")
    page.fill("#f_customer", "台陽科技")
    page.select_option("#f_overdue_gt", label="逾期超過 60 天")
    page.click("#form button[type=submit]")
    page.wait_for_selector(".summary")
    check(runs[-1]["params"] == {"customer": "台陽科技", "overdue_gt": 60} and runs[-1]["template_id"] == "ar_invoices", "送出的參數型別正確（數字不是字串）")
    check("t=ar_invoices" in page.url and "%E5%8F%B0%E9%99%BD" in page.url, "網址記住報表與條件（可加書籤）")
    check(page.locator("#result table tbody tr").count() == 1 and page.locator("#result .tag").count() == 2, "結果表格與條件標籤")
    check(page.locator("#result .next a").get_attribute("href").startswith("/?q=") and page.locator("#result details summary").inner_text() == "查詢的 SQL",
          "接著問連到問答、可展開 SQL")
    page.close()
    url = BASE + "reports?" + urlencode({"t": "ar_invoices", "p": json.dumps({"customer": "台陽科技", "overdue_gt": 60})})
    page = page_for("reports.html", {"**/api/reports/catalog": json_route(CAT), "**/api/reports/run": run_handler}, width=1300)
    n = len(runs)
    page.goto(url)
    page.wait_for_selector(".summary")
    check(len(runs) == n + 1 and page.locator("#f_customer").input_value() == "台陽科技" and page.locator("#f_overdue_gt").input_value() == "60",
          "從連結開啟：帶入條件並自動查詢")
    page.close()

    page = page_for("about.html", {"**/health": json_route({"postgres": True, "qdrant": False, "lmstudio": True, "lmstudio_loaded": [evil]}),
                                   "**/api/reports/catalog": json_route(CAT), "**/api/docs": json_route({"groups": [{"name": "合約", "items": [evil]}], "total": 1})})
    page.goto(BASE + "about")
    page.wait_for_selector("#reports li")
    page.wait_for_selector(".pill.bad")
    check(page.locator(".pill").count() == 3 and "文件索引未連線" in page.locator(".pill.bad").inner_text(), "系統介紹：即時狀態")
    check(page.locator("#reports li").count() == 2 and page.locator("#docs li").count() == 1, "系統介紹：報表與文件清單")
    check(page.evaluate("window.__xss") is None and page.locator(".page img").count() == 0, "系統介紹的動態內容不會執行 HTML")
    page.close()

    # 問答頁：從其他頁「用問的」過來（/?q=）會自動送出並清掉網址參數
    page = browser.new_page(viewport={"width": 1300, "height": 900})
    page.route(BASE + "*", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=HTML))
    page.route("http://app.test/static/**", lambda r: r.fulfill(path=str(WEB / r.request.url.split("/static/")[1])))
    qreqs = mock(page, TPL)
    page.goto(BASE + "?" + urlencode({"q": "台陽科技有哪些發票逾期"}))
    page.wait_for_selector(".card.answer")
    check(qreqs and qreqs[0]["question"] == "台陽科技有哪些發票逾期" and "?q=" not in page.url, "問答頁 ?q= 自動提問")
    page.close()

    browser.close()

print(f"前端檢查全部通過（{len(passed)} 項）")
for n in passed:
    print("  ✓", n)
