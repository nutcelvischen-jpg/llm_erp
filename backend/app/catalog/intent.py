"""T14d 意圖辨識：問題 → 既定程式（模板）＋參數。

1. 候選：問題與各模板 examples 的 embedding 最大餘弦相似度，取前 5；最高分 < INTENT_MIN_SIM 直接判未命中（不呼叫 LLM）。
2. LLM（溫度 0、關閉思考）回報 status：
   match（某個候選完整回答問題）／unsure（只有部分相符或有多種解讀 → 列出最多 3 個替代方案）／unsupported（資料庫沒有這類資料）。
   期間只輸出代碼、名稱照使用者原話，日期與名稱比對一律由程式處理。
3. 程式驗證參數（normalize_params）：enum 同義詞、int 夾值、period 語法、entity 比對、丟棄未知參數。
4. 結果：template（直接執行）／clarify（反問）／confirm（列出最接近的既定程式讓使用者選）／no_match（婉拒）。
   confirm 與 no_match 都寫入 app.unmatched_questions。
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import numpy as np

from .base import ParamSpec, QueryTemplate
from .entities import KIND_LABELS, EntityIndex, default_index
from .periods import COMPARE_KINDS, resolve_period
from .registry import TEMPLATES

log = logging.getLogger(__name__)

INTENT_MIN_SIM = 0.35
TOP_CANDIDATES = 5
MAX_PROPOSALS = 3

ENUM_DISPLAY = {"desc": "由高到低", "asc": "由低到高", "time": "依時間", **COMPARE_KINDS}


@dataclass
class Proposal:
    """confirm 模式下給使用者選的一個既定程式。"""
    template_id: str
    title: str
    description: str
    params: dict
    params_readable: list[str]
    columns: list[str]
    notes: list[str] = field(default_factory=list)   # 例如「指標不支援「毛利率」，改用預設「營收」」


@dataclass
class Intent:
    kind: Literal["template", "clarify", "confirm", "no_match"]
    template_id: str | None = None
    params: dict = field(default_factory=dict)
    params_readable: list[str] = field(default_factory=list)
    message: str = ""
    options: list[str] = field(default_factory=list)          # clarify：可點選的答案
    candidates: list[dict] = field(default_factory=list)      # [{template_id, title, score}]
    proposals: list[Proposal] = field(default_factory=list)   # confirm：最接近的既定程式
    notes: list[str] = field(default_factory=list)            # 例如「已將『華發』視為『華發實業』」


# ---------- 參數驗證 ----------
@dataclass
class Normalized:
    params: dict
    readable: list[str]
    notes: list[str] = field(default_factory=list)
    clarify: str | None = None
    options: list[str] = field(default_factory=list)
    degraded: bool = False   # 使用者要求的值不支援、改用了預設 → 不可直接執行，要讓使用者確認


def _enum_value(spec: ParamSpec, raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().casefold()
    for std, syns in (spec.choices or {}).items():
        if s == std.casefold() or s in (x.casefold() for x in syns):
            return std
    return None


def _int_value(spec: ParamSpec, raw: Any) -> int | None:
    try:
        v = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    if spec.min is not None:
        v = max(spec.min, v)
    if spec.max is not None:
        v = min(spec.max, v)
    return v


def readable(t: QueryTemplate, params: dict, today: date) -> list[str]:
    out = []
    for s in t.params:
        v = params.get(s.name)
        if v is None:
            continue
        if s.kind == "period":
            out.append(f"{s.label}：{resolve_period(v, today).label}")
        elif s.kind == "enum":
            out.append(f"{s.label}：{ENUM_DISPLAY.get(v, v)}")
        else:
            out.append(f"{s.label}：{v:,}" if isinstance(v, int) else f"{s.label}：{v}")
    return out


def normalize_params(t: QueryTemplate, raw: dict | None, today: date, entities: EntityIndex) -> Normalized:
    raw = raw if isinstance(raw, dict) else {}
    params: dict[str, Any] = {}
    notes: list[str] = []
    degraded = False
    for s in t.params:
        v = raw.get(s.name)
        if v in ("", "null", "None"):
            v = None
        if s.kind == "enum":
            val = _enum_value(s, v)
            if val is None and v is not None:
                notes.append(f"{s.label}不支援「{v}」，改用「{ENUM_DISPLAY.get(s.default, s.default)}」")
                degraded = True
            params[s.name] = val if val is not None else s.default
        elif s.kind == "int":
            val = _int_value(s, v) if v is not None else None
            params[s.name] = val if val is not None else s.default
        elif s.kind == "period":
            try:
                resolve_period(str(v), today)
                params[s.name] = str(v)
            except ValueError:
                if v is not None:
                    notes.append(f"期間「{v}」無法辨識，改用「{resolve_period(s.default, today).label}」")
                    degraded = True
                params[s.name] = s.default
        elif s.kind == "entity" and v is None:
            params[s.name] = None
        elif s.kind == "entity":
            m = entities.match(s.entity, str(v))
            label = KIND_LABELS[s.entity]
            if m.status in ("exact", "fuzzy"):
                params[s.name] = m.value
                if m.status == "fuzzy":
                    notes.append(f"已將「{v}」視為「{m.value}」")
            elif m.status == "ambiguous":
                return Normalized({}, [], notes, f"「{v}」對應到多個{label}，請問是哪一個？", m.options)
            else:
                msg = f"找不到{label}「{v}」。"
                msg += "您是指以下其中一個嗎？" if m.options else "請確認名稱。"
                return Normalized({}, [], notes, msg, m.options)
        if s.required and params.get(s.name) is None:
            return Normalized({}, [], notes, f"請問要查哪個{s.label}？")
    params["_today"] = today
    return Normalized(params, readable(t, params, today), notes, degraded=degraded)


# ---------- 候選（embedding） ----------
class ExampleIndex:
    def __init__(self, embed: Callable[[list[str]], list[list[float]]], templates: dict[str, QueryTemplate]):
        self._embed, self._templates = embed, templates
        self._mat: np.ndarray | None = None
        self._owner: list[str] = []
        self._lock = threading.Lock()

    def _build(self):
        texts, owner = [], []
        for t in self._templates.values():
            for ex in t.examples:
                texts.append(ex)
                owner.append(t.id)
        m = np.asarray(self._embed(texts), dtype=np.float32)
        self._mat = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        self._owner = owner

    def top(self, question: str, k: int = TOP_CANDIDATES) -> list[tuple[str, float]]:
        if self._mat is None:
            with self._lock:
                if self._mat is None:
                    self._build()
        q = np.asarray(self._embed([question])[0], dtype=np.float32)
        sims = self._mat @ (q / (np.linalg.norm(q) + 1e-9))
        best: dict[str, float] = {}
        for tid, s in zip(self._owner, sims):
            best[tid] = max(best.get(tid, -1.0), float(s))
        return sorted(best.items(), key=lambda x: -x[1])[:k]


# ---------- LLM prompt ----------
PERIOD_CODES = ("this_month、last_month、this_quarter、last_quarter、this_year、last_year、ytd（今年累計）、"
                "last_n_days:N、last_n_months:N（含本月）、all（全部期間）、"
                "quarter:<this_year|last_year|YYYY>:<1-4>、month:<this_year|last_year|YYYY>:<1-12>")

INTENT_SYSTEM = """你是公司 ERP 的查詢路由器。公司只能用下列「既定查詢程式」回答數字問題，你的工作是判斷使用者的問題該用哪一個程式、要帶什麼參數。
今天是 {today}。

