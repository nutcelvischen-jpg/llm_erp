CREATE SCHEMA IF NOT EXISTS app;
SET search_path TO app;

CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  session_id  VARCHAR(64),
  user_id     VARCHAR(64) DEFAULT 'demo',
  route       VARCHAR(20),            -- sql/docs/both/chat
  question    TEXT NOT NULL,
  sql_text    TEXT,
  sql_ok      BOOLEAN,
  sql_rows    INT,
  doc_sources JSONB,
  answer      TEXT,
  latency_ms  INT,
  prompt_tokens INT,
  completion_tokens INT,
  error       TEXT
);

CREATE TABLE sql_examples (            -- Text-to-SQL few-shot
  id          SERIAL PRIMARY KEY,
  question    TEXT NOT NULL,
  sql_text    TEXT NOT NULL,
  tags        TEXT[],
  embedding   REAL[]                   -- 1024 維，PoC 用陣列即可
);

CREATE TABLE notifications (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  job_name    VARCHAR(50),
  channel     VARCHAR(20),             -- line/console
  payload     TEXT,
  sent        BOOLEAN DEFAULT FALSE
);

CREATE TABLE feedback (
  id          BIGSERIAL PRIMARY KEY,
  audit_id    BIGINT REFERENCES audit_log(id),
  score       SMALLINT,                -- 1 讚 / -1 倒讚
  comment     TEXT,
  ts          TIMESTAMPTZ DEFAULT now()
);
