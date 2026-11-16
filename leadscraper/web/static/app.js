/* LeadScraper dashboard. Builds one model from the server's event stream
   (live, or replayed after a reload) or from a past run's saved states. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hostOf = (url) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url || ""; } };
const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
const fmtDur = (s) => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

const S = {
  meta: null,
  steps: [],
  stepIndex: {},
  leads: new Map(),
  run: null,
  runEndTs: null,
  mode: "live", // live | replay
  filter: "all",
  sources: {},
  selected: null,
  es: null,
  dirty: false,
};

/* ---------------- model ---------------- */

function resetModel() {
  S.leads.clear();
  S.sources = {};
  S.run = null;
  S.runEndTs = null;
  chipStation.clear();
  $("#ledger").replaceChildren();
  rowEls.clear();
  $("#feed").replaceChildren();
}

function newLead(ref) {
  return {
    id: ref.id, name: ref.name, website: ref.website, source: ref.source,
    status: "queued", current: S.steps[0]?.node, completed: [], stoppedAt: null,
    reason: "", state: { lead: ref }, row: null, order: S.leads.size,
  };
}

function stepLabel(node) {
  const s = S.steps[S.stepIndex[node]];
  return s ? `${s.num} ${s.label}` : node;
}

function nodeSummary(node, u) {
  switch (node) {
    case "assess_business": return u.assessment ? `${u.assessment.business_type}, ${u.assessment.worth_pursuing ? "worth pursuing" : "not a fit"}` : "";
    case "find_documentation": return u.docs?.doc_url ? `docs at ${hostOf(u.docs.doc_url)}${new URL(u.docs.doc_url).pathname.replace(/\/$/, "")} (score ${u.docs.score})` : `best score ${u.docs?.score ?? 0}`;
    case "collect_contacts": { const r = u.raw_contacts || {}; return `${Object.keys(r.emails || {}).length} emails, ${Object.keys(r.phones || {}).length} phones in ${(r.pages_visited || []).length} pages`; }
    case "purify_contacts": { const c = u.contacts || {}; return `kept ${(c.emails || []).length} emails, ${(c.phone_numbers || []).length} phones`; }
    case "research_company": { const r = u.research || {}; return `${(r.people || []).length} people, ${(r.signals || []).length} intent signals${r.recipient ? `, write to ${r.recipient.name}` : ""}`; }
    case "analyze_documentation": return u.doc_analysis ? `docs scored ${u.doc_analysis.overall_score}/10` : "";
    case "generate_report": return u.report ? `lead score ${u.report.lead_score}/100` : "";
    default: return "";
  }
}

function applyNode(lead, node, update) {
  Object.assign(lead.state, update);
  if (!lead.completed.includes(node)) lead.completed.push(node);
  const st = update.status;
  if (st && st !== "running") {
    lead.status = st;
    lead.current = null;
    if (st !== "qualified") { lead.stoppedAt = node; lead.reason = update.skip_reason || ""; }
  } else {
    lead.status = "running";
    const next = S.steps[S.stepIndex[node] + 1];
    lead.current = next ? next.node : null;
  }
}

