"""T23 Agent 主流程（純 Python，不用 LangGraph）。

route → sql / docs / both（兩支並行）/ chat → 組裝 Markdown → 稽核。
任何一支失敗都回「這部分查詢失敗：原因」，不丟例外。

sql 分支目前接 text2sql.run（AI 產生 SQL，必經 sql_guard、唯讀角色執行），回答一律標示
「AI 即時產生」。T14b–T14f 的模板查詢完成後，只需替換 _default_sql。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from .. import audit, numcheck
from . import prompts
from .router import Route

log = logging.getLogger(__name__)

AI_SQL_WARNING = "AI 即時產生的查詢，請查核 SQL 與結果"
TABLE_ROWS = 20
MERGE_TABLE_ROWS = 20
_NOT_APPLICABLE = "這個問題無法用目前的 ERP 資料回答"  # text2sql 婉拒（不是故障）


@dataclass
class AgentResult:
    markdown: str
    route: str
    answer: str = ""
    rewritten: str = ""
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    attempts: int = 0
    sources: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    tokens: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0})
    warning: str | None = None
    error: str | None = None
    audit_id: int | None = None


@dataclass
class Deps:
    """外部呼叫集中在這裡，測試時替換。"""
    route: Callable = None
    sql: Callable = None
    retrieve: Callable = None
    rag_answer: Callable = None
    chat: Callable = None
    audit_write: Callable = None

    def __post_init__(self):
        from ..rag import answer as rag_answer_mod
        from ..rag import retrieve as retrieve_mod
        from . import router

        self.route = self.route or router.route
        self.sql = self.sql or _default_sql
        self.retrieve = self.retrieve or retrieve_mod.retrieve
        self.rag_answer = self.rag_answer or rag_answer_mod.answer
        self.chat = self.chat or _default_chat
        self.audit_write = self.audit_write or audit.write


def _default_sql(question: str):
    from .. import text2sql

    return text2sql.run(question)


def _default_chat(messages: list[dict]):
    from .. import llm

    return llm.chat(messages, temperature=0.3, max_tokens=500)


# ---------- 各分支 ----------
@dataclass
class _Sql:
    ok: bool = False
    applicable: bool = True
    text: str = ""
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None
    attempts: int = 0


@dataclass
class _Docs:
    ok: bool = False
    text: str = ""
    sources: list[dict] = field(default_factory=list)
    refused: bool = False
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


def run_sql(question: str, deps: Deps) -> _Sql:
    try:
        a = deps.sql(question)
    except Exception as e:
        log.exception("sql 分支失敗")
        return _Sql(error=f"數據查詢失敗：{e}")
    if a.error:
        return _Sql(applicable=not a.error.startswith(_NOT_APPLICABLE), sql=a.sql, error=a.error,
                    attempts=a.attempts)
    expl = (a.explanation or "").strip()
    bad = numcheck.unsupported_numbers(expl, [question, a.sql], a.rows)
    if bad or not expl:
        if bad:
            log.warning("查詢說明含未獲支持的數字 %s，改用固定句型", bad)
        expl = f"查詢結果如下表（共 {a.row_count:,} 列）。"
    return _Sql(True, True, expl, a.sql, list(a.columns), list(a.rows), a.row_count, None, a.attempts)


def run_docs(question: str, deps: Deps) -> _Docs:
    try:
        hits = deps.retrieve(question)
    except Exception as e:
        log.exception("docs 分支檢索失敗")
        return _Docs(error=f"文件檢索失敗：{e}")
    r = deps.rag_answer(question, hits)
    if r.error:
        return _Docs(error=f"文件回答失敗：{r.error}")
    refused = "查無" in r.text and not r.sources
    return _Docs(True, r.text, [asdict(s) for s in r.sources], refused, None, r.prompt_tokens,
                 r.completion_tokens)


def run_chat(question: str, history: list[dict] | None, deps: Deps) -> tuple[str, dict, str | None]:
    msgs = [{"role": "system", "content": prompts.CHAT_SYSTEM}]
    msgs += [{"role": h["role"], "content": str(h["content"])[:500]} for h in (history or [])[-12:]
             if h.get("role") in ("user", "assistant") and h.get("content")]
    msgs.append({"role": "user", "content": question})
    try:
        r = deps.chat(msgs)
    except Exception as e:  # noqa: BLE001
        return "", {"prompt": 0, "completion": 0}, f"回覆失敗：{e}"
    text = r.text.strip()
    if numcheck.unsupported_numbers(text, [question]):  # 閒聊不得出現任何公司數字
        text = "我是公司的 ERP 智慧助理，可以查詢營收、應收、庫存、採購數字，以及合約、SOP、規格書與人資規章。"
    return text, {"prompt": r.prompt_tokens, "completion": r.completion_tokens}, None


def _table_text(columns: list[str], rows: list[list], n: int) -> str:
    lines = [" | ".join(columns)] + [" | ".join("" if c is None else str(c) for c in r) for r in rows[:n]]
    return "\n".join(lines)


def merge_both(question: str, s: _Sql, d: _Docs, deps: Deps) -> tuple[str, dict]:
    """兩支都有內容時由 LLM 寫綜合結論；數字檢查不過或失敗時退回固定組合。"""
    fixed = "\n\n".join(x for x in (s.text if s.ok else "", d.text if d.ok else "") if x)
    tokens = {"prompt": 0, "completion": 0}
    if not (s.ok and d.ok and not d.refused):
        return fixed, tokens
    user = (f"問題：{question}\n\n# 查詢結果（共 {s.row_count} 列，以下最多 {MERGE_TABLE_ROWS} 列）\n"
            f"{_table_text(s.columns, s.rows, MERGE_TABLE_ROWS)}\n\n# 文件回答\n{d.text}")
    try:
        r = deps.chat([{"role": "system", "content": prompts.MERGE_SYSTEM}, {"role": "user", "content": user}])
    except Exception as e:  # noqa: BLE001
        log.warning("綜合結論失敗，改用固定組合：%s", e)
        return fixed, tokens
    tokens = {"prompt": r.prompt_tokens, "completion": r.completion_tokens}
    text = r.text.strip()
    bad = numcheck.unsupported_numbers(text, [question, d.text], s.rows)
    if bad or not text:
        log.warning("綜合結論含未獲支持的數字 %s，改用固定組合", bad)
        return fixed, tokens
    return text, tokens


# ---------- Markdown ----------
def _cell(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v).replace("|", "\\|").replace("\n", " ")


def md_table(columns: list[str], rows: list[list], total: int) -> str:
    if not columns:
        return ""
    out = ["| " + " | ".join(_cell(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows[:TABLE_ROWS]]
    if total > TABLE_ROWS:
        out.append(f"\n僅顯示前 {TABLE_ROWS} 列，共 {total:,} 列")
    return "\n".join(out)


def build_markdown(answer: str, s: _Sql | None, d: _Docs | None, failures: list[str]) -> str:
    parts = [answer] if answer else []
    parts += [f"> 這部分查詢失敗：{f}" for f in failures]
    if s and s.ok:
        parts.append(f"**數據**（{AI_SQL_WARNING}）\n\n{md_table(s.columns, s.rows, s.row_count)}")
        parts.append(f"<details><summary>查詢的 SQL</summary>\n\n```sql\n{s.sql}\n```\n</details>")
    if d and d.ok and d.sources:
        src = [f"{i}. {x['file_name']} 第 {x['page']} 頁" + (f" › {x['heading']}" if x["heading"] else "")
               for i, x in enumerate(d.sources, 1)]
        parts.append("**來源**\n\n" + "\n".join(src))
    return "\n\n".join(parts)


# ---------- 主流程 ----------
def run_agent(question: str, history: list[dict] | None = None, session_id: str | None = None,
              deps: Deps | None = None) -> AgentResult:
    deps = deps or Deps()
    t0 = time.perf_counter()
    question = question.strip()
    try:
        rt: Route = deps.route(question, history)
    except Exception as e:
        log.exception("路由失敗")
        rt = Route("chat", question, "error")
        route_err = str(e)
    else:
        route_err = None
    q = rt.rewritten or question
    s: _Sql | None = None
    d: _Docs | None = None
    failures: list[str] = []
    tokens = {"prompt": 0, "completion": 0}
    answer = ""

    if rt.kind == "both":
        with ThreadPoolExecutor(max_workers=2) as ex:
            fs, fd = ex.submit(run_sql, q, deps), ex.submit(run_docs, q, deps)
            s, d = fs.result(), fd.result()
    elif rt.kind == "sql":
        s = run_sql(q, deps)
    elif rt.kind == "docs":
        d = run_docs(q, deps)

    if s and not s.ok and (s.applicable or rt.kind == "sql"):
        failures.append(s.error or "未知錯誤")
    if d and not d.ok:
        failures.append(d.error or "未知錯誤")
    if d:
        tokens["prompt"] += d.prompt_tokens
        tokens["completion"] += d.completion_tokens

    if rt.kind == "both":
        answer, t = merge_both(q, s, d, deps)
        tokens = {k: tokens[k] + t[k] for k in tokens}
    elif rt.kind == "sql":
        answer = s.text if s.ok else ""
    elif rt.kind == "docs":
        answer = d.text if d.ok else ""
    else:
        answer, t, err = run_chat(q, history, deps)
        tokens = t
        if err:
            failures.append(err)
    if route_err:
        failures.insert(0, f"問題分類失敗：{route_err}")

    res = AgentResult(
        markdown=build_markdown(answer, s, d, failures), route=rt.kind, answer=answer, rewritten=q,
        sql=s.sql if s else "", columns=s.columns if s and s.ok else [], rows=s.rows if s and s.ok else [],
        row_count=s.row_count if s and s.ok else 0, attempts=s.attempts if s else 0, sources=d.sources if d and d.ok else [],
        tokens=tokens, warning=AI_SQL_WARNING if s and s.ok else None,
        error="；".join(failures) or None,
    )
    res.latency_ms = int((time.perf_counter() - t0) * 1000)
    res.audit_id = deps.audit_write(audit.AuditRecord(
        question=question, session_id=session_id, route=rt.kind,
        sql_text=res.sql or None, sql_ok=(s.ok if s else None), sql_rows=(res.row_count if s else None),
        doc_sources=res.sources or None, answer=res.markdown, latency_ms=res.latency_ms,
        prompt_tokens=tokens["prompt"], completion_tokens=tokens["completion"], error=res.error,
    ))
    return res
