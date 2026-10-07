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
  --accent: #4eba65; --accent-ink: #0d1f12; --spade: #d0202f; --danger: #e5534b; --radius: 14px;
  --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #faf9f6; --side: #f1efea; --panel: #fff; --raised: #ece9e2; --line: #d9d5cc; --text: #1d1c1a; --dim: #6d6a63; --accent: #2f8f46; --accent-ink: #fff; }
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
body { font: 15px/1.55 var(--font); background: var(--bg); color: var(--text); display: flex; }
button, select, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

/* sidebar */
aside { width: 264px; flex: none; background: var(--side); border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 14px 10px; gap: 4px; overflow: hidden; }
.brand { display: flex; align-items: center; gap: 8px; padding: 4px 8px 12px; font-weight: 600; font-size: 17px; }
.brand .mark { color: var(--spade); font-size: 20px; }
.nav { display: flex; align-items: center; gap: 10px; width: 100%; background: none; border: 0; border-radius: 10px; padding: 8px 10px; text-align: left; }
.nav:hover:not(:disabled) { background: var(--raised); }
.nav[aria-current="true"] { background: var(--raised); }
.nav:disabled { color: var(--dim); cursor: default; }
.nav small { margin-left: auto; color: var(--dim); font-size: 11px; }
.label { color: var(--dim); font-size: 12.5px; font-weight: 600; padding: 16px 10px 4px; }
.project { padding: 4px 10px; color: var(--dim); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#sessions { overflow-y: auto; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 1px; }
.session { flex: none; display: flex; flex-direction: column; gap: 1px; background: none; border: 0; border-radius: 8px; padding: 7px 10px; text-align: left; color: var(--text); min-width: 0; transition-property: background-color; transition-duration: 120ms; }
.session .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session .m { font-size: 12px; color: var(--dim); font-variant-numeric: tabular-nums; }
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

.status { display: flex; align-items: center; gap: 8px; color: var(--dim); font-size: 13px; }
.status .spade { color: var(--spade); font-size: 16px; animation: pulse 1.3s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: .35; transform: scale(.9); } 50% { opacity: 1; transform: scale(1.1); } }
@media (prefers-reduced-motion: reduce) { .status .spade { animation: none; } }
a { color: var(--accent); text-underline-offset: 2px; }
.cite { margin: 0 .12em; font-size: .8em; vertical-align: super; text-decoration: none; }