function handle(ev) {
  switch (ev.type) {
    case "run_started":
      resetModel();
      S.run = ev.run;
      for (const name of ev.run.sources?.length ? ev.run.sources : (ev.run.kind === "batch" ? S.meta.sources.filter((s) => s.enabled).map((s) => s.name) : []))
        S.sources[name] = { phase: "waiting", count: 0 };
      feed(ev.ts, ev.run.kind === "audit" ? `<span class="sig">Single-site audit started</span>` : `<span class="sig">Run started</span> <b>${esc(ev.run.id)}</b>`);
      break;
    case "source":
      S.sources[ev.source] = { phase: ev.phase, count: ev.count };
      if (ev.phase === "start") feed(ev.ts, `Collecting from <b>${esc(ev.source)}</b>`);
      else feed(ev.ts, `<span class="${ev.phase === "done" ? "ok" : "err"}">${esc(ev.source)}: ${ev.phase === "done" ? `${ev.count} leads` : "failed"}</span>`);
      break;
    case "lead_queued":
      if (!S.leads.has(ev.lead.id)) S.leads.set(ev.lead.id, newLead(ev.lead));
      feed(ev.ts, `Queued <b>${esc(hostOf(ev.lead.website))}</b> <span class="hint">from ${esc(ev.lead.source)}</span>`);
      break;
    case "lead_started": {
      const l = S.leads.get(ev.id); if (l) { l.status = "running"; l.current = S.steps[0].node; }
      break;
    }
    case "lead_node": {
      const l = S.leads.get(ev.id); if (!l) break;
      applyNode(l, ev.node, ev.update);
      const host = esc(hostOf(l.website));
      const sum = esc(nodeSummary(ev.node, ev.update));
      if (l.status === "skipped") feed(ev.ts, `<b>${host}</b> <span class="drop">dropped at ${esc(stepLabel(ev.node))}</span>: ${esc(l.reason)}`);
      else if (l.status === "error") feed(ev.ts, `<b>${host}</b> <span class="err">error at ${esc(stepLabel(ev.node))}</span>: ${esc(l.reason)}`);
      else if (l.status === "qualified") feed(ev.ts, `<b>${host}</b> <span class="ok">qualified</span>, ${sum}`);
      else feed(ev.ts, `<b>${host}</b> ${esc(stepLabel(ev.node))}: ${sum}`);
      break;
    }
    case "lead_done": {
      let l = S.leads.get(ev.id);
      if (!l) { l = newLead({ id: ev.id, ...ev.state.lead }); S.leads.set(ev.id, l); }
      l.state = ev.state; l.row = ev.row; l.status = ev.row.status; l.current = null;
      if (l.status !== "qualified") { l.stoppedAt = ev.state.stage; l.reason = ev.state.skip_reason || ""; }
      l.completed = S.steps.map((s) => s.node).filter((n) => ev.state.timings && n in ev.state.timings);
      if (S.selected === l.id) renderDossier();
      break;
    }
    case "run_stopping":
      feed(ev.ts, `<span class="drop">Stopping: no new leads will start</span>`);
      break;
    case "run_finished":
      S.run = ev.run; S.runEndTs = ev.ts;
      feed(ev.ts, ev.run.status === "failed" ? `<span class="err">Run failed: ${esc(ev.run.error)}</span>` : `<span class="ok">Run ${esc(ev.run.status)}</span>`);
      loadHistory();
      break;
    case "log":
      if (ev.level === "warning" || ev.level === "error" || /browser|challenge|rate limit/i.test(ev.message))
        feed(ev.ts, `<span class="${esc(ev.level)}">${esc(ev.logger)}</span> ${esc(ev.message)}`);
      break;
  }
  S.dirty = true;
}

/* ---------------- feed ---------------- */

function feed(ts, html) {
  const li = document.createElement("li");
  li.innerHTML = `<time>${fmtTime(ts)}</time><span class="msg">${html}</span>`;
  const list = $("#feed");
  list.prepend(li);
  while (list.children.length > 250) list.lastElementChild.remove();
}

/* ---------------- rendering ---------------- */

function favHTML(website, name) {
  const host = hostOf(website);
  const letter = esc((name || host || "?").replace(/^[^a-z0-9]+/i, "").charAt(0).toUpperCase());
  return `<span class="fav"><span>${letter}</span><img src="https://${esc(host)}/favicon.ico" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()"></span>`;
}

const CHECK_SVG = `<svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>`;
const chipStation = new Map(); // lead id -> station key, to animate moves

function chipFor(lead, stationKey, cls) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = `lchip ${cls}`;
  el.dataset.id = lead.id;
  el.title = lead.reason ? `${lead.name}: ${lead.reason}` : lead.name;
  el.innerHTML = `${favHTML(lead.website, lead.name)}<span>${esc(hostOf(lead.website))}</span>`;
  if (chipStation.get(lead.id) !== stationKey) {
    el.classList.add("arrive");
    el.addEventListener("animationend", () => el.classList.remove("arrive"), { once: true });
  }
  chipStation.set(lead.id, stationKey);
  return el;
}

function buildTrack() {
  const track = $("#track");
  track.replaceChildren();
  const stations = [...S.steps, { node: "__done", num: "OK", label: "Qualified", desc: "Report and outreach ready to send" }];
  stations.forEach((s, i) => {
    const li = document.createElement("li");
    li.className = "station" + (s.node === "__done" ? " final" : "");
    li.dataset.node = s.node;
    li.innerHTML = `
      <div class="rail"><span class="node-dot">${i + 1 === stations.length ? CHECK_SVG : i + 1}</span></div>
      <div class="station-card">
        <span class="station-num">${s.node === "__done" ? "OUTPUT" : "STEP " + esc(s.num)}</span>
        <h3 class="station-title">${esc(s.label)}</h3>
        <p class="station-desc">${esc(s.desc)}</p>
        <div class="station-counts"></div>
        <div class="lane"></div>
      </div>`;
    track.append(li);
  });
}

