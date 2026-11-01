"use strict";
// 各頁共用：品牌設定、建立節點、數字格式、可排序表格、自動圖表、SQL 區塊、CSV、標題列導覽。
// 規則：使用者或模型的內容一律用 textContent，絕不使用 innerHTML。

// ---- 可客製的品牌設定：換公司名稱、色系，只要改這裡 ----
const BRAND = {
  name: "ERP 智慧助理",
  tagline: "用中文問 ERP 資料，全程在公司內網處理，資料不外流",
  color: "#0f4c81",
  palette: ["#0f4c81", "#2a9d8f", "#e9a23b", "#d1495b", "#7a5ea8", "#5b8def"],
};
const NAV = [["/", "儀表板", ["/", "/dashboard"]], ["/reports", "報表"], ["/chat", "問答"], ["/about", "系統介紹"]];   // [網址, 名稱, 也算這頁的路徑]

// 建立節點：文字一律用 textContent，絕不使用 innerHTML
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) node.append(c);
  return node;
}
const NO_SEPARATOR_COLUMNS = /^(年|年度|年份|季|月|月份)$/;

function fmt(v, col) {
  if (v === null || v === undefined) return "-";
  if (typeof v === "number") {
    if (NO_SEPARATOR_COLUMNS.test(col)) return String(v);
    return Number.isInteger(v) ? v.toLocaleString("zh-TW") : v.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
  }
  if (typeof v === "boolean") return v ? "是" : "否";
  return String(v);
}
const isNumericCol = (rows, i) => rows.some((r) => r[i] !== null) && rows.every((r) => r[i] === null || typeof r[i] === "number");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------- 表格（可點欄位標題排序）
function buildTable(columns, rows, limit, total) {
  const numCols = columns.map((_, i) => isNumericCol(rows, i));
  const sort = { col: -1, dir: 1 };
  const tbody = el("tbody");
  const arrows = [];
  const head = el("tr", {}, columns.map((c, i) => {
    const arrow = el("span", { class: "arrow", "aria-hidden": "true" });
    arrows.push(arrow);
    const btn = el("button", { type: "button", "aria-label": `依「${c}」排序` }, [document.createTextNode(c + " "), arrow]);
    btn.addEventListener("click", () => {
      if (sort.col === i) { if (sort.dir === 1) sort.dir = -1; else { sort.col = -1; sort.dir = 1; } } else { sort.col = i; sort.dir = 1; }
      draw();
    });
    return el("th", { class: numCols[i] ? "num" : "" }, btn);
  }));

  function draw() {
    let data = rows;
    if (sort.col >= 0) {
      const c = sort.col;
      data = [...rows].sort((a, b) => {
        const x = a[c], y = b[c];
        if (x === null || x === undefined) return (y === null || y === undefined) ? 0 : 1;   // 空值永遠排最後
        if (y === null || y === undefined) return -1;
        const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "zh-TW");
        return r * sort.dir;
      });
    }
    arrows.forEach((a, i) => { a.textContent = i === sort.col ? (sort.dir === 1 ? "▲" : "▼") : ""; });
    tbody.replaceChildren(...data.slice(0, limit).map((r) => el("tr", {}, r.map((v, i) => el("td", { class: numCols[i] ? "num" : "", text: fmt(v, columns[i]) })))));
  }
  draw();

  const frag = document.createDocumentFragment();
  frag.append(el("div", { class: "table-box" }, el("table", {}, [el("thead", {}, head), tbody])));
  const shown = Math.min(limit, rows.length);
  if (total > shown) frag.append(el("p", { class: "note", text: `僅顯示前 ${shown} 列，共 ${total} 列` }));
  return frag;
}

// ---------------------------------------------------------------- 自動圖表
const MAGNITUDE = (v) => (Math.abs(v) >= 1e8 ? `${+(v / 1e8).toFixed(2)}億` : Math.abs(v) >= 1e4 ? `${+(v / 1e4).toFixed(1)}萬` : String(v));

function chartSpec(columns, rows) {
  if (columns.length < 2 || rows.length < 2 || rows.length > 40) return null;
  const yq = /^年(度|份)?$/.test(columns[0]) && columns[1] === "季";     // 年 + 季 合併成「2025Q3」
  const start = yq ? 2 : 1;
  const numIdx = [];
  for (let i = start; i < columns.length; i++) { if (!isNumericCol(rows, i)) return null; numIdx.push(i); }
  if (numIdx.length < 1 || numIdx.length > 3) return null;
  if (!yq && isNumericCol(rows, 0) && !/(月|年|季|週)/.test(columns[0])) return null;   // 第一欄是一般數字（例如代碼）就不畫
  const labels = rows.map((r) => (yq ? `${r[0]}Q${r[1]}` : String(r[0] ?? "-")));
  const time = yq || /(月|日期|週|季|年)/.test(columns[0]) || labels.every((l) => /^\d{4}-\d{2}(-\d{2})?$/.test(l));
  const series = numIdx.map((i) => ({ name: columns[i], data: rows.map((r) => r[i]) }));
  const scale = series.map((s) => Math.max(0, ...s.data.map((v) => Math.abs(v ?? 0))));
  const axis = series.map((_, k) => (k > 0 && scale[0] > 0 && scale[k] > 0 && (scale[0] / scale[k] > 20 || scale[k] / scale[0] > 20) ? 1 : 0));
  const type = time ? "line" : rows.length > 8 ? "hbar" : "bar";
  if (type === "hbar") {   // 橫條圖只有一條數值軸，量級差太多的欄位不畫（表格裡仍看得到）
    const keep = series.map((_, k) => axis[k] === 0);
    return { labels, series: series.filter((_, k) => keep[k]), axis: axis.filter((_, k) => keep[k]), type };
  }
  return { labels, series, axis, type };
}