/* composer */
.dock { padding: 0 18px 18px; }
main.empty #thread { display: none; }
main.empty .dock { margin: auto 0; padding-bottom: 12vh; }
.hero { text-align: center; margin: 0 auto 18px; max-width: 760px; display: none; }
main.empty .hero { display: block; }
.hero small { display: block; color: var(--accent); font-size: 13px; margin-bottom: 4px; }
.hero h1 { margin: 0; font-weight: 500; font-size: 28px; text-wrap: balance; }
.box { max-width: 760px; margin: 0 auto; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 12px 14px 10px; }
.box:focus-within { border-color: var(--dim); }
textarea:focus-visible { outline: none; }
textarea { width: 100%; resize: none; border: 0; background: none; outline: none; min-height: 28px; max-height: 40vh; display: block; }
.bar { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.chips { display: flex; background: var(--raised); border-radius: 99px; padding: 2px; }
.chip { border: 0; background: none; border-radius: 99px; padding: 4px 13px; color: var(--dim); }
.chip[aria-pressed="true"] { background: var(--panel); color: var(--text); box-shadow: 0 0 0 1px var(--line); }
select { background: var(--raised); border: 1px solid var(--line); border-radius: 9px; padding: 5px 8px; max-width: 220px; }

/* answer actions */
.answer { display: flex; flex-direction: column; gap: 6px; }
.actions { display: flex; align-items: center; gap: 2px; margin-left: -8px; animation: rise .24s ease-out both; }
@keyframes rise { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.act, .src { position: relative; display: inline-grid; place-items: center; height: 34px; min-width: 34px; padding: 0 8px; border: 0; background: none; color: var(--dim); border-radius: 10px;
  transition-property: background-color, color, transform; transition-duration: 150ms; transition-timing-function: ease-out; }
.act::before { content: ""; position: absolute; inset: -3px; }
.act:hover, .src:hover { background: var(--raised); color: var(--text); }
.act:active, .src:active { transform: scale(.96); }
.act[aria-pressed="true"] { color: var(--accent); }
.act[data-i="down"][aria-pressed="true"] { color: var(--danger); }
.act.council { color: var(--accent); display: inline-flex; gap: 6px; align-items: center; }
.act .count { font-size: 12.5px; font-variant-numeric: tabular-nums; }
.ico { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; display: block; }
.act[data-i="down"] .ico { transform: rotate(180deg); }
.act .ico + .ico { position: absolute; opacity: 0; transform: scale(.6); filter: blur(3px); }
.act .ico { transition-property: opacity, transform, filter; transition-duration: 150ms; transition-timing-function: ease-out; }
.act.done .ico:first-child { opacity: 0; transform: scale(.6); filter: blur(3px); }
.act.done .ico + .ico { opacity: 1; transform: none; filter: none; }
.act[data-tip]::after { content: attr(data-tip); position: absolute; bottom: calc(100% + 7px); left: 50%; transform: translate(-50%, 3px); background: var(--raised); color: var(--text); border: 1px solid var(--line);
  font-size: 12px; line-height: 1; padding: 6px 9px; border-radius: 8px; white-space: nowrap; opacity: 0; pointer-events: none; transition: opacity 120ms ease-out, transform 120ms ease-out; z-index: 4; }
.act:hover::after, .act:focus-visible::after { opacity: 1; transform: translate(-50%, 0); transition-delay: 300ms; }
.src { display: inline-flex; align-items: center; gap: 9px; margin-left: 6px; font-size: 13px; font-variant-numeric: tabular-nums; }
.faces { display: inline-flex; }
.face { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-size: 10.5px; font-weight: 700; color: #fff; box-shadow: 0 0 0 2px var(--bg); margin-left: -6px; }
.face:first-child { margin-left: 0; }
.menuwrap { position: relative; }
.menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 5; min-width: 190px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 4px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, .28), 0 1px 2px rgba(0, 0, 0, .22); }
.menu button { display: flex; gap: 10px; align-items: center; width: 100%; border: 0; background: none; padding: 8px 10px; border-radius: 8px; text-align: left; transition-property: background-color; transition-duration: 120ms; }
.menu button:hover { background: var(--raised); }
.menu .ico { width: 16px; height: 16px; color: var(--dim); }
.dlg-body h3 { margin: 0 0 8px; font-size: 14px; }
.dlg-body ol, .dlg-body ul { margin: 0; padding-left: 1.3em; display: flex; flex-direction: column; gap: 7px; }
.dlg-body li .host { color: var(--dim); font-size: 12.5px; margin-left: 8px; }
@media (prefers-reduced-motion: reduce) { .actions { animation: none; } .act, .src, .act .ico, .act::after { transition: none !important; } }

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

<template id="icons">
  <svg data-i="copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/></svg>
  <svg data-i="check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
  <svg data-i="export" viewBox="0 0 24 24"><path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v4.5A2.5 2.5 0 0 0 7.5 20h9a2.5 2.5 0 0 0 2.5-2.5V13"/></svg>
  <svg data-i="up" viewBox="0 0 24 24"><path d="M7 11v9H4.5A1.5 1.5 0 0 1 3 18.5v-6A1.5 1.5 0 0 1 4.5 11H7z"/><path d="M7 11l3.4-6.1A1.8 1.8 0 0 1 14 5.8V9h4.6a2 2 0 0 1 2 2.3l-1.1 6.5a2 2 0 0 1-2 1.7H7"/></svg>
  <svg data-i="council" viewBox="0 0 24 24"><circle cx="6" cy="5.5" r="2"/><circle cx="18" cy="5.5" r="2"/><circle cx="12" cy="19" r="2"/><path d="M6 7.5v1.2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V7.5M12 11.7V17"/></svg>
  <svg data-i="retry" viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>
  <svg data-i="more" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>
</template>

<dialog id="sources" aria-labelledby="sources-title">
  <div class="dlg-head"><h2 id="sources-title">Sources</h2><button class="btn" id="sources-close">Close</button></div>
  <div class="dlg-body" id="sources-body"></div>
</dialog>

<script>window.BONNY_TOKEN = "__TOKEN__";</script>
<script>
"use strict";
const TOKEN = window.BONNY_TOKEN;
const $ = (id) => document.getElementById(id);
const st = { busy: false, ui: "computer", mode: "hold", bubble: null, bubbleText: "", tools: new Map(), session: "", queued: 0,
  status: null, since: 0, activity: "", ticker: 0, titles: new Map(), fetched: [], pending: new Map(), queries: [], wrap: null, turn: null, sent: new Map() };

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

/* Links open in a new tab and only ever for http(s) addresses. */
function link(url, label) {
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return label;
    const cite = /^\d{1,3}$/.test(label);   // numbered citations read as spaced [1] marks, so [1][2] doesn't run together as "12"
    return h("a", { href: u.href, target: "_blank", rel: "noopener noreferrer", class: cite ? "cite" : "" }, cite ? "[" + label + "]" : label);
  } catch (e) { return label; }
}