function renderTrack() {
  const leads = [...S.leads.values()];
  for (const st of document.querySelectorAll(".station")) {
    const node = st.dataset.node;
    const lane = $(".lane", st);
    let here, html;
    if (node === "__done") {
      here = leads.filter((l) => l.status === "qualified").sort((a, b) => (b.state.report?.lead_score ?? 0) - (a.state.report?.lead_score ?? 0));
      html = `<span><b>${here.length}</b> reported</span>`;
      st.classList.toggle("touched", here.length > 0);
      fillLane(lane, here.map((l) => [l, node, "won"]));
    } else {
      const working = leads.filter((l) => l.current === node && l.status === "running");
      const waiting = leads.filter((l) => l.current === node && l.status === "queued");
      const dropped = leads.filter((l) => l.stoppedAt === node);
      const passed = leads.filter((l) => l.completed.includes(node) && l.stoppedAt !== node).length;
      html = `<span><b>${working.length + waiting.length}</b> here</span><span class="pass"><b>${passed}</b> passed</span><span class="drop"><b>${dropped.length}</b> out</span>`;
      st.classList.toggle("active", working.length > 0);
      st.classList.toggle("touched", passed + dropped.length > 0);
      st.classList.toggle("flowing", passed > 0 && leads.some((l) => l.status === "running" && S.stepIndex[l.current] > S.stepIndex[node]));
      fillLane(lane, [
        ...working.map((l) => [l, node, "working"]),
        ...waiting.map((l) => [l, node, ""]),
        ...dropped.map((l) => [l, node, l.status === "error" ? "err" : "dropped"]),
      ]);
    }
    const counts = $(".station-counts", st);
    if (counts.innerHTML !== html) counts.innerHTML = html;
  }
}

function fillLane(lane, items) {
  const MAX = 9;
  const shown = items.slice(0, MAX);
  const sig = shown.map(([l, , c]) => `${l.id}:${c}`).join("|") + `#${items.length}`;
  if (lane.dataset.sig === sig) return;
  lane.dataset.sig = sig;
  const nodes = shown.map(([l, key, cls]) => chipFor(l, key, cls));
  if (items.length > MAX) {
    const more = document.createElement("span");
    more.className = "lane-more";
    more.textContent = `+${items.length - MAX}`;
    nodes.push(more);
  }
  lane.replaceChildren(...nodes);
}

const rowEls = new Map();

function leadMatches(l) {
  switch (S.filter) {
    case "qualified": return l.status === "qualified";
    case "active": return l.status === "running" || l.status === "queued";
    case "dropped": return l.status === "skipped" || l.status === "error";
    default: return true;
  }
}

function sortLeads(a, b) {
  const rank = (l) => ({ running: 0, queued: 1, qualified: 2, skipped: 3, error: 4 }[l.status] ?? 5);
  return rank(a) - rank(b)
    || (b.state.report?.lead_score ?? -1) - (a.state.report?.lead_score ?? -1)
    || a.order - b.order;
}

function meterHTML(l) {
  const cells = S.steps.map((s) => {
    let c = "";
    if (l.stoppedAt === s.node) c = l.status === "error" ? "fail" : "stop";
    else if (l.completed.includes(s.node)) c = "done";
    else if (l.current === s.node && l.status === "running") c = "now";
    return `<i class="${c}" title="${esc(s.num + " " + s.label)}"></i>`;
  }).join("");
  let label;
  if (l.status === "qualified") label = "report ready";
  else if (l.status === "queued") label = "waiting for a worker";
  else if (l.status === "running") label = `${stepLabel(l.current)}...`;
  else label = l.reason || `stopped at ${stepLabel(l.stoppedAt)}`;
  return `<div class="meter">${cells}</div><div class="meter-label" title="${esc(label)}">${esc(label)}</div>`;
}

function rowHTML(l) {
  const doc = l.state.doc_analysis?.overall_score;
  const ls = l.state.report?.lead_score;
  return `
    <div class="prod">${favHTML(l.website, l.name)}
      <div class="prod-text"><div class="prod-name">${esc(l.name)}</div><div class="prod-sub">${esc(hostOf(l.website))} / ${esc(l.source)}</div></div>
    </div>
    <div>${meterHTML(l)}</div>
    <div class="num"><span class="score ${doc == null ? "dim" : ""}">${doc ?? "-"}</span></div>
    <div class="num lead-score"><span class="score ${ls == null ? "dim" : ""}">${ls ?? "-"}</span>${ls == null ? "" : `<span class="bar"><i style="width:${ls}%"></i></span>`}</div>
    <div><span class="status ${esc(l.status)}">${esc(l.status)}</span></div>`;
}

