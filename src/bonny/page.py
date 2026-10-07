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
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20170%20100%22%3E%3Cstyle%3E.b%7Bfill%3A%2316231b%7D%40media%20%28prefers-color-scheme%3Adark%29%7B.b%7Bfill%3A%23e3dfd6%7D%7D%3C%2Fstyle%3E%3Cdefs%3E%3Cmask%20id%3D%22p%22%20maskUnits%3D%22userSpaceOnUse%22%20x%3D%220%22%20y%3D%220%22%20width%3D%22100%22%20height%3D%22100%22%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20fill%3D%22%23fff%22%2F%3E%3Cpolyline%20points%3D%2234%2C44%2052%2C57%2034%2C70%22%20fill%3D%22none%22%20stroke%3D%22%23000%22%20stroke-width%3D%227.5%22%2F%3E%3Crect%20x%3D%2257%22%20y%3D%2266.5%22%20width%3D%2215%22%20height%3D%227%22%20fill%3D%22%23000%22%2F%3E%3C%2Fmask%3E%3Cmask%20id%3D%22c%22%20maskUnits%3D%22userSpaceOnUse%22%20x%3D%220%22%20y%3D%220%22%20width%3D%22100%22%20height%3D%22100%22%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20fill%3D%22%23fff%22%2F%3E%3Cpolyline%20points%3D%2237%2C36%2024%2C48%2037%2C60%22%20fill%3D%22none%22%20stroke%3D%22%23000%22%20stroke-width%3D%227%22%2F%3E%3Cpolyline%20points%3D%2263%2C36%2076%2C48%2063%2C60%22%20fill%3D%22none%22%20stroke%3D%22%23000%22%20stroke-width%3D%227%22%2F%3E%3Cline%20x1%3D%2256%22%20y1%3D%2235%22%20x2%3D%2244%22%20y2%3D%2263%22%20stroke%3D%22%23000%22%20stroke-width%3D%227%22%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Cpath%20fill%3D%22%23d0202f%22%20mask%3D%22url%28%23p%29%22%20d%3D%22M50%205%20C50%205%209%2036%209%2060%20C9%2074%2021%2084%2034%2082%20C41%2081%2046%2077%2048%2072%20C48%2084%2044%2092%2033%2096%20L67%2096%20C56%2092%2052%2084%2052%2072%20C54%2077%2059%2081%2066%2082%20C79%2084%2091%2074%2091%2060%20C91%2036%2050%205%2050%205%20Z%22%2F%3E%3Cg%20transform%3D%22translate%2870%200%29%22%3E%3Cg%20mask%3D%22url%28%23c%29%22%3E%3Cpath%20class%3D%22b%22%20transform%3D%22rotate%28180%2050%2050%29%22%20d%3D%22M50%205%20C50%205%209%2036%209%2060%20C9%2074%2021%2084%2034%2082%20C41%2081%2046%2077%2048%2072%20C48%2084%2044%2092%2033%2096%20L67%2096%20C56%2092%2052%2084%2052%2072%20C54%2077%2059%2081%2066%2082%20C79%2084%2091%2074%2091%2060%20C91%2036%2050%205%2050%205%20Z%22%2F%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E">
<style>
@font-face { font-family: "Bricolage Grotesque"; src: url(/static/bricolage-grotesque.woff2) format("woff2"); font-weight: 400 800; font-stretch: 75% 100%; font-display: swap; unicode-range: U+0000-00FF, U+2010-2027, U+2190-21FF; }
@font-face { font-family: "JetBrains Mono"; src: url(/static/jetbrains-mono.woff2) format("woff2"); font-weight: 400 700; font-display: swap; unicode-range: U+0000-00FF, U+2010-2027, U+2190-21FF; }