/* A small, safe markdown subset: fences, headings, lists, paragraphs, `code` and **bold**. Text only, no HTML. */
function inline(text) {
  const out = document.createDocumentFragment();
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>)\]]+)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    out.append(text.slice(last, m.index));
    const tok = m[0];
    if (tok[0] === "`") out.append(h("code", {}, tok.slice(1, -1)));
    else if (tok[0] === "*") out.append(h("strong", {}, tok.slice(2, -2)));
    else if (tok[0] === "[") { const cut = tok.lastIndexOf("]("); out.append(link(tok.slice(cut + 2, -1), tok.slice(1, cut))); }
    else { const url = tok.replace(/[.,;:!?]+$/, ""); out.append(link(url, url), tok.slice(url.length)); }
    last = m.index + tok.length;
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
function scroll() { placeStatus(); thread.scrollTop = thread.scrollHeight; }
function setEmpty(empty) { $("main").classList.toggle("empty", empty); }
function addUser(text) { setEmpty(false); col.append(h("div", { class: "msg user" }, text)); scroll(); }
function startBubble() {
  st.bubble = h("div", { class: "msg bonny" }); st.bubbleText = "";
  st.wrap = h("div", { class: "answer" }, st.bubble); col.append(st.wrap);
}
function paintBubble() { if (st.bubble) { st.bubble.replaceChildren(markdown(st.bubbleText)); scroll(); } }
function note(text, cls) { setEmpty(false); col.append(h("div", { class: "note " + (cls || "") }, text)); scroll(); }

