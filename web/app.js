/* ChainSight live dashboard: plain JavaScript, no external libraries. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const GOODS = { medicine: "Medicine", medical_equipment: "Medical equipment", relief_supplies: "Relief supplies", other: "General goods" };
const TYPE_LABEL = { ORDER_PLACED: "Placed", INVOICE: "Invoice", DISPATCHED: "Dispatched", DELAYED: "Delayed", DELIVERED: "Delivered",
  CANCELED: "Canceled", TEMP_EXCURSION: "Cold chain", REGION_DISRUPTION: "Disruption" };
const ACTION = { expedite: "Expedite by Same Day", upgrade_second_class: "Upgrade to Second Class", upgrade_first_class: "Upgrade to First Class", split_shipment: "Split shipment",
  switch_supplier: "Switch supplier", replace_shipment: "Send replacement", hold_invoice: "Hold invoice", monitor: "Monitor" };
const ANOMALY = { price_jump: "Invoice price spike", quantity_mismatch: "Short shipment", temperature_excursion: "Cold chain break" };

const TOAST_MS = 15000; // how long non critical notifications stay on screen
const state = {
  cursor: null, tab: "overview", filter: "all", paused: false, sound: false, history: [], unread: 0,
  seenRisk: new Set(), summary: null, lastProcessed: 0, lastChange: 0, bannerDismissed: null, drawerId: null, failures: 0,
};

async function api(path, opts = {}) {
  const r = await fetch(path, { cache: "no-store", ...opts });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

/* ---------- formatting ---------- */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtTime(ts) {
  const m = /(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(ts || "");
  return m ? `${MONTHS[+m[2] - 1]} ${+m[3]} ${m[4]}:${m[5]}` : "";
}
function toDate(ts) { const m = /(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(ts || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null; }
function daysBetween(a, b) { const x = toDate(a), y = toDate(b); return x && y ? (y - x) / 86400000 : 0; }
function money(v) {
  v = +v || 0;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}
const pct = (v) => `${Math.round((+v || 0) * 100)}%`;
const goodsChip = (g) => `<span class="chip ${esc(g || "other")}">${esc(GOODS[g] || "General goods")}</span>`;
const isEssential = (g) => g && g !== "other";
function parse(p) { try { return typeof p === "string" ? JSON.parse(p) : (p || {}); } catch { return {}; } }

function pbar(p) {
  const v = +p || 0;
  const cls = v >= 0.3 ? "hot" : v >= 0.15 ? "warm" : "";
  return `<div class="pbar"><div class="pbar-track"><div class="pbar-fill ${cls}" style="width:${Math.min(100, v * 160).toFixed(0)}%"></div></div><span class="pbar-val">${v.toFixed(3)}</span></div>`;
}
function scoreBar(score) {
  const v = +score || 0;
  const cls = v < 70 ? "hot" : v < 80 ? "warm" : "";
  return `<div class="pbar"><div class="pbar-track"><div class="pbar-fill ${cls}" style="width:${Math.max(0, Math.min(100, (v - 40) / 0.6)).toFixed(0)}%"></div></div><span class="pbar-val">${v.toFixed(1)}</span></div>`;
}
function miniBand(r) {
  const due = daysBetween(r.order_ts, r.promised_ts);
  const max = Math.max(r.eta_p90 || 0, due, 1) + 1;
  const x = (d) => `${Math.max(0, Math.min(100, (d / max) * 100)).toFixed(1)}%`;
  return `<div class="band" title="P10 ${(+r.eta_p10).toFixed(1)}, P50 ${(+r.eta_p50).toFixed(1)}, P90 ${(+r.eta_p90).toFixed(1)} days; promised ${due.toFixed(1)}">
    <div class="band-track"></div>
    <div class="band-range" style="left:${x(r.eta_p10)};width:calc(${x(r.eta_p90)} - ${x(r.eta_p10)})"></div>
    <div class="band-p50" style="left:${x(r.eta_p50)}"></div>
    <div class="band-due" style="left:${x(due)}"></div></div>`;
}
function statusCell(r) {
  if (r.requires_approval && r.alert_status === "OPEN") return `<span class="chip approval">Approve</span>`;
  if (r.alert_status === "APPROVED" || r.alert_status === "REJECTED") return `<span class="chip ${r.alert_status}">${r.alert_status === "APPROVED" ? "Approved" : "Rejected"}</span>`;
  if (r.verdict) return `<span class="chip ${esc(r.verdict)}">${esc(r.verdict.toLowerCase())}</span>`;
  return `<span class="cell-sub">${esc((r.status || "").replace("_", " ").toLowerCase())}</span>`;
}

/* ---------- sound ---------- */
let audio;
function beep() {
  if (!state.sound) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    [880, 660].forEach((f, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = f; o.type = "sine";
      g.gain.setValueAtTime(0.0001, audio.currentTime + i * 0.16);
      g.gain.exponentialRampToValueAtTime(0.15, audio.currentTime + i * 0.16 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + i * 0.16 + 0.15);
      o.connect(g).connect(audio.destination); o.start(audio.currentTime + i * 0.16); o.stop(audio.currentTime + i * 0.16 + 0.16);
    });
  } catch { /* audio not available */ }
}

/* ---------- toasts and notification history ---------- */
function toast({ title, body, cls = "", sticky = false, sid = null, action = "Review" }) {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${cls}`;
  el.innerHTML = `<button class="toast-close" aria-label="Close">×</button>
    <div class="toast-title">${title}</div><div class="toast-body">${body}</div>
    ${sid ? `<div class="toast-actions"><button class="btn primary">${esc(action)}</button></div>` : ""}`;
  const close = () => { el.classList.add("leave"); setTimeout(() => el.remove(), 300); };
  $(".toast-close", el).onclick = close;
  if (sid) $(".btn", el).onclick = () => { openDrawer(sid); close(); };
  box.prepend(el);
  const keep = action === "Review and approve"; // approval requests stay until handled
  if (keep) el.classList.add("keep");
  if (!sticky && !keep) setTimeout(close, TOAST_MS);
  const all = $$(".toast:not(.keep)", box);
  if (all.length > 3) all.slice(3).forEach((t) => t.remove());
  state.history.unshift({ title, body, sid, cls, at: state.summary ? state.summary.sim_clock : "" });
  state.history = state.history.slice(0, 80);
  state.unread += 1;
  renderBell();
}
function renderBell() {
  const c = $("#bellCount");
  c.textContent = state.unread > 99 ? "99+" : state.unread;
  c.classList.toggle("hidden", state.unread === 0);
  const list = $("#historyList");
  list.innerHTML = state.history.length ? state.history.map((h, i) =>
    `<div class="history-item" data-i="${i}"><b>${h.title}</b><span>${h.body}</span><div class="cell-sub">${esc(fmtTime(h.at))}</div></div>`).join("")
    : `<div class="empty">No notifications yet</div>`;
  $$(".history-item", list).forEach((el) => {
    const h = state.history[+el.dataset.i];
    el.onclick = () => { if (h.sid) openDrawer(h.sid); $("#history").classList.add("hidden"); };
  });
}

function onAlert(a, many) {
  const essential = isEssential(a.goods) || (a.criticality || 0) >= 4;
  const name = esc(a.product_name || `Shipment ${a.shipment_id}`);
  if (a.verdict === "DISMISS") {
    if (essential || a.scenario) toast({ title: "False alarm dismissed", body: `${name}: GenAI review found no real risk`, cls: "green", sid: a.shipment_id, action: "See why" });
    return;
  }
  if (!essential && !a.scenario && (a.priority < 0.3 || many)) return;
  const needs = a.requires_approval && a.status === "OPEN";
  toast({
    title: `${needs ? "Approval needed" : "Delivery risk"} · ${esc(GOODS[a.goods] || "General goods")}`,
    body: `${name} from ${esc(a.supplier_name || "")}. ${esc(a.root_cause || "")} Suggested: ${esc(ACTION[a.recommended_action] || a.recommended_action)}.`,
    cls: essential ? "red" : "amber", sticky: essential, sid: a.shipment_id, action: needs ? "Review and approve" : "Review",
  });
  if (essential) beep();
}
function onAnomaly(n) {
  const red = n.kind === "temperature_excursion";
  toast({ title: ANOMALY[n.kind] || n.kind, body: `${esc(n.product_name || "")}: ${esc(n.detail)}`, cls: red ? "red" : "amber", sticky: red, sid: n.shipment_id });
  if (red) beep();
}
function onDisruption(e) {
  const p = parse(e.payload);
  toast({ title: `Regional disruption · ${esc(p.region || "")}`, body: `${esc(p.reason || "")}. ${p.affected ?? "Open"} shipments delayed ${p.delay_days ?? ""} days, priorities recalculated.`, cls: "red", sticky: true });
  beep();
}

/* ---------- live feed ---------- */
function feedText(e) {
  const p = parse(e.payload);
  const name = esc(e.product_name || "");
  switch (e.type) {
    case "DELAYED": return `${name} delayed ${p.delay_days ?? ""} day(s)${p.reason ? `, ${esc(p.reason)}` : ""}`;
    case "INVOICE": return `${name} invoiced at $${(+p.unit_price || 0).toFixed(2)} per unit`;
    case "DISPATCHED": return `${name} dispatched, ${p.shipped_qty} units`;
    case "TEMP_EXCURSION": return `${name} logged ${p.temp_c} C, allowed ${esc(p.limit || "")}`;
    case "REGION_DISRUPTION": return `${esc(p.region)}: ${esc(p.reason)}, ${p.affected ?? ""} shipments hit`;
    default: return name || `Shipment ${e.shipment_id}`;
  }
}
function addFeed(events, animate) {
  if (state.paused) return;
  const feed = $("#feed");
  const html = events.slice(-60).reverse().map((e) => {
    const hot = ["DELAYED", "TEMP_EXCURSION", "REGION_DISRUPTION"].includes(e.type) && (isEssential(e.goods) || e.type !== "DELAYED");
    return `<div class="feed-item ${animate ? "enter" : ""} ${hot ? "alert" : ""}" data-sid="${e.shipment_id}">
      <div class="feed-time">${esc(fmtTime(e.sim_ts))}</div>
      <div><span class="feed-type t-${esc(e.type)}">${esc(TYPE_LABEL[e.type] || e.type)}</span>${isEssential(e.goods) ? goodsChip(e.goods) : ""}${e.scenario ? ` <span class="chip scn">${esc(e.scenario)}</span>` : ""}
      <span class="feed-text">${feedText(e)}</span></div></div>`;
  }).join("");
  feed.insertAdjacentHTML("afterbegin", html);
  $$(".feed-item", feed).slice(120).forEach((el) => el.remove());
  $$(".feed-item", feed).forEach((el) => { el.onclick = () => { const s = +el.dataset.sid; if (s) openDrawer(s); }; });
}

async function pollUpdates() {
  const c = state.cursor;
  const q = c ? `?ev=${c.ev}&al=${c.al}&an=${c.an}` : "?ev=-1&al=-1&an=-1";
  const d = await api(`/api/updates${q}`);
  state.cursor = d.cursor;
  if (d.events.length) addFeed(d.events, !d.init);
  if (d.init) return;
  const many = d.alerts.filter((a) => a.verdict !== "DISMISS").length > 4;
  d.alerts.forEach((a) => onAlert(a, many));
  d.anomalies.forEach(onAnomaly);
  d.events.filter((e) => e.type === "REGION_DISRUPTION").forEach(onDisruption);
}

/* ---------- summary, KPIs, banner ---------- */
function kpi(label, value, note, cls = "") { return { label, value: String(value), note, cls }; }
async function loadSummary() {
  const s = await api("/api/summary");
  if (state.summary && s.events_processed + 5 < state.summary.events_processed) { // replay was restarted
    state.cursor = null; $("#feed").innerHTML = ""; state.seenRisk.clear();
  }
  if (s.events_processed !== state.lastProcessed) { state.lastChange = Date.now(); state.lastProcessed = s.events_processed; }
  state.summary = s;
  const live = !s.finished && Date.now() - state.lastChange < 5000 && s.events_processed > 0;
  $("#liveDot").classList.toggle("on", live);
  $("#simClock").textContent = s.events_processed ? `${fmtTime(s.sim_clock)}${s.finished ? " · replay finished" : live ? " · live" : " · paused"}` : "Waiting for replay";
  const arch = (s.platform || "").split("|")[0].trim();
  const badge = $("#platformBadge");
  badge.textContent = arch === "s390x" ? "IBM LinuxONE · s390x" : arch ? `Local machine · ${arch}` : "Platform unknown";
  badge.title = s.platform || "";
  $("#feedRate").textContent = `${s.events_per_sec} events per second · ${s.events_processed.toLocaleString()} of ${s.events_total.toLocaleString()}`;

  const cards = [
    kpi("Events per second", s.events_per_sec, `${s.events_processed.toLocaleString()} scored so far`),
    kpi("Essential goods at risk", s.medical_at_risk, `above ${pct(s.threshold)} breach risk`, s.medical_at_risk ? "red" : ""),
    kpi("Value at risk", money(s.value_at_risk), `${s.open_shipments} open shipments`),
    kpi("Waiting for approval", s.approvals_pending, "one click approval", s.approvals_pending ? "amber" : ""),
    kpi("False alarms dismissed", s.dismissed, `${s.confirmed} alerts confirmed by GenAI`),
    kpi("Scoring time", `${s.avg_ms} ms`, `per new order on ${arch || "this machine"}`),
  ];
  const box = $("#kpis");
  if (!box.children.length) box.innerHTML = cards.map(() => `<div class="kpi"><div class="kpi-label"></div><div class="kpi-value"></div><div class="kpi-note"></div></div>`).join("");
  [...box.children].forEach((el, i) => {
    const c = cards[i];
    const v = $(".kpi-value", el);
    if (v.textContent !== c.value && v.textContent !== "") { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
    el.className = `kpi ${c.cls}`;
    $(".kpi-label", el).textContent = c.label; v.textContent = c.value; $(".kpi-note", el).textContent = c.note;
  });

  const d = s.disruption;
  const banner = $("#banner");
  if (d && d.at !== state.bannerDismissed) {
    $("#bannerText").textContent = `Regional disruption in ${d.region}: ${d.affected} open shipments delayed at ${fmtTime(d.at)}. Priorities recalculated, essential goods first.`;
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
}

/* ---------- shipments at risk ---------- */
async function loadRisk() {
  const f = state.filter;
  const q = f === "scenarios" ? "?scope=scenarios" : f === "essential" ? "?goods=essential" : "";
  const list = await api(`/api/risk${q}`);
  const tb = $("#riskTable tbody");
  $("#riskEmpty").classList.toggle("hidden", list.length > 0);
  tb.innerHTML = list.map((r) => {
    const fresh = !state.seenRisk.has(r.shipment_id) && state.seenRisk.size > 0;
    return `<tr class="${isEssential(r.goods) ? "crit" : ""} ${fresh ? "new" : ""}" data-sid="${r.shipment_id}">
      <td><div class="cell-main">${esc(r.product_name || "Shipment")}</div>
          <div class="cell-sub">#${r.shipment_id} · ${esc(r.ship_mode)} · ${esc(r.region)} ${r.scenario ? `<span class="chip scn">${esc(r.scenario)}</span>` : ""}</div></td>
      <td>${goodsChip(r.goods)}<div class="cell-sub">criticality ${r.criticality}/5</div></td>
      <td><div class="cell-main">${esc(r.supplier_name)}</div><div class="cell-sub">score ${r.supplier_score ?? "–"}</div></td>
      <td>${miniBand(r)}</td>
      <td><b style="color:${r.breach_prob >= (state.summary?.threshold ?? 0.7) ? "var(--red)" : "inherit"}">${pct(r.breach_prob)}</b></td>
      <td>${pbar(r.priority)}</td>
      <td>${statusCell(r)}</td></tr>`;
  }).join("");
  if (state.seenRisk.size === 0 || list.length) list.forEach((r) => state.seenRisk.add(r.shipment_id));
  $$("tr", tb).forEach((tr) => { tr.onclick = () => openDrawer(+tr.dataset.sid); });
}

/* ---------- scenarios ---------- */
async function loadScenarios() {
  const list = await api("/api/scenarios");
  const grid = $("#scenarioGrid");
  if (!list.length) { grid.innerHTML = `<div class="card empty">No scenarios in this run. Start the replay without --no-scenarios.</div>`; return; }
  grid.innerHTML = list.map((sc) => {
    const done = sc.rows.length === sc.shipment_ids.length && sc.rows.every((r) => ["DELIVERED", "CANCELED"].includes(r.status));
    const st = !sc.rows.length ? ["Waiting", ""] : done ? ["Complete", "done"] : ["Live", "live"];
    const rowsHtml = sc.rows.length ? sc.rows.map((r) => `
      <div class="scn-row" data-sid="${r.shipment_id}">
        <div class="scn-main"><div class="scn-name-line"><span class="cell-main">${esc(r.product_name)}</span> ${goodsChip(r.goods)}</div>
             <div class="scn-meta">${esc(r.supplier_name)} · score ${r.supplier_score ?? "–"} · stock cover ${(+r.inventory_cover).toFixed(1)} d</div>
             <div class="scn-meta">${r.verdict ? `<span class="chip ${esc(r.verdict)}">${esc(r.verdict.toLowerCase())}</span> ` : ""}${esc(ACTION[r.recommended_action] || "")}${r.requires_approval ? " · needs approval" : ""}</div></div>
        <div class="scn-prio"><div class="cell-sub">priority</div>${pbar(r.priority)}</div>
      </div>`).join("") : `<div class="scn-wait">Waiting for these shipments to arrive in the stream</div>`;
    return `<div class="scn-card">
      <div class="scn-top"><span class="scn-id">${esc(sc.id)}</span><span class="scn-name">${esc(sc.name)}</span><span class="scn-state ${st[1]}">${st[0]}</span></div>
      <p class="scn-story">${esc(sc.story)}</p>
      <div class="scn-expected"><b>Expected:</b> ${esc(sc.expected)}</div>
      <div>${rowsHtml}</div></div>`;
  }).join("");
  $$(".scn-row", grid).forEach((el) => { el.onclick = () => openDrawer(+el.dataset.sid); });
}

/* ---------- suppliers ---------- */
async function loadSuppliers() {
  const list = await api("/api/suppliers");
  $("#supplierTable tbody").innerHTML = list.map((s, i) => `
    <tr><td>${i + 1}</td><td><div class="cell-main">${esc(s.name)}</div><div class="cell-sub">${esc(s.department)}</div></td>
      <td>${(s.n_orders || 0).toLocaleString()}</td><td>${pct(s.on_time_rate)}</td><td>${pct(s.quality_rate)}</td>
      <td>${scoreBar(s.score)}</td></tr>`).join("");
  drawSupplierChart(list);
}
function drawSupplierChart(list) {
  const W = 640, H = 380, m = { l: 48, r: 20, t: 16, b: 44 };
  if (!list.length) { $("#supplierChart").innerHTML = `<div class="empty">No suppliers yet</div>`; return; }
  const maxN = Math.max(...list.map((s) => s.n_orders || 0), 10);
  const lx = (n) => Math.log10((n || 0) + 1);
  const minS = Math.min(50, Math.floor(Math.min(...list.map((s) => s.score)) / 10) * 10);
  const X = (n) => m.l + (lx(n) / lx(maxN)) * (W - m.l - m.r);
  const Y = (s) => m.t + (1 - (s - minS) / (100 - minS)) * (H - m.t - m.b);
  let g = "";
  for (let s = minS; s <= 100; s += 10) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(s)}" y2="${Y(s)}" stroke="#eef1f5"/><text x="${m.l - 8}" y="${Y(s) + 4}" text-anchor="end" font-size="11" fill="#8a93a3">${s}</text>`;
  [1, 10, 100, 1000, 10000].filter((n) => n <= maxN * 1.2).forEach((n) => {
    g += `<line x1="${X(n)}" x2="${X(n)}" y1="${m.t}" y2="${H - m.b}" stroke="#eef1f5"/><text x="${X(n)}" y="${H - m.b + 16}" text-anchor="middle" font-size="11" fill="#8a93a3">${n.toLocaleString()}</text>`;
  });
  g += `<text x="${(W + m.l) / 2}" y="${H - 6}" text-anchor="middle" font-size="11.5" fill="#5d6779">Delivered orders (log scale)</text>
        <text transform="translate(13 ${(H - m.b) / 2}) rotate(-90)" text-anchor="middle" font-size="11.5" fill="#5d6779">Supplier score</text>`;
  const pts = list.map((s) => {
    const demo = String(s.supplier_id).startsWith("SUPM");
    const c = demo ? "#da1e28" : "#0f62fe";
    const right = X(s.n_orders) > W * 0.6;
    const label = demo ? `<text x="${X(s.n_orders) + (right ? -10 : 10)}" y="${Y(s.score) + 4}" text-anchor="${right ? "end" : "start"}" font-size="11.5" font-weight="600" fill="#161b26">${esc(s.name)} · ${(+s.score).toFixed(1)}</text>` : "";
    return `<g><title>${esc(s.name)}: score ${s.score}, ${s.n_orders} orders</title><circle cx="${X(s.n_orders)}" cy="${Y(s.score)}" r="${demo ? 6 : 4.5}" fill="${c}" fill-opacity="${demo ? 0.9 : 0.35}" stroke="${c}"/>${label}</g>`;
  }).join("");
  $("#supplierChart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Supplier score against order history">${g}${pts}</svg>
    <div class="chips" style="margin-top:6px"><span class="chip medicine">Demo scenario suppliers</span><span class="chip scn">Suppliers derived from the dataset</span></div>`;
}

/* ---------- anomalies and platform ---------- */
async function loadAnomalies() {
  const list = await api("/api/anomalies");
  $("#anomalyTable tbody").innerHTML = list.length ? list.map((n) => `
    <tr data-sid="${n.shipment_id}"><td class="mono">${esc(fmtTime(n.sim_ts))}</td>
      <td><span class="chip ${n.kind === "temperature_excursion" ? "medicine" : "DOWNGRADE"}">${esc(ANOMALY[n.kind] || n.kind)}</span></td>
      <td><div class="cell-main">${esc(n.product_name || "")}</div><div class="cell-sub">#${n.shipment_id} · ${esc(n.supplier_name || "")}</div></td>
      <td>${esc(n.detail)}</td></tr>`).join("") : `<tr><td colspan="4" class="empty">No anomalies yet</td></tr>`;
  $$("#anomalyTable tbody tr[data-sid]").forEach((tr) => { tr.onclick = () => openDrawer(+tr.dataset.sid); });
}
async function loadPlatform() {
  const p = await api("/api/platform");
  const parts = (p.platform || "").split("|").map((x) => x.trim());
  $("#platformFacts").innerHTML = `<dt>Architecture</dt><dd>${esc(parts[0] || "")}</dd><dt>Operating system</dt><dd>${esc(parts[1] || "")}</dd>
    <dt>Runtime</dt><dd>${esc(parts[2] || "")}</dd><dt>Model backend</dt><dd>${esc(p.backend)}</dd>`;
  $("#timingTable tbody").innerHTML = p.by_type.map((t) => `<tr><td><span class="feed-type t-${esc(t.type)}">${esc(TYPE_LABEL[t.type] || t.type)}</span></td>
    <td>${t.n.toLocaleString()}</td><td class="mono">${t.avg_ms}</td><td class="mono">${t.max_ms}</td></tr>`).join("");
  $("#sourceList").innerHTML = p.sources.map((s) => `<span class="chip ${s.source === "rule" ? "other" : "scn"}">${esc(s.source || "none")}: ${s.n}</span>`).join("") || `<span class="muted">No alerts yet</span>`;
}

/* ---------- drawer ---------- */
function bandSvg(s) {
  const due = daysBetween(s.order_ts, s.promised_ts);
  const max = Math.ceil(Math.max(s.eta_p90, due) + 1);
  const W = 680, H = 92, l = 20, r = 20;
  const X = (d) => l + (d / max) * (W - l - r);
  let ticks = "";
  for (let d = 0; d <= max; d++) ticks += `<line x1="${X(d)}" x2="${X(d)}" y1="56" y2="61" stroke="#c1c7d0"/><text x="${X(d)}" y="76" font-size="11" text-anchor="middle" fill="#8a93a3">${d}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%">
    <line x1="${l}" x2="${W - r}" y1="56" y2="56" stroke="#c1c7d0"/>${ticks}
    <rect x="${X(s.eta_p10)}" y="30" width="${Math.max(2, X(s.eta_p90) - X(s.eta_p10))}" height="18" rx="9" fill="#a6c8ff"/>
    <line x1="${X(s.eta_p50)}" x2="${X(s.eta_p50)}" y1="24" y2="54" stroke="#0f62fe" stroke-width="3"/>
    <text x="${X(s.eta_p50)}" y="18" font-size="11.5" text-anchor="middle" fill="#0f62fe" font-weight="600">likely ${(+s.eta_p50).toFixed(1)} d</text>
    <line x1="${X(due)}" x2="${X(due)}" y1="10" y2="56" stroke="#da1e28" stroke-dasharray="4 3" stroke-width="2"/>
    <text x="${X(due) + 6}" y="44" font-size="11" fill="#da1e28">promised ${due.toFixed(1)} d</text>
    <text x="${W / 2}" y="90" font-size="11" text-anchor="middle" fill="#5d6779">Days after order · band shows early (P10) to late (P90)</text></svg>`;
}
function card(title, inner, sub = "") { return `<div class="card"><div class="card-head"><div><h2>${title}</h2>${sub ? `<p class="muted">${sub}</p>` : ""}</div></div>${inner}</div>`; }

async function openDrawer(sid) {
  state.drawerId = sid;
  $("#drawer").classList.add("open"); $("#scrim").classList.remove("hidden");
  $("#drawerBody").innerHTML = `<div class="empty">Loading shipment ${sid}</div>`;
  let d;
  try { d = await api(`/api/shipment/${sid}`); } catch { $("#drawerBody").innerHTML = `<div class="empty">Shipment not found</div>`; return; }
  if (state.drawerId !== sid) return; // closed or switched while loading
  renderDrawer(d);
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.add("hidden"); state.drawerId = null; }

function renderDrawer({ shipment: s, alert: a, events, anomalies }) {
  const thr = state.summary?.threshold ?? 0.7;
  $("#drawerTitle").innerHTML = `<div class="drawer-title">${esc(s.product_name)}</div>
    <div class="drawer-sub">${goodsChip(s.essential_goods_type)} <span>criticality ${s.criticality}/5</span>
    ${s.scenario ? `<span class="chip scn">Scenario ${esc(s.scenario)}</span>` : ""}
    <span>· #${s.shipment_id} · ${esc(s.ship_mode)} · ${esc(s.region)}</span></div>`;

  const pd = s.priority_detail || {};
  const factors = [["Breach risk", pd.breach, 1], ["Criticality", pd.criticality, 1], ["Stockout", pd.stockout, 1], ["Urgency", pd.urgency, 1], ["Supplier factor", pd.supplier, 1.25]]
    .filter((f) => f[1] !== undefined)
    .map(([n, v, max]) => `<div class="factor"><span>${n}</span><div class="factor-track"><div class="factor-fill" style="width:${(v / max) * 100}%"></div></div><span class="mono">${(+v).toFixed(2)}</span></div>`).join("");

  const drivers = (s.drivers || []);
  const dmax = Math.max(...drivers.map((x) => Math.abs(x.contribution)), 0.001);
  const dHtml = drivers.map((x) => {
    const w = (Math.abs(x.contribution) / dmax) * 50;
    const pos = x.contribution >= 0;
    return `<div class="driver"><span>${esc(x.label)} = <b>${esc(x.value)}</b></span>
      <div class="driver-track"><div class="driver-mid"></div><div class="driver-fill" style="${pos ? `left:50%` : `left:${50 - w}%`};width:${w}%;background:${pos ? "var(--red)" : "var(--green)"}"></div></div>
      <span class="mono" style="text-align:right">${x.contribution > 0 ? "+" : ""}${(+x.contribution).toFixed(3)}</span></div>`;
  }).join("") || `<div class="empty">No drivers recorded</div>`;

  let alertHtml = card("GenAI review", `<div class="empty">No alert raised. Risk stayed below the ${pct(thr)} threshold and no anomaly was found.</div>`);
  if (a) {
    const ev = Object.fromEntries((a.evidence || []).map((e) => [e.id, e.text]));
    const opts = (a.options || []).map((o) => `<div class="opt ${o.action === a.recommended_action ? "best" : ""}">
        <span><b>${esc(ACTION[o.action] || o.action)}</b><div class="cell-sub">${esc(o.detail)}</div></span>
        <span class="mono">${pct(o.breach_prob_after)}</span><span class="mono">${(+o.days_saved).toFixed(1)} d</span><span class="mono">${(+o.net_value).toFixed(0)}</span></div>`).join("");
    const cites = (a.citations || []).map((c) => `<div class="cite"><code>${esc(c)}</code><span>${esc(ev[c] || "not in evidence")}</span></div>`).join("");
    const needs = a.requires_approval && a.status === "OPEN";
    const statusChip = a.status === "APPROVED" || a.status === "REJECTED" ? `<span class="chip ${a.status}">${a.status === "APPROVED" ? "Approved" : "Rejected"}</span>` : `<span class="cell-sub">status ${esc(a.status.toLowerCase())}</span>`;
    alertHtml = `
      ${needs ? `<div class="approve-bar"><span>${esc(ACTION[a.recommended_action] || a.recommended_action)} needs one click approval</span>
        <button class="btn danger" id="rejectBtn">Reject</button><button class="btn primary" id="approveBtn">Approve</button></div>` : ""}
      ${card("GenAI review", `
        <div class="verdict"><span class="chip ${esc(a.verdict)}">${esc(a.verdict)}</span><span class="cell-sub">reviewed by ${esc(a.source || "rule")} in ${(+a.llm_ms).toFixed(0)} ms</span>${statusChip}</div>
        <p style="margin:10px 0 4px"><b>Root cause:</b> ${esc(a.root_cause)}</p>
        <p style="margin:0 0 10px"><b>Recommended:</b> ${esc(ACTION[a.recommended_action] || a.recommended_action)}. ${esc(a.justification)}</p>
        <h3 class="sub">Citations, each checked against the evidence packet</h3>${cites}`)}
      ${card("Options, rescored counterfactually", `<div class="opt head"><span>Option</span><span>Risk after</span><span>Days saved</span><span>Net value</span></div>${opts}`, "The same models rescore the shipment under each option")}
      ${card("Draft email", `<div class="email">${esc(a.draft_email)}</div><div style="margin-top:8px"><button class="btn" id="copyEmail">Copy</button></div>`, "Drafted automatically for the supplier or carrier")}`;
  }
  const tl = [...events.map((e) => ({ t: e.sim_ts, k: TYPE_LABEL[e.type] || e.type, type: e.type, x: feedText({ ...e, product_name: "" }).replace(/^\s+/, "") })),
    ...anomalies.map((n) => ({ t: n.sim_ts, k: ANOMALY[n.kind] || n.kind, type: "TEMP_EXCURSION", x: n.detail }))]
    .sort((x, y) => (x.t > y.t ? 1 : -1))
    .map((e) => `<div class="tl"><span class="mono">${esc(fmtTime(e.t))}</span><span><span class="feed-type t-${esc(e.type)}">${esc(e.k)}</span></span><span>${esc(e.x)}</span></div>`).join("");

  $("#drawerBody").innerHTML = `
    <div class="stat-row">
      <div class="stat"><div class="stat-label">Breach probability</div><div class="stat-value ${s.breach_prob >= thr ? "red" : ""}">${pct(a ? a.breach_prob : s.breach_prob)}</div></div>
      <div class="stat"><div class="stat-label">Priority</div><div class="stat-value">${(+(a ? a.priority : s.priority)).toFixed(3)}</div></div>
      <div class="stat"><div class="stat-label">Supplier score</div><div class="stat-value">${s.supplier_score ?? "–"}</div><div class="cell-sub">${esc(s.supplier_name)}</div></div>
      <div class="stat"><div class="stat-label">Inventory cover</div><div class="stat-value">${(+s.inventory_cover).toFixed(1)} d</div><div class="cell-sub">simulated estimate</div></div>
    </div>
    ${card("Delivery forecast", bandSvg(s), `Updated with every event. Promised by ${esc(fmtTime(s.promised_ts))}`)}
    ${alertHtml}
    ${card("Why this priority", factors || `<div class="empty">No breakdown recorded</div>`, `Priority ${(+s.priority).toFixed(3)} = breach × criticality × stockout × urgency × supplier factor`)}
    ${card("Model drivers", dHtml, "Red pushes risk up, green pulls it down")}
    ${card("Event timeline", `<div class="timeline">${tl}</div>`)}`;

  const act = async (kind) => {
    let r;
    try { r = await api(`/api/alerts/${a.alert_id}/${kind}`, { method: "POST" }); } catch {
      toast({ title: "Could not save", body: "The database was busy. Please try again.", cls: "amber" }); return;
    }
    toast({ title: kind === "approve" ? "Action approved" : "Action rejected", body: `${esc(ACTION[a.recommended_action] || a.recommended_action)} for ${esc(s.product_name)}`, cls: kind === "approve" ? "green" : "" });
    if (r.changed && state.drawerId === s.shipment_id) openDrawer(s.shipment_id);
    loadSummary(); loadRisk();
  };
  if ($("#approveBtn")) $("#approveBtn").onclick = () => act("approve");
  if ($("#rejectBtn")) $("#rejectBtn").onclick = () => act("reject");
  if ($("#copyEmail")) $("#copyEmail").onclick = () => { navigator.clipboard?.writeText(a.draft_email); $("#copyEmail").textContent = "Copied"; };
}

/* ---------- wiring ---------- */
const LOADERS = { overview: loadRisk, scenarios: loadScenarios, suppliers: loadSuppliers, anomalies: loadAnomalies, platform: loadPlatform };
function showTab(t) {
  state.tab = t;
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${t}`));
  safe(LOADERS[t]);
}
async function safe(fn) {
  try { await fn(); state.failures = 0; } catch (e) {
    state.failures += 1;
    if (state.failures > 3) { $("#simClock").textContent = "Disconnected, retrying"; $("#liveDot").classList.remove("on"); }
  }
}

$$(".tab").forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });
$$("#riskFilter .seg-btn").forEach((b) => {
  b.onclick = () => { state.filter = b.dataset.f; state.seenRisk.clear(); $$("#riskFilter .seg-btn").forEach((x) => x.classList.toggle("active", x === b)); safe(loadRisk); };
});
$("#pauseFeed").onclick = () => { state.paused = !state.paused; $("#pauseFeed").textContent = state.paused ? "Resume" : "Pause"; };
$("#soundBtn").onclick = () => {
  state.sound = !state.sound;
  $("#soundBtn").classList.toggle("on", state.sound);
  $("#soundWaves").setAttribute("opacity", state.sound ? "1" : ".25");
  $("#soundBtn").title = `Sound for critical alerts: ${state.sound ? "on" : "off"}`;
  if (state.sound) beep();
};
$("#bellBtn").onclick = () => { $("#history").classList.toggle("hidden"); state.unread = 0; renderBell(); };
$("#clearHistory").onclick = () => { state.history = []; state.unread = 0; renderBell(); };
$("#bannerClose").onclick = () => { state.bannerDismissed = state.summary?.disruption?.at; $("#banner").classList.add("hidden"); };
$("#drawerClose").onclick = closeDrawer;
$("#scrim").onclick = closeDrawer;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
document.addEventListener("click", (e) => {
  const h = $("#history");
  if (!h.classList.contains("hidden") && !h.contains(e.target) && !$("#bellBtn").contains(e.target)) h.classList.add("hidden");
});

(async function start() {
  await safe(loadSummary);
  await safe(pollUpdates);
  showTab("overview");
  setInterval(() => safe(pollUpdates), 1500);
  setInterval(() => safe(loadSummary), 2000);
  setInterval(() => { if (state.tab !== "platform") safe(LOADERS[state.tab]); }, 3000);
  setInterval(() => { if (state.tab === "platform") safe(loadPlatform); }, 6000);
})();