/* The site's tokens. A theme (see Customize) overrides these; with none, the page follows the system light or dark, as the site does. */
:root {
  --bg: #e8e5dd; --tint: #dfdbd0; --text: #16231b; --dim: #566058; --line: #c6c1b4; --link: #1d6a36; --spade: #d0202f; --term: #0a120d;
  --panel-alpha: 1; --bg-image: none; --img-dim: .4; --img-blur: 0px; --img-size: cover; --img-repeat: no-repeat;
  --font-body: "Bricolage Grotesque", -apple-system, "Segoe UI", sans-serif; --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
  --panel: color-mix(in srgb, var(--bg) calc(var(--panel-alpha) * 100%), transparent);
  --side: color-mix(in srgb, var(--tint) calc(var(--panel-alpha) * 100%), transparent);
  --glow: color-mix(in srgb, var(--link) 14%, transparent); --spot: color-mix(in srgb, var(--link) 10%, transparent);
  --danger: var(--spade);
}
@media (prefers-color-scheme: dark) { :root { --bg: #0f1a14; --tint: #13241a; --text: #e3dfd6; --dim: #9aa39c; --line: #24382b; --link: #6cc985; } }
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
body { font: 16px/1.6 var(--font-body); color: var(--text); background: transparent; }
button, select, textarea, input { font: inherit; color: inherit; }
button { cursor: pointer; }
a { color: var(--link); text-underline-offset: 3px; }
:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
[hidden] { display: none !important; }

/* the background: the theme's colour, an optional image, and a veil of the colour over it */
#bg { position: fixed; inset: 0; z-index: -2; background: var(--bg); overflow: hidden; }
#bg::before { content: ""; position: absolute; inset: -32px; background-image: var(--bg-image); background-size: var(--img-size); background-repeat: var(--img-repeat); background-position: center; filter: blur(var(--img-blur)); }
#bg::after { content: ""; position: absolute; inset: 0; background: var(--bg); opacity: var(--img-dim); }
.glow { position: fixed; left: 0; top: 0; width: 700px; height: 700px; margin: -350px 0 0 -350px; border-radius: 50%; pointer-events: none; opacity: 0; z-index: -1;
  background: radial-gradient(closest-side, var(--glow), transparent); transform: translate3d(var(--gx, 50vw), var(--gy, 30vh), 0); transition: opacity 1.2s; }
.glow.on { opacity: 1; }

/* cut corners, drawn as on the site: a 1px edge made by two stacked shapes, since clip-path would clip a plain border */
.cut { --c: 10px; --edge: var(--line); --fill: var(--bg); position: relative; isolation: isolate; background: var(--edge);
  clip-path: polygon(0 0, calc(100% - var(--c)) 0, 100% var(--c), 100% 100%, var(--c) 100%, 0 calc(100% - var(--c)));
  transition-property: background-color, transform; transition-duration: .25s; transition-timing-function: ease-out; }
.cut::before { content: ""; position: absolute; inset: 1px; z-index: -1; background: var(--fill);
  clip-path: polygon(0 0, calc(100% - var(--c) + 1px) 0, 100% calc(var(--c) - 1px), 100% 100%, calc(var(--c) - 1px) 100%, 0 calc(100% - var(--c) + 1px)); }
.cut::after { content: ""; position: absolute; inset: 1px; z-index: -1; opacity: 0; transition: opacity .35s; pointer-events: none; background: radial-gradient(180px circle at var(--x, 50%) var(--y, 50%), var(--spot), transparent 72%);
  clip-path: polygon(0 0, calc(100% - var(--c) + 1px) 0, 100% calc(var(--c) - 1px), 100% 100%, calc(var(--c) - 1px) 100%, 0 calc(100% - var(--c) + 1px)); }
.cut:hover { --edge: var(--dim); }
.cut:hover::after { opacity: 1; }
.cut:focus-visible, .cut:focus-within { --edge: var(--link); outline: 0; }
body[data-shape="round"] .cut, body[data-shape="square"] .cut { clip-path: none; background: var(--fill); border: 1px solid var(--edge); border-radius: calc(var(--c) * .9); }
body[data-shape="square"] .cut { border-radius: 0; }
body[data-shape="round"] .cut::before, body[data-shape="round"] .cut::after, body[data-shape="square"] .cut::before, body[data-shape="square"] .cut::after { display: none; }

.btn { --c: 8px; display: inline-flex; align-items: center; justify-content: center; height: 30px; padding: 0 14px; border: 0; font: 600 12.5px/1 var(--mono); letter-spacing: .01em; color: var(--text); white-space: nowrap; }
.btn:active:not(:disabled) { transform: scale(.97); }
.btn:disabled { opacity: .5; cursor: default; }
.btn.primary { --edge: var(--text); --fill: var(--text); color: var(--bg); }
.btn.primary:hover { --edge: var(--link); --fill: var(--link); }
.btn.danger { color: var(--danger); }
.sel { --c: 6px; display: inline-flex; align-items: stretch; height: 28px; max-width: 210px; min-width: 0; padding: 0; font: 500 12px/1 var(--mono); }
.sel select { appearance: none; -webkit-appearance: none; background: none; border: 0; outline: 0; width: 100%; min-width: 0; height: 28px; padding: 0 24px 0 10px; text-overflow: ellipsis; cursor: pointer; font: inherit; }
.sel select option { background: var(--bg); color: var(--text); }
.caret { position: absolute; right: 9px; pointer-events: none; font-size: 9px; font-style: normal; color: var(--dim); }
.seg { display: inline-flex; gap: 4px; }
#opts { display: none; }
.chip { --c: 6px; height: 28px; padding: 0 12px; border: 0; font: 500 12px/1 var(--mono); color: var(--dim); }
.chip[aria-pressed="true"] { --edge: var(--text); --fill: var(--text); color: var(--bg); }
.tag { background: var(--text); color: var(--bg); font: 500 11px/1.4 var(--mono); letter-spacing: .04em; padding: 4px 11px; --c: 7px;
  clip-path: polygon(0 0, calc(100% - var(--c)) 0, 100% var(--c), 100% 100%, var(--c) 100%, 0 calc(100% - var(--c))); }
body[data-shape="round"] .tag { clip-path: none; border-radius: 99px; }
body[data-shape="square"] .tag { clip-path: none; }
.mono { font: 500 12.5px/1.4 var(--mono); letter-spacing: .01em; }
.note { color: var(--dim); font-size: 13px; line-height: 1.5; }
.note.error { color: var(--danger); }
.spacer { flex: 1; }

/* layout */
.app { display: flex; height: 100%; }
aside { width: 268px; flex: none; background: var(--side); border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 18px 0 8px; overflow: hidden; }
.brand { display: flex; align-items: center; gap: 10px; padding: 0 18px 16px; font-weight: 800; font-size: 19px; letter-spacing: -.01em; border-bottom: 1px solid var(--line); }
.brand svg { height: 24px; width: auto; display: block; }
.brand .clyde { fill: var(--spade); }
.brand .bonny { fill: var(--text); }
nav { display: flex; flex-direction: column; padding: 8px 0; border-bottom: 1px solid var(--line); }
.nav { display: flex; align-items: center; gap: 10px; width: 100%; background: none; border: 0; border-left: 2px solid transparent; padding: 7px 18px; font: 500 13px/1.4 var(--mono); text-align: left; color: var(--text);
  transition-property: color, background-color, border-color; transition-duration: .2s; }
.nav:hover:not(:disabled) { color: var(--link); }
.nav[aria-current="true"] { border-left-color: var(--link); background: color-mix(in srgb, var(--link) 9%, transparent); }
.nav:disabled { color: var(--dim); cursor: default; }
.nav small { margin-left: auto; color: var(--dim); font-size: 11px; }
.label { padding: 14px 18px 4px; font: 600 11.5px/1.4 var(--mono); color: var(--dim); }
.project { padding: 2px 18px; font: 400 12px/1.5 var(--mono); color: var(--dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#sessions { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; margin-top: 4px; }
.srow { position: relative; flex: none; display: flex; border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent); transition: opacity .18s ease-out, transform .18s ease-out; }
.srow .session { flex: 1; border-bottom: 0; padding-right: 46px; }
.srow.gone { opacity: 0; transform: translateX(-8px); pointer-events: none; }
.del { position: absolute; right: 8px; top: 50%; translate: 0 -50%; width: 28px; height: 28px; display: grid; place-items: center; border: 0; background: none; color: var(--dim); opacity: 0;
  transition-property: opacity, color, background-color; transition-duration: .12s; }
.del::before { content: ""; position: absolute; inset: -6px; }
.srow:hover .del, .srow:focus-within .del, .del:focus-visible { opacity: 1; }
.del:hover { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); }
@media (hover: none) { .del { opacity: .75; } }
body[data-shape="round"] .del { border-radius: 8px; }
.toast { --c: 10px; --fill: var(--text); --edge: var(--text); position: fixed; left: 50%; bottom: 124px; translate: -50% 0; z-index: 30; display: flex; align-items: center; gap: 16px; padding: 9px 16px; color: var(--bg); font: 500 12.5px/1.4 var(--mono); max-width: calc(100vw - 32px); }
.toast button { color: inherit; background: none; border: 0; padding: 4px 0; font: 700 12.5px var(--mono); text-decoration: underline; text-underline-offset: 3px; }
.session { flex: none; display: flex; flex-direction: column; gap: 1px; background: none; border: 0; border-left: 2px solid transparent; padding: 8px 18px; text-align: left; min-width: 0; color: var(--text);
  transition-property: background-color; transition-duration: .15s; }
.session:hover { background: color-mix(in srgb, var(--text) 5%, transparent); }
.session[aria-current="true"] { border-left-color: var(--link); background: color-mix(in srgb, var(--link) 9%, transparent); }
.session .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14.5px; }
.session .m { font: 400 11.5px/1.4 var(--mono); color: var(--dim); font-variant-numeric: tabular-nums; }
.empty-note { color: var(--dim); padding: 6px 18px; font-size: 13px; }

main { flex: 1; min-width: 0; display: flex; justify-content: center; }
.frame { width: 100%; max-width: 880px; height: 100%; display: flex; flex-direction: column; background: var(--panel); border-left: 1px solid var(--line); border-right: 1px solid var(--line); }
@media (max-width: 1280px) { .frame { max-width: none; border-right: 0; } }
.top { display: flex; align-items: center; gap: 10px; padding: 11px 22px; min-height: 50px; border-bottom: 1px solid var(--line); }
#toggle { display: none; background: none; border: 1px solid var(--line); padding: 3px 9px; }
#thread { flex: 1; overflow-y: auto; padding: 22px 26px 30px; }
.col { max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 22px; }
.msg.user { --c: 10px; --fill: var(--tint); align-self: flex-end; padding: 8px 16px; max-width: 82%; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 15.5px; }
.msg.bonny { overflow-wrap: anywhere; font-size: 16.5px; line-height: 1.65; }
.msg.bonny p { margin: 0 0 .85em; } .msg.bonny p:last-child { margin-bottom: 0; }
.msg.bonny h3 { margin: .7em 0 .3em; font-size: 17px; font-weight: 750; letter-spacing: -.01em; }
.msg.bonny ul { margin: 0 0 .85em; padding-left: 1.3em; }
.msg code { font: .86em var(--mono); background: color-mix(in srgb, var(--text) 8%, transparent); padding: .1em .35em; }
.msg pre { background: var(--term); color: #e8e4dc; border: 1px solid var(--line); padding: 14px 16px; overflow-x: auto; margin: 0 0 .85em; font: 12.5px/1.55 var(--mono); }
.msg pre code { background: none; padding: 0; font: inherit; }
.tool { display: flex; gap: 8px; align-items: baseline; color: var(--dim); font: 400 12px/1.5 var(--mono); }
.tool .dot { color: var(--link); }
.tool.bad .dot { color: var(--danger); }
.card { --c: 12px; --fill: var(--tint); padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.card .row { display: flex; gap: 8px; }
.status { display: flex; align-items: center; gap: 8px; color: var(--dim); font: 400 12px/1.5 var(--mono); font-variant-numeric: tabular-nums; }
.status .spade { color: var(--spade); font-size: 16px; animation: pulse 1.3s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: .35; transform: scale(.9); } 50% { opacity: 1; transform: scale(1.1); } }
.cite { margin: 0 .12em; font-size: .8em; vertical-align: super; text-decoration: none; }

/* composer */
.dock { padding: 0 26px 22px; }
main.empty #thread { display: none; }
main.empty .dock { margin: auto 0; padding-bottom: 12vh; }
.hero { max-width: 720px; margin: 0 auto 20px; display: none; }
main.empty .hero { display: block; }
.hero .kind { font: 500 12.5px/1.4 var(--mono); color: var(--link); margin-bottom: 8px; }
.hero h2 { margin: 0; font-weight: 800; font-stretch: 86%; font-size: 44px; line-height: 1.05; letter-spacing: -.035em; text-wrap: balance; }
.box { --c: 16px; max-width: 720px; margin: 0 auto; padding: 14px 16px 12px; }
textarea:focus-visible { outline: none; }
::placeholder { color: var(--dim); opacity: 1; }
.skip { position: absolute; left: 12px; top: -48px; z-index: 20; padding: 8px 14px; background: var(--text); color: var(--bg); font: 600 12.5px var(--mono); text-decoration: none; transition: top .15s ease-out; }
.skip:focus { top: 12px; }
.elapsed { color: var(--dim); }
#input { width: 100%; resize: none; border: 0; background: none; outline: none; min-height: 28px; max-height: 40vh; display: block; font: 16px/1.5 var(--font-body); }
.bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.bar .right { margin-left: auto; display: flex; gap: 8px; }

/* attachments: the tray above the message box, drag and drop, and files shown in a sent message */
.btn.icon { padding: 0; width: 30px; }
.btn.icon .ico { width: 16px; height: 16px; }
.tray { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 0 10px; }
.att { --c: 6px; display: inline-flex; align-items: center; gap: 8px; height: 36px; padding: 0 4px 0 5px; max-width: 230px; font: 500 12px/1.2 var(--mono); }
.att img, .att .ft { width: 26px; height: 26px; flex: none; object-fit: cover; }
.att .ft { display: grid; place-items: center; color: var(--link); }
.att .ft .ico { width: 16px; height: 16px; }
.att .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.att .sz { color: var(--dim); font-size: 11px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.att .rm { width: 22px; height: 22px; flex: none; border: 0; background: none; color: var(--dim); display: grid; place-items: center; transition-property: color; transition-duration: .12s; }
.att .rm:hover { color: var(--danger); }
.att .rm .ico { width: 12px; height: 12px; }
.att[data-state="uploading"] { opacity: .65; }
#drop { position: fixed; inset: 0; z-index: 40; display: none; place-items: center; pointer-events: none; background: color-mix(in srgb, var(--bg) 82%, transparent); font: 600 17px/1.4 var(--mono); }
#drop span { padding: 18px 28px; border: 2px dashed var(--link); }
body.dragging #drop { display: grid; }
.msg.user .thumbs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; justify-content: flex-end; }
.msg.user .thumbs:last-child { margin-bottom: 0; }
.msg.user .thumbs img { max-width: 220px; max-height: 160px; object-fit: cover; display: block; border: 1px solid var(--line); }
.msg.user .fchip { font: 500 11.5px/1.4 var(--mono); color: var(--dim); padding: 3px 9px; border: 1px solid var(--line); white-space: nowrap; }

/* dialogs: square, hairline, like the site's own panels */
dialog { background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 0; padding: 0; width: min(720px, 94vw); max-height: 86vh; }
dialog::backdrop { background: rgba(0, 0, 0, .5); }
.dlg-head { display: flex; align-items: center; padding: 12px 18px; border-bottom: 1px solid var(--line); background: var(--tint); }
.dlg-head h2 { margin: 0; font-size: 17px; font-weight: 750; letter-spacing: -.01em; flex: 1; }
.dlg-body { padding: 16px 18px 20px; overflow-y: auto; max-height: calc(86vh - 56px); display: flex; flex-direction: column; gap: 14px; }
.dlg-body h3 { margin: 0 0 8px; font-size: 14px; }
.dlg-body ol, .dlg-body ul { margin: 0; padding-left: 1.3em; display: flex; flex-direction: column; gap: 7px; }
.dlg-body li .host { color: var(--dim); font: 400 12px var(--mono); margin-left: 8px; }
.ans { border: 1px solid var(--line); padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.ans.win { border-color: var(--link); }
.ans header { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ans .ref { font: 500 12.5px var(--mono); }
.meter { flex: 1; min-width: 80px; height: 5px; background: color-mix(in srgb, var(--text) 10%, transparent); overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--link); }
.ans .text { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 9.5em; overflow: hidden; cursor: pointer; }
.ans.open .text { max-height: none; }
.vote { display: inline-flex; gap: 4px; }
.vote .act[aria-pressed="true"] { color: var(--link); }

/* answer actions */
.answer { display: flex; flex-direction: column; gap: 6px; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; margin-left: -8px; animation: rise .24s ease-out both; }
@keyframes rise { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.act, .src { position: relative; display: inline-grid; place-items: center; height: 30px; min-width: 30px; padding: 0 7px; border: 0; background: none; color: var(--dim);
  transition-property: background-color, color, transform; transition-duration: 150ms; transition-timing-function: ease-out; }
.act::before { content: ""; position: absolute; inset: -5px; }
.act:hover, .src:hover { background: color-mix(in srgb, var(--text) 8%, transparent); color: var(--text); }
.act:active, .src:active { transform: scale(.96); }
.act[aria-pressed="true"] { color: var(--link); }
.act[data-i="down"][aria-pressed="true"] { color: var(--danger); }
.act.council { color: var(--link); display: inline-flex; gap: 6px; align-items: center; }
.act .count { font: 500 12px var(--mono); font-variant-numeric: tabular-nums; }
.ico { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; display: block; }
.act[data-i="down"] .ico { transform: rotate(180deg); }
.act .ico + .ico { position: absolute; opacity: 0; transform: scale(.6); filter: blur(3px); }
.act .ico { transition-property: opacity, transform, filter; transition-duration: 150ms; transition-timing-function: ease-out; }
.act.done .ico:first-child { opacity: 0; transform: scale(.6); filter: blur(3px); }
.act.done .ico + .ico { opacity: 1; transform: none; filter: none; }
.act[data-tip]::after { content: attr(data-tip); position: absolute; bottom: calc(100% + 7px); left: 50%; transform: translate(-50%, 3px); background: var(--text); color: var(--bg);
  font: 500 11px/1 var(--mono); padding: 6px 9px; white-space: nowrap; opacity: 0; pointer-events: none; transition: opacity 120ms ease-out, transform 120ms ease-out; z-index: 4; }
.act:hover::after, .act:focus-visible::after { opacity: 1; transform: translate(-50%, 0); transition-delay: 300ms; }
.src { display: inline-flex; align-items: center; gap: 9px; margin-left: 6px; white-space: nowrap; font: 500 12px var(--mono); font-variant-numeric: tabular-nums; }
.faces { display: inline-flex; }
.face { width: 19px; height: 19px; border-radius: 50%; display: grid; place-items: center; font: 700 10px var(--font-body); color: #fff; box-shadow: 0 0 0 2px var(--bg); margin-left: -6px; }
.face:first-child { margin-left: 0; }
.menuwrap { position: relative; }
.menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 5; min-width: 190px; background: var(--bg); border: 1px solid var(--line); padding: 4px; box-shadow: 0 10px 28px rgba(0, 0, 0, .25); }
.menu button { display: flex; gap: 10px; align-items: center; width: 100%; border: 0; background: none; padding: 8px 10px; text-align: left; font: 500 12.5px var(--mono); transition-property: background-color; transition-duration: 120ms; }
.menu button:hover { background: color-mix(in srgb, var(--text) 8%, transparent); }
.menu .ico { width: 15px; height: 15px; color: var(--dim); }
body[data-shape="round"] .act, body[data-shape="round"] .src, body[data-shape="round"] .menu button { border-radius: 9px; }
body[data-shape="round"] .menu, body[data-shape="round"] .msg pre, body[data-shape="round"] .ans { border-radius: 12px; }
body[data-shape="round"] dialog { border-radius: 14px; }

/* artifacts: the files Clyde wrote or edited, with a sandboxed preview */
#artifacts-view { display: none; flex: 1; min-height: 0; flex-direction: column; }
main[data-view="artifacts"] #artifacts-view { display: flex; }
main[data-view="artifacts"] #thread, main[data-view="artifacts"] .dock { display: none; }
.art-top { display: flex; align-items: center; gap: 14px; padding: 12px 22px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.art-top h2 { margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -.02em; }
.art-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(230px, 300px) minmax(0, 1fr); }
.art-list { overflow-y: auto; border-right: 1px solid var(--line); }
.art-item { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; padding: 10px 18px; background: none; border: 0; border-left: 2px solid transparent; border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
  transition-property: background-color; transition-duration: .15s; }
.art-item:hover { background: color-mix(in srgb, var(--text) 5%, transparent); }
.art-item[aria-current="true"] { border-left-color: var(--link); background: color-mix(in srgb, var(--link) 9%, transparent); }
.art-item .n { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art-item .m { font: 400 11.5px/1.4 var(--mono); color: var(--dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art-item.gone .n { text-decoration: line-through; color: var(--dim); }
.art-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.art-bar { display: flex; align-items: center; gap: 10px; padding: 10px 18px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.art-bar .t { flex: 1; min-width: 160px; }
.art-bar .t b { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art-bar .t span { display: block; font: 400 11.5px/1.4 var(--mono); color: var(--dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art-bar a.btn { text-decoration: none; }
.art-back { display: none; }
.art-view { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; }
.art-view iframe { flex: 1; width: 100%; min-height: 0; border: 0; background: #fff; }
.art-view img { max-width: calc(100% - 40px); max-height: calc(100% - 40px); display: block; margin: 20px auto; object-fit: contain; }
.art-view pre { margin: 0; padding: 16px 20px; font: 12.5px/1.55 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.art-view .doc { padding: 22px 26px; max-width: 760px; margin: 0 auto; width: 100%; font-size: 16px; line-height: 1.65; }
.art-view .doc p { margin: 0 0 .85em; } .art-view .doc h3 { margin: .8em 0 .3em; font-size: 18px; } .art-view .doc ul { margin: 0 0 .85em; padding-left: 1.3em; }
.art-view .doc pre { background: var(--term); color: #e8e4dc; border: 1px solid var(--line); margin: 0 0 .85em; }
.art-empty { padding: 28px 22px; color: var(--dim); font-size: 14.5px; }
.art-note { padding: 8px 18px; border-bottom: 1px solid var(--line); background: var(--tint); }
.art-card { flex-direction: row; align-items: center; gap: 12px; }
.art-card .ico { color: var(--link); width: 20px; height: 20px; flex: none; }
.art-card .grow { flex: 1; min-width: 0; }
@media (max-width: 820px) {
  .art-body { grid-template-columns: minmax(0, 1fr); }
  .art-pane { display: none; }
  .art-body.open .art-list { display: none; }
  .art-body.open .art-pane { display: flex; }
  .art-back { display: inline-flex; }
}

/* Customize: a side sheet that leaves the page visible, so changes show as they are made */
dialog#look { position: fixed; inset: 0 0 0 auto; margin: 0; width: min(392px, 100vw); height: 100vh; max-height: none; border-width: 0 0 0 1px; display: flex; flex-direction: column; }
dialog#look:not([open]) { display: none; }
.look-body { overflow-y: auto; flex: 1; }
.sec { padding: 14px 18px 16px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.sec h3 { margin: 0; font: 600 12px/1.4 var(--mono); color: var(--dim); }
.swatches { display: flex; flex-wrap: wrap; gap: 8px; }
.swatch { --c: 7px; display: inline-flex; align-items: center; gap: 8px; height: 30px; padding: 0 12px 0 8px; border: 0; font: 500 12px/1 var(--mono); }
.swatch[aria-pressed="true"] { --edge: var(--link); }
.swatch i { width: 14px; height: 14px; border: 1px solid var(--line); }
.pickers { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.pickers label { display: flex; align-items: center; justify-content: space-between; gap: 8px; font: 500 12px var(--mono); }
input[type="color"] { width: 36px; height: 24px; padding: 0; border: 1px solid var(--line); background: none; cursor: pointer; }
.rowc { display: flex; align-items: center; gap: 10px; }
.rowc > span, .rowc > label.k { width: 118px; font: 500 12px var(--mono); }
.rowc input[type="range"] { flex: 1; min-width: 0; accent-color: var(--link); }
.rowc output { width: 44px; text-align: right; font: 500 12px var(--mono); font-variant-numeric: tabular-nums; color: var(--dim); }
.look-body input[type="text"] { width: 100%; height: 32px; padding: 0 10px; background: none; border: 1px solid var(--line); font: 14px var(--font-body); }
.look-body textarea { width: 100%; min-height: 120px; padding: 10px; background: var(--term); color: #e8e4dc; border: 1px solid var(--line); font: 12px/1.5 var(--mono); resize: vertical; }
.thumb { height: 64px; border: 1px solid var(--line); background: var(--bg-image) center / cover; }

@media (max-width: 820px) {
  aside { position: fixed; z-index: 5; inset: 0 auto 0 0; transform: translateX(-100%); transition: transform .2s; background: var(--bg); }
  body.side-open aside { transform: none; box-shadow: 0 0 0 100vmax rgba(0, 0, 0, .5); }
  #toggle { display: inline-block; }
  .bar { flex-wrap: nowrap; gap: 5px; }
  .bar .chip { padding: 0 9px; }
  .bar .btn.icon { flex: none; }
  .bar .btn { padding: 0 11px; }
  .dock { padding: 0 14px 18px; }
  .bar .right { margin-left: auto; }
  #opts { display: inline-block; }
  .bar .sel { display: none; }
  .bar.opts-open { flex-wrap: wrap; }
  .bar.opts-open .sel { display: inline-flex; flex: 1 1 140px; max-width: none; }
  .bar.opts-open .right { order: 9; }
  .hero h2 { font-size: 34px; }
  .pickers { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) { .actions { animation: none; } .act, .src, .act .ico, .act::after, .cut, .glow { transition: none !important; } .status .spade { animation: none; } }
</style>
<style id="theme">__THEME__</style>
<style id="custom">__CUSTOM__</style>
</head>
<body data-shape="__SHAPE__">
<a class="skip" href="#input">Skip to the message box</a>
<h1 class="sr">Bonny</h1>
<div class="sr" id="announce" role="status" aria-live="polite"></div>
<div id="bg" aria-hidden="true"></div>
<div class="glow" id="glow" aria-hidden="true"></div>
<div id="drop" aria-hidden="true"><span>Drop to attach</span></div>
<div class="app">
<aside id="side" aria-label="Bonny">
  <div class="brand">
    <svg class="mark" viewBox="0 0 170 100" role="img" aria-label="Bonny">
      <defs>
        <mask id="bm-prompt" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><rect width="100" height="100" fill="#fff"/><polyline points="34,44 52,57 34,70" fill="none" stroke="#000" stroke-width="7.5"/><rect x="57" y="66.5" width="15" height="7" fill="#000"/></mask>
        <mask id="bm-code" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><rect width="100" height="100" fill="#fff"/><polyline points="37,36 24,48 37,60" fill="none" stroke="#000" stroke-width="7"/><polyline points="63,36 76,48 63,60" fill="none" stroke="#000" stroke-width="7"/><line x1="56" y1="35" x2="44" y2="63" stroke="#000" stroke-width="7"/></mask>
      </defs>
      <path class="clyde" mask="url(#bm-prompt)" d="M50 5 C50 5 9 36 9 60 C9 74 21 84 34 82 C41 81 46 77 48 72 C48 84 44 92 33 96 L67 96 C56 92 52 84 52 72 C54 77 59 81 66 82 C79 84 91 74 91 60 C91 36 50 5 50 5 Z"/>
      <g transform="translate(70 0)"><g mask="url(#bm-code)"><path class="bonny" transform="rotate(180 50 50)" d="M50 5 C50 5 9 36 9 60 C9 74 21 84 34 82 C41 81 46 77 48 72 C48 84 44 92 33 96 L67 96 C56 92 52 84 52 72 C54 77 59 81 66 82 C79 84 91 74 91 60 C91 36 50 5 50 5 Z"/></g></g>
    </svg>
    Bonny
  </div>
  <nav>
    <button class="nav" id="new"><span aria-hidden="true">+</span> New</button>
    <button class="nav" id="nav-computer" aria-current="true"><span aria-hidden="true">&gt;_</span> Computer</button>
    <button class="nav" disabled><span aria-hidden="true">&#9719;</span> Automations <small>soon</small></button>
    <button class="nav" id="nav-artifacts"><span aria-hidden="true">&#9635;</span> Artifacts</button>
    <button class="nav" id="customize"><span aria-hidden="true">&#9998;</span> Customize</button>
  </nav>
  <div class="label">Project</div>
  <div class="project" id="project" title=""></div>
  <div class="label">Sessions</div>
  <div id="sessions"></div>
</aside>

<main class="empty" id="main" data-view="chat">
  <div class="frame">
    <div class="top">
      <button id="toggle" aria-label="Show or hide the sidebar" aria-controls="side" aria-expanded="false">&#9776;</button>
      <span class="tag" id="state-pill"></span>
      <span class="spacer"></span>
      <span class="tag" id="queue-pill" hidden></span>
    </div>
    <div id="thread" role="log" aria-live="off" aria-label="Conversation"><div class="col" id="col"></div></div>
    <div class="dock">
      <div class="hero"><div class="kind" id="hero-kind">Computer</div><h2 id="hero-title">What should we work on?</h2></div>
      <form class="box cut" id="form">
        <div class="tray" id="tray" role="list" aria-label="Attached files" hidden></div>
      <label class="sr" for="input">Message Bonny</label>
        <textarea id="input" rows="1" placeholder="Describe what you want done"></textarea>
        <div class="bar">
          <button type="button" class="btn cut icon" id="attach" aria-label="Attach images or text files" title="Attach images or text files"></button>
          <input class="sr" id="files" type="file" multiple tabindex="-1" aria-hidden="true" accept="image/png,image/jpeg,image/gif,image/webp,text/*,.md,.markdown,.json,.csv,.log,.py,.js,.mjs,.ts,.tsx,.jsx,.css,.html,.htm,.xml,.yaml,.yml,.toml,.ini,.sh,.sql,.svg,.txt">
          <div class="seg" role="group" aria-label="Mode">
            <button type="button" class="chip cut" data-mode="search" aria-pressed="false">Search</button>
            <button type="button" class="chip cut" data-mode="computer" aria-pressed="true">Computer</button>
          </div>
          <button type="button" class="chip cut" id="opts" aria-expanded="false" aria-controls="model perm">Options</button>
          <label class="sr" for="model">Model</label>
          <span class="sel cut"><select id="model"></select><i class="caret" aria-hidden="true">&#9662;</i></span>
          <label class="sr" for="perm">Permissions</label>
          <span class="sel cut"><select id="perm"><option value="hold">Ask before changes</option><option value="all_in">Go ahead</option></select><i class="caret" aria-hidden="true">&#9662;</i></span>
          <div class="right">
            <button type="button" class="btn cut danger" id="stop" hidden>Stop</button>
            <button type="button" class="btn cut" id="steer" hidden>Steer</button>
            <button type="submit" class="btn cut primary" id="send">Send</button>
          </div>
        </div>
      </form>
    </div>
    <section id="artifacts-view" aria-label="Artifacts">
      <div class="art-top"><h2>Artifacts</h2><div class="seg" id="art-filter" role="group" aria-label="Show"></div></div>
      <div class="art-body" id="art-body">
        <div class="art-list" id="art-list" aria-label="Files"></div>
        <div class="art-pane" id="art-pane"></div>
      </div>
    </section>
  </div>
</main>
</div>

<div class="toast cut" id="toast" role="status" hidden></div>

<dialog id="council" aria-labelledby="council-title">
  <div class="dlg-head"><h2 id="council-title">Council</h2><button class="btn cut" id="council-close">Close</button></div>
  <div class="dlg-body" id="council-body"></div>
</dialog>

<dialog id="sources" aria-labelledby="sources-title">
  <div class="dlg-head"><h2 id="sources-title">Sources</h2><button class="btn cut" id="sources-close">Close</button></div>
  <div class="dlg-body" id="sources-body"></div>
</dialog>

<dialog id="look" aria-labelledby="look-title">
  <div class="dlg-head"><h2 id="look-title">Customize</h2><button class="btn cut" id="look-close">Done</button></div>
  <div class="look-body">
    <section class="sec"><h3>Theme</h3><div class="swatches" id="presets"></div></section>
    <section class="sec"><h3>Colors</h3><div class="pickers" id="pickers"></div><div class="note" id="contrast" role="status"></div><div><button class="btn cut" id="reset-colors" type="button">Reset colors</button></div></section>
    <section class="sec"><h3>Background image</h3>
      <div class="thumb" id="thumb" hidden></div>
      <div class="rowc"><label class="btn cut" for="bgfile">Choose image</label><input class="sr" id="bgfile" type="file" accept="image/png,image/jpeg,image/gif,image/webp"><button class="btn cut" id="bg-remove" type="button">Remove</button></div>
      <div class="note" id="bg-note">PNG, JPEG, GIF or WebP, up to 8 MB. It stays on this machine.</div>
      <div class="rowc"><label class="k" for="dim">Dim</label><input type="range" id="dim" min="0" max="90" step="5"><output id="dim-out"></output></div>
      <div class="rowc"><label class="k" for="blur">Blur</label><input type="range" id="blur" min="0" max="24" step="1"><output id="blur-out"></output></div>
      <div class="rowc"><label class="k" for="glass">See-through</label><input type="range" id="glass" min="0" max="90" step="5"><output id="glass-out"></output></div>
      <div class="rowc"><label class="k" for="fit">Fit</label><span class="sel cut"><select id="fit" aria-label="Image fit"><option value="cover">Fill</option><option value="contain">Fit inside</option><option value="tile">Tile</option><option value="center">Center</option></select><i class="caret" aria-hidden="true">&#9662;</i></span></div>
    </section>
    <section class="sec"><h3>Shape and type</h3>
      <div class="seg" id="shapes" role="group" aria-label="Corner shape"><button type="button" class="chip cut" data-shape="cut" aria-pressed="false">Cut</button><button type="button" class="chip cut" data-shape="round" aria-pressed="false">Round</button><button type="button" class="chip cut" data-shape="square" aria-pressed="false">Square</button></div>
      <div class="rowc"><label class="k" for="font">Font</label><span class="sel cut"><select id="font" aria-label="Font"><option value="site">Bricolage (site)</option><option value="system">System</option><option value="serif">Serif</option><option value="mono">Mono</option></select><i class="caret" aria-hidden="true">&#9662;</i></span></div>
    </section>
    <section class="sec"><h3>Greeting</h3><label class="sr" for="greeting">Greeting</label><input type="text" id="greeting" maxlength="80" placeholder="What should we work on?"></section>
    <section class="sec"><h3>Custom CSS</h3><label class="sr" for="css">Custom CSS</label><textarea id="css" spellcheck="false" placeholder="body { ... }"></textarea>
      <div class="note">Any CSS, applied as you type, like an old profile page. Images and scripts from other sites are blocked; use Choose image above for pictures.</div></section>
    <section class="sec"><h3>Theme code</h3><label class="sr" for="code">Theme code</label><textarea id="code" spellcheck="false"></textarea>
      <div class="rowc"><button class="btn cut" id="code-copy" type="button">Copy code</button><button class="btn cut" id="code-apply" type="button">Apply code</button></div>
      <div class="note">Share a look as text. It leaves out your background image.</div></section>
    <section class="sec"><div><button class="btn cut danger" id="reset-all" type="button">Reset everything</button></div></section>
  </div>
</dialog>

<template id="icons">
  <svg data-i="copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/></svg>
  <svg data-i="check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
  <svg data-i="export" viewBox="0 0 24 24"><path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v4.5A2.5 2.5 0 0 0 7.5 20h9a2.5 2.5 0 0 0 2.5-2.5V13"/></svg>
  <svg data-i="up" viewBox="0 0 24 24"><path d="M7 11v9H4.5A1.5 1.5 0 0 1 3 18.5v-6A1.5 1.5 0 0 1 4.5 11H7z"/><path d="M7 11l3.4-6.1A1.8 1.8 0 0 1 14 5.8V9h4.6a2 2 0 0 1 2 2.3l-1.1 6.5a2 2 0 0 1-2 1.7H7"/></svg>
  <svg data-i="council" viewBox="0 0 24 24"><circle cx="6" cy="5.5" r="2"/><circle cx="18" cy="5.5" r="2"/><circle cx="12" cy="19" r="2"/><path d="M6 7.5v1.2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V7.5M12 11.7V17"/></svg>
  <svg data-i="retry" viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>
  <svg data-i="trash" viewBox="0 0 24 24"><path d="M4.5 7h15"/><path d="M9.5 7V4.5h5V7"/><path d="M6.5 7l.9 12.5h9.2L17.5 7"/><path d="M10.2 11v5.2M13.8 11v5.2"/></svg>
  <svg data-i="clip" viewBox="0 0 24 24"><path d="M19 11.5l-6.8 6.8a4.2 4.2 0 0 1-6-6l7.2-7.2a2.8 2.8 0 0 1 4 4l-7.2 7.2a1.4 1.4 0 0 1-2-2l6.5-6.5"/></svg>
  <svg data-i="x" viewBox="0 0 24 24"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>
  <svg data-i="file" viewBox="0 0 24 24"><path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/></svg>
  <svg data-i="more" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>
</template>

<script>window.BONNY_TOKEN = "__TOKEN__";</script>
<script>
"use strict";
const TOKEN = window.BONNY_TOKEN;
const $ = (id) => document.getElementById(id);
const st = { busy: false, ui: "computer", mode: "hold", bubble: null, bubbleText: "", tools: new Map(), session: "", queued: 0,
  status: null, since: 0, activity: "", ticker: 0, titles: new Map(), fetched: [], pending: new Map(), queries: [], wrap: null, turn: null, sent: new Map(), said: "" };

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
function addUser(text, atts) {
  setEmpty(false);
  const files = (atts || []).filter((a) => a.kind !== "image" || !a.url);
  const pics = (atts || []).filter((a) => a.kind === "image" && a.url);
  col.append(h("div", { class: "msg user cut" },
    pics.length ? h("div", { class: "thumbs" }, pics.map((a) => h("img", { src: a.url, alt: a.name }))) : null,
    files.length ? h("div", { class: "thumbs" }, files.map((a) => h("span", { class: "fchip" }, a.name))) : null,
    text ? h("div", {}, text) : null));
  scroll();
}
function startBubble() {
  st.bubble = h("div", { class: "msg bonny" }); st.bubbleText = "";
  st.wrap = h("div", { class: "answer" }, st.bubble); col.append(st.wrap);
}
function paintBubble() { if (st.bubble) { st.bubble.replaceChildren(markdown(st.bubbleText)); scroll(); } }
function note(text, cls) { setEmpty(false); col.append(h("div", { class: "note " + (cls || ""), ...(cls === "error" ? { role: "alert" } : {}) }, text)); scroll(); }
function announce(text) { $("announce").textContent = text; }

/* Waiting feedback: a pulsing spade, what Clyde says it is doing, and how long it has been. */
function paintStatus() {
  if (!st.status) return;
  const secs = Math.round((Date.now() - st.since) / 1000);
  const words = st.activity || "Thinking…";
  st.status.children[1].textContent = words;
  st.status.children[2].textContent = secs ? " · " + secs + "s" : "";
  if (words !== st.said) { st.said = words; announce(words); }   // announce what it is doing, not the ticking seconds
}
function placeStatus() { if (st.status) col.append(st.status); }
function begin() {
  if (st.status) return;
  st.busy = true; st.since = Date.now(); st.activity = "Starting…";
  st.status = h("div", { class: "status" }, h("span", { class: "spade", "aria-hidden": "true" }, "\u2660"), h("span", {}), h("span", { class: "elapsed", "aria-hidden": "true" }));
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
  $("state-pill").textContent = $("model").value || "…";
  $("queue-pill").hidden = !st.queued;
  $("queue-pill").textContent = st.queued + " queued";
  const search = st.ui === "search";
  $("hero-kind").textContent = search ? "Search" : "Computer";
  $("hero-title").textContent = (T && T.greeting) || (search ? "What do you want to know?" : "What should we work on?");
  $("input").placeholder = search ? "Ask anything" : "Describe what you want done";
  document.querySelectorAll("#form .chip[data-mode]").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.mode === st.ui)));
  $("nav-computer").setAttribute("aria-current", String(!search && $("main").dataset.view !== "artifacts"));
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
    ? sessions.map((s) => {
      const row = h("div", { class: "srow" },
        h("button", { class: "session", "data-id": s.id, title: s.title, "aria-current": String(s.id === st.session), onclick: () => openSession(s.id) },
          h("span", { class: "t" }, s.title), h("span", { class: "m" }, when(s.updated))),
        h("button", { class: "del", type: "button", "aria-label": "Delete session: " + s.title, title: "Delete" }, ico("trash")));
      row.querySelector(".del").addEventListener("click", () => deleteSession(s, row));
      return row;
    })
    : [h("div", { class: "empty-note" }, "No saved sessions yet")]));
}
function renderMessages(messages) {
  col.replaceChildren(); st.bubble = null; st.wrap = null;
  let question = "";
  for (const m of messages) {
    if (m.role === "user") {
      question = m.text;
      addUser(m.text, [...(m.files || []).map((name) => ({ name, kind: "text" })),
        ...Array.from({ length: m.images || 0 }, (_, n) => ({ name: "Picture", kind: "image", url: "/session/image?t=" + encodeURIComponent(TOKEN) + "&session=" + encodeURIComponent(st.session) + "&i=" + m.i + "&n=" + n }))]);
      continue;
    }
    setEmpty(false);
    col.append(h("div", { class: "answer" }, h("div", { class: "msg bonny" }, markdown(m.text)),
      actionRow({ text: m.text, question, search: false, mode: null, info: sourceInfo(m.text, new Map(), []), council: null, quiet: true })));
  }
  setEmpty(!messages.length); scroll();
}
async function showSession() { renderMessages((await api("/api/sessions/" + encodeURIComponent(st.session))).messages); }

/* A small message with an optional action, for confirmations (Undo) and for things that can't happen right now. */
let toastTimer = 0;
function toast(text, action) {
  const t = $("toast");
  const kids = [h("span", {}, text)];
  if (action) { const b = h("button", { type: "button" }, action.label); b.addEventListener("click", () => { t.hidden = true; action.run(); }); kids.push(b); }
  t.replaceChildren(...kids); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, action ? 8000 : 4500);
}
let opening = 0;
async function openSession(id) {
  if (st.busy) { toast("Bonny is working. Stop her, or wait, to open another session."); return; }
  showView("chat"); document.body.classList.remove("side-open"); $("toggle").setAttribute("aria-expanded", "false");
  document.querySelectorAll("#sessions .session").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));   // answer the tap at once
  const mine = ++opening;
  const slow = setTimeout(() => { if (mine === opening) { setEmpty(false); col.replaceChildren(h("div", { class: "status" }, h("span", { class: "spade", "aria-hidden": "true" }, "\u2660"), h("span", {}, "Opening\u2026"))); } }, 120);
  try {
    const r = await api("/api/session/open", { id });
    if (mine !== opening) return;
    st.session = r.session; renderMessages(r.messages); applyState(r); $("input").focus();
  } catch (e) { toast(e.message); await refresh(); }
  finally { clearTimeout(slow); }
}
async function deleteSession(s, row) {
  const wasOpen = s.id === st.session;
  row.classList.add("gone");
  let result;
  try { result = await api("/api/session/delete", { id: s.id }); }
  catch (e) { row.classList.remove("gone"); toast(e.message); return; }
  const nextId = row.nextElementSibling ? row.nextElementSibling.querySelector(".session").dataset.id : "";   // the list is rebuilt, so remember it by id
  if (wasOpen) { st.session = result.state.session; renderMessages([]); }
  await refresh();
  ($("sessions").querySelector('[data-id="' + nextId + '"]') || $("new")).focus();
  toast("Deleted \u201c" + (s.title.length > 34 ? s.title.slice(0, 33) + "\u2026" : s.title) + "\u201d", { label: "Undo", run: async () => {
    try { await api("/api/session/restore", { id: s.id }); await refresh(); if (wasOpen) await openSession(s.id); } catch (e) { toast(e.message); }
  } });
}


/* sending */
async function send() {
  const input = $("input"), text = input.value.trim();
  if (pending.some((p) => p.state === "uploading")) { toast("Still uploading your files."); return; }
  const atts = pending.filter((p) => p.state === "ready");
  if (!text && !atts.length) return;
  try {
    const search = st.ui === "search";
    await submit(text, search, search ? "plan" : $("perm").value, atts);
    input.value = ""; autosize();
    pending = pending.filter((p) => !atts.includes(p)); paintTray();   // the pictures stay alive for the sent bubble
  } catch (e) { note(e.message, "error"); }
}
async function submit(text, search, mode, atts) {
  const queuedBehind = st.busy;
  st.sent.set(text, { search, mode, atts: atts || [] });
  await api("/api/prompt", { text, search, mode, attachments: (atts || []).map((a) => a.id) });
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
document.querySelectorAll("#form .chip[data-mode]").forEach((c) => c.addEventListener("click", () => { st.ui = c.dataset.mode; paintControls(); }));
$("nav-computer").addEventListener("click", () => { showView("chat"); st.ui = "computer"; paintControls(); $("input").focus(); });
$("new").addEventListener("click", async () => {
  if (st.busy) { toast("Bonny is working. Stop her, or wait, to start a new session."); return; }
  try {
    const r = await api("/api/session/new", {});
    showView("chat"); st.session = r.session; renderMessages(r.messages); applyState(r); document.body.classList.remove("side-open"); $("toggle").setAttribute("aria-expanded", "false"); $("input").focus();
    await refresh();
  } catch (e) { toast(e.message); }
});
$("toggle").addEventListener("click", () => { const open = document.body.classList.toggle("side-open"); $("toggle").setAttribute("aria-expanded", String(open)); if (open) $("new").focus(); });
$("model").addEventListener("change", async () => { try { applyState(await api("/api/model", { model: $("model").value })); } catch (e) { note(e.message, "error"); refresh(); } });
$("perm").addEventListener("change", async () => { try { if (!st.busy) st.mode = (await api("/api/mode", { mode: $("perm").value })).mode; } catch (e) { note(e.message, "error"); } });

/* events from the running turn */
function permissionCard(e) {
  const allow = h("button", { class: "btn cut primary" }, "Allow"), deny = h("button", { class: "btn cut" }, "Deny");
  const answer = (ok) => async () => { allow.disabled = deny.disabled = true; try { await api("/api/permission", { card: e.card, allow: ok }); } catch (err) { note(err.message, "error"); } };
  allow.addEventListener("click", answer(true)); deny.addEventListener("click", answer(false));
  col.append(h("div", { class: "card cut", role: "group", "aria-label": "Permission needed" },
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
  const project = $("project").textContent;   // show paths inside the project as short ones, and don't say the tool name twice
  const said = (e.summary || "").split(project + "/").join("").replace(new RegExp("^" + e.tool + "\\s*[·:]?\\s*"), "");
  row.lastChild.textContent = e.tool + (said ? " · " + said : "") + (e.phase === "end" ? (e.error ? " — failed" : " — done") : " …");
  st.bubble = null; scroll();
}
function handle(e) {
  if (e.kind === "turn_start") {
    const sent = st.sent.get(e.text);
    addUser(e.text, sent && sent.atts && sent.atts.length ? sent.atts : (e.files || []).map((f) => ({ name: f.name, kind: f.kind })));
    begin(); st.bubble = null; st.wrap = null; st.titles.clear(); st.fetched = []; st.pending.clear(); st.queries = [];
    st.turn = { text: e.text, ...(st.sent.get(e.text) || { search: false, mode: null }) };
  }
  else if (e.kind === "text") { if (!st.bubble) startBubble(); st.bubbleText += e.text; paintBubble(); }
  else if (e.kind === "tool") toolLine(e);
  else if (e.kind === "notice") note(e.message);
  else if (e.kind === "permission") permissionCard(e);
  else if (e.kind === "artifact") { artifactCard(e); if ($("main").dataset.view === "artifacts") loadArtifacts().catch(() => {}); }
  else if (e.kind === "error") { finish(); note(e.message, "error"); }
  else if (e.kind === "turn_end") {
    finish();
    if (e.stopped) { note("Stopped."); announce("Stopped."); }
    else { finishAnswer(e); announce("Bonny answered."); }
    st.bubble = null; st.wrap = null; st.tools.clear(); st.busy = false; refresh();
  } else if (e.kind === "session") { st.session = e.session; showSession().catch(() => renderMessages([])).then(refresh); }
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
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  document.querySelectorAll(".menu").forEach((m) => { m.hidden = true; });
  if ($("look").open) $("look").close();
  if (document.body.classList.contains("side-open")) { document.body.classList.remove("side-open"); $("toggle").setAttribute("aria-expanded", "false"); $("toggle").focus(); }
});

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
  const items = [retryItem, mdItem];
  const closeMenu = (back) => { menu.hidden = true; more.setAttribute("aria-expanded", "false"); if (back) more.focus(); };
  const more = actBtn("more", "More", () => {
    const open = menu.hidden;
    document.querySelectorAll(".menu").forEach((m) => { m.hidden = true; });
    menu.hidden = !open; more.setAttribute("aria-expanded", String(open));
    if (open) retryItem.focus();
  }, { "aria-haspopup": "menu", "aria-expanded": "false" });
  menu.addEventListener("keydown", (e) => {
    const at = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(at + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(at + items.length - 1) % items.length].focus(); }
    else if (e.key === "Escape") { e.stopPropagation(); closeMenu(true); }
    else if (e.key === "Tab") closeMenu(false);
  });
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

/* Artifacts: the files Clyde wrote or edited, with a preview that can't reach your files, your network or Bonny. */
const KINDS = { page: "Page", document: "Document", image: "Image", code: "Code", other: "File" };
const FILTERS = [["all", "All"], ["page", "Pages"], ["document", "Documents"], ["image", "Images"], ["code", "Code"]];
let arts = [], artFilter = "all", artSel = "", artScripts = false;
const rawUrl = (path, extra) => "/artifact/raw?t=" + encodeURIComponent(TOKEN) + "&path=" + encodeURIComponent(path) + (extra || "");
function showView(name) {
  $("main").dataset.view = name;
  $("nav-artifacts").setAttribute("aria-current", String(name === "artifacts"));
  paintControls();
}
function paintArtFilters() {
  $("art-filter").replaceChildren(...FILTERS.map(([key, label]) => {
    const b = h("button", { type: "button", class: "chip cut", "aria-pressed": String(artFilter === key) }, label);
    b.addEventListener("click", () => { artFilter = key; paintArtFilters(); paintArtList(); });
    return b;
  }));
}
function paintArtList() {
  const shown = arts.filter((a) => artFilter === "all" || a.group === artFilter);
  $("art-list").replaceChildren(...(shown.length ? shown.map((a) => {
    const b = h("button", { type: "button", class: "art-item" + (a.exists ? "" : " gone"), "aria-current": String(a.path === artSel), title: a.path },
      h("span", { class: "n" }, a.name), h("span", { class: "m" }, (a.folder ? a.folder + " · " : "") + KINDS[a.group] + " · " + when(a.updated)));
    b.addEventListener("click", () => selectArtifact(a.path));
    return b;
  }) : [h("div", { class: "art-empty" }, arts.length ? "Nothing in this filter." : "Nothing here yet. Files Clyde writes or edits for you will show up here.")]));
}
async function loadArtifacts() {
  arts = (await api("/api/artifacts")).artifacts;
  paintArtFilters(); paintArtList();
  if (!arts.length) paintPane(null);
  else if (!artSel && matchMedia("(min-width: 821px)").matches) await selectArtifact(arts[0].path);
}
async function openArtifacts(path) {
  showView("artifacts"); document.body.classList.remove("side-open"); $("toggle").setAttribute("aria-expanded", "false");
  try { await loadArtifacts(); if (path) await selectArtifact(path); } catch (e) { toast(e.message); }
}
async function selectArtifact(path) {
  artSel = path; paintArtList(); $("art-body").classList.add("open");
  const row = arts.find((a) => a.path === path);
  paintPane(row ? { ...row, loading: row.kind === "text" || row.kind === "markdown" } : null);
  try { const info = await api("/api/artifact?path=" + encodeURIComponent(path)); if (artSel === path) paintPane(info); }
  catch (e) { if (artSel === path) paintPane(row ? { ...row, error: e.message } : null); }
}
function paintPane(info) {
  const pane = $("art-pane");
  if (!info) { pane.replaceChildren(h("div", { class: "art-empty" }, "Pick a file to preview it.")); return; }
  const back = h("button", { class: "btn cut art-back", type: "button" }, "Back");
  back.addEventListener("click", () => $("art-body").classList.remove("open"));
  const download = h("a", { class: "btn cut", href: rawUrl(info.path, "&download=1"), download: info.name }, "Download");
  const show = h("button", { class: "btn cut", type: "button" }, "Show in folder");
  show.addEventListener("click", async () => { try { await api("/api/artifact/reveal", { path: info.path }); } catch (e) { toast(e.message); } });
  const tools = [];
  if (info.kind === "html" && info.exists) {
    const scripts = h("button", { class: "btn cut", type: "button", "aria-pressed": String(artScripts) }, "Scripts: " + (artScripts ? "on" : "off"));
    scripts.addEventListener("click", () => { artScripts = !artScripts; paintPane(info); });
    tools.push(scripts);
  }
  const view = h("div", { class: "art-view" });
  const notes = [];
  if (!info.exists) view.append(h("div", { class: "art-empty" }, "This file is no longer on disk."));
  else if (info.error) view.append(h("div", { class: "art-empty" }, "Couldn't open it: " + info.error));
  else if (info.kind === "html") {
    notes.push(artScripts ? "Scripts run in a sandbox: they can't reach Bonny, your files or the network." : "Previews can't load pictures, fonts or scripts from other sites, and scripts are off.");
    view.append(h("iframe", { sandbox: artScripts ? "allow-scripts" : "", src: rawUrl(info.path, artScripts ? "&scripts=1" : ""), title: "Preview of " + info.name }));
  } else if (info.kind === "image") view.append(h("img", { src: rawUrl(info.path), alt: info.name }));
  else if (info.loading) view.append(h("div", { class: "art-empty" }, "Loading…"));
  else if (info.kind === "markdown" && info.text != null) view.append(h("div", { class: "doc" }, markdown(info.text)));
  else if (info.kind === "text" && info.text != null) view.append(h("pre", {}, info.text));
  else view.append(h("div", { class: "art-empty" }, "There's no preview for this kind of file. Use Download to open it."));
  if (info.truncated) notes.push("Showing the first part of a large file. Download it to see everything.");
  pane.replaceChildren(h("div", { class: "art-bar" }, back, h("div", { class: "t" }, h("b", {}, info.name), h("span", {}, info.path)), ...tools, download, show),
    ...notes.map((n) => h("div", { class: "art-note note" }, n)), view);
}
function artifactCard(e) {
  const open = h("button", { class: "btn cut", type: "button" }, "Preview");
  open.addEventListener("click", () => openArtifacts(e.path));
  col.append(h("div", { class: "card cut art-card" }, ico("file"), h("div", { class: "grow" }, h("b", {}, e.name), h("div", { class: "note" }, (e.tool === "Write" ? "Written" : "Edited") + " by Bonny")), open));
  st.bubble = null; scroll();
}
$("nav-artifacts").addEventListener("click", () => openArtifacts());

/* Attachments: images and text files, from the button, a drop or a paste. Each is uploaded as soon as it is chosen. */
const MAX_ATTACH = 6, MAX_ATTACH_BYTES = 12_000_000;
let pending = [];
const fmtSize = (n) => (n < 1024 ? n + " B" : n < 1048576 ? Math.round(n / 1024) + " KB" : (n / 1048576).toFixed(1) + " MB");
function paintTray() {
  $("tray").hidden = !pending.length;
  $("tray").replaceChildren(...pending.map((p) => {
    const rm = h("button", { class: "rm", type: "button", "aria-label": "Remove " + p.name }, ico("x"));
    rm.addEventListener("click", () => { pending = pending.filter((x) => x !== p); paintTray(); $("input").focus(); });
    return h("div", { class: "att cut", role: "listitem", "data-state": p.state },
      p.kind === "image" && p.url ? h("img", { src: p.url, alt: "" }) : h("span", { class: "ft", "aria-hidden": "true" }, ico("file")),
      h("span", { class: "nm", title: p.name }, p.name), h("span", { class: "sz" }, p.state === "uploading" ? "Uploading…" : fmtSize(p.size)), rm);
  }));
}
async function attachFiles(files) {
  for (const file of files) {
    if (pending.length >= MAX_ATTACH) { toast("You can attach up to " + MAX_ATTACH + " files to a message."); break; }
    if (file.size > MAX_ATTACH_BYTES) { toast((file.name || "That file") + " is over 12 MB."); continue; }
    const isImage = file.type.startsWith("image/") && file.type !== "image/svg+xml";
    const item = { name: file.name || "pasted-image.png", size: file.size, state: "uploading", kind: isImage ? "image" : "text", url: isImage ? URL.createObjectURL(file) : "" };
    pending.push(item); paintTray();
    try {
      const res = await fetch("/api/attachments", { method: "POST", headers: { "X-Bonny-Token": TOKEN, "X-File-Name": encodeURIComponent(item.name), "Content-Type": "application/octet-stream" }, body: file });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      Object.assign(item, { id: data.id, kind: data.kind, size: data.size, state: "ready" });
      if (data.note) toast(data.note);
    } catch (e) { pending = pending.filter((x) => x !== item); if (item.url) URL.revokeObjectURL(item.url); toast(e.message); }
    paintTray();
  }
}
$("attach").append(ico("clip"));
$("opts").addEventListener("click", () => { const open = document.querySelector(".bar").classList.toggle("opts-open"); $("opts").setAttribute("aria-expanded", String(open)); });
$("attach").addEventListener("click", () => $("files").click());
$("files").addEventListener("change", () => { attachFiles([...$("files").files]); $("files").value = ""; });
$("input").addEventListener("paste", (e) => {
  const files = [...((e.clipboardData && e.clipboardData.files) || [])];
  if (!files.length) return;
  if (!e.clipboardData.getData("text")) e.preventDefault();
  attachFiles(files);
});
let dragDepth = 0;
const dragsFiles = (e) => [...((e.dataTransfer && e.dataTransfer.types) || [])].includes("Files");
addEventListener("dragenter", (e) => { if (dragsFiles(e)) { e.preventDefault(); dragDepth++; document.body.classList.add("dragging"); } });
addEventListener("dragover", (e) => { if (dragsFiles(e)) e.preventDefault(); });
addEventListener("dragleave", (e) => { if (dragsFiles(e)) { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove("dragging"); } });
addEventListener("drop", (e) => {
  if (!dragsFiles(e)) return;
  e.preventDefault(); dragDepth = 0; document.body.classList.remove("dragging");
  showView("chat"); attachFiles([...e.dataTransfer.files]);
});

/* council popup */
function openCouncil(c) {
  const best = c.answers.reduce((a, b) => ((b.p ?? -1) > (a.p ?? -1) ? b : a), c.answers[0]);
  $("council-body").replaceChildren(
    h("div", { class: "note" }, c.ranked ? "Laya rated how well each answer fits your message. That is not the same as being true." : "Laya wasn't available, so these answers are unranked."),
    ...c.answers.map((a) => {
      const up = actBtn("up", "Good answer", () => {}, { "aria-pressed": "false" });
      const down = actBtn("up", "Poor answer", () => {}, { "aria-pressed": "false" });
      down.dataset.i = "down";
      const vote = (v, me, other) => async () => {
        try { await api("/api/vote", { ref: a.ref, vote: v }); me.setAttribute("aria-pressed", "true"); other.setAttribute("aria-pressed", "false"); } catch (err) { note(err.message, "error"); }
      };
      up.onclick = vote("up", up, down); down.onclick = vote("down", down, up);
      const pct = a.p == null ? null : Math.round(a.p * 100);
      const win = a === best && c.ranked;
      const card = h("div", { class: "ans" + (win ? " win" : "") },
        h("header", {}, h("span", { class: "ref" }, a.ref),
          pct == null ? h("span", { class: "note" }, "unranked") : h("span", { class: "meter", role: "img", "aria-label": pct + " percent" }, h("i", { style: "width:" + pct + "%" })),
          pct == null ? null : h("span", { class: "note" }, pct + "%"),
          win ? h("span", { class: "tag" }, "shown") : null,
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

/* Customize: presets, colours, a background image, shape, font, greeting and CSS. The server saves them on this machine. */
const THEME_VARS = new Set();
const COLORS = [["bg", "Background"], ["tint", "Panels"], ["text", "Text"], ["dim", "Muted"], ["line", "Lines"], ["link", "Links"], ["spade", "Spade"]];
let T = null, presets = {}, hasImage = false, saveTimer = 0, dirty = false;
function applyTheme(payload) {
  T = payload.theme; presets = payload.presets; hasImage = payload.image;
  const root = document.documentElement.style;
  for (const k of [...THEME_VARS]) if (!(k in payload.vars)) { root.removeProperty(k); THEME_VARS.delete(k); }
  for (const [k, v] of Object.entries(payload.vars)) { root.setProperty(k, v); THEME_VARS.add(k); }
  $("theme").textContent = "";   // the first-paint copy; from here the page owns the variables
  $("custom").textContent = T.css;
  document.body.dataset.shape = T.shape;
  paintControls(); paintLook();
}
function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); }
function paintContrast() {
  const cs = getComputedStyle(document.documentElement);
  const c = (k) => cs.getPropertyValue("--" + k).trim();
  const weak = [["text", "Text"], ["dim", "Muted text"], ["link", "Links"]].filter(([k]) => /^#[0-9a-f]{6}$/i.test(c(k)) && /^#[0-9a-f]{6}$/i.test(c("bg")) && contrast(c(k), c("bg")) < 4.5)
    .map(([k, label]) => label + " on the background is " + contrast(c(k), c("bg")).toFixed(1) + ":1");
  $("contrast").textContent = weak.length ? "Low contrast: " + weak.join("; ") + ". 4.5:1 or higher is easier to read." : "";
}
function setIfIdle(el, value) { if (document.activeElement !== el && el.value !== value) el.value = value; }
function paintLook() {
  document.querySelectorAll("#presets .swatch").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preset === T.preset)));
  const cs = getComputedStyle(document.documentElement);
  document.querySelectorAll("#pickers input").forEach((i) => { const v = cs.getPropertyValue("--" + i.dataset.key).trim(); if (/^#[0-9a-f]{6}$/i.test(v) && document.activeElement !== i) i.value = v.toLowerCase(); });
  for (const [id, value, unit] of [["dim", Math.round(T.dim * 100), "%"], ["blur", T.blur, "px"], ["glass", Math.round(T.glass * 100), "%"]]) {
    if (document.activeElement !== $(id)) $(id).value = value;
    $(id + "-out").textContent = value + unit;
  }
  $("thumb").hidden = !hasImage; $("bg-remove").disabled = !hasImage;
  $("bg-note").textContent = hasImage ? "Background set. It stays on this machine." : "PNG, JPEG, GIF or WebP, up to 8 MB. It stays on this machine.";
  document.querySelectorAll("#shapes .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.shape === T.shape)));
  $("fit").value = T.fit; $("font").value = T.font;
  paintContrast();
  setIfIdle($("greeting"), T.greeting); setIfIdle($("css"), T.css); setIfIdle($("code"), JSON.stringify(T, null, 2));
}
function change(edit) { edit(T); dirty = true; clearTimeout(saveTimer); saveTimer = setTimeout(saveTheme, 80); }
async function saveTheme() {
  dirty = false;
  try { const r = await api("/api/theme", T); if (!dirty) applyTheme(r); } catch (e) { $("bg-note").textContent = e.message; }
}
function buildLook(payload) {
  const swatch = (name, label, bg, link) => {
    const b = h("button", { type: "button", class: "swatch cut", "data-preset": name, "aria-pressed": "false" },
      h("i", { style: name === "auto" ? "background:linear-gradient(135deg,#e8e5dd 50%,#0f1a14 50%)" : "background:" + bg + ";box-shadow:inset -6px -6px 0 " + link }), label);
    b.addEventListener("click", () => change((t) => { t.preset = name; t.colors = {}; }));
    return b;
  };
  $("presets").replaceChildren(swatch("auto", "Auto"), ...Object.entries(payload.presets).map(([n, c]) => swatch(n, n[0].toUpperCase() + n.slice(1), c.bg, c.link)));
  $("pickers").replaceChildren(...COLORS.map(([key, label]) => {
    const input = h("input", { type: "color", "data-key": key, "aria-label": label });
    input.addEventListener("input", () => change((t) => { t.colors[key] = input.value; }));
    return h("label", {}, label, input);
  }));
}
$("reset-colors").addEventListener("click", () => change((t) => { t.colors = {}; }));
for (const [id, field, scale] of [["dim", "dim", 100], ["blur", "blur", 1], ["glass", "glass", 100]]) {
  $(id).addEventListener("input", () => { $(id + "-out").textContent = $(id).value + (id === "blur" ? "px" : "%"); change((t) => { t[field] = Number($(id).value) / scale; }); });
}
$("fit").addEventListener("change", () => change((t) => { t.fit = $("fit").value; }));
$("font").addEventListener("change", () => change((t) => { t.font = $("font").value; }));
document.querySelectorAll("#shapes .chip").forEach((c) => c.addEventListener("click", () => change((t) => { t.shape = c.dataset.shape; })));
$("greeting").addEventListener("input", () => change((t) => { t.greeting = $("greeting").value; }));
$("css").addEventListener("input", () => change((t) => { t.css = $("css").value; }));
$("bgfile").addEventListener("change", async () => {
  const file = $("bgfile").files[0];
  if (!file) return;
  try {
    const res = await fetch("/api/theme/image", { method: "POST", headers: { "X-Bonny-Token": TOKEN, "Content-Type": file.type || "application/octet-stream" }, body: file });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    applyTheme(data);
  } catch (e) { $("bg-note").textContent = e.message; }
  $("bgfile").value = "";
});
$("bg-remove").addEventListener("click", async () => { try { applyTheme(await api("/api/theme/image/remove", {})); } catch (e) { $("bg-note").textContent = e.message; } });
$("code-copy").addEventListener("click", async () => { await copyText($("code").value); const b = $("code-copy"); b.textContent = "Copied"; setTimeout(() => { b.textContent = "Copy code"; }, 1500); });
$("code-apply").addEventListener("click", () => {
  try { const parsed = JSON.parse($("code").value); T = parsed; dirty = true; saveTheme(); }
  catch (e) { $("bg-note").textContent = "That isn't a valid theme code."; }
});
$("reset-all").addEventListener("click", async () => { try { await api("/api/theme/image/remove", {}); T = {}; dirty = true; await saveTheme(); } catch (e) { $("bg-note").textContent = e.message; } });
$("customize").addEventListener("click", () => { $("look").show(); paintLook(); $("look-close").focus(); });
$("look").addEventListener("close", () => $("customize").focus());
$("look-close").addEventListener("click", () => $("look").close());

/* The site's pointer glow and card spotlight, only with a mouse and when motion is welcome. */
if (matchMedia("(hover: hover) and (pointer: fine)").matches && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const glow = $("glow");
  addEventListener("pointermove", (e) => {
    glow.style.setProperty("--gx", e.clientX + "px"); glow.style.setProperty("--gy", e.clientY + "px"); glow.classList.add("on");
    const c = e.target.closest && e.target.closest(".cut");
    if (c) { const r = c.getBoundingClientRect(); c.style.setProperty("--x", e.clientX - r.left + "px"); c.style.setProperty("--y", e.clientY - r.top + "px"); }
  }, { passive: true });
}

/* start */
(async function init() {
  try {
    const [{ models }, state, look] = await Promise.all([api("/api/models"), api("/api/state"), api("/api/theme")]);
    buildLook(look); applyTheme(look);
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