function renderLedger() {
  const body = $("#ledger");
  const leads = [...S.leads.values()].sort(sortLeads);
  const visible = leads.filter(leadMatches);
  const visibleIds = new Set(visible.map((l) => l.id));
  for (const [id, el] of rowEls) if (!visibleIds.has(id)) { el.remove(); rowEls.delete(id); }
  visible.forEach((l, i) => {
    let el = rowEls.get(l.id);
    const html = rowHTML(l);
    if (!el) {
      el = document.createElement("div");
      el.className = "row";
      el.setAttribute("role", "row");
      el.tabIndex = 0;
      el.dataset.id = l.id;
      el.addEventListener("animationend", () => (el.style.animation = "none"), { once: true });
      rowEls.set(l.id, el);
    }
    if (el._html !== html) { el.innerHTML = html; el._html = html; }
    if (body.children[i] !== el) body.insertBefore(el, body.children[i] || null);
  });
  $("#ledgerEmpty").hidden = leads.length > 0;

  const counts = { all: leads.length, qualified: 0, active: 0, dropped: 0 };
  for (const l of leads) {
    if (l.status === "qualified") counts.qualified++;
    else if (l.status === "running" || l.status === "queued") counts.active++;
    else counts.dropped++;
  }
  for (const b of document.querySelectorAll("#tabs button")) $("span", b).textContent = counts[b.dataset.filter];
}

