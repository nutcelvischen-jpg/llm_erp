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


def fresh(browser):
    page = browser.new_page(viewport={"width": 1100, "height": 800})
    page.route(BASE, lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=HTML))
    page.goto(BASE)
    return page


def shot(page, name):
    if SHOTS:
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
    check(page.locator("img").count() == 0 and page.locator("script").count() == 1, "沒有被注入的 img/script 元素")
    check(evil in page.locator(".explain").inner_text(), "說明文字原樣顯示為文字")
    check(evil in page.locator("th").first.inner_text(), "欄位名稱原樣顯示為文字")
    check("window.__xss=4" in page.locator(".msg-user").inner_text(), "使用者輸入原樣顯示為文字")
    page.close()

    browser.close()

print(f"前端檢查全部通過（{len(passed)} 項）")
for n in passed:
    print("  ✓", n)
