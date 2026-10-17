# Telemetry

[Back to the README](../README.md)

## Telemetry

- On for a new install, with a notice the first time you run Clyde in a terminal. If you already had Clyde, an update asks once
  (default No) and stays off unless you say yes. `clyde telemetry off` stops it and deletes the queue; `clyde telemetry on` turns it
  on. It is never switched on by itself in an editor, a script or CI. `CLYDE_TELEMETRY=off` and `DO_NOT_TRACK=1` always win
- What it can record is fixed in `SCHEMA` in `src/telemetry.py` and checked on every event: counts, flags and words from
  fixed sets, so a prompt, a path, a model's name or an error message cannot be sent even by mistake:
  - `run` (after each agent run): the surface (terminal, `-p`, Bonnie, editor), how it ended, turns, tool calls, tool errors,
    repeated calls refused, a bucket for the first request's size, which tool list the model got, the kind of provider, which
    built-in provider it was (a provider you added yourself is just "custom") and a size bucket for the model
  - `provider_error`: a built-in provider's name (else "custom") and the kind of failure (HTTP 429, timeout, SSL…)
  - `tune`: how `clyde tune` ended and a bucket for the memory it saved
  - `bonnie_start`, and `bonnie_use` for each Bonnie action that succeeded: one word for the feature (`prompt`, `mode`,
    `session_new`, `automation_run`, `provider_connect`…), never what was said
  - every event also carries Clyde's version, a random install id, the OS, CPU, Python version, a RAM bucket and the date
- Events wait in `~/.clyde/telemetry/queue.jsonl`; `clyde telemetry show` prints exactly that and the schema, and
  `clyde telemetry off` stops it and deletes the queue. `clyde telemetry reset-id` gives a new install id
- They go out in one batch when Clyde exits, or on `clyde telemetry send`, and only while telemetry is on. The default
  receiver is a Cloudflare Worker (`worker/` in this repo, so you can read exactly what it does). It re-checks every event
  against the same schema, refuses a whole batch if one event is off it, and keeps only daily counters in a database: no event,
  no install id and no address is stored (an install is counted once a day through a salted hash that is deleted after about
  three days). Cloudflare itself sees the sender's IP address at its edge, as with any web request; the Worker never reads it
- To send somewhere else use `clyde telemetry endpoint https://…` (or `CLYDE_TELEMETRY_URL`); only https (or localhost) is accepted
- `tools/telemetry_receiver.py` is a reference receiver you can run yourself; `worker/README.md` shows how to deploy your own Worker

### This website

- `site/analytics.js` counts visits without cookies, accounts or any stored identifier: which page was opened, which tab,
  screenshot tab, copy button or link to another site was clicked, and where the visitor came from as a host name
  (`github.com`), as the label a link carries in `?ref=` (the README's links carry `?ref=github-readme`), as `internal` for a move
  between the site's own pages, or `direct`. Do Not Track and Global Privacy Control switch it off, and `privacy.html` has a switch
  for one browser
- It reports to the project's GoatCounter, `https://dea6cat.goatcounter.com/count`, set in `ENDPOINT` at the top of
  `site/analytics.js`; with `ENDPOINT` empty it sends nothing. The beacon is GoatCounter's `GET /count` (`p`, `e`, `r`, `t`, `b`),
  so another GoatCounter site works, and so does `python3 tools/telemetry_receiver.py 8787 events.jsonl site-counts.json` behind
  https. That receiver counts per day, tells visitors apart with a salted hash that changes daily and is never saved, and
  `python3 tools/telemetry_receiver.py report site-counts.json` prints the pages, clicks and where visitors came from
- To tell the repository's own link apart too, set the repository's website to `https://dea6cat.github.io/ClydeCLI/?ref=github-about`