function drawChart(div, spec, palette = BRAND.palette) {   // 回傳 echarts 實例（呼叫端負責 dispose）
  if (!window.echarts || !div.isConnected) return null;
  const pal = palette;
  const horizontal = spec.type === "hbar";
  const nAxes = Math.max(...spec.axis) + 1;
  const valueAxis = (i) => ({ type: "value", axisLabel: { formatter: MAGNITUDE }, splitLine: { show: i === 0 } });
  const chart = window.echarts.init(div);
  chart.setOption({
    color: pal,
    grid: { left: 8, right: 16, top: spec.series.length > 1 ? 40 : 24, bottom: 8, containLabel: true },
    legend: spec.series.length > 1 ? { top: 0 } : undefined,
    tooltip: {
      trigger: "axis", axisPointer: { type: spec.type === "line" ? "line" : "shadow" },
      formatter: (ps) => `${esc(ps[0].axisValueLabel ?? ps[0].name)}<br/>` + ps.map((p) => `${p.marker}${esc(p.seriesName)}：<b>${esc(p.value === null || p.value === undefined ? "-" : Number(p.value).toLocaleString("zh-TW", { maximumFractionDigits: 2 }))}</b>`).join("<br/>"),
    },
    xAxis: horizontal ? valueAxis(0) : { type: "category", data: spec.labels, axisLabel: { interval: 0, rotate: spec.labels.length > 8 ? 30 : 0 } },
    yAxis: horizontal ? { type: "category", data: spec.labels, inverse: true } : (nAxes > 1 ? [valueAxis(0), valueAxis(1)] : valueAxis(0)),
    series: spec.series.map((s, k) => ({
      name: s.name, data: s.data, type: spec.type === "line" ? "line" : "bar", yAxisIndex: horizontal ? 0 : spec.axis[k],
      barMaxWidth: 34, symbolSize: 7, smooth: false,
    })),
  });
  return chart;
}

function sqlWithBinds(d) {   // SQL 只含 :name 參數；把綁定的值列在下方，方便核對
  const binds = Object.entries(d.binds || {}).map(([k, v]) => `-- :${k} = ${JSON.stringify(v)}`);
  return binds.length ? `${d.sql}\n${binds.join("\n")}` : d.sql;
}

function renderSql(sql, open) {
  const copy = el("button", { class: "copy", type: "button", "aria-label": "複製 SQL", text: "複製 SQL" });
  copy.addEventListener("click", async (e) => {
    e.stopPropagation();
    try { await navigator.clipboard.writeText(sql); copy.textContent = "已複製"; } catch { copy.textContent = "請手動複製"; }
    setTimeout(() => { copy.textContent = "複製 SQL"; }, 1500);
  });
  const d = el("details", {}, [el("summary", { text: "查詢的 SQL" }), el("div", { class: "sql-box" }, [el("pre", { text: sql }), copy])]);
  if (open) d.setAttribute("open", "");
  d.addEventListener("click", (e) => e.stopPropagation());
  return d;
}

// ---------------------------------------------------------------- 匯出：CSV（Excel 可直接開）與複製
function csvText(columns, rows) {
  const cell = (v) => { const t = v === null || v === undefined ? "" : String(v); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  return [columns, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
}
function downloadCsv(d, title) {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const name = `${(title || "查詢結果").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40)}_${stamp}.csv`;
  const url = URL.createObjectURL(new Blob(["\ufeff" + csvText(d.columns, d.rows)], { type: "text/csv;charset=utf-8" }));
  const a = el("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function csvButton(d, title, cls) {
  const b = el("button", { class: cls, type: "button", text: "下載 CSV", "aria-label": "下載表格為 CSV" });
  b.addEventListener("click", (ev) => { ev.stopPropagation(); downloadCsv(d, title); });
  return b;
}


// ---------------------------------------------------------------- 標題列：品牌與導覽
function applyBrand() {
  document.documentElement.style.setProperty("--brand", BRAND.color);
  const n = document.getElementById("brandName"), t = document.getElementById("brandTag");
  if (n) n.textContent = BRAND.name;
  if (t) t.textContent = BRAND.tagline;
  const nav = document.getElementById("topnav");
  if (nav) nav.replaceChildren(...NAV.map(([href, label, paths = [href]]) => el("a", { href, text: label, ...(paths.includes(location.pathname) ? { "aria-current": "page" } : {}) })));
}
const fmtMoney = (v) => (v === null || v === undefined ? "-" : `${Math.round(v).toLocaleString("zh-TW")}`);
const reportUrl = (templateId, params = {}) => `/reports?${new URLSearchParams({ t: templateId, p: JSON.stringify(params) })}`;
const askUrl = (question) => `/chat?${new URLSearchParams({ q: question })}`;
const qs = (obj) => new URLSearchParams(Object.entries(obj).filter(([, v]) => v !== null && v !== undefined && v !== "")).toString();
