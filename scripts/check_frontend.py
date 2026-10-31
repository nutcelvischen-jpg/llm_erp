"""前端檢查：用 Playwright 開 backend/app/web/index.html，攔截 /api/chat 回傳假資料，驗證行為與安全性。

用法：python3 scripts/check_frontend.py [截圖資料夾]
（Playwright 不是專案依賴；需要時自行安裝：pip install playwright && playwright install chromium）
頁面以假網址 http://app.test/ 提供，不需要啟動後端。
"""
import json
import sys
from pathlib import Path

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

    browser.close()

print(f"前端檢查全部通過（{len(passed)} 項）")
for n in passed:
    print("  ✓", n)
