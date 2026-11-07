# Demo 影片說明

- `llm_erp_demo_narrated.mp4`：**完整版**，約 134 秒、1440×900，含旁白（台灣女聲，Gemini TTS）與燒入字幕。
- `llm_erp_demo.srt`：同一份字幕的獨立檔（可另行匯入剪輯軟體）。
- `llm_erp_demo.mp4`：無旁白、無字幕的原始畫面。

畫面由 `scripts/record_demo_auto.py` 自動操作瀏覽器錄製；旁白與字幕由 `scripts/make_demo_video.py` 合成
（AI 思考的等待時間已壓縮，結果畫面會停住等旁白講完）。
全程在地端執行（LM Studio + PostgreSQL + Qdrant），資料不外流；畫面中的數字都由公司既定的查詢程式
在唯讀資料庫查得，AI 只負責理解問題與用白話說明結果。

## 影片內容

| 段落 | 提問 | 重點 | 截圖 |
|---|---|---|---|
| 儀表板 | （首頁） | 指標卡與圖表，不經 AI，直接讀資料庫 | `01_dashboard.png` |
| 毛利同期比較 | 今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？ | 全公司毛利較去年同期少 6.0%，掉最多的是鴻遠機械（-836,777 元）；展開「查詢的 SQL」可稽核 | `02_margin_drop.png` |
| 營收趨勢 | 鴻遠機械最近 12 個月每個月的營收 | 自動畫折線圖，2026 年 6 月起營收明顯下滑 | `03_revenue_trend.png` |
| ERP + 合約 | 鴻遠機械今年營收多少？依鴻遠機械的合約，今年拿得到折讓嗎？ | 數字來自 ERP，條件來自合約 PDF：今年營收 10,192,507 元，未達合約門檻 2,000 萬，拿不到折讓；附《銷售合約_鴻遠機械.pdf》第 3 頁來源 | `04_contract_merging.png` |
| 呆滯庫存 | 哪些料號超過 180 天沒動？壓了多少錢？ | 12 個料號、庫存金額合計 2,902,034 元；展開 SQL | `05_dead_stock.png` |
| 缺料預警 | 依目前待出貨訂單，哪些料號會缺料？建議採購多少？ | 3 個料號缺料（含 GEAR-M2-40T），附建議採購量 | `06_shortage_alert.png` |
| 應收帳齡 | 應收帳款的帳齡分佈 | 長條圖與表格；逾期 61 天以上共 584,374 元 | `07_ar_aging.png` |

## 三個要講的重點

1. **AI 不寫 SQL**：每題都標示「標準查詢：○○」與參數標籤，SQL 由程式寫死並經守門員檢查；沒命中時會反問或請使用者確認，不會亂猜。
2. **數字可稽核**：回答中的數字都能在結果表與展開的 SQL 中找到。
3. **文件問答附出處**：合約、SOP 的回答附檔名與頁碼，可回看 PDF 原頁。

## 重新錄製與合成

```bash
make up && make llm-up && make dev      # /health 須回 "ok": true
uv run --with playwright python scripts/record_demo_auto.py          # 錄畫面 + timeline.json
uv run --with pillow python scripts/make_demo_video.py --key-file <OpenRouter 金鑰檔>   # 旁白 + 字幕 + 合成
```

- 旁白文字寫在 `make_demo_video.py` 的 `NARRATION`；旁白裡的數字取自畫面，資料或日期變動後要同步修改。
- 聲音可用 `--voice` 更換（女聲如 Kore、Sulafat、Zephyr、Leda），預設 Kore。語音逐句快取在 `_work/`，改文字只會重新產生有變動的句子。
- 金鑰只在執行時讀取（或用環境變數 `OPENROUTER_API_KEY`），不會寫進程式碼或影片。
- 需要 `ffmpeg`（`brew install ffmpeg`）。

資料是示範用假資料，每題的數字會隨「今天」的日期略有不同。
