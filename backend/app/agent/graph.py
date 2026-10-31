"""Agent 主流程（純 Python，不用 LangGraph）。

route → sql / docs / both（兩支並行）/ chat → 組裝 Markdown → 稽核。
任何一支失敗都回「這部分查詢失敗：原因」，不丟例外。

sql 分支走「既定程式」（catalog.runner.answer_question，T14f）：LLM 只辨識模板與參數、看結果寫回覆，
要執行的 SQL 一律由程式寫死。沒有明確命中時列出最接近的既定程式讓使用者確認（confirm），AI 不寫 SQL。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from .. import audit, numcheck
from ..catalog.answer import numbers_supported
from . import prompts
from .router import Route

log = logging.getLogger(__name__)

TABLE_ROWS = 20
MERGE_TABLE_ROWS = 20


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
    # 既定程式（模板）相關
    mode: str | None = None              # template / clarify / confirm / no_match / error
    template_id: str | None = None
    template_title: str | None = None
    params_readable: list[str] = field(default_factory=list)
    binds: dict = field(default_factory=dict)
    answer_source: str | None = None     # llm / fixed
    options: list[str] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
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


def _default_sql(question: str, choice: dict | None = None, data_part_only: bool = False):
    from ..catalog import runner

    return runner.answer_question(question, choice=choice, data_part_only=data_part_only)


def _default_chat(messages: list[dict]):
    from .. import llm

    return llm.chat(messages, temperature=0.3, max_tokens=500)


# ---------- 各分支 ----------
@dataclass
class _Sql:
    """sql 分支的結果（包裝 CatalogAnswer）。ok = 有執行既定程式且成功。"""
    ok: bool = False
    applicable: bool = True     # False：clarify／confirm／no_match（不是故障）
    text: str = ""
    error: str | None = None
    cat: object = None          # CatalogAnswer

    def get(self, name, default=None):
        return getattr(self.cat, name, default) if self.cat is not None else default


@dataclass
class _Docs:
    ok: bool = False
    text: str = ""
    sources: list[dict] = field(default_factory=list)
    refused: bool = False
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


def run_sql(question: str, deps: Deps, choice: dict | None = None, data_part_only: bool = False) -> _Sql:
    try:
        if choice:
            a = deps.sql(question, choice)
        elif data_part_only:
            a = deps.sql(question, None, True)
        else:
            a = deps.sql(question)
    except Exception as e:
        log.exception("sql 分支失敗")
        return _Sql(error=f"數據查詢失敗：{e}")
    if a.mode == "template":
        return _Sql(True, True, a.answer, None, a)
    if a.mode == "error":
        return _Sql(False, True, "", a.error or "查詢失敗", a)
    return _Sql(False, False, a.answer, None, a)   # clarify / confirm / no_match


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
    """每列寫成「欄位=值」，避免模型把相鄰欄位的數字對錯（例如把缺口當成建議採購量）。"""
    return "\n".join(f"第 {i} 列：" + "；".join(f"{c}={'-' if v is None else v}" for c, v in zip(columns, r))
                     for i, r in enumerate(rows[:n], 1))


def merge_both(question: str, s: _Sql, d: _Docs, deps: Deps) -> tuple[str, dict]:
    """兩支都有內容時由 LLM 寫綜合結論；數字檢查不過或失敗時退回固定組合。"""
    fixed = "\n\n".join(x for x in (s.text if s and s.ok else "", d.text if d and d.ok else "") if x)
    tokens = {"prompt": 0, "completion": 0}
    if not (s and s.ok and d and d.ok and not d.refused):
        return fixed, tokens
    rows = s.get("rows", [])
    user = (f"問題：{question}\n\n# 查詢結果（{s.get('template_title')}；共 {len(rows)} 列，以下最多 "
            f"{MERGE_TABLE_ROWS} 列）\n{_table_text(s.get('columns', []), rows, MERGE_TABLE_ROWS)}\n\n"
            f"# 查詢結論\n{s.text}\n\n# 文件回答\n{d.text}")
    try:
        r = deps.chat([{"role": "system", "content": prompts.MERGE_SYSTEM}, {"role": "user", "content": user}])
    except Exception as e:  # noqa: BLE001
        log.warning("綜合結論失敗，改用固定組合：%s", e)
        return fixed, tokens
    tokens = {"prompt": r.prompt_tokens, "completion": r.completion_tokens}
    text = r.text.strip()
    ok, bad = numbers_supported(text, rows, {}, [question, d.text, s.text, *s.get("params_readable", [])])
    if not ok or not text:
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
        tags = "｜".join(s.get("params_readable", []))
        parts.append(f"**數據**（標準查詢：{s.get('template_title')}{'｜' + tags if tags else ''}）\n\n"
                     + md_table(s.get("columns", []), s.get("rows", []), s.get("row_count", 0)))
        binds = "\n".join(f"-- :{k} = {v!r}" for k, v in s.get("binds", {}).items())
        parts.append(f"<details><summary>查詢的 SQL</summary>\n\n```sql\n{s.get('sql')}\n{binds}\n```\n</details>")
    elif s and s.get("mode") == "confirm":
        items = [f"{i}. **{p['title']}**：{'、'.join(p['params_readable']) or '無參數'}\n   結果欄位：{'、'.join(p['columns'])}"
                 for i, p in enumerate(s.get("proposals", []), 1)]
        parts.append("\n".join(items))
    elif s and s.get("mode") == "clarify" and s.get("options"):
        parts.append("可選：" + "、".join(s.get("options")))
    elif s and s.get("mode") == "no_match" and s.get("suggestions"):
        parts.append("可以這樣問：" + "、".join(s.get("suggestions")))
    if d and d.ok and d.sources:
        src = [f"{i}. {x['file_name']} 第 {x['page']} 頁" + (f" › {x['heading']}" if x["heading"] else "")
               for i, x in enumerate(d.sources, 1)]
        parts.append("**來源**\n\n" + "\n".join(src))
    return "\n\n".join(parts)


# ---------- 主流程 ----------
def run_agent(question: str, history: list[dict] | None = None, session_id: str | None = None,
              deps: Deps | None = None, choice: dict | None = None) -> AgentResult:
    """choice：使用者在「確認既定程式」畫面點選的 {template_id, params}；有值時不再路由，直接執行。"""
    deps = deps or Deps()
    t0 = time.perf_counter()
    question = question.strip()
    try:
        rt: Route = Route("sql", question, "choice") if choice else deps.route(question, history)
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
            # 路由有拆出數字／文件兩部分就各問各的；沒有就用整句（意圖辨識只看數字部分）
            if rt.sql_part:
                fs = ex.submit(run_sql, rt.sql_part, deps)
            else:
                fs = ex.submit(run_sql, q, deps, None, True)
            fd = ex.submit(run_docs, rt.docs_part or q, deps)
            s, d = fs.result(), fd.result()
    elif rt.kind == "sql":
        s = run_sql(q, deps, choice)
    elif rt.kind == "docs":
        d = run_docs(q, deps)

    if s and s.error:  # 只有真正的故障才算失敗；clarify／confirm／no_match 是正常的回覆
        failures.append(s.error)
    if d and not d.ok:
        failures.append(d.error or "未知錯誤")
    if d:
        tokens["prompt"] += d.prompt_tokens
        tokens["completion"] += d.completion_tokens

    if rt.kind == "both":
        answer, t = merge_both(q, s, d, deps)
        tokens = {k: tokens[k] + t[k] for k in tokens}
    elif rt.kind == "sql":
        answer = s.text  # template 的結論，或 clarify／confirm／no_match 的提示
    elif rt.kind == "docs":
        answer = d.text if d.ok else ""
    else:
        answer, t, err = run_chat(q, history, deps)
        tokens = t
        if err:
            failures.append(err)
    if route_err:
        failures.insert(0, f"問題分類失敗：{route_err}")

    cat = s.cat if s else None
    res = AgentResult(
        markdown=build_markdown(answer, s, d, failures), route=rt.kind, answer=answer, rewritten=q,
        sources=d.sources if d and d.ok else [], tokens=tokens, error="；".join(failures) or None,
    )
    if cat is not None and (rt.kind == "sql" or s.ok):
        res.mode, res.template_id, res.template_title = cat.mode, cat.template_id, cat.template_title
        res.params_readable, res.notes, res.answer_source = cat.params_readable, cat.notes, cat.answer_source
        res.options, res.proposals, res.suggestions = cat.options, cat.proposals, cat.suggestions
        if s.ok:
            res.sql, res.binds, res.columns, res.rows, res.row_count = (cat.sql, cat.binds, cat.columns, cat.rows,
                                                                       cat.row_count)
            res.attempts = 1
    res.latency_ms = int((time.perf_counter() - t0) * 1000)
    res.audit_id = deps.audit_write(audit.AuditRecord(
        question=question, session_id=session_id, route=rt.kind,
        sql_text=(f"{res.sql}\n-- template: {res.template_id}\n-- binds: {res.binds}" if res.sql else None),
        sql_ok=(s.ok if s and s.applicable else None), sql_rows=(res.row_count if s and s.ok else None),
        doc_sources=res.sources or None, answer=res.markdown, latency_ms=res.latency_ms,
        prompt_tokens=tokens["prompt"], completion_tokens=tokens["completion"], error=res.error,
    ))
    return res
