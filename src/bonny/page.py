"""The page `clyde luv bonny` serves at /: one self-contained HTML file (no build step, no external requests).

It talks to the local API in server.py with the per-run token that is substituted for __TOKEN__. Every piece of
model or tool text reaches the page through textContent (never innerHTML), so a reply can't inject markup.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bonny</title>
<style>
:root {
  --bg: #151515; --side: #1b1b1b; --panel: #222; --raised: #2a2a2a; --line: #333; --text: #ebe9e4; --dim: #a09d95;
  --accent: #4eba65; --accent-ink: #0d1f12; --danger: #e5534b; --radius: 14px;
  --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #faf9f6; --side: #f1efea; --panel: #fff; --raised: #ece9e2; --line: #d9d5cc; --text: #1d1c1a; --dim: #6d6a63; --accent: #2f8f46; --accent-ink: #fff; }
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { font: 15px/1.55 var(--font); background: var(--bg); color: var(--text); display: flex; }
button, select, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

/* sidebar */
aside { width: 264px; flex: none; background: var(--side); border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 14px 10px; gap: 4px; overflow: hidden; }
.brand { display: flex; align-items: center; gap: 8px; padding: 4px 8px 12px; font-weight: 600; font-size: 17px; }
.brand .mark { color: var(--accent); font-size: 20px; }
.nav { display: flex; align-items: center; gap: 10px; width: 100%; background: none; border: 0; border-radius: 10px; padding: 8px 10px; text-align: left; }
.nav:hover:not(:disabled) { background: var(--raised); }
.nav[aria-current="true"] { background: var(--raised); }
.nav:disabled { color: var(--dim); cursor: default; }
.nav small { margin-left: auto; color: var(--dim); font-size: 11px; }
.label { color: var(--dim); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; padding: 14px 10px 4px; }
.project { padding: 4px 10px; color: var(--dim); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#sessions { overflow-y: auto; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 1px; }
.session { flex: none; background: none; border: 0; border-radius: 8px; padding: 7px 10px; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.session:hover { background: var(--raised); }
.session[aria-current="true"] { background: var(--raised); color: var(--accent); }
.empty-note { color: var(--dim); padding: 6px 10px; font-size: 13px; }

/* main */
main { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 100%; }
.top { display: flex; align-items: center; gap: 10px; padding: 12px 18px; min-height: 52px; }
#toggle { display: none; background: none; border: 1px solid var(--line); border-radius: 8px; padding: 4px 9px; }
.pill { font-size: 12px; color: var(--dim); border: 1px solid var(--line); border-radius: 99px; padding: 2px 10px; }
.pill b { color: var(--text); font-weight: 600; }
.spacer { flex: 1; }
#thread { flex: 1; overflow-y: auto; padding: 8px 18px 24px; }
.col { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
.msg.user { align-self: flex-end; background: var(--raised); border-radius: var(--radius); padding: 9px 14px; max-width: 85%; white-space: pre-wrap; overflow-wrap: anywhere; }
.msg.bonny { overflow-wrap: anywhere; }
.msg.bonny p { margin: 0 0 .8em; } .msg.bonny p:last-child { margin-bottom: 0; }
.msg.bonny h3 { margin: .6em 0 .3em; font-size: 16px; }
.msg.bonny ul { margin: 0 0 .8em; padding-left: 1.3em; }
.msg code { font-family: var(--mono); font-size: .9em; background: var(--raised); border-radius: 5px; padding: .1em .35em; }
.msg pre { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px; overflow-x: auto; margin: 0 0 .8em; }
.msg pre code { background: none; padding: 0; }
.note { color: var(--dim); font-size: 13px; }
.note.error { color: var(--danger); }
.tool { display: flex; gap: 8px; align-items: baseline; color: var(--dim); font-size: 13px; font-family: var(--mono); }
.tool .dot { color: var(--accent); }
.tool.bad .dot { color: var(--danger); }
.card { border: 1px solid var(--line); background: var(--panel); border-radius: var(--radius); padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.card .row { display: flex; gap: 8px; }
.btn { border: 1px solid var(--line); background: var(--raised); border-radius: 9px; padding: 6px 13px; }
.btn:hover:not(:disabled) { border-color: var(--dim); }
.btn:disabled { opacity: .5; cursor: default; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); font-weight: 600; }
.btn.danger { color: var(--danger); }
.link { background: none; border: 0; color: var(--accent); padding: 0; text-align: left; }
.link:hover { text-decoration: underline; }

/* composer */
.dock { padding: 0 18px 18px; }
main.empty #thread { display: none; }
main.empty .dock { margin: auto 0; padding-bottom: 12vh; }
.hero { text-align: center; margin: 0 auto 18px; max-width: 760px; display: none; }
main.empty .hero { display: block; }
.hero small { display: block; color: var(--accent); font-size: 13px; margin-bottom: 4px; }
.hero h1 { margin: 0; font-weight: 500; font-size: 28px; }
.box { max-width: 760px; margin: 0 auto; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 12px 14px 10px; }
.box:focus-within { border-color: var(--dim); }
textarea:focus-visible { outline: none; }
textarea { width: 100%; resize: none; border: 0; background: none; outline: none; min-height: 28px; max-height: 40vh; display: block; }
.bar { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.chips { display: flex; background: var(--raised); border-radius: 99px; padding: 2px; }
.chip { border: 0; background: none; border-radius: 99px; padding: 4px 13px; color: var(--dim); }
.chip[aria-pressed="true"] { background: var(--panel); color: var(--text); box-shadow: 0 0 0 1px var(--line); }
select { background: var(--raised); border: 1px solid var(--line); border-radius: 9px; padding: 5px 8px; max-width: 220px; }

/* council popup */
dialog { background: var(--panel); color: var(--text); border: 1px solid var(--line); border-radius: 16px; padding: 0; width: min(720px, 94vw); max-height: 86vh; }
dialog::backdrop { background: rgba(0, 0, 0, .55); }
.dlg-head { display: flex; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--line); }
.dlg-head h2 { margin: 0; font-size: 16px; flex: 1; }
.dlg-body { padding: 14px 18px 18px; overflow-y: auto; max-height: calc(86vh - 60px); display: flex; flex-direction: column; gap: 12px; }
.ans { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.ans.win { border-color: var(--accent); }
.ans header { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ans .ref { font-family: var(--mono); font-size: 13px; }
.meter { flex: 1; min-width: 80px; height: 6px; background: var(--raised); border-radius: 99px; overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--accent); }
.ans .text { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 9.5em; overflow: hidden; cursor: pointer; }
.ans.open .text { max-height: none; }
.vote button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }

@media (max-width: 820px) {
  aside { position: fixed; z-index: 5; inset: 0 auto 0 0; transform: translateX(-100%); transition: transform .2s; }
  body.menu aside { transform: none; box-shadow: 0 0 0 100vmax rgba(0, 0, 0, .5); }
  #toggle { display: inline-block; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<aside aria-label="Bonny">
  <div class="brand"><span class="mark" aria-hidden="true">&#9824;</span> Bonny</div>
  <button class="nav" id="new"><span aria-hidden="true">+</span> New</button>
  <button class="nav" id="nav-computer" aria-current="true"><span aria-hidden="true">&#9638;</span> Computer</button>
  <button class="nav" disabled><span aria-hidden="true">&#9719;</span> Automations <small>soon</small></button>
  <button class="nav" disabled><span aria-hidden="true">&#9635;</span> Artifacts <small>soon</small></button>
  <button class="nav" id="customize"><span aria-hidden="true">&#9881;</span> Customize</button>
  <div class="label">Project</div>
  <div class="project" id="project" title=""></div>
  <div class="label">Sessions</div>
  <div id="sessions"></div>
</aside>

<main class="empty" id="main">
  <div class="top">
    <button id="toggle" aria-label="Show or hide the sidebar">&#9776;</button>
    <span class="pill" id="state-pill"></span>
    <span class="spacer"></span>
    <span class="pill" id="queue-pill" hidden></span>
  </div>
  <div id="thread" role="log" aria-label="Conversation"><div class="col" id="col"></div></div>
  <div class="dock">
    <div class="hero"><small id="hero-kind">Computer</small><h1 id="hero-title">What should we work on?</h1></div>
    <form class="box" id="form">
      <label class="sr" for="input">Message Bonny</label>
      <textarea id="input" rows="1" placeholder="Describe what you want done"></textarea>
      <div class="bar">
        <div class="chips" role="group" aria-label="Mode">
          <button type="button" class="chip" data-mode="search" aria-pressed="false">Search</button>
          <button type="button" class="chip" data-mode="computer" aria-pressed="true">Computer</button>
        </div>
        <label class="sr" for="model">Model</label>
        <select id="model"></select>
        <label class="sr" for="perm">Permissions</label>
        <select id="perm"><option value="hold">Ask before changes</option><option value="all_in">Go ahead</option></select>
        <span class="spacer"></span>
        <button type="button" class="btn danger" id="stop" hidden>Stop</button>
        <button type="button" class="btn" id="steer" hidden>Steer</button>
        <button type="submit" class="btn primary" id="send">Send</button>
      </div>
    </form>
  </div>
</main>

<dialog id="council" aria-labelledby="council-title">
  <div class="dlg-head"><h2 id="council-title">Council</h2><button class="btn" id="council-close">Close</button></div>
  <div class="dlg-body" id="council-body"></div>
</dialog>

<script>window.BONNY_TOKEN = "__TOKEN__";</script>
<script>
"use strict";
const TOKEN = window.BONNY_TOKEN;
const $ = (id) => document.getElementById(id);
const st = { busy: false, ui: "computer", mode: "hold", bubble: null, bubbleText: "", tools: new Map(), session: "", queued: 0 };

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Bonny-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) node.append(kid);
  return node;
}

/* A small, safe markdown subset: fences, headings, lists, paragraphs, `code` and **bold**. Text only, no HTML. */
function inline(text) {
  const out = document.createDocumentFragment();
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    out.append(text.slice(last, m.index));
    out.append(m[0][0] === "`" ? h("code", {}, m[0].slice(1, -1)) : h("strong", {}, m[0].slice(2, -2)));
    last = m.index + m[0].length;
  }
  out.append(text.slice(last));
  return out;
}
function markdown(src) {
  const frag = document.createDocumentFragment();
  src.split(/^```.*$/m).forEach((part, i) => {
    if (i % 2) { frag.append(h("pre", {}, h("code", {}, part.replace(/^\n|\n$/g, "")))); return; }
    for (const block of part.split(/\n{2,}/)) {
      const lines = block.split("\n").filter((l) => l.trim());
      if (!lines.length) continue;
      if (lines.every((l) => /^\s*[-*] /.test(l))) frag.append(h("ul", {}, lines.map((l) => h("li", {}, inline(l.replace(/^\s*[-*] /, ""))))));
      else if (/^#{1,3} /.test(lines[0])) { frag.append(h("h3", {}, inline(lines[0].replace(/^#+ /, "")))); if (lines.length > 1) frag.append(h("p", {}, inline(lines.slice(1).join(" ")))); }
      else frag.append(h("p", {}, inline(lines.join("\n"))));
    }
  });
  return frag;
}

const col = $("col"), thread = $("thread");
function scroll() { thread.scrollTop = thread.scrollHeight; }
function setEmpty(empty) { $("main").classList.toggle("empty", empty); }
function addUser(text) { setEmpty(false); col.append(h("div", { class: "msg user" }, text)); scroll(); }
function startBubble() { st.bubble = h("div", { class: "msg bonny" }); st.bubbleText = ""; col.append(st.bubble); }
function paintBubble() { if (st.bubble) { st.bubble.replaceChildren(markdown(st.bubbleText)); scroll(); } }
function note(text, cls) { setEmpty(false); col.append(h("div", { class: "note " + (cls || "") }, text)); scroll(); }

/* controls */
function paintControls() {
  $("send").textContent = st.busy ? "Queue" : "Send";
  $("stop").hidden = $("steer").hidden = !st.busy;
  $("state-pill").replaceChildren("Model ", h("b", {}, $("model").value || "…"));
  $("queue-pill").hidden = !st.queued;
  $("queue-pill").textContent = st.queued + " queued";
  const search = st.ui === "search";
  $("hero-kind").textContent = search ? "Search" : "Computer";
  $("hero-title").textContent = search ? "What do you want to know?" : "What should we work on?";
  $("input").placeholder = search ? "Ask anything" : "Describe what you want done";
  document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.mode === st.ui)));
  $("nav-computer").setAttribute("aria-current", String(!search));
}
function applyState(s) {
  st.busy = s.busy; st.queued = s.queued; st.mode = s.mode; st.session = s.session;
  $("project").textContent = s.cwd; $("project").title = s.cwd;
  if (s.model && [...$("model").options].some((o) => o.value === s.model)) $("model").value = s.model;
  if (s.mode === "all_in" || s.mode === "hold") $("perm").value = s.mode;
  paintControls();
}
async function refresh() {
  applyState(await api("/api/state"));
  const { sessions } = await api("/api/sessions");
  $("sessions").replaceChildren(...(sessions.length
    ? sessions.map((s) => h("button", { class: "session", title: s.title, "aria-current": String(s.id === st.session), onclick: () => openSession(s.id) }, s.title))
    : [h("div", { class: "empty-note" }, "No saved sessions yet")]));
}
async function showSession() {
  col.replaceChildren(); st.bubble = null;
  const { messages } = await api("/api/sessions/" + encodeURIComponent(st.session));
  for (const m of messages) {
    if (m.role === "user") addUser(m.text);
    else { setEmpty(false); col.append(h("div", { class: "msg bonny" }, markdown(m.text))); }
  }
  setEmpty(!messages.length); scroll();
}
async function openSession(id) {
  try { await api("/api/session/open", { id }); document.body.classList.remove("menu"); } catch (e) { note(e.message, "error"); }
}

/* sending */
async function send() {
  const input = $("input"), text = input.value.trim();
  if (!text) return;
  try {
    if (!st.busy) {
      const want = st.ui === "search" ? "plan" : $("perm").value;
      if (want !== st.mode) st.mode = (await api("/api/mode", { mode: want })).mode;
    }
    await api("/api/prompt", { text });
    input.value = ""; autosize();
    st.queued = (await api("/api/state")).queued; paintControls();
  } catch (e) { note(e.message, "error"); }
}
$("form").addEventListener("submit", (e) => { e.preventDefault(); send(); });
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
function autosize() { const t = $("input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, window.innerHeight * 0.4) + "px"; }
$("input").addEventListener("input", autosize);
$("stop").addEventListener("click", () => api("/api/stop", {}).catch((e) => note(e.message, "error")));
$("steer").addEventListener("click", async () => {
  const text = $("input").value.trim();
  if (!text) return;
  try { await api("/api/steer", { text }); $("input").value = ""; autosize(); note("Sent to the running task: " + text); } catch (e) { note(e.message, "error"); }
});
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { st.ui = c.dataset.mode; paintControls(); }));
$("nav-computer").addEventListener("click", () => { st.ui = "computer"; paintControls(); $("input").focus(); });
$("customize").addEventListener("click", () => $("perm").focus());
$("new").addEventListener("click", async () => { try { await api("/api/session/new", {}); document.body.classList.remove("menu"); } catch (e) { note(e.message, "error"); } });
$("toggle").addEventListener("click", () => document.body.classList.toggle("menu"));
$("model").addEventListener("change", async () => { try { applyState(await api("/api/model", { model: $("model").value })); } catch (e) { note(e.message, "error"); refresh(); } });
$("perm").addEventListener("change", async () => { try { if (!st.busy) st.mode = (await api("/api/mode", { mode: $("perm").value })).mode; } catch (e) { note(e.message, "error"); } });

/* events from the running turn */
function permissionCard(e) {
  const allow = h("button", { class: "btn primary" }, "Allow"), deny = h("button", { class: "btn" }, "Deny");
  const answer = (ok) => async () => { allow.disabled = deny.disabled = true; try { await api("/api/permission", { card: e.card, allow: ok }); } catch (err) { note(err.message, "error"); } };
  allow.addEventListener("click", answer(true)); deny.addEventListener("click", answer(false));
  col.append(h("div", { class: "card", role: "group", "aria-label": "Permission needed" },
    h("div", {}, h("b", {}, "Bonny wants to use " + e.tool), h("div", { class: "note" }, e.message)), h("div", { class: "row" }, allow, deny)));
  st.bubble = null; scroll();
}
function toolLine(e) {
  let row = st.tools.get(e.call);
  if (!row) { row = h("div", { class: "tool" }, h("span", { class: "dot", "aria-hidden": "true" }, "•"), h("span", {})); st.tools.set(e.call, row); col.append(row); }
  row.classList.toggle("bad", !!e.error);
  row.lastChild.textContent = e.tool + (e.summary ? " · " + e.summary : "") + (e.phase === "end" ? (e.error ? " — failed" : " — done") : " …");
  st.bubble = null; scroll();
}
function handle(e) {
  if (e.kind === "turn_start") { addUser(e.text); st.busy = true; st.bubble = null; paintControls(); }
  else if (e.kind === "text") { if (!st.bubble) startBubble(); st.bubbleText += e.text; paintBubble(); }
  else if (e.kind === "tool") toolLine(e);
  else if (e.kind === "permission") permissionCard(e);
  else if (e.kind === "error") note(e.message, "error");
  else if (e.kind === "turn_end") {
    if (e.stopped) note("Stopped.");
    if (e.council) councilButton(e.council);
    st.bubble = null; st.tools.clear(); st.busy = false; refresh();
  } else if (e.kind === "session") { showSession().then(refresh); }
}
async function poll(after) {
  for (;;) {
    try {
      const data = await api("/api/events?after=" + after);
      for (const e of data.events) handle(e);
      after = data.last;
    } catch (err) { await new Promise((r) => setTimeout(r, 1500)); }
  }
}

/* council popup */
function councilButton(c) {
  col.append(h("button", { class: "link", onclick: () => openCouncil(c) }, "Council · " + c.answers.length + " answers · see all and vote"));
  scroll();
}
function openCouncil(c) {
  const best = c.answers.reduce((a, b) => ((b.p ?? -1) > (a.p ?? -1) ? b : a), c.answers[0]);
  $("council-body").replaceChildren(
    h("div", { class: "note" }, c.ranked ? "Laya rated how well each answer fits your message. That is not the same as being true." : "Laya wasn't available, so these answers are unranked."),
    ...c.answers.map((a) => {
      const up = h("button", { class: "btn", "aria-pressed": "false", "aria-label": "Good answer" }, "▲");
      const down = h("button", { class: "btn", "aria-pressed": "false", "aria-label": "Poor answer" }, "▼");
      const vote = (v, me, other) => async () => {
        try { await api("/api/vote", { ref: a.ref, vote: v }); me.setAttribute("aria-pressed", "true"); other.setAttribute("aria-pressed", "false"); } catch (err) { note(err.message, "error"); }
      };
      up.addEventListener("click", vote("up", up, down)); down.addEventListener("click", vote("down", down, up));
      const pct = a.p == null ? null : Math.round(a.p * 100);
      const win = a === best && c.ranked;
      const card = h("div", { class: "ans" + (win ? " win" : "") },
        h("header", {}, h("span", { class: "ref" }, a.ref),
          pct == null ? h("span", { class: "note" }, "unranked") : h("span", { class: "meter", role: "img", "aria-label": pct + " percent" }, h("i", { style: "width:" + pct + "%" })),
          pct == null ? null : h("span", { class: "note" }, pct + "%"),
          win ? h("span", { class: "pill" }, "shown") : null,
          h("span", { class: "vote" }, up, down)),
        h("div", { class: "text", title: "Click to read all" }, a.text));
      card.querySelector(".text").addEventListener("click", () => card.classList.toggle("open"));
      return card;
    }),
    ...Object.entries(c.failed || {}).map(([ref, why]) => h("div", { class: "note" }, ref + " — " + why)),
    h("div", { class: "note" }, "Votes are saved on this machine only.")
  );
  $("council").showModal();
}
$("council-close").addEventListener("click", () => $("council").close());

/* start */
(async function init() {
  try {
    const [{ models }, state] = await Promise.all([api("/api/models"), api("/api/state")]);
    $("model").replaceChildren(...models.map((m) => h("option", { value: m }, m)));
    if (!models.includes(state.model)) $("model").prepend(h("option", { value: state.model }, state.model));
    applyState(state);
    await showSession();
    await refresh();
    poll(state.event);
  } catch (e) { note("Couldn't reach Bonny: " + e.message, "error"); }
})();
</script>
</body>
</html>
"""
