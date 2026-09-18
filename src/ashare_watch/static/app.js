/* ==========================================================================
   A 股实时行情 · 前端
   --------------------------------------------------------------------------
   两个关键点：

   1. **红涨绿跌。** 颜色由 CSS 变量 --up / --down 定义，这里只负责给出
      "涨"还是"跌"的语义类名（change-up / change-down），配色交给 CSS。
      这样配色规则只存在于一个地方，不会出现某个组件忘了反过来。
   2. 同一份代码支持两种形态：本地服务（轮询 /api/dashboard）和单文件快照
      （数据通过 window.__SNAPSHOT__ 内联注入）。
   ========================================================================== */

const state = {
  snapshot: null,
  rankKey: "gainers",
  chartDays: 30,
  meta: {},
  secondsLeft: 0,
  standalone: false,
};

const $ = (id) => document.getElementById(id);
const esc = (t) =>
  String(t ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );

/* ------------------------------------------------------------- 格式化 */
const num = (value, digits = 2) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

const pct = (value) =>
  value === null || value === undefined
    ? "—"
    : `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;

const signed = (value, digits = 2) =>
  value === null || value === undefined
    ? "—"
    : `${value > 0 ? "+" : ""}${num(value, digits)}`;

function money(value) {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)} 万亿`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)} 亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)} 万`;
  return num(value, 0);
}

/** 成交量按「手」显示（1 手 = 100 股），这是 A 股的习惯口径。 */
function hands(value) {
  if (value === null || value === undefined) return "—";
  const h = value / 100;
  if (h >= 1e8) return `${(h / 1e8).toFixed(2)} 亿手`;
  if (h >= 1e4) return `${(h / 1e4).toFixed(1)} 万手`;
  return `${h.toLocaleString("en-US", { maximumFractionDigits: 0 })} 手`;
}

const dirClass = (d) => (d === "up" ? "change-up" : d === "down" ? "change-down" : "change-flat");

/* ------------------------------------------------------------- 迷你走势 */
function sparkline(closes, direction) {
  if (!closes || closes.length < 2) return "";
  const W = 100, H = 30, pad = 2;
  const min = Math.min(...closes), max = Math.max(...closes);
  const span = max - min || 1;
  const x = (i) => (W * i) / (closes.length - 1);
  const y = (v) => H - pad - ((v - min) / span) * (H - pad * 2);
  const line = closes.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
  const area = `${line} L${W},${H} L0,${H} Z`;
  // 注意：A 股是红涨绿跌，这里跟美股相反
  const stroke =
    direction === "up" ? "var(--up)" : direction === "down" ? "var(--down)" : "var(--flat)";
  const gid = `sp-${Math.random().toString(36).slice(2, 8)}`;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${stroke}" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="${stroke}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${stroke}" stroke-width="1.6"
          stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

/* ------------------------------------------------------------- 指数主卡 */
function renderIndexes(indexes) {
  const host = $("index-cards");
  if (!indexes.length) {
    host.innerHTML = '<section class="panel">未能获取指数数据。</section>';
    return;
  }
  host.innerHTML = indexes
    .map((q) => {
      const d = q.direction;
      const range =
        q.day_low !== null && q.day_high !== null
          ? `<span>日内 <b>${num(q.low)} – ${num(q.high)}</b></span>`
          : "";
      const prev = q.prev_close !== null ? `<span>昨收 <b>${num(q.prev_close)}</b></span>` : "";
      return `<section class="index-card ${d}">
        <div>
          <div class="index-name">${esc(q.name)}</div>
          <div class="index-symbol">${esc(q.sina || q.code)}</div>
        </div>
        <div class="index-value ${dirClass(d)}">${num(q.price)}</div>
        <div class="index-change">
          <span class="${dirClass(d)}">${signed(q.change)}</span>
          <span class="pct ${dirClass(d)}">${pct(q.change_pct)}</span>
        </div>
        <div class="index-spark">${sparkline(q.history, d)}</div>
        <div class="index-foot">${prev}${range}
          <span>更新 <b>${esc((q.timestamp || "").slice(11) || "—")}</b></span>
        </div>
      </section>`;
    })
    .join("");
}

/* ------------------------------------------------------------- 市场宽度 */
function renderBreadth(snapshot) {
  const b = snapshot.breadth || {};
  const up = b.advancers || 0, down = b.decliners || 0, flat = b.unchanged || 0;
  const total = b.total || up + down + flat || 1;

  $("breadth-bar").innerHTML = `
    <div class="seg up" style="flex-grow:${Math.max(up, 0.001)}">${up ? ((up / total) * 100).toFixed(0) + "%" : ""}</div>
    <div class="seg flat" style="flex-grow:${Math.max(flat, 0.001)}">${flat ? ((flat / total) * 100).toFixed(0) + "%" : ""}</div>
    <div class="seg down" style="flex-grow:${Math.max(down, 0.001)}">${down ? ((down / total) * 100).toFixed(0) + "%" : ""}</div>`;
  $("breadth-up").textContent = up.toLocaleString();
  $("breadth-flat").textContent = flat.toLocaleString();
  $("breadth-down").textContent = down.toLocaleString();
  $("breadth-total").textContent = `样本 ${total.toLocaleString()} 只`;

  const cov = snapshot.coverage || {};
  const ratio = total ? (up / total) * 100 : 0;
  const stats = [
    { k: "上涨占比", v: `${ratio.toFixed(1)}%`, cls: ratio >= 50 ? "change-up" : "change-down" },
    { k: "全市场覆盖", v: `${(cov.universe || 0).toLocaleString()} 只`, cls: "" },
    { k: "自选股", v: `${cov.watchlist || 0} 只`, cls: "" },
    { k: "采集耗时", v: `${((snapshot.generated_ms || 0) / 1000).toFixed(1)} s`, cls: "" },
  ];
  $("mini-stats").innerHTML = stats
    .map((s) => `<div class="mini-stat"><span class="k">${s.k}</span><span class="v ${s.cls}">${esc(s.v)}</span></div>`)
    .join("");
}

/* ------------------------------------------------------------- 涨跌停 */
function renderLimits(snapshot) {
  const l = snapshot.limits || {};
  const up = l["涨停家数"] || 0;
  const down = l["跌停家数"] || 0;
  const oneUp = l["一字涨停"] || 0;
  const oneDown = l["一字跌停"] || 0;
  const broken = l["炸板家数"] || 0;
  const total = (snapshot.breadth || {}).total || 0;

  $("limit-sample").textContent = total ? `样本 ${total.toLocaleString()} 只` : "—";
  const cells = [
    { k: "涨停家数", v: up, cls: "accent-up" },
    { k: "跌停家数", v: down, cls: "accent-down" },
    { k: "一字涨停", v: oneUp, cls: "accent-up" },
    { k: "一字跌停", v: oneDown, cls: "accent-down" },
    { k: "炸板家数", v: broken, cls: "" },
    { k: "涨跌停比", v: down ? (up / down).toFixed(2) : (up ? "∞" : "—"), cls: up >= down ? "accent-up" : "accent-down" },
  ];
  $("limit-grid").innerHTML = cells
    .map((c) => `<div class="limit-cell ${c.cls}"><span class="k">${c.k}</span><span class="v">${esc(c.v)}</span></div>`)
    .join("");
}

/* ------------------------------------------------------------- 走势图 */
/**
 * 画一条折线：网格 + 面积 + 悬停十字线。
 *
 * 指数的日线、个股的日线、个股的分时用的是同一套画法，所以做成一个函数，
 * 参数里换「取哪个值、横轴写什么」就够了：
 *   host      容器元素
 *   rows      数据行
 *   value     从一行里取出要画的数值
 *   label     从一行里取出横轴标签
 *   baseline  可选的基准线（分时图用昨收），同时决定红绿
 *
 * 参数名刻意不叫 valueOf / toString：那样会撞上 Object.prototype 上现成的
 * 方法，`opts.valueOf` 永远是真值，一调用就抛
 * "Cannot convert undefined or null to object"。这个坑踩过一次。
 */
let chartSeq = 0;

function drawLineChart(host, rows, opts = {}) {
  const valueOf = typeof opts.value === "function" ? opts.value : ((r) => r.close);
  const labelOf = typeof opts.label === "function" ? opts.label : ((r) => r.date || "");
  const fallbackHeight = opts.height || 260;
  const points = (rows || []).filter(
    (r) => valueOf(r) !== null && valueOf(r) !== undefined
  );
  if (points.length < 2) {
    host.innerHTML = `<div style="color:var(--muted);padding:20px">${esc(opts.empty || "暂无数据。")}</div>`;
    return;
  }

  const W = Math.max(host.clientWidth || 720, 320);
  const H = host.clientHeight || fallbackHeight;
  const padL = opts.padLeft ?? 58, padR = 16, padT = 16, padB = 28;
  const innerW = W - padL - padR, innerH = H - padT - padB;

  const closes = points.map(valueOf);
  const lo = Math.min(...closes), hi = Math.max(...closes);
  const pad = (hi - lo || 1) * 0.08;
  const yMin = lo - pad, yMax = hi + pad;
  const x = (i) => padL + (innerW * i) / (points.length - 1);
  const y = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;

  const hasBaseline = opts.baseline !== undefined && opts.baseline !== null;
  const rising = hasBaseline ? closes[closes.length - 1] >= opts.baseline : closes[closes.length - 1] >= closes[0];
  const stroke = rising ? "var(--up)" : "var(--down)";
  const rgb = rising ? "#ef4444" : "#22c55e";
  const gradId = `chartGrad${++chartSeq}`;
  const tickDigits = opts.digits ?? (yMax < 100 ? 2 : 0);

  const grid = Array.from({ length: 5 }, (_, i) => {
    const value = yMin + ((yMax - yMin) * i) / 4;
    return `<line class="grid-line" x1="${padL}" y1="${y(value).toFixed(1)}" x2="${W - padR}" y2="${y(value).toFixed(1)}"/>
      <text class="axis-label" x="${padL - 8}" y="${(y(value) + 4).toFixed(1)}" text-anchor="end">${num(value, tickDigits)}</text>`;
  }).join("");

  const line = closes.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(closes.length - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${padL},${(
    padT + innerH
  ).toFixed(1)} Z`;

  const step = Math.max(1, Math.floor(points.length / 6));
  const xLabels = points
    .map((r, i) =>
      i % step === 0 || i === points.length - 1
        ? `<text class="axis-label" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(
            labelOf(r)
          )}</text>`
        : ""
    )
    .join("");

  const baselineLine = hasBaseline
    ? `<line x1="${padL}" y1="${y(opts.baseline).toFixed(1)}" x2="${W - padR}"
             y2="${y(opts.baseline).toFixed(1)}" stroke="rgba(236,233,245,.34)"
             stroke-width="1" stroke-dasharray="4 4"/>`
    : "";

  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <defs>
      <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${rgb}" stop-opacity="0.26"/>
        <stop offset="100%" stop-color="${rgb}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${grid}
    ${baselineLine}
    <path d="${area}" fill="url(#${gradId})"/>
    <path d="${line}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round"/>
    <g class="hover" style="display:none">
      <line class="crosshair" y1="${padT}" y2="${padT + innerH}"/>
      <circle class="marker" r="4.5" stroke="${stroke}"/>
      <text class="tip-line" text-anchor="middle"></text>
    </g>
    <rect class="hit" x="${padL}" y="${padT}" width="${innerW}" height="${innerH}"/>
    ${xLabels}
  </svg>`;

  const svg = host.querySelector("svg");
  const hover = svg.querySelector(".hover");
  const crosshair = hover.querySelector("line");
  const marker = hover.querySelector("circle");
  const tip = hover.querySelector("text");

  svg.querySelector(".hit").addEventListener("mousemove", (event) => {
    const rect = svg.getBoundingClientRect();
    const px = (event.clientX - rect.left) * (W / rect.width);
    const index = Math.max(0, Math.min(points.length - 1, Math.round(((px - padL) / innerW) * (points.length - 1))));
    const row = points[index];
    const value = valueOf(row);
    hover.style.display = "";
    crosshair.setAttribute("x1", x(index));
    crosshair.setAttribute("x2", x(index));
    marker.setAttribute("cx", x(index));
    marker.setAttribute("cy", y(value));
    tip.setAttribute("x", Math.min(Math.max(x(index), padL + 44), W - padR - 44));
    tip.setAttribute("y", Math.max(y(value) - 12, padT + 10));
    tip.textContent = `${typeof opts.tip === "function" ? opts.tip(row) : labelOf(row)}  ${num(value, tickDigits)}`;
  });
  svg.querySelector(".hit").addEventListener("mouseleave", () => { hover.style.display = "none"; });
}

function renderHistory() {
  drawLineChart(
    $("history-chart"),
    (state.snapshot?.index_history || []).slice(-state.chartDays),
    { empty: "暂无历史数据。", label: (r) => (r.date || "").slice(5) }
  );
}

/* ------------------------------------------------------------ 行业板块 */
/** 环球市场。按「贵金属 / 能源 / 基本金属 / 外汇」分组展示。
 *
 *  分组顺序固定，因为这四类对 A 股的传导路径不同：
 *  黄金看避险，原油看石化与航空成本，伦铜看有色，外汇看外资流向。
 *  数字用等宽字体对齐，小数位按各自量级决定（汇率 4 位、黄金 2 位），
 *  否则美元人民币会显示成一潭死水。
 */
const MACRO_ORDER = [
  "贵金属", "国内贵金属", "能源", "基本金属", "黑色系", "化工", "农产品",
  "海外股指", "外汇", "数字货币",
];

/* 品种涨到五十多个以后，面板会长到一屏半；分组标题点一下就能收起来，
   收起的是哪几组记在浏览器里，下次打开还是收起的状态。 */
const MACRO_COLLAPSED_KEY = "ashare-watch:macro-collapsed";

function loadCollapsedGroups() {
  let raw = null;
  try {
    raw = localStorage.getItem(MACRO_COLLAPSED_KEY);
  } catch (error) {
    return { set: new Set(), saved: false };   // 无痕模式下 localStorage 不可用
  }
  if (raw === null) return { set: new Set(), saved: false };
  try {
    const list = JSON.parse(raw);
    return {
      set: new Set(Array.isArray(list) ? list.filter((g) => typeof g === "string") : []),
      saved: true,
    };
  } catch (error) {
    return { set: new Set(), saved: false };
  }
}

function saveCollapsedGroups() {
  try {
    localStorage.setItem(MACRO_COLLAPSED_KEY, JSON.stringify([...collapsedGroups]));
  } catch (error) {
    /* 存不进去就只在本次会话有效 */
  }
  macroPrefsSaved = true;
}

const macroPrefs = loadCollapsedGroups();
const collapsedGroups = macroPrefs.set;
let macroPrefsSaved = macroPrefs.saved;

/** 窄屏第一次打开时默认全部收起。
 *
 *  56 个品种在手机上铺开有七八千像素高，一路往下拉很劝退；而 10 个分组标题
 *  加起来还不到一屏，先收着、想看哪组再点开更合理。桌面屏幕宽，默认展开。
 *  用户一旦手动点过，之后就以他的选择为准。
 */
function collapseAllOnFirstMobileVisit(groups) {
  if (macroPrefsSaved) return;
  if (!window.matchMedia("(max-width: 760px)").matches) return;
  groups.forEach((name) => collapsedGroups.add(name));
  saveCollapsedGroups();
}

function toggleMacroGroup(groupEl) {
  const collapsed = groupEl.classList.toggle("collapsed");
  if (collapsed) {
    collapsedGroups.add(groupEl.dataset.group);
  } else {
    collapsedGroups.delete(groupEl.dataset.group);
  }
  groupEl.querySelector(".macro-group-label")
    .setAttribute("aria-expanded", String(!collapsed));
  saveCollapsedGroups();
  syncMacroToggle();
}

/** 「全部收起 / 全部展开」。面板有五十多个品种时会很长，给一个一键开关。 */
function bindMacroToggle() {
  const btn = $("macro-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const groups = [...document.querySelectorAll("#macro-groups .macro-group")];
    if (!groups.length) return;
    const collapseAll = !groups.every((g) => g.classList.contains("collapsed"));
    groups.forEach((group) => {
      if (collapseAll) {
        collapsedGroups.add(group.dataset.group);
      } else {
        collapsedGroups.delete(group.dataset.group);
      }
      group.classList.toggle("collapsed", collapseAll);
      group.querySelector(".macro-group-label")
        .setAttribute("aria-expanded", String(!collapseAll));
    });
    saveCollapsedGroups();
    syncMacroToggle();
  });
  syncMacroToggle();
}

function syncMacroToggle() {
  const btn = $("macro-toggle");
  if (!btn) return;
  const groups = [...document.querySelectorAll("#macro-groups .macro-group")];
  const allCollapsed = groups.length > 0
    && groups.every((g) => g.classList.contains("collapsed"));
  btn.textContent = allCollapsed ? "全部展开" : "全部收起";
}

function renderMacro(macro) {
  const host = $("macro-groups");
  if (!macro || !macro.length) {
    host.innerHTML = '<div class="empty">环球市场数据暂不可用。</div>';
    $("macro-note").textContent = "—";
    return;
  }
  const grouped = new Map();
  macro.forEach((m) => {
    const key = m.group || "其他";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(m);
  });
  const order = [...MACRO_ORDER.filter((k) => grouped.has(k)),
                 ...[...grouped.keys()].filter((k) => !MACRO_ORDER.includes(k))];

  collapseAllOnFirstMobileVisit(order);

  host.innerHTML = order
    .map((group) => {
      const cards = grouped
        .get(group)
        .map((m) => {
          const d = m.direction;
          const digits = m.digits ?? 2;
          const price = m.price === null || m.price === undefined
            ? "—"
            : Number(m.price).toLocaleString("en-US", {
                minimumFractionDigits: digits, maximumFractionDigits: digits,
              });
          return `<div class="macro-card ${d}">
            <div class="mh">
              <span class="mn">${esc(m.name)}</span>
              <span class="mu">${esc(m.unit || "")}</span>
            </div>
            <div class="mp ${dirClass(d)}">${price}</div>
            <div class="mc">
              <span class="${dirClass(d)}">${signed(m.change, digits)}</span>
              <span class="pct ${dirClass(d)}">${pct(m.change_pct)}</span>
            </div>
          </div>`;
        })
        .join("");
      const items = grouped.get(group);
      const collapsed = collapsedGroups.has(group);
      return `<div class="macro-group ${collapsed ? "collapsed" : ""}" data-group="${esc(group)}">
        <button type="button" class="macro-group-label" aria-expanded="${!collapsed}">
          <span class="chev" aria-hidden="true"></span>
          <span>${esc(group)}</span>
          <span class="gl-count">${items.length}</span>
        </button>
        <div class="macro-cards">${cards}</div>
      </div>`;
    })
    .join("");

  host.querySelectorAll(".macro-group-label").forEach((btn) => {
    btn.addEventListener("click", () => toggleMacroGroup(btn.closest(".macro-group")));
  });

  $("macro-note").textContent = `${macro.length} 个品种`;
  syncMacroToggle();
}

function renderSectors(sectors) {
  const host = $("sector-list");
  $("sector-count").textContent = sectors.length ? `${sectors.length} 个板块` : "—";
  if (!sectors.length) {
    host.innerHTML = '<div style="color:var(--muted);font-size:13px">暂无板块数据。</div>';
    return;
  }
  // 涨得最好的和跌得最差的一样重要，各取一半展示
  const shown = sectors.length <= 24 ? sectors : [...sectors.slice(0, 12), ...sectors.slice(-12)];
  const maxAbs = Math.max(...shown.map((s) => Math.abs(s.change_pct))) || 1;
  host.innerHTML = shown
    .map((s) => {
      const width = (Math.abs(s.change_pct) / maxAbs) * 50;
      const up = s.change_pct >= 0;
      return `<div class="sector-row">
        <span class="name" title="${esc(s.name)}｜领涨 ${esc(s.leader_name)}">${esc(s.name)}</span>
        <span class="bar-track"><span class="mid"></span>
          <span class="bar ${up ? "up" : "down"}" style="width:${width.toFixed(1)}%"></span>
        </span>
        <span class="val ${up ? "change-up" : "change-down"}">${pct(s.change_pct)}</span>
      </div>`;
    })
    .join("");
}

/* ------------------------------------------------------------- 自选股 */
function limitTag(q) {
  if (!q.limit_status) return "";
  const up = q.limit_status.includes("涨");
  return `<span class="limit-tag ${up ? "up" : "down"}">${esc(q.limit_status)}</span>`;
}

function stTag(q) {
  return q.is_st ? '<span class="tag-st">ST</span>' : "";
}

function renderWatchlist(watchlist) {
  $("watchlist-count").textContent = `${watchlist.length} 只`;
  $("watchlist").innerHTML = watchlist
    .map((q) => {
      const d = q.direction;
      return `<div class="watch-card ${d}" data-code="${esc(q.code)}">
        <div class="top">
          <span class="sym">${esc(q.code)}</span>
          <span class="pct ${dirClass(d)}">${pct(q.change_pct)}</span>
        </div>
        <div class="nm" title="${esc(q.name)}">${esc(q.name)}${stTag(q)}${limitTag(q)}</div>
        <div class="px ${dirClass(d)}">${num(q.price)}</div>
        <div class="chg ${dirClass(d)}">${signed(q.change)}</div>
        <div class="vol">量 ${hands(q.volume)}</div>
      </div>`;
    })
    .join("");
}

/* --------------------------------------------------------------- 榜单 */
function renderRank() {
  const rows = state.snapshot?.[state.rankKey] || [];
  $("rank-body").innerHTML = rows
    .map((q, i) => {
      const d = q.direction;
      return `<tr data-code="${esc(q.code)}">
        <td class="idx">${i + 1}</td>
        <td><div class="sym">${esc(q.code)}${stTag(q)}${limitTag(q)}</div>
            <div class="nm" title="${esc(q.name)}">${esc(q.name)} · ${esc(q.board || "")}</div></td>
        <td class="num">${num(q.price)}</td>
        <td class="num ${dirClass(d)}">${signed(q.change)}</td>
        <td class="num"><span class="pill ${dirClass(d)}">${pct(q.change_pct)}</span></td>
        <td class="num">${money(q.amount)}</td>
        <td class="num">${q.turnover === null || q.turnover === undefined ? "—" : q.turnover.toFixed(2) + "%"}</td>
      </tr>`;
    })
    .join("") || '<tr><td colspan="7" style="color:var(--muted);padding:18px">暂无数据。</td></tr>';
}

/* --------------------------------------------------------------- 状态 */
function renderStatus(snapshot) {
  const market = snapshot.market || {};
  const badge = $("market-badge");
  const status = market.status || "Unknown";
  $("market-label").textContent = market.session ? `${status} · ${market.session}` : status;
  badge.className =
    "badge " +
    (market.is_open ? "open" : ["集合竞价", "午间休市"].includes(status) ? "break" : "closed");
  $("fetched-at").textContent = (snapshot.fetched_at || "").replace("T", " ").slice(0, 19);

  $("warnings").innerHTML = (snapshot.warnings || [])
    .map((w) => `<div class="warn">${esc(w)}</div>`)
    .join("");

  const cov = snapshot.coverage || {};
  $("foot-meta").textContent =
    `样本 ${(cov.universe || 0).toLocaleString()} 只 · 板块 ${cov.sectors || 0} 个 · ` +
    `生成于 ${(snapshot.fetched_at || "").slice(11, 19)}`;
}

function render(snapshot) {
  state.snapshot = snapshot;
  renderStatus(snapshot);
  renderIndexes(snapshot.indexes || []);
  renderBreadth(snapshot);
  renderLimits(snapshot);
  renderHistory();
  renderSectors(snapshot.sectors || []);
  renderMacro(snapshot.macro || []);
  renderWatchlist(snapshot.watchlist || []);
  renderRank();
}

/* ---------------------------------------------------------------- 搜索
 *
 *  在全市场 5500+ 只里本地过滤，不发任何请求。
 *  索引是精简数组，字段顺序固定为：
 *    [代码, 名称, 现价, 涨跌幅, 换手率, 成交额(万元)]
 *  用数组而不是对象是为了压体积（对象写法要 500KB+，数组只要 200 多 KB）。
 *
 *  因为是纯本地过滤，**静态分享页面里也能用**。
 */
let searchIndex = null;
const SEARCH_LIMIT = 12;

function boardName(code) {
  if (/^(688|689)/.test(code)) return "科创板";
  if (/^(300|301|302)/.test(code)) return "创业板";
  if (/^(8|4|92)/.test(code)) return "北交所";
  return "主板";
}

function searchStocks(query) {
  const raw = query.trim();
  if (!raw || !searchIndex) return [];
  const lower = raw.toLowerCase();
  const hits = [];
  for (const row of searchIndex) {
    const code = row[0];
    const name = row[1];
    // 打分：代码精确 > 代码前缀 > 名称前缀 > 代码包含 > 名称包含
    let score = 0;
    if (code === lower) score = 100;
    else if (code.startsWith(lower)) score = 80;
    else if (name.startsWith(raw)) score = 70;
    else if (code.includes(lower)) score = 50;
    else if (name.includes(raw)) score = 40;
    if (score) hits.push({ score, row });
  }
  hits.sort((a, b) => b.score - a.score);
  return hits.slice(0, SEARCH_LIMIT).map((hit) => hit.row);
}

function renderSearchResults(rows, query) {
  const host = $("search-results");
  const clear = $("search-clear");
  if (!query.trim()) {
    host.hidden = true;
    host.innerHTML = "";
    clear.hidden = true;
    return;
  }
  clear.hidden = false;
  host.hidden = false;

  if (!searchIndex) {
    host.innerHTML = '<div class="search-empty">搜索索引还在加载…</div>';
    return;
  }
  if (!rows.length) {
    host.innerHTML = `<div class="search-empty">没有找到匹配「${esc(query)}」的股票</div>`;
    return;
  }

  const body = rows
    .map((row) => {
      const [code, name, price, pctValue, turnover, amountWan] = row;
      const d =
        pctValue === null || pctValue === undefined
          ? "flat"
          : pctValue > 0.0001 ? "up" : pctValue < -0.0001 ? "down" : "flat";
      const turn =
        turnover === null || turnover === undefined ? "—" : turnover.toFixed(2) + "%";
      const on = isFollowed(code);
      return `<div class="search-row" data-code="${esc(code)}">
        <span class="sr-code ${dirClass(d)}">${esc(code)}</span>
        <span class="sr-name">${esc(name)}<em>${boardName(code)}</em></span>
        <span class="sr-price ${dirClass(d)}">${num(price)}</span>
        <span class="sr-pct ${dirClass(d)}">${pct(pctValue)}</span>
        <span class="sr-meta">${turn} · ${money((amountWan || 0) * 10000)}</span>
        <button class="star-btn ${on ? "on" : ""}" data-code="${esc(code)}"
                title="${on ? "取消关注" : "加入关注"}">${on ? "★" : "☆"}</button>
      </div>`;
    })
    .join("");
  const more =
    rows.length >= SEARCH_LIMIT
      ? '<div class="search-more">只显示前 12 条，输入更具体的关键词试试</div>'
      : "";
  host.innerHTML = body + more;
}

function onSearchInput() {
  const query = $("search-input").value;
  renderSearchResults(searchStocks(query), query);
}

async function loadSearchIndex() {
  // 静态分享页：索引已内联在页面里，直接用，不产生任何请求
  if (window.__SEARCH_INDEX__) {
    searchIndex = window.__SEARCH_INDEX__;
  } else {
    try {
      const response = await fetch("/api/search-index", { cache: "no-store" });
      searchIndex = (await response.json()).rows || [];
    } catch (error) {
      searchIndex = null; // 搜索不可用不该影响其它功能
    }
  }
  // 建一份 code → 行 的映射：关注列表在没有后端时靠它取数
  searchRowsByCode = new Map();
  if (searchIndex) {
    for (const row of searchIndex) searchRowsByCode.set(row[0], row);
  }
}

// 点搜索结果打开详情时，要让下拉立刻收起；但同一个点击还会冒泡到 document
// 上「点搜索框就展开下拉」的逻辑，会把刚收起的下拉又展开。用一个短标志挡一下。
let searchJumping = false;

function bindSearch() {
  $("search-input").addEventListener("input", onSearchInput);
  $("search-input").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      $("search-input").value = "";
      onSearchInput();
      $("search-input").blur();
    }
  });
  $("search-clear").addEventListener("click", () => {
    $("search-input").value = "";
    onSearchInput();
    $("search-input").focus();
  });
  // 星标用事件委托：搜索结果每次重绘，逐个绑定会漏
  $("search-results").addEventListener("click", (event) => {
    const btn = event.target.closest(".star-btn");
    if (btn) {
      event.stopPropagation();
      toggleFollow(btn.dataset.code);
      return;
    }
    // 点结果本身 = 看这只股票的详情
    const row = event.target.closest(".search-row");
    if (row) {
      searchJumping = true;
      $("search-results").hidden = true;
      openDetail(row.dataset.code);
    }
  });
  $("follow-clear").addEventListener("click", () => {
    if (!followed.length) return;
    // 二次确认做在按钮自己身上，不用浏览器的 confirm 弹窗：
    // 原生弹窗的样式和整个页面不搭，而且会阻塞其它渲染。
    if (!clearArmed) {
      armClear();
      return;
    }
    disarmClear();
    followed = [];
    followQuotes.clear();
    saveFollowState();
    renderFollow();
  });
  // 点击搜索框以外的区域收起下拉
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-block")) {
      $("search-results").hidden = true;
    } else if (!searchJumping && $("search-input").value.trim()) {
      $("search-results").hidden = false;
    }
    searchJumping = false;
  });
}

/* ------------------------------------------------------------ 我的关注
 *
 *  关注列表存在浏览器 localStorage 里，而不是服务端。三个理由：
 *    1. 静态分享页面没有服务端，但搜索和关注同样应该能用；
 *    2. 关注是个人偏好，不值得为它引入账号体系；
 *    3. 不需要为它改服务端配置再重启。
 *
 *  行情数据取两条路：
 *    * 本地服务：`/api/quotes?codes=...` 拿实时行情（和自选股同一节奏）
 *    * 静态页面：从内联的全市场搜索索引里查，会有几分钟滞后，但至少有数据
 *
 *  另外把「上一次看到的行情」也一起存下来。刷新页面时先用它把卡片画出来，
 *  接口回来再覆盖——否则刚打开的一瞬间会是一屏「—」，看着像坏了。
 */
const FOLLOW_KEY = "ashare-watch:followed";
const FOLLOW_LIMIT = 30;

function isStockCode(code) {
  return typeof code === "string" && /^\d{6}$/.test(code);
}

function loadFollowState() {
  const empty = { codes: [], quotes: {} };
  let raw = null;
  try {
    // 隐私模式下 localStorage 可能直接抛，只有这一行需要兜
    raw = localStorage.getItem(FOLLOW_KEY);
  } catch (error) {
    return empty;
  }
  if (!raw) return empty;
  let data = null;
  try {
    data = JSON.parse(raw);
  } catch (error) {
    return empty; // 存储被改坏了，当没有处理
  }
  // 下面故意放在 try 外面：万一哪天写出 bug（比如变量声明顺序不对），
  // 让它当场报错，而不是被 catch 吞掉、把用户的关注列表悄悄清空一次。
  if (Array.isArray(data)) return { codes: data.filter(isStockCode), quotes: {} };
  return {
    codes: Array.isArray(data.codes) ? data.codes.filter(isStockCode) : [],
    quotes: data.quotes && typeof data.quotes === "object" ? data.quotes : {},
  };
}

const FOLLOW_STATE = loadFollowState();
let followed = FOLLOW_STATE.codes;
let followQuotes = new Map(Object.entries(FOLLOW_STATE.quotes));  // code -> 扁平对象
let searchRowsByCode = new Map();

function saveFollowState() {
  try {
    localStorage.setItem(FOLLOW_KEY, JSON.stringify({
      codes: followed,
      quotes: Object.fromEntries(followQuotes),
    }));
  } catch (error) {
    /* 存不进去就只在本次会话有效，不影响使用 */
  }
}

const isFollowed = (code) => followed.includes(code);

let clearArmed = false;
let clearTimer = 0;

/** 把「全部清空」切成待确认状态，4 秒内没再点就自动收回去。 */
function armClear() {
  clearArmed = true;
  const btn = $("follow-clear");
  btn.textContent = "再点一次确认";
  btn.classList.add("armed");
  clearTimeout(clearTimer);
  clearTimer = setTimeout(disarmClear, 4000);
}

function disarmClear() {
  clearArmed = false;
  clearTimeout(clearTimer);
  const btn = $("follow-clear");
  if (!btn) return;
  btn.textContent = "全部清空";
  btn.classList.remove("armed");
}

function toggleFollow(code) {
  if (isFollowed(code)) {
    followed = followed.filter((c) => c !== code);
  } else {
    if (followed.length >= FOLLOW_LIMIT) {
      // 同样不用 alert：在计数那一条上提示就好，不打断操作
      flashFollowHint(`最多 ${FOLLOW_LIMIT} 只`);
      return;
    }
    // 新加的放最前面，刚点完能立刻看到
    followed = [code, ...followed];
  }
  saveFollowState();
  renderFollow();
  refreshFollowQuotes();
  renderSearchResults(searchStocks($("search-input").value), $("search-input").value);
  // 关注面板现在在另一个标签页里，不给点反馈的话会怀疑自己没点到
  const name = (quoteFor(code) || {}).name || code;
  showToast(isFollowed(code) ? `已加入关注 · ${name}` : `已移出关注 · ${name}`);
}

function flashFollowHint(text) {
  const chip = $("follow-count");
  chip.textContent = text;
  chip.classList.add("warn");
  clearTimeout(flashFollowHint.timer);
  flashFollowHint.timer = setTimeout(() => {
    chip.classList.remove("warn");
    renderFollow();
  }, 2500);
}

function renderFollow() {
  const host = $("follow-list");
  const count = $("follow-count");
  const clear = $("follow-clear");
  count.textContent = followed.length ? `${followed.length} 只` : "—";
  clear.hidden = followed.length === 0;
  syncTabBadge();

  if (!followed.length) {
    host.innerHTML = `<div class="follow-empty">
      还没有关注的股票。<br />
      在上面的搜索框里输入<b>代码或名称</b>，点结果右侧的 <b>☆</b> 即可加入。<br />
      <span style="font-size:11.5px">关注列表保存在你自己的浏览器里，不会上传。</span>
    </div>`;
    return;
  }

  host.innerHTML = followed
    .map((code) => {
      const q = quoteFor(code);
      if (!q) {
        // 手上一条数据都没有（新加的、又还没拉到行情）：不要摆一排「—」，
        // 那看起来像接口挂了。给一个明确的等待态。
        return `<div class="watch-card pending" data-code="${esc(code)}">
          <button class="remove-btn" data-code="${esc(code)}" title="移除关注">×</button>
          <div class="top"><span class="sym">${esc(code)}</span></div>
          <div class="nm">正在取行情…</div>
          <div class="px">…</div>
        </div>`;
      }
      const d = q.direction || "flat";
      const limit = q.limit_status
        ? `<span class="limit-tag ${q.limit_status.includes("涨") ? "up" : "down"}">${esc(q.limit_status)}</span>`
        : "";
      const st = q.is_st ? '<span class="tag-st">ST</span>' : "";
      const chg = q.change === undefined || q.change === null
        ? ""
        : `<div class="chg ${dirClass(d)}">${signed(q.change)}</div>`;
      const vol = q.amount
        ? `<div class="vol">额 ${money(q.amount)}${q.turnover != null ? ` · 换手 ${q.turnover.toFixed(2)}%` : ""}</div>`
        : "";
      return `<div class="watch-card ${d}" data-code="${esc(code)}">
        <button class="remove-btn" data-code="${esc(code)}" title="移除关注">×</button>
        <div class="top">
          <span class="sym">${esc(code)}</span>
          <span class="pct ${dirClass(d)}">${pct(q.change_pct)}</span>
        </div>
        <div class="nm" title="${esc(q.name || "")}">${esc(q.name || "")}${st}${limit}</div>
        <div class="px ${dirClass(d)}">${q.price ? num(q.price) : "—"}</div>
        ${chg}${vol}
      </div>`;
    })
    .join("");

  host.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => toggleFollow(btn.dataset.code));
  });
}

/** 关注卡片的数据来源：先用手上的实时行情，没有就用搜索索引兜底。 */
function quoteFor(code) {
  return followQuotes.get(code) || rowToQuote(searchRowsByCode.get(code)) || null;
}

/**
 * 把搜索索引的一行（数组）转成和行情一样的扁平结构。
 * 字段顺序见 `derive.build_search_index`：代码、名称、现价、涨跌幅、换手率、
 * 成交额(万元)、市盈率、市净率、总市值(亿元)、流通市值(亿元)。
 */
function rowToQuote(row) {
  if (!row) return null;
  const [code, name, price, changePct, turnover, amountWan, pe, pb, capYi, floatYi] = row;
  return {
    code,
    name,
    price,
    change_pct: changePct,
    turnover,
    amount: (amountWan || 0) * 10000,
    pe,
    pb,
    market_cap: capYi ? capYi * 1e8 : null,
    float_cap: floatYi ? floatYi * 1e8 : null,
    direction: changePct === null || changePct === undefined
      ? "flat"
      : changePct > 0.0001 ? "up" : changePct < -0.0001 ? "down" : "flat",
  };
}

async function refreshFollowQuotes() {
  if (!followed.length) {
    followQuotes.clear();
    return;
  }
  // 静态分享页没有后端：退回用内联的全市场索引（滞后几分钟，但至少有数据）
  if (window.__SNAPSHOT__) {
    followed.forEach((code) => {
      const row = searchRowsByCode.get(code);
      if (row) followQuotes.set(code, rowToQuote(row));
    });
    saveFollowState();
    renderFollow();
    return;
  }
  try {
    const response = await fetch(`/api/quotes?codes=${followed.join(",")}`, { cache: "no-store" });
    const data = await response.json();
    const next = new Map();
    (data.quotes || []).forEach((q) => {
      next.set(q.code, {
        code: q.code,
        name: q.name,
        price: q.price,
        change: q.change,
        change_pct: q.change_pct,
        turnover: q.turnover,
        amount: q.amount,
        direction: q.direction,
        is_st: q.is_st,
        limit_status: q.limit_status,
      });
    });
    followQuotes = next;
    saveFollowState();
    renderFollow();
  } catch (error) {
    /* 拿不到就继续显示上一次的数据 */
  }
}

/* --------------------------------------------------------------- 拉取 */
let loadingElapsed = 0;

/* ------------------------------------------------------------ 主导航
 *
 *  原来是「一页到底」，手机上要拉很久才看得到榜单。现在横着切成几屏：
 *  概览 / 自选·关注 / 环球市场 / 行业板块 / 榜单。
 *  选中的标签记在浏览器里，刷新之后还停在原来那一屏。
 */
const TAB_KEY = "ashare-watch:tab";
const TAB_NAMES = ["overview", "mine", "macro", "sectors", "rank"];

function savedTab() {
  try {
    const name = localStorage.getItem(TAB_KEY);
    return TAB_NAMES.includes(name) ? name : "overview";
  } catch (error) {
    return "overview";  // 无痕模式下 localStorage 可能不可用
  }
}

function showTab(name) {
  if (!TAB_NAMES.includes(name)) name = "overview";
  document.querySelectorAll("#main-tabs .tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.panel === name);
  });
  try {
    localStorage.setItem(TAB_KEY, name);
  } catch (error) {
    /* 存不进去就只在本次会话有效 */
  }
  // 面板隐藏时容器量不到宽度，切回来必须重画一次，否则图会挤成一小条
  if (name === "overview") renderHistory();
  syncTabBadge();
}

function bindTabs() {
  $("main-tabs").addEventListener("click", (event) => {
    const btn = event.target.closest(".tab");
    if (btn) showTab(btn.dataset.panel);
  });
  showTab(savedTab());
}

/** 「自选 · 关注」标签上带一个关注数，点了 ☆ 之后一眼能看到有没有成功。 */
function syncTabBadge() {
  const badge = $("tab-badge-mine");
  if (!badge) return;
  badge.hidden = followed.length === 0;
  badge.textContent = followed.length;
}

/* ---------------------------------------------------------- 个股详情
 *
 *  数据**点开的时候才去抓**。全市场 5500 多只不可能每只都预先抓一份 K 线，
 *  那是 5500 个请求；而单只股票只要 4 个请求、半秒左右，点开时再抓完全来得及。
 *
 *  静态分享页没有后端，这里会退化成「只展示搜索索引里已有的行情和基本面」，
 *  并且明确告诉访客分时和盘口需要在本机跑服务。
 */
const detailCache = new Map();   // code -> { at, data }
let detailCode = "";

function openDetail(code) {
  if (!/^\d{6}$/.test(code)) return;
  detailCode = code;
  const local = rowToQuote(searchRowsByCode.get(code));

  $("detail-scrim").hidden = false;
  $("detail").hidden = false;
  document.body.classList.add("drawer-open");
  renderDetailHeader(code, local);
  updateFollowButton(code);

  const cached = detailCache.get(code);
  if (cached && Date.now() - cached.at < 15000) {
    renderDetailBody(cached.data, local, code);
    return;
  }

  $("detail-foot").textContent = "";
  if (window.__SNAPSHOT__) {
    // 静态分享页：没有后端可问
    renderDetailBody(null, local, code);
    return;
  }

  $("detail-body").innerHTML =
    '<div class="detail-loading">正在拉取行情、分时和资金流向…</div>';
  fetch(`/api/stock?code=${code}`, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (detailCode !== code) return;   // 用户已经点开别的股票了
      detailCache.set(code, { at: Date.now(), data });
      renderDetailHeader(code, data.quote || local);
      renderDetailBody(data, local, code);
    })
    .catch((error) => {
      if (detailCode !== code) return;
      $("detail-body").innerHTML =
        `<div class="detail-note">详情拉取失败（${esc(error.message)}）。<br />` +
        "检查一下网络，或者关掉重开试试。</div>";
    });
}

function closeDetail() {
  detailCode = "";
  $("detail").hidden = true;
  $("detail-scrim").hidden = true;
  document.body.classList.remove("drawer-open");
}

function bindDetail() {
  $("detail-close").addEventListener("click", closeDetail);
  $("detail-scrim").addEventListener("click", closeDetail);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("detail").hidden) closeDetail();
  });
  $("detail-follow").addEventListener("click", () => {
    if (!detailCode) return;
    toggleFollow(detailCode);
    updateFollowButton(detailCode);
  });
}

function updateFollowButton(code) {
  const btn = $("detail-follow");
  const on = isFollowed(code);
  btn.textContent = on ? "★ 已关注" : "☆ 关注";
  btn.classList.toggle("on", on);
}

function renderDetailHeader(code, q) {
  q = q || {};
  const d = q.direction || "flat";
  $("detail-code").textContent = code;
  $("detail-name").textContent = q.name || "—";
  $("detail-price").textContent = q.price ? num(q.price) : "—";
  $("detail-price").className = dirClass(d);
  const bits = [];
  if (q.change !== null && q.change !== undefined) bits.push(signed(q.change));
  if (q.change_pct !== null && q.change_pct !== undefined) bits.push(pct(q.change_pct));
  $("detail-change").textContent = bits.join("  ") || "—";
  $("detail-change").className = dirClass(d);
  $("detail-tags").innerHTML =
    `<span class="dh-board">${esc(boardName(code))}</span>${stTag(q)}${limitTag(q)}`;
}

/**
 * 把「实时行情」和「全市场索引」两边的数据合起来。
 *
 * 为什么要合：实时行情接口不提供市盈率、市净率、市值，这几个字段只有全市场
 * 索引里有。合的时候以实时为准，实时缺的（是 null）才用索引里的补上——
 * 注意不能简单地 `{...local, ...live}`，那样实时那边的 null 会把索引里的值盖掉。
 */
function mergeQuote(live, local) {
  const merged = { ...(local || {}), ...(live || {}) };
  ["pe", "pb", "market_cap", "float_cap", "turnover"].forEach((key) => {
    const fromLive = live ? live[key] : null;
    if (fromLive === null || fromLive === undefined) {
      merged[key] = local ? local[key] : null;
    }
  });
  return merged;
}

/** 把详情渲染进抽屉。``detail`` 为 null 表示拿不到后端数据（静态分享页）。 */
function renderDetailBody(detail, local, code) {
  const q = mergeQuote(detail && detail.quote, local);
  const host = $("detail-body");
  const blocks = [];

  const kv = (key, value, cls = "") =>
    `<div class="kv"><span class="k">${esc(key)}</span><span class="v ${cls}">${value}</span></div>`;

  const amplitude =
    q.high && q.low && q.prev_close
      ? ((q.high - q.low) / q.prev_close) * 100
      : null;

  blocks.push(`<div class="detail-block"><h4>关键指标</h4><div class="kv-grid">
    ${kv("今开", num(q.open))}
    ${kv("昨收", num(q.prev_close))}
    ${kv("最高", num(q.high), dirClass(q.direction))}
    ${kv("最低", num(q.low), dirClass(q.direction))}
    ${kv("成交量", hands(q.volume))}
    ${kv("成交额", money(q.amount))}
    ${kv("换手率", q.turnover !== null && q.turnover !== undefined ? `${q.turnover.toFixed(2)}%` : "—")}
    ${kv("振幅", amplitude === null ? "—" : `${amplitude.toFixed(2)}%`)}
    ${kv("市盈率", q.pe !== null && q.pe !== undefined ? q.pe.toFixed(2) : "—")}
    ${kv("市净率", q.pb !== null && q.pb !== undefined ? q.pb.toFixed(2) : "—")}
    ${kv("总市值", money(q.market_cap))}
    ${kv("流通市值", money(q.float_cap))}
  </div></div>`);

  const canChart = Boolean(detail);
  blocks.push(`<div class="detail-block"><h4>分时走势</h4>
    <div class="chart" id="detail-intraday" style="height:220px"></div></div>`);
  blocks.push(`<div class="detail-block"><h4>日线（近 120 个交易日）</h4>
    <div class="chart" id="detail-daily" style="height:220px"></div></div>`);
  blocks.push(`<div class="detail-block"><h4>买卖五档</h4>
    <div id="detail-orderbook"></div></div>`);
  blocks.push(`<div class="detail-block"><h4>资金流向（最近 5 个交易日）</h4>
    <div id="detail-flow"></div></div>`);

  if (!canChart) {
    blocks.push(`<div class="detail-note">
      这是静态快照页，只带得动行情和基本面。<br />
      分时、K 线和五档盘口要在本机跑起服务（双击 <b>start.bat</b>）之后才能看到。
    </div>`);
  }

  host.innerHTML = blocks.join("");

  if (canChart) {
    renderIntradayChart(detail.intraday || [], q);
    drawLineChart($("detail-daily"), (detail.daily || []).slice(-120), {
      empty: "没有拿到日线数据。",
      label: (r) => (r.date || "").slice(5),
    });
    $("detail-orderbook").innerHTML = renderOrderbook(detail.orderbook);
    $("detail-flow").innerHTML = renderFlow(detail.moneyflow || []);
  } else {
    const hint = '<div class="detail-note">跑起本地服务后这里会显示。</div>';
    $("detail-intraday").outerHTML = hint;
    $("detail-daily").outerHTML = hint;
    $("detail-orderbook").outerHTML = hint;
    $("detail-flow").outerHTML = hint;
  }

  $("detail-foot").textContent = detail
    ? `数据时间 ${detail.fetched_at || ""} · 点开时才抓取，不进快照`
    : "静态快照页 · 数据来自内联的全市场索引";
}

function renderIntradayChart(rows, q) {
  const host = $("detail-intraday");
  if (!host) return;
  // 只画最近一个交易日，否则会把昨天的尾巴也连进来
  const lastDay = rows.length ? String(rows[rows.length - 1].date || "").slice(0, 10) : "";
  const today = rows.filter((r) => String(r.date || "").startsWith(lastDay));
  drawLineChart(host, today, {
    empty: "没有拿到分时数据。",
    height: 220,
    baseline: q.prev_close || null,
    label: (r) => String(r.date || "").slice(11, 16),
    tip: (r) => String(r.date || "").slice(11, 16),
  });
}

function renderOrderbook(orderbook) {
  const bids = (orderbook && orderbook.bids) || [];
  const asks = (orderbook && orderbook.asks) || [];
  if (!bids.length && !asks.length) {
    return '<div class="detail-note">没有盘口数据。指数没有五档，停牌时也可能是空的。</div>';
  }
  const peak = Math.max(...bids.map((x) => x[1]), ...asks.map((x) => x[1]), 1);
  const side = (rows, cls, label) =>
    rows
      .map(
        ([price, volume], index) => `<div class="ob-row ${cls}">
          <span class="ob-bar" style="width:${((volume / peak) * 100).toFixed(1)}%"></span>
          <span class="lv">${label}${index + 1}</span>
          <span class="ob-price">${num(price)}</span>
          <span class="ob-vol">${hands(volume)}</span>
        </div>`
      )
      .join("");
  return `<div class="orderbook">
    <div class="ob-side"><div class="ob-title">买盘（价 / 量）</div>${side(bids, "bid", "买")}</div>
    <div class="ob-side"><div class="ob-title">卖盘（价 / 量）</div>${side(asks, "ask", "卖")}</div>
  </div>`;
}

function renderFlow(rows) {
  if (!rows.length) {
    return '<div class="detail-note">没有拿到资金流向数据。</div>';
  }
  const peak = Math.max(...rows.map((r) => Math.abs(r.main_net || 0)), 1);
  return `<div class="flow-list">${rows
    .map((r) => {
      const net = r.main_net || 0;
      const up = net >= 0;
      const width = Math.min((Math.abs(net) / peak) * 50, 50);
      return `<div class="flow-row">
        <span class="d">${esc(String(r.date || "").slice(5))}</span>
        <span class="bar-track">
          <span class="bar ${up ? "up" : "down"}" style="width:${width.toFixed(1)}%"></span>
          <span class="mid"></span>
        </span>
        <span class="${dirClass(up ? "up" : "down")}">${money(net)}</span>
        <span class="${dirClass(up ? "up" : "down")}">${pct(r.change_pct)}</span>
      </div>`;
    })
    .join("")}</div>`;
}

/* ---------------------------------------------------------------- 提示 */
let toastTimer = 0;

function showToast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2200);
}

/** 点行情卡、关注卡、榜单行都能打开详情。 */
function bindRowClicks() {
  const open = (event) => {
    // 卡片上的按钮有自己的动作（移除关注、加入关注），别抢它们的点击
    if (event.target.closest(".remove-btn") || event.target.closest(".star-btn")) return;
    const hit = event.target.closest("[data-code]");
    if (hit) openDetail(hit.dataset.code);
  };
  ["watchlist", "follow-list", "rank-body"].forEach((id) => {
    const host = $(id);
    if (host) host.addEventListener("click", open);
  });
}

function showLoading() {
  let el = document.getElementById("loading-screen");
  if (!el) {
    el = document.createElement("div");
    el.id = "loading-screen";
    el.className = "loading-screen";
    el.innerHTML = `<div class="spinner"></div>
      <div class="loading-title">正在抓取 A 股行情…</div>
      <div class="loading-sub" id="loading-sub">全市场约 5500 只，首次抓取需要几秒</div>`;
    document.querySelector(".layout").prepend(el);
  }
  loadingElapsed += 1;
  const sub = document.getElementById("loading-sub");
  if (sub && loadingElapsed >= 3) {
    sub.textContent = `仍在抓取（已等待约 ${loadingElapsed * 10} 秒），请稍候…`;
  }
}

function clearLoading() {
  const el = document.getElementById("loading-screen");
  if (el) el.remove();
  loadingElapsed = 0;
}

async function load({ silent = false } = {}) {
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.meta = data.meta || {};
    if (data.snapshot) {
      render(data.snapshot);
      clearLoading();
    } else {
      showLoading();
    }
    state.secondsLeft = state.meta.next_refresh_in ?? 0;
    updateCountdown();
  } catch (error) {
    if (!silent) {
      $("warnings").innerHTML = `<div class="warn">读取数据失败：${esc(
        error.message
      )}（页面会继续自动重试）</div>`;
    }
  }
}

function updateCountdown() {
  if (state.standalone) {
    $("next-label").textContent = "页面类型";
    $("countdown").textContent = "静态快照";
    return;
  }
  const el = $("countdown");
  if (state.secondsLeft <= 0) {
    el.textContent = "即将刷新";
    return;
  }
  const m = Math.floor(state.secondsLeft / 60), s = state.secondsLeft % 60;
  el.textContent = m > 0 ? `${m} 分 ${String(s).padStart(2, "0")} 秒` : `${s} 秒`;
}

/** 静态托管（分享出去）时的顶部提示条。
 *
 *  这一条不是装饰，是必要的：别人通过链接打开时，看到的是**导出那一刻**的
 *  行情。如果页面上没有任何说明，很容易被当成实时数据使用。
 *  所以这里明确写出数据时间，并在数据较旧时加粗提醒。
 */
function renderShareBanner(snapshot) {
  const host = $("share-banner");
  if (!host) return;
  const fetched = (snapshot.fetched_at || "").replace("T", " ").slice(0, 19);
  let staleMinutes = null;
  if (snapshot.fetched_at) {
    const ts = new Date(snapshot.fetched_at).getTime();
    if (!Number.isNaN(ts)) staleMinutes = Math.round((Date.now() - ts) / 60000);
  }
  const stale = staleMinutes !== null && staleMinutes > 60;
  const ageText =
    staleMinutes === null
      ? ""
      : staleMinutes < 1
      ? "（刚刚生成）"
      : staleMinutes < 60
      ? `（${staleMinutes} 分钟前生成）`
      : `（${Math.floor(staleMinutes / 60)} 小时前生成，数据可能已过期）`;

  host.hidden = false;
  host.innerHTML = `<div class="warn share${stale ? " stale" : ""}">
    这是 <b>${esc(fetched)}</b> 的行情快照${esc(ageText)}。
    本页为静态页面，<b>不会自动更新</b>——想看实时行情请在本机运行项目。
  </div>`;
}

/* --------------------------------------------------------------- 交互 */
$("refresh-btn").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.classList.add("loading");
  try {
    await fetch("/api/refresh", { method: "POST" });
    await load();
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
  }
});

$("export-btn").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const response = await fetch("/api/export", { method: "POST" });
    const data = await response.json();
    alert(`已导出单文件快照：\n${data.path}\n\n双击即可在浏览器打开，不需要联网，也可以直接发给别人。`);
  } catch (error) {
    alert("导出失败：" + error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll("#rank-tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#rank-tabs .tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    state.rankKey = tab.dataset.key;
    renderRank();
  });
});

document.querySelectorAll("#range-tabs .range").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#range-tabs .range").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    state.chartDays = Number(tab.dataset.days);
    renderHistory();
  });
});

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => renderHistory(), 160);
});

/* --------------------------------------------------------------- 启动 */
if (window.__SNAPSHOT__) {
  state.standalone = true;
  $("refresh-btn").style.display = "none";
  $("export-btn").style.display = "none";
  $("subtitle").textContent = "行情快照 · 静态页面";
  render(window.__SNAPSHOT__);
  renderShareBanner(window.__SNAPSHOT__);
  updateCountdown();
  bindSearch();
  bindMacroToggle();
  bindTabs();
  bindDetail();
  bindRowClicks();
  renderFollow();
  loadSearchIndex().then(refreshFollowQuotes);
} else {
  load();
  setInterval(() => load({ silent: true }), 10_000);
  setInterval(() => {
    if (state.secondsLeft > 0) state.secondsLeft -= 1;
    updateCountdown();
  }, 1_000);
  bindSearch();
  bindMacroToggle();
  bindTabs();
  bindDetail();
  bindRowClicks();
  renderFollow();
  // 搜索索引跟着全市场快照走（服务端 TTL 4 分钟），5 分钟取一次足够
  loadSearchIndex().then(refreshFollowQuotes);
  setInterval(loadSearchIndex, 300_000);
  // 关注列表的行情单独刷新：它可能要取自选股之外的代码，
  // 所以走 /api/quotes，20 秒一次（复用连接，成本很低）
  setInterval(refreshFollowQuotes, 20_000);
}