/* Waiting feedback: a pulsing spade, what Clyde says it is doing, and how long it has been. */
function paintStatus() {
  if (!st.status) return;
  const secs = Math.round((Date.now() - st.since) / 1000);
  st.status.lastChild.textContent = (st.activity || "Thinking…") + (secs ? " · " + secs + "s" : "");
}
function placeStatus() { if (st.status) col.append(st.status); }
function begin() {
  if (st.status) return;
  st.busy = true; st.since = Date.now(); st.activity = "Starting…";
  st.status = h("div", { class: "status", role: "status" }, h("span", { class: "spade", "aria-hidden": "true" }, "\u2660"), h("span", {}));
  paintStatus(); setEmpty(false); placeStatus(); scroll();
  st.ticker = setInterval(async () => {
    try { st.activity = (await api("/api/state")).activity || ""; } catch (e) { /* keep the last words */ }
    paintStatus();
  }, 1000);
  paintControls();
}
function finish() {
  clearInterval(st.ticker); st.ticker = 0;
  if (st.status) { st.status.remove(); st.status = null; }
}

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
function when(iso) {
  const d = new Date(iso), now = new Date();
  if (isNaN(d)) return "";
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 864e5);
  return days === 0 ? "Today, " + time : days === 1 ? "Yesterday, " + time : d.toLocaleDateString([], { month: "short", day: "numeric" }) + ", " + time;
}
async function refresh() {
  applyState(await api("/api/state"));
  const { sessions } = await api("/api/sessions");
  $("sessions").replaceChildren(...(sessions.length
    ? sessions.map((s) => h("button", { class: "session", title: s.title, "aria-current": String(s.id === st.session), onclick: () => openSession(s.id) },
        h("span", { class: "t" }, s.title), h("span", { class: "m" }, when(s.updated))))
    : [h("div", { class: "empty-note" }, "No saved sessions yet")]));
}
async function showSession() {
  col.replaceChildren(); st.bubble = null;
  const { messages } = await api("/api/sessions/" + encodeURIComponent(st.session));
  let question = "";
  for (const m of messages) {
    if (m.role === "user") { question = m.text; addUser(m.text); continue; }
    setEmpty(false);
    col.append(h("div", { class: "answer" }, h("div", { class: "msg bonny" }, markdown(m.text)),
      actionRow({ text: m.text, question, search: false, mode: null, info: sourceInfo(m.text, new Map(), []), council: null, quiet: true })));
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
    const search = st.ui === "search";
    await submit(text, search, search ? "plan" : $("perm").value);
    input.value = ""; autosize();
  } catch (e) { note(e.message, "error"); }
}
async function submit(text, search, mode) {
  const queuedBehind = st.busy;
  st.sent.set(text, { search, mode });
  await api("/api/prompt", { text, search, mode });
  if (queuedBehind) note("Queued: " + text); else begin();
  st.queued = (await api("/api/state")).queued; paintControls();
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
function trackSources(e) {
  if (e.phase === "start") {
    if (e.url) st.pending.set(e.call, e.url);
    if (e.tool === "WebSearch") st.queries.push(e.summary);
  } else if (!e.error) {
    if (st.pending.has(e.call)) st.fetched.push(st.pending.get(e.call));
    for (const r of e.results || []) st.titles.set(r.url, r.title);
  }
}
function toolLine(e) {
  trackSources(e);
  let row = st.tools.get(e.call);
  if (!row) { row = h("div", { class: "tool" }, h("span", { class: "dot", "aria-hidden": "true" }, "•"), h("span", {})); st.tools.set(e.call, row); col.append(row); }
  row.classList.toggle("bad", !!e.error);
  row.lastChild.textContent = e.tool + (e.summary ? " · " + e.summary : "") + (e.phase === "end" ? (e.error ? " — failed" : " — done") : " …");
  st.bubble = null; scroll();
}
function handle(e) {
  if (e.kind === "turn_start") {
    addUser(e.text); begin(); st.bubble = null; st.wrap = null; st.titles.clear(); st.fetched = []; st.pending.clear(); st.queries = [];
    st.turn = { text: e.text, ...(st.sent.get(e.text) || { search: false, mode: null }) };
  }
  else if (e.kind === "text") { if (!st.bubble) startBubble(); st.bubbleText += e.text; paintBubble(); }
  else if (e.kind === "tool") toolLine(e);
  else if (e.kind === "permission") permissionCard(e);
  else if (e.kind === "error") { finish(); note(e.message, "error"); }
  else if (e.kind === "turn_end") {
    finish();
    if (e.stopped) note("Stopped.");
    else finishAnswer(e);
    st.bubble = null; st.wrap = null; st.tools.clear(); st.busy = false; refresh();
  } else if (e.kind === "session") { showSession().then(refresh); }
}
async function poll(after) {
  for (;;) {
    try {
      const data = await api("/api/events?after=" + after);
      for (const e of data.events) { try { handle(e); } catch (err) { console.error("event", e.kind, err); } }
      after = data.last;
    } catch (err) { await new Promise((r) => setTimeout(r, 1500)); }
  }
}

/* Answer actions: copy, export, rate, council and sources under each reply. */
const icons = $("icons").content;
function ico(name) { const n = icons.querySelector('[data-i="' + name + '"]').cloneNode(true); n.classList.add("ico"); n.setAttribute("aria-hidden", "true"); return n; }
function actBtn(name, tip, onclick, extra) {
  const b = h("button", { class: "act", type: "button", "data-i": name, "data-tip": tip, "aria-label": tip, ...(extra || {}) }, ico(name));
  b.addEventListener("click", onclick);
  return b;
}
function flash(btn, text) {
  const was = btn.dataset.tip;
  const swap = !!btn.querySelector(".ico + .ico");   // only the copy button has a check icon to cross-fade to
  btn.dataset.tip = text; if (swap) btn.classList.add("done");
  setTimeout(() => { btn.dataset.tip = was; btn.classList.remove("done"); }, 1600);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) { const t = h("textarea", {}, text); document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); }
}
function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
function sourceInfo(text, titles, fetched) {
  const cited = [], seen = new Set();
  const add = (u) => {
    let n; try { n = new URL(u); } catch (e) { return; }
    if (!/^https?:$/.test(n.protocol) || seen.has(n.href)) return;
    seen.add(n.href); cited.push({ url: n.href, title: titles.get(n.href) || titles.get(u) || "", host: hostOf(n.href) });
  };
  for (const m of text.matchAll(/https?:\/\/[^\s<>)\]]+/g)) add(m[0].replace(/[.,;:!?]+$/, ""));
  fetched.forEach(add);
  const others = [...titles].filter(([u]) => !seen.has(u) && !seen.has(new URL(u).href)).map(([u, t]) => ({ url: u, title: t, host: hostOf(u) }));
  return { cited, others };
}
function hue(host) { let x = 0; for (const c of host) x = (x * 31 + c.charCodeAt(0)) % 360; return x; }
function sourcesChip(info) {
  const n = info.cited.length;
  const label = n ? n + (n === 1 ? " source" : " sources") : info.others.length + " results, none cited";
  const faces = n ? h("span", { class: "faces", "aria-hidden": "true" }, info.cited.slice(0, 3).map((s) => h("span", { class: "face", style: "background:hsl(" + hue(s.host) + " 34% 38%)" }, (s.host[0] || "?").toUpperCase()))) : null;
  const b = h("button", { class: "src", type: "button", "aria-label": label + ", show the list" }, faces, h("span", {}, label));
  b.addEventListener("click", () => openSources(info));
  return b;
}
function openSources(info) {
  const row = (s) => h("li", {}, link(s.url, s.title || s.host), h("span", { class: "host" }, s.host));
  $("sources-body").replaceChildren(
    info.cited.length ? h("div", {}, h("h3", {}, "Cited in the answer"), h("ol", {}, info.cited.map(row))) : h("p", { class: "note" }, "The answer cites no sources."),
    info.others.length ? h("div", {}, h("h3", {}, "Also found"), h("ul", {}, info.others.map(row))) : null);
  $("sources").showModal();
}
$("sources-close").addEventListener("click", () => $("sources").close());

