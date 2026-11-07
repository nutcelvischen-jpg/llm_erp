#!/bin/bash
# 雙擊即可：啟動服務 → 暖機 → 錄系統操作畫面 → 收尾。錄好的檔案在 data/video/clips/
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
BASE=http://localhost:8000
echo "▶ 1/5 啟動 Postgres、Qdrant、模型常駐"
make up && make llm-up || { echo "啟動失敗，請把上面的訊息貼給 Claude"; read -p "按 Enter 關閉"; exit 1; }

STARTED=0
if curl -sf $BASE/health >/dev/null; then
  echo "▶ 2/5 伺服器已在執行，沿用"
else
  echo "▶ 2/5 啟動伺服器 (make dev)"
  nohup make dev > /tmp/erp_dev.log 2>&1 &
  STARTED=1
  for i in $(seq 1 60); do curl -sf $BASE/health >/dev/null && break; sleep 1; done
  curl -sf $BASE/health >/dev/null || { echo "伺服器沒起來，log：/tmp/erp_dev.log"; tail -20 /tmp/erp_dev.log; read -p "按 Enter 關閉"; exit 1; }
fi

echo "▶ 3/5 暖機（載入 reranker，約 10–20 秒）"
for q in "今年到目前為止毛利跟去年同期比怎樣？哪個客戶掉最多？" "鴻遠機械的合約，延遲交貨罰款怎麼算？" "哪些料號超過 180 天沒動？壓了多少錢？"; do
  curl -s -m 120 -X POST $BASE/api/chat -H 'Content-Type: application/json' -d "{\"question\": \"$q\"}" >/dev/null
done

echo "▶ 4/5 錄影（約 2–3 分鐘，過程中請不要操作瀏覽器）"
uv run --with playwright python scripts/record_video_clips.py
RC=$?

echo "▶ 5/5 收尾"
if [ $STARTED = 1 ]; then pkill -f "uvicorn.*8000" 2>/dev/null; fi
open data/video/clips 2>/dev/null
[ $RC = 0 ] && echo "✅ 完成，檔案在 data/video/clips/，回 Claude 說一聲" || echo "❌ 錄影出錯（上面有訊息），請貼給 Claude"
read -p "按 Enter 關閉視窗"