# 候選的既定查詢程式
{catalog}

# 期間代碼（period 參數只能填這些代碼，不要自己算日期）
{period_codes}

# 判斷規則
1. status = "match"：某一個程式「完整」回答了問題：結果欄位直接就是使用者要的數字，參數也都在標準值內。填 template_id 與 params。
   問的是程式沒有提供的計算（例如平均每筆、成長率排名、某指標不在標準值內），就不是 match。
2. status = "unsure"：沒有程式能完整回答，但有程式能回答其中一部分或相近的問題；或問題有多種解讀。
   在 alternatives 列出最多 3 個最接近的程式與參數（最相近的放前面）。
3. status = "unsupported"：問題與這些 ERP 數字無關（例如薪資、人事、天氣、競爭對手、合約條款或規章內容），
   或要求修改資料。template_id 為 null。
4. params 只填該程式列出的參數。enum 參數填標準值；客戶、供應商、料號、業務照使用者的原話填入（系統會比對）；
   使用者沒提到的參數不要填（系統會用預設值）。
5. 只輸出 JSON。
"""

INTENT_JSON_HINT = ('{"status": "match|unsure|unsupported", "template_id": "模板 id 或 null", "params": {}, '
                    '"alternatives": [{"template_id": "...", "params": {}}]}')


def _param_line(s: ParamSpec) -> str:
    if s.kind == "enum":
        spec = "標準值：" + "／".join(s.choices)
    elif s.kind == "int":
        spec = f"整數 {s.min}–{s.max}"
    elif s.kind == "period":
        spec = "期間代碼"
    else:
        spec = f"{KIND_LABELS[s.entity]}名稱（照原話）"
    flags = "必填" if s.required else f"預設 {s.default}" if s.default is not None else "選填"
    return f"    - {s.name}（{s.label}，{spec}，{flags}）"


def format_catalog(ids: list[str]) -> str:
    parts = []
    for tid in ids:
        t = TEMPLATES[tid]
        defaults = {s.name: s.default for s in t.params}
        try:
            cols = "、".join(t.columns(defaults))
        except (KeyError, TypeError):
            cols = ""
        lines = [f"- id: {t.id}｜{t.title}：{t.description}", f"  例句：{'；'.join(t.examples[:3])}"]
        if cols:
            lines.append(f"  結果欄位（預設參數）：{cols}")
        lines.append("  參數：" if t.params else "  參數：無")
        lines += [_param_line(s) for s in t.params]
        parts.append("\n".join(lines))
    return "\n".join(parts)


def build_messages(question: str, ids: list[str], today: date) -> list[dict]:
    system = INTENT_SYSTEM.format(today=today.isoformat(), catalog=format_catalog(ids), period_codes=PERIOD_CODES)
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


# ---------- 主流程 ----------
@dataclass
class Deps:
    embed: Callable | None = None
    chat_json: Callable | None = None
    entities: EntityIndex | None = None
    log_unmatched: Callable | None = None
    examples: ExampleIndex | None = None

    def __post_init__(self):
        if self.embed is None:
            from .. import llm
            self.embed = llm.embed
        if self.chat_json is None:
            from .. import llm
            self.chat_json = lambda m: llm.chat_json(m, INTENT_JSON_HINT, max_tokens=600)
        self.entities = self.entities or default_index()
        self.log_unmatched = self.log_unmatched or log_unmatched
        self.examples = self.examples or _default_examples(self.embed)


_examples: ExampleIndex | None = None


def _default_examples(embed) -> ExampleIndex:
    global _examples
    if _examples is None:
        _examples = ExampleIndex(embed, TEMPLATES)
    return _examples


def log_unmatched(question: str, kind: str, candidates: list[dict]) -> None:
    try:
        from sqlalchemy import text

        from ..db import engine
        with engine.begin() as c:
            c.execute(text("INSERT INTO app.unmatched_questions (question, kind, candidates) "
                           "VALUES (:q, :k, CAST(:c AS jsonb))"),
                      {"q": question, "k": kind, "c": json.dumps(candidates, ensure_ascii=False)})
    except Exception as e:  # noqa: BLE001 — 紀錄失敗不能影響回答
        log.error("寫入 unmatched_questions 失敗：%s", str(e)[:200])


def _proposal(tid: str, raw: dict | None, today: date, entities: EntityIndex) -> Proposal | None:
    t = TEMPLATES.get(tid)
    if t is None:
        return None
    n = normalize_params(t, raw, today, entities)
    if n.clarify:  # 需要反問的方案不適合直接讓使用者按「執行」
        return None
    return Proposal(t.id, t.title, t.description, n.params, n.readable, t.columns(n.params), n.notes)


NO_MATCH_MSG = "這類問題目前沒有對應的既定查詢，已記錄下來，之後會評估新增。"
CONFIRM_MSG = "找不到完全符合的既定查詢。您是要查下列其中一個嗎？點選後才會執行。"


def recognize(question: str, today: date | None = None, deps: Deps | None = None) -> Intent:
    today = today or date.today()
    deps = deps or Deps()
    try:
        top = deps.examples.top(question)
    except Exception as e:  # noqa: BLE001
        log.warning("意圖候選計算失敗：%s", e)
        return Intent("no_match", message="AI 暫時無法使用，請稍後再試。")
    candidates = [{"template_id": tid, "title": TEMPLATES[tid].title, "score": round(s, 3)} for tid, s in top]
    if not top or top[0][1] < INTENT_MIN_SIM:
        deps.log_unmatched(question, "no_match", candidates)
        return Intent("no_match", message=NO_MATCH_MSG, candidates=candidates)

    ids = [tid for tid, _ in top]
    try:
        out = deps.chat_json(build_messages(question, ids, today))
    except Exception as e:  # noqa: BLE001
        log.warning("意圖辨識 LLM 失敗：%s", e)
        return Intent("no_match", message="AI 暫時無法使用，請稍後再試。", candidates=candidates)

    status = str(out.get("status") or "").lower()
    tid = out.get("template_id")
    if status == "unsupported" or (status not in ("match", "unsure") and not tid):
        deps.log_unmatched(question, "no_match", candidates)
        return Intent("no_match", message=NO_MATCH_MSG, candidates=candidates)

    if status == "match" and tid in ids:
        t = TEMPLATES[tid]
        n = normalize_params(t, out.get("params"), today, deps.entities)
        if n.clarify:
            return Intent("clarify", tid, message=n.clarify, options=n.options, candidates=candidates, notes=n.notes)
        if not n.degraded:
            return Intent("template", tid, n.params, n.readable, candidates=candidates, notes=n.notes)
        # 要求的參數值不支援：不直接執行，改列出來讓使用者確認（附上改用了什麼）

    # unsure，或 LLM 選了不在候選內的模板 → 列出最接近的既定程式讓使用者確認
    alts = out.get("alternatives") if isinstance(out.get("alternatives"), list) else []
    raw_props = ([{"template_id": tid, "params": out.get("params")}] if tid in ids else []) + alts
    proposals, seen = [], set()
    for a in raw_props:
        if not isinstance(a, dict):
            continue
        aid = a.get("template_id")
        if aid in ids and aid not in seen:
            p = _proposal(aid, a.get("params"), today, deps.entities)
            if p:
                proposals.append(p)
                seen.add(aid)
        if len(proposals) == MAX_PROPOSALS:
            break
    if not proposals:
        deps.log_unmatched(question, "no_match", candidates)
        return Intent("no_match", message=NO_MATCH_MSG, candidates=candidates)
    deps.log_unmatched(question, "confirm", [{"template_id": p.template_id, "params": p.params_readable}
                                             for p in proposals])
    return Intent("confirm", message=CONFIRM_MSG, candidates=candidates, proposals=proposals)


def confirm(template_id: str, raw_params: dict, today: date | None = None,
            entities: EntityIndex | None = None) -> Intent:
    """使用者在 confirm 畫面點選後：後端重新驗證模板與參數（不信任前端），回傳可執行的 Intent。"""
    today = today or date.today()
    t = TEMPLATES.get(template_id)
    if t is None:
        return Intent("no_match", message="這個查詢不存在。")
    n = normalize_params(t, raw_params, today, entities or default_index())
    if n.clarify:
        return Intent("clarify", template_id, message=n.clarify, options=n.options, notes=n.notes)
    return Intent("template", template_id, n.params, n.readable, notes=n.notes)