function markdownOf(o) {
  const lines = ["# " + o.question, "", o.text];
  const used = o.info ? o.info.cited : [];
  if (used.length) lines.push("", "## Sources", ...used.map((s, i) => (i + 1) + ". [" + (s.title || s.host) + "](" + s.url + ")"));
  return lines.join("\n") + "\n";
}
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = h("a", { href: url, download: name }); document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.addEventListener("click", (e) => { if (!e.target.closest(".menuwrap")) document.querySelectorAll(".menu").forEach((m) => { m.hidden = true; }); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".menu").forEach((m) => { m.hidden = true; }); });

function actionRow(o) {
  const md = () => markdownOf(o);
  const copy = actBtn("copy", "Copy answer", async () => { await copyText(o.text); flash(copy, "Copied"); });
  copy.append(ico("check"));
  const exp = actBtn("export", "Export as Markdown", () => download((o.question.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "answer") + ".md", md()));
  const rate = async (vote) => {
    try {
      await api("/api/feedback", { vote, question: o.question });
      up.setAttribute("aria-pressed", String(vote === "up")); down.setAttribute("aria-pressed", String(vote === "down"));
      flash(vote === "up" ? up : down, "Saved on this machine");
    } catch (err) { note(err.message, "error"); }
  };
  const up = actBtn("up", "Good answer", () => rate("up"), { "aria-pressed": "false" });
  const down = actBtn("up", "Poor answer", () => rate("down"), { "aria-pressed": "false" });
  down.dataset.i = "down";
  const kids = [copy, exp, up, down];
  if (o.council) {
    const c = actBtn("council", "See every council answer", () => openCouncil(o.council));
    c.classList.add("council"); c.append(h("span", { class: "count" }, String(o.council.answers.length)));
    kids.push(c);
  }
  if (o.info && (o.info.cited.length || o.info.others.length)) kids.push(sourcesChip(o.info));
  const retryItem = h("button", { type: "button", role: "menuitem" }, ico("retry"), "Try again");
  const mdItem = h("button", { type: "button", role: "menuitem" }, ico("copy"), "Copy as Markdown");
  const menu = h("div", { class: "menu", role: "menu", hidden: "" }, retryItem, mdItem);
  const more = actBtn("more", "More", () => { const open = menu.hidden; document.querySelectorAll(".menu").forEach((m) => { m.hidden = true; }); menu.hidden = !open; more.setAttribute("aria-expanded", String(open)); }, { "aria-haspopup": "menu", "aria-expanded": "false" });
  retryItem.addEventListener("click", async () => { menu.hidden = true; try { await submit(o.question, !!o.search, o.search ? "plan" : (o.mode || $("perm").value)); } catch (err) { note(err.message, "error"); } });
  mdItem.addEventListener("click", async () => { menu.hidden = true; await copyText(md()); });
  return h("div", { class: "actions", role: "group", "aria-label": "Answer actions", style: o.quiet ? "animation:none" : "" }, kids, h("span", { class: "spacer" }), h("span", { class: "menuwrap" }, more, menu));
}
function finishAnswer(e) {
  if (!st.wrap || !e.answer) return;
  const info = sourceInfo(e.answer, st.titles, st.fetched);
  st.wrap.append(actionRow({ text: e.answer, question: st.turn ? st.turn.text : "", search: !!(st.turn && st.turn.search), mode: st.turn && st.turn.mode, info, council: e.council }));
  if (!info.cited.length && st.queries.length) note("Searched the web for “" + st.queries.join("”, “") + "”, but the answer cites no sources.");
  scroll();
}

/* council popup */
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