let shown = {};
function setStat(id, value) {
  const el = document.getElementById(id);
  const text = String(value);
  if (el.textContent === text) return;
  const num = Number(text);
  const prev = Number(shown[id]);
  shown[id] = text;
  if (!Number.isFinite(num) || !Number.isFinite(prev) || !Number.isInteger(num)) { el.textContent = text; return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 500);
    el.textContent = Math.round(prev + (num - prev) * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderStats() {
  const leads = [...S.leads.values()];
  const running = leads.filter((l) => l.status === "running").length;
  const queued = leads.filter((l) => l.status === "queued").length;
  const qualified = leads.filter((l) => l.status === "qualified").length;
  const finished = leads.filter((l) => ["qualified", "skipped", "error"].includes(l.status)).length;
  let emails = 0, phones = 0;
  const docScores = [];
  for (const l of leads) {
    emails += l.state.contacts?.emails?.length || 0;
    phones += l.state.contacts?.phone_numbers?.length || 0;
    if (l.state.doc_analysis) docScores.push(l.state.doc_analysis.overall_score);
  }
  setStat("statCollected", leads.length);
  setStat("statRunning", running);
  setStat("statQualified", qualified);
  setStat("statContacts", emails + phones);
  setStat("statDoc", docScores.length ? (docScores.reduce((a, b) => a + b, 0) / docScores.length).toFixed(1) : "-");
  $("#statQueued").textContent = `${queued} queued`;
  $("#statRate").textContent = finished ? `${Math.round((qualified / finished) * 100)}% of ${finished} finished` : "-";
  $("#statContactSplit").textContent = `${emails} emails, ${phones} phones`;
  const srcCount = new Set(leads.map((l) => l.source)).size;
  $("#statSources").textContent = leads.length ? `from ${srcCount} source${srcCount === 1 ? "" : "s"}` : "no run yet";
  $("#statRunId").textContent = S.run?.id || (S.mode === "replay" ? "saved run" : "-");
  renderElapsed();
}

function renderElapsed() {
  if (S.mode === "replay" || !S.run?.started) { $("#statElapsed").textContent = S.mode === "replay" ? "-" : "0:00"; return; }
  const end = S.runEndTs || Date.now() / 1000;
  $("#statElapsed").textContent = fmtDur(end - S.run.started);
}

function renderSources() {
  const list = $("#sourceStatus");
  const names = S.meta.sources.map((s) => s.name);
  const extra = Object.keys(S.sources).filter((n) => !names.includes(n));
  list.innerHTML = [...S.meta.sources, ...extra.map((n) => ({ name: n, url: "" }))].map((s) => {
    const st = S.sources[s.name];
    const phase = !st ? "idle" : st.phase;
    const label = { idle: "idle", waiting: "waiting", start: "collecting", done: `${st?.count} leads`, error: "failed" }[phase];
    return `<li><span class="sname">${esc(s.name)}</span><span class="sphase ${esc(phase)}">${esc(label)}</span><span class="surl">${esc(s.url)}</span></li>`;
  }).join("");
}

function renderChrome() {
  const running = S.mode === "live" && S.run?.status === "running";
  const badge = $("#liveBadge");
  badge.dataset.state = S.mode === "replay" ? "replay" : running ? "running" : S.run ? "finished" : "idle";
  $("span", badge).textContent = S.mode === "replay" ? "Saved run" : running ? "Live" : S.run ? (S.run.status === "running" ? "Live" : S.run.status[0].toUpperCase() + S.run.status.slice(1)) : "Idle";
  $("#runBtn").disabled = running || !S.meta.has_api_key;
  $("#auditBtn").disabled = running || !S.meta.has_api_key;
  $("#stopBtn").hidden = !running;
}

function render() {
  if (!S.dirty) return;
  S.dirty = false;
  renderTrack();
  renderLedger();
  renderStats();
  renderSources();
  renderChrome();
  if (S.selected) renderDossierLive();
}

/* ---------------- dossier ---------------- */

function dial(score) {
  const r = 44, c = 2 * Math.PI * r;
  const off = score == null ? c : c * (1 - clamp(score, 0, 100) / 100);
  return `<div class="dial"><svg viewBox="0 0 104 104"><circle class="track-c" cx="52" cy="52" r="${r}"/><circle class="val-c" cx="52" cy="52" r="${r}" stroke-dasharray="${c}" stroke-dashoffset="${c}" data-off="${off}"/></svg><b>${score ?? "-"}</b><small>/ 100</small></div>`;
}

function ticks(score) {
  return `<div class="ticks">${Array.from({ length: 10 }, (_, i) => `<i class="${i < score ? "on" : ""} ${score >= 8 ? "hi" : ""}" style="animation-delay:${i * 35}ms"></i>`).join("")}</div>`;
}

function list(items) { return items?.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="small-note">none noted</p>`; }

let dossierSig = "";
function renderDossierLive() {
  const l = S.leads.get(S.selected);
  if (!l) return;
  const sig = `${l.status}|${l.completed.length}|${!!l.row}`;
  if (sig !== dossierSig) renderDossier();
}

function renderDossier() {
  const l = S.leads.get(S.selected);
  if (!l) return;
  dossierSig = `${l.status}|${l.completed.length}|${!!l.row}`;
  const st = l.state;
  const a = st.assessment, d = st.docs, an = st.doc_analysis, r = st.report, c = st.contacts;
  const parts = [];

  parts.push(`<header class="dos-head">${favHTML(l.website, l.name)}
    <div><h2 class="dos-title">${esc(l.name)}</h2>
      <div class="dos-meta"><a href="${esc(st.homepage_url || l.website)}" target="_blank" rel="noopener">${esc(hostOf(st.homepage_url || l.website))}</a>
      <span>/</span><span>${esc(l.source)}</span>${st.lead?.source_url ? `<a href="${esc(st.lead.source_url)}" target="_blank" rel="noopener">listing</a>` : ""}
      <span class="status ${esc(l.status)}">${esc(l.status)}</span></div></div>
    ${dial(r?.lead_score)}</header>`);

  if (l.status === "skipped" || l.status === "error")
    parts.push(`<div class="callout ${l.status === "error" ? "err" : ""}"><b>${l.status === "error" ? "Error" : "Dropped"} at ${esc(stepLabel(l.stoppedAt))}</b>${esc(l.reason)}</div>`);
  else if (l.status === "running" || l.status === "queued")
    parts.push(`<div class="callout work"><b>In progress</b>${l.status === "queued" ? "Waiting for a free worker." : `Now running ${esc(stepLabel(l.current))}. This dossier fills in as each step finishes.`}</div>`);

  if (r) {
    const breakdown = String(r.lead_score_reason || "").split("; ").filter(Boolean).map((p) => {
      const cls = p.startsWith("+") && !p.startsWith("+0") ? "plus" : p.startsWith("-") ? "minus" : "";
      return `<span class="tag ${cls}">${esc(p)}</span>`;
    }).join("");
    parts.push(`<section class="dos-sec"><h4><span class="mono">06</span>Summary</h4><p class="dos-p">${esc(r.executive_summary)}</p>
      <p class="small-note">Lead score = ${esc(r.lead_score)} (deterministic rubric)</p><div class="tags">${breakdown}</div></section>`);
  }

  if (a) {
    parts.push(`<section class="dos-sec"><h4><span class="mono">2.1</span>Qualification</h4>
      <dl class="kv"><dt>Business</dt><dd>${esc(a.business_type)}</dd>
      <dt>Worth pursuing</dt><dd>${a.worth_pursuing ? "Yes" : "No"}${a.likely_has_documentation ? ", has or needs docs" : ""}</dd>
      <dt>Confidence</dt><dd><span class="conf"><i style="--w:${Math.round(a.confidence * 100)}%"></i>${Math.round(a.confidence * 100)}%</span></dd>
      <dt>Reasoning</dt><dd>${esc(a.reasoning)}</dd></dl>
      ${st.header_doc_links?.length ? `<div class="tags">${st.header_doc_links.slice(0, 10).map((x) => `<span class="tag">${esc(x.text || hostOf(x.url))}</span>`).join("")}</div>` : `<p class="small-note">No documentation words in the header navigation.</p>`}
    </section>`);
  }

  if (an) {
    const dims = ["quality", "completeness", "usability"].map((k) => `
      <div class="dim"><span class="dim-name">${k[0].toUpperCase() + k.slice(1)}</span>${ticks(an[k].score)}<span class="dim-score">${an[k].score}</span>
      <span class="dim-why">${esc(an[k].justification)}</span></div>`).join("");
    const m = st.doc_metrics || {};
    parts.push(`<section class="dos-sec"><h4><span class="mono">05</span>Documentation audit</h4>
      <div class="overall"><b>${an.overall_score}<small style="font-size:24px;color:var(--ink-3)">/10</small></b><span>${esc(an.doc_type)}<br>${m.pages_sampled ?? 0} pages sampled, ${m.code_blocks_total ?? 0} code blocks${m.code_languages?.length ? ", " + esc(m.code_languages.join(", ")) : ""}${m.has_search ? ", has search" : ", no search"}</span></div>
      <div class="dims">${dims}</div>
      <div class="cols3"><div class="good"><h5>Strengths</h5>${list(an.strengths)}</div><div class="bad"><h5>Weaknesses</h5>${list(an.weaknesses)}</div><div class="miss"><h5>Missing</h5>${list(an.missing_sections)}</div></div>
    </section>`);
  }

  if (r?.improvements?.length) {
    parts.push(`<section class="dos-sec"><h4><span class="mono">06</span>Recommended improvements</h4><ol class="improvements">${r.improvements.map((i) => `
      <li><div class="imp-top"><span class="prio ${esc(i.priority)}">${esc(i.priority)}</span>${esc(i.area)}</div><div class="imp-issue">${esc(i.issue)}</div><div class="imp-fix">${esc(i.recommendation)}</div></li>`).join("")}</ol></section>`);
  }

  if (c || st.raw_contacts) {
    const items = c ? [...c.emails, ...c.phone_numbers] : [...Object.keys(st.raw_contacts.emails || {}), ...Object.keys(st.raw_contacts.phones || {})];
    const rejected = st.contact_guard?.rejected_by_guard || [];
    const raw = st.raw_contacts || {};
    parts.push(`<section class="dos-sec"><h4><span class="mono">${c ? "04" : "03"}</span>Contacts</h4>
      <div class="contacts">${items.map((x) => `<span class="contact">${esc(x)}<button type="button" data-copy="${esc(x)}">copy</button></span>`).join("") || `<span class="small-note">none found</span>`}</div>
      <p class="small-note">${raw.pages_visited ? `Crawled ${raw.pages_visited.length} pages, regex found ${Object.keys(raw.emails || {}).length} emails and ${Object.keys(raw.phones || {}).length} phones.` : ""}${c ? ` AI kept ${items.length}.` : ""}${rejected.length ? ` Guard blocked: ${esc(rejected.join(", "))}.` : ""}</p>
    </section>`);
  }

  const rs = st.research;
  if (rs) {
    const people = (rs.people || []).map((p) => `<li><b>${esc(p.name)}</b>, ${esc(p.role)}${rs.recipient && rs.recipient.name === p.name ? ` <span class="tag plus">recommended recipient</span>` : ""}
      <br><a class="hint" href="${esc(p.source_url)}" target="_blank" rel="noopener">${esc(p.source_url)}</a></li>`).join("");
    const sigs = (rs.signals || []).map((s) => `<li><b>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title)}</b>
      <span class="hint">${esc(s.date || "undated")}${s.days_ago != null ? `, ${s.days_ago} days ago` : ""}</span><br>${esc(s.summary)} ${esc(s.why_it_matters)}</li>`).join("");
    parts.push(`<section class="dos-sec"><h4><span class="mono">4.5</span>People &amp; intent signals</h4>
      <h5>People named on the site</h5>${people ? `<ul class="plain-list">${people}</ul>` : `<p class="small-note">None named on ${rs.people_pages?.length ? esc(rs.people_pages.map(hostOf).join(", ") + " pages checked") : "the pages checked"}.</p>`}
      <h5>Recent changes</h5>${sigs ? `<ul class="plain-list">${sigs}</ul>` : `<p class="small-note">${rs.changelog_url ? `No docs-relevant entries on ${esc(rs.changelog_url)}.` : "No changelog found."}</p>`}
      ${rs.rejected_by_guard?.length ? `<p class="small-note">Guard blocked (not on the fetched pages): ${esc(rs.rejected_by_guard.join(", "))}.</p>` : ""}
      ${rs.error ? `<p class="small-note">Research error: ${esc(rs.error)}</p>` : ""}</section>`);
  }

  if (r?.outreach) {
    const to = [rs?.recipient ? `${rs.recipient.name} (${rs.recipient.role})` : "", c?.emails?.[0] || ""].filter(Boolean).join(" / ");
    const text = `Subject: ${r.outreach.subject}\n\n${r.outreach.body}`;
    parts.push(`<section class="dos-sec"><h4><span class="mono">06</span>Outreach opener</h4>
      <div class="letter"><button type="button" class="copy" data-copy="${esc(text)}">copy email</button>
        <div class="letter-row"><span>To</span><span>${esc(to || "(no email, phone only)")}</span></div>
        <div class="letter-row"><span>Subject</span><span class="letter-subject">${esc(r.outreach.subject)}</span></div>
        <p class="letter-body">${esc(r.outreach.body)}</p></div></section>`);
  }

  if (d) {
    const cands = (d.candidates || []).slice().sort((x, y) => y.score - x.score).slice(0, 8);
    parts.push(`<section class="dos-sec"><h4><span class="mono">2.2</span>How the docs were found</h4>
      <dl class="kv"><dt>Documentation</dt><dd>${d.doc_url ? `<a href="${esc(d.doc_url)}" target="_blank" rel="noopener">${esc(d.doc_url)}</a>` : "not found"}</dd><dt>Regex score</dt><dd>${d.score}</dd></dl>
      <div class="tags">${(d.signals || []).map((s) => `<span class="tag hot">${esc(s)}</span>`).join("")}</div>
      ${cands.length ? `<table class="candidates"><tbody>${cands.map((x) => `<tr class="${x.url === d.doc_url ? "best" : ""}"><td>${x.score}</td><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a><br><span class="hint">${esc(x.reason)}</span></td></tr>`).join("")}</tbody></table>` : ""}
    </section>`);
  }

  if (st.timings && Object.keys(st.timings).length) {
    const max = Math.max(...Object.values(st.timings), 0.1);
    parts.push(`<section class="dos-sec"><h4><span class="mono">t</span>Step timings</h4><div class="timings">${Object.entries(st.timings).map(([n, v]) => `
      <div class="timing"><span>${esc(stepLabel(n))}</span><span class="t-bar"><i style="width:${(v / max) * 100}%"></i></span><span class="t-v">${v.toFixed(1)}s</span></div>`).join("")}</div></section>`);
  }

  const body = $("#dossier");
  body.innerHTML = parts.join("");
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const v = $(".val-c", body);
    if (v) v.style.strokeDashoffset = v.dataset.off;
  }));
}

function openDossier(id) {
  S.selected = id;
  renderDossier();
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  $("#drawer").scrollTop = 0;
}

function closeDossier() {
  S.selected = null;
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
}

/* ---------------- data loading ---------------- */

function connectLive() {
  if (S.es) S.es.close();
  S.mode = "live";
  resetModel();
  S.dirty = true;
  S.es = new EventSource("/api/events");
  S.es.onmessage = (m) => handle(JSON.parse(m.data));
}

async function loadReplay(runId) {
  if (S.es) { S.es.close(); S.es = null; }
  S.mode = "replay";
  resetModel();
  const data = await api(`/api/history/${encodeURIComponent(runId)}`);
  S.run = { id: runId, status: "finished" };
  const rows = new Map(data.rows.map((r) => [r.website, r]));
  Object.entries(data.states).forEach(([id, st]) => {
    const l = newLead({ id, ...st.lead });
    l.state = st;
    l.row = rows.get(st.lead.website) || null;
    l.status = st.status;
    l.current = null;
    l.completed = S.steps.map((s) => s.node).filter((n) => st.timings && n in st.timings);
    if (st.status !== "qualified") { l.stoppedAt = st.stage; l.reason = st.skip_reason || ""; }
    S.leads.set(id, l);
    const src = st.lead.source;
    S.sources[src] = { phase: "done", count: (S.sources[src]?.count || 0) + 1 };
  });
  feed(Date.now() / 1000, `Viewing saved run <b>${esc(runId)}</b>`);
  S.dirty = true;
}

async function loadHistory() {
  const runs = await api("/api/history").catch(() => []);
  const sel = $("#historySelect");
  const current = sel.value || "live";
  sel.innerHTML = `<option value="live">Live session</option>` + runs.map((r) =>
    `<option value="${esc(r.id)}">${esc(r.id.replace(/^run-(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d).*/, "$1-$2-$3 $4:$5"))}  (${r.qualified}/${r.total})</option>`).join("");
  sel.value = [...sel.options].some((o) => o.value === current) ? current : "live";
}

async function api(url, body) {
  const res = await fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

function showError(msg) {
  const el = $("#formError");
  el.textContent = msg;
  el.hidden = !msg;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 1800);
}

/* ---------------- controls ---------------- */

function buildControls() {
  $("#sourcePills").innerHTML = S.meta.sources.map((s) => `
    <label class="pill"><input type="checkbox" name="source" value="${esc(s.name)}" ${s.enabled ? "checked" : ""}>
      <span class="tick"><svg viewBox="0 0 12 12"><path d="M2.5 6.2l2.3 2.3 4.7-5"/></svg></span>
      ${esc(s.name)} <small>${esc(s.adapter)}</small></label>`).join("");

  for (const st of document.querySelectorAll(".stepper")) {
    const out = $("output", st);
    st.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-delta]");
      if (!b) return;
      const v = clamp(Number(st.dataset.value) + Number(b.dataset.delta), Number(st.dataset.min), Number(st.dataset.max));
      st.dataset.value = v;
      out.textContent = v;
    });
  }

  $("#runForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    showError("");
    const sources = [...document.querySelectorAll("input[name=source]:checked")].map((i) => i.value);
    if (!sources.length) return showError("Pick at least one source.");
    const limit = Number($(".stepper[data-name=limit]").dataset.value);
    const concurrency = Number($(".stepper[data-name=concurrency]").dataset.value);
    try {
      if (S.mode !== "live") { $("#historySelect").value = "live"; connectLive(); }
      await api("/api/runs", { sources, limit, concurrency });
    } catch (err) { showError(err.message); }
  });

  const audit = async () => {
    showError("");
    const url = $("#auditUrl").value.trim();
    if (!url) return showError("Enter a website to audit.");
    try {
      if (S.mode !== "live") { $("#historySelect").value = "live"; connectLive(); }
      await api("/api/audit", { url });
      $("#auditUrl").value = "";
    } catch (err) { showError(err.message); }
  };
  $("#auditBtn").addEventListener("click", audit);
  $("#auditUrl").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); audit(); } });

  $("#stopBtn").addEventListener("click", () => api("/api/stop", {}).catch((e) => showError(e.message)));

  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filter]");
    if (!b) return;
    S.filter = b.dataset.filter;
    for (const t of document.querySelectorAll("#tabs button")) t.setAttribute("aria-selected", String(t === b));
    S.dirty = true;
  });

  const openFrom = (e) => {
    const el = e.target.closest("[data-id]");
    if (el && S.leads.has(el.dataset.id)) openDossier(el.dataset.id);
  };
  $("#ledger").addEventListener("click", openFrom);
  $("#ledger").addEventListener("keydown", (e) => { if (e.key === "Enter") openFrom(e); });
  $("#track").addEventListener("click", openFrom);
  $("#drawerClose").addEventListener("click", closeDossier);
  $("#scrim").addEventListener("click", closeDossier);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDossier(); });
  $("#dossier").addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    navigator.clipboard.writeText(b.dataset.copy).then(() => toast("Copied"), () => toast("Copy failed"));
  });

  $("#feedClear").addEventListener("click", () => $("#feed").replaceChildren());

  $("#historySelect").addEventListener("change", (e) => {
    closeDossier();
    if (e.target.value === "live") connectLive();
    else loadReplay(e.target.value).catch((err) => showError(err.message));
  });

  $("#themeBtn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("ls-theme", next); } catch {}
  });
}

/* ---------------- boot ---------------- */

async function boot() {
  try {
    const t = localStorage.getItem("ls-theme");
    if (t) document.documentElement.dataset.theme = t;
  } catch {}
  S.meta = await api("/api/meta");
  S.steps = S.meta.steps;
  S.steps.forEach((s, i) => (S.stepIndex[s.node] = i));
  document.documentElement.style.setProperty("--steps", S.steps.length);
  document.documentElement.style.setProperty("--stations", S.steps.length + 1);
  $("#modelChip").textContent = S.meta.model;
  $("#footModel").textContent = `${S.meta.model} | LangGraph | Playwright`;
  $("#keyWarning").hidden = S.meta.has_api_key;
  buildTrack();
  buildControls();
  await loadHistory();
  connectLive();
  const loop = () => { render(); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  setInterval(renderElapsed, 1000);
}

boot().catch((err) => showError(`Could not load dashboard: ${err.message}`));
