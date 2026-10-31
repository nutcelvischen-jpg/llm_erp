-- T14d：沒有明確對應到既定查詢程式的問題，記錄下來供日後做成新模板
CREATE TABLE IF NOT EXISTS app.unmatched_questions (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  question    TEXT NOT NULL,
  kind        VARCHAR(20),              -- no_match / confirm（列出候選讓使用者確認）
  candidates  JSONB
);
