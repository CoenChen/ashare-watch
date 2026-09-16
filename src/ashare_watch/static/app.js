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
function renderHistory() {
  const host = $("history-chart");
  const rows = (state.snapshot?.index_history || []).slice(-state.chartDays);
  if (rows.length < 2) {
    host.innerHTML = '<div style="color:var(--muted);padding:20px">暂无历史数据。</div>';
    return;
  }

  const W = Math.max(host.clientWidth || 720, 320);
  const H = host.clientHeight || 260;
  const padL = 58, padR = 16, padT = 16, padB = 28;
  const innerW = W - padL - padR, innerH = H - padT - padB;

  const closes = rows.map((r) => r.close);
  const lo = Math.min(...closes), hi = Math.max(...closes);
  const pad = (hi - lo || 1) * 0.08;
  const yMin = lo - pad, yMax = hi + pad;
  const x = (i) => padL + (innerW * i) / (rows.length - 1);
  const y = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;

  const rising = closes[closes.length - 1] >= closes[0];
  const stroke = rising ? "var(--up)" : "var(--down)";

  const grid = Array.from({ length: 5 }, (_, i) => {
    const value = yMin + ((yMax - yMin) * i) / 4;
    return `<line class="grid-line" x1="${padL}" y1="${y(value).toFixed(1)}" x2="${W - padR}" y2="${y(value).toFixed(1)}"/>
      <text class="axis-label" x="${padL - 8}" y="${(y(value) + 4).toFixed(1)}" text-anchor="end">${num(value, 0)}</text>`;
  }).join("");

  const line = closes.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(closes.length - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${padL},${(
    padT + innerH
  ).toFixed(1)} Z`;

  const step = Math.max(1, Math.floor(rows.length / 6));
  const xLabels = rows
    .map((r, i) =>
      i % step === 0 || i === rows.length - 1
        ? `<text class="axis-label" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(
            (r.date || "").slice(5)
          )}</text>`
        : ""
    )
    .join("");

  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <defs>
      <linearGradient id="histGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${rising ? "#ef4444" : "#22c55e"}" stop-opacity="0.26"/>
        <stop offset="100%" stop-color="${rising ? "#ef4444" : "#22c55e"}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${grid}
    <path d="${area}" fill="url(#histGrad)"/>
    <path d="${line}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round"/>
    <g id="hist-hover" style="display:none">
      <line class="crosshair" y1="${padT}" y2="${padT + innerH}"/>
      <circle class="marker" r="4.5" stroke="${stroke}"/>
      <text class="tip-line" text-anchor="middle"></text>
    </g>
    <rect class="hit" x="${padL}" y="${padT}" width="${innerW}" height="${innerH}"/>
    ${xLabels}
  </svg>`;

  const svg = host.querySelector("svg");
  const hover = svg.querySelector("#hist-hover");
  const crosshair = hover.querySelector("line");
  const marker = hover.querySelector("circle");
  const tip = hover.querySelector("text");

  svg.querySelector(".hit").addEventListener("mousemove", (event) => {
    const rect = svg.getBoundingClientRect();
    const px = (event.clientX - rect.left) * (W / rect.width);
    const index = Math.max(0, Math.min(rows.length - 1, Math.round(((px - padL) / innerW) * (rows.length - 1))));
    const row = rows[index];
    hover.style.display = "";
    crosshair.setAttribute("x1", x(index));
    crosshair.setAttribute("x2", x(index));
    marker.setAttribute("cx", x(index));
    marker.setAttribute("cy", y(row.close));
    tip.setAttribute("x", Math.min(Math.max(x(index), padL + 44), W - padR - 44));
    tip.setAttribute("y", Math.max(y(row.close) - 12, padT + 10));
    tip.textContent = `${row.date}  ${num(row.close)}`;
  });
  svg.querySelector(".hit").addEventListener("mouseleave", () => { hover.style.display = "none"; });
}

/* ------------------------------------------------------------ 行业板块 */
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
      return `<div class="watch-card ${d}">
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
      return `<tr>
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
  renderWatchlist(snapshot.watchlist || []);
  renderRank();
}

/* --------------------------------------------------------------- 拉取 */
let loadingElapsed = 0;

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
    $("next-label").textContent = "模式";
    $("countdown").textContent = "离线快照";
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
  $("subtitle").textContent = "离线快照 · 数据时间 " + (window.__SNAPSHOT__.fetched_at || "").slice(0, 19);
  render(window.__SNAPSHOT__);
  updateCountdown();
} else {
  load();
  setInterval(() => load({ silent: true }), 10_000);
  setInterval(() => {
    if (state.secondsLeft > 0) state.secondsLeft -= 1;
    updateCountdown();
  }, 1_000);
}

