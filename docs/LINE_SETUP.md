# LINE 推播設定（選配）

每週一 08:00 的「呆滯庫存與缺料預警」除了寫進 `app.notifications`，也可以推播到 LINE。
沒有設定時系統會記錄 `LINE 未設定，跳過`，其他功能不受影響。

> **注意：資料會離開公司內網。** 推播內容（料號、金額、建議採購量）會經過 LINE 的伺服器。
> 若公司規定 ERP 數字不得外傳，請不要設定，或改用公司內部的通知管道。

## 1. 建立 Messaging API channel

1. 用公司 LINE 帳號登入 [LINE Developers Console](https://developers.line.biz/console/)。
2. 建立 Provider（例如「台中精密零件」）。
3. 依畫面指示建立 LINE 官方帳號，並在 LINE Official Account Manager 的「設定 › Messaging API」啟用 Messaging API，選擇剛才的 Provider。
4. 回到 Developers Console，Provider 下會出現這個 Messaging API channel。

## 2. 取得 Channel access token

Channel 頁面 › **Messaging API** 分頁 › 最下方 **Channel access token (long-lived)** › Issue，複製整串 token。

## 3. 取得推播對象 ID

- **推給自己（Demo 建議）**：Channel 頁面 › **Basic settings** 分頁 › **Your user ID**（`U` 開頭）。
  接著用手機掃 Messaging API 分頁的 QR code，把官方帳號**加為好友**，否則收不到。
- **推到群組**：把官方帳號邀進群組（需先在 Official Account Manager 允許「加入群組」），
  群組 ID（`C` 開頭）只能從 webhook 的 `join` 事件取得。本 PoC 沒有 webhook 伺服器，建議先推給個人。

## 4. 填進 `.env` 並測試

```env
LINE_CHANNEL_ACCESS_TOKEN=貼上 token
LINE_TARGET_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

```bash
uv run python -m backend.app.jobs.line_push --test        # 手機應收到「LINE 推播測試成功」
# 重啟 make dev 讓設定生效後，手動觸發一次預警：
curl -s -X POST localhost:8000/admin/jobs/dead_stock/run  # 回應 "line_sent": true，手機收到預警
```

設定後產生的通知 `channel` 為 `line`；推播成功才會把 `app.notifications.sent` 設為 `true`。
推播失敗（token 錯誤、未加好友、網路不通）只記錄 log，通知仍保留為 `sent = false`，可之後補送：

```bash
uv run python -m backend.app.jobs.line_push               # 推送所有尚未送出的 LINE 通知
```

## 常見問題

| 症狀 | 原因 | 處理 |
|---|---|---|
| log 顯示 `LINE 推播失敗 HTTP 401` | token 錯誤或已重新發行 | 重新複製 long-lived token |
| `HTTP 400`，訊息提到 `to` | 對象 ID 錯誤 | 確認是 Your user ID，不是 Channel ID |
| 回 200 但手機沒收到 | 沒有把官方帳號加為好友 | 掃 QR code 加好友 |
| `HTTP 429` | 超過免費方案的每月則數或頻率上限 | 在 Official Account Manager 確認方案 |
