# 開發進度

| 任務 | 狀態 | 日期 | 備註 |
|---|---|---|---|
| T01 建立 repo 骨架 | ✅ 完成 | 2026-10-30 | 見下方 |

## T01 建立 repo 骨架
**驗收指令**：`make setup && uv run python -c "import fastapi, sqlglot, qdrant_client, docling; print('ok')"`
**輸出**：`ok`（`make test` 無測試，正常）

**與 TASKS.md 的差異（兩處最小修正，版本與依賴未動）**
1. `pyproject.toml` 加 `[tool.setuptools.packages.find] include = ["backend*"]`：根目錄有 backend/data/sql/scripts/docs 多個頂層資料夾，setuptools 自動探索會失敗。
2. `Makefile` 的 `uv venv` 加 `--allow-existing`：讓 `make setup` 可重複執行。

**環境註記**：此任務在雲端容器（Python 3.12、uv 0.11）驗收；使用者 Mac 的 shell 當時連不上，需在 Mac 上再跑一次 `make setup` 確認（`uv.lock` 已附）。

**Mac 驗收（2026-10-30）**：`make setup` 成功，import 檢查輸出 `ok`。
