# K2-Horizon-7B on an 18 GB Mac — tool calls and the window

*Research note, 2026-11-23/24. Machine: Apple M3 Pro, 18 GB. Ollama 0.40.17, llama.cpp `llama-server` build 11429, oMLX v0.7.2 (native Metal kernels built). One run per number.*

## The headline

K2-Horizon-7B writes tool calls in its own tagged format (`<ifm|tool_calls>`, XML by default, JSON on request). Clyde does **not** need a parser for it: both runtimes Clyde supports, Ollama and oMLX, turn those calls into native `tool_calls` before Clyde sees them. What stops this model on this Mac is the window, not the format.

## The model

`IFM/K2-Horizon-7B`: dense, about 9.0B parameters despite the name, Apache-2.0, open data and training code. Its card's benchmark numbers are self-reported and ran at 256k context with output budgets up to 500k tokens; nothing here checks them.

Its chat template offers three tool-call formats through `chat_template_kwargs.tool_call_format`: `xml` (default), `json`, `xml_typed`. Even `json` is wrapped in `<ifm|tool_call>` tags, so Clyde's own text repair (`recover_toolcalls`, which reads fenced or bare JSON) recovers neither: offline, both shapes returned `[]`.

## Measurements

Probe: one chat request with a single `Read` tool, once per format, against the runtime directly (no Clyde), checking whether the reply carries native `tool_calls` or raw tags in its text.

| Runtime | Build | Loads? | `xml` | `json` |
|---|---|---|---|---|
| llama.cpp `llama-server` | build 11429, `IFM/K2-Horizon-7B-GGUF` Q4_K_M | **No**: `unknown model architecture: 'k2-horizon'` | — | — |
| Ollama 0.40.17 | same GGUF (5.59 GB file) | yes, reports the `tools` capability | native call, 5.8 s | native call, 2.0 s |
| oMLX v0.7.2 | `hermitdave/K2-Horizon-7B-oQ4e` (5.29 GB) | yes | native call, 1.7 s | native call, 1.8 s |

No raw `<ifm|…>` text reached the reply in any run. oMLX ships a dedicated `patches/k2_horizon/` (a tool parser and a decoding grammar for the tagged format); Ollama parses it from the model's template.

The oQ4e build carries an older revision of the chat template than `IFM/K2-Horizon-7B`; its tool-call tags and call instructions are identical (checked by diff), only its text normalization differs.

Through Clyde's own loop (`clyde -p`, `CLYDE_CONTEXT_TOKENS` set):

| Runtime | Window | Task | Result |
|---|---|---|---|
| Ollama | 4096 | either | HTTP 400 before the model ran: `request (7345 tokens) exceeds the available context size (4096 tokens)` |
| Ollama | 8192 | Read a file outside the project | Model called `Read` correctly; Clyde's `-p` permission rule denied it (outside the project); the model reported the denial truthfully. 42 s |
| Ollama | 8192 | Find which file defines `recover_toolcalls` | Called `Grep`, answered `src/providers/toolcall_repair.py` (correct). 10 s |
| oMLX | 8192 | Read `pyproject.toml`, report the version | Model called `Read`, Clyde ran it (71 lines); the next request failed: `Prompt is too long: 8456 tokens > 8192 maximum context length` |
| oMLX | 8192 | Find `recover_toolcalls` | Refused by oMLX's memory guard before the model ran: `Prefill would require ~7.74 GB peak (current 6.52 GB + KV+SDPA 1.22 GB) but the prefill limit is 7.55 GB` |

Resident memory: Ollama 4.9 GB at a 4096 window, 5.6 GB at 8192, 100% GPU. Swap stayed flat in every run (2,766 MB on Ollama, 2,726 MB on oMLX); the watchdog (kill at +1 GB) never fired.

## What this implies

- **No XML tool-call feature.** It was proposed for this model and is not built: both supported runtimes already deliver native calls. Revisit only if a runtime Clyde supports is measured passing raw tags through.
- **The window is the limit.** On this machine Clyde's first request was about 7k tokens before the conversation added anything (the 7,345 in the 4096 run), so an 8192 window left under 1k for the conversation and one file read overflowed it. Clyde sent that request instead of compacting first: its compaction and trimming checks counted only the conversation messages, not the system prompt and tool definitions that make up most of the request (`needs_auto_compact` in `src/compact_service/service.py`, `trim_old_tool_results` in `src/context_system/microcompact.py`). Most of that 7k is this machine's MCP setup, not Clyde's own floor: see below.
- **On this Mac, Ollama is the runtime that completed the tasks.** oMLX parsed the calls as well, but its prefill guard leaves no room for an 8192 window next to this model's 6.5 GB.

## Where the starting tokens go (2026-11-24)

The same one-line prompt ("Reply with the single word: ok"), the same model and the same Ollama, sent by three agents through a logging proxy; each agent's first request was replayed to Ollama in parts, so every count is in K2-Horizon's own tokenizer. Ollama itself adds 17 tokens (its chat template around the message) and manages nothing else: it neither trims nor summarizes, and refuses a request past `num_ctx` with HTTP 400. `ollama launch`, by its own help text, starts third-party agents (Claude Code, Codex, pi, OpenCode and others) against it; it was not run here.

| Agent (as configured on this machine) | System prompt | Tool definitions | First request |
|---|---|---|---|
| Clyde, in this repo | 6,281 | 656 (5 tools) | 6,954 |
| Clyde, empty folder (the global CLAUDE.md only) | 6,717 | 656 (5 tools) | 7,390 |
| pi (`pi -p`, no project) | 7,866 (60 skills listed) | 642 (4 tools) | 8,525 |
| Claude Code (`claude -p`, this user's plugins and settings) | — | — | 30,170 (Ollama's own count of the real request) |

Of Clyde's 6,281-token system prompt, 5,120 were the `## More tools` index: 262 deferred tools, one line each, 207 of them from one MCP server (`rea`), 14 from `dart`, 5 from `caveman`, 36 built in. The same request without those MCP lines is 2,364 tokens: that is Clyde's own floor here, against pi's 8.5k and Claude Code's 30k. Claude Code's 30k was not broken down (it carries much of its context in the messages, not the system prompt, so the replay above cannot split it). pi's system prompt is 653 tokens without its `<available_skills>` block (60 skills, 31,107 characters) and 7,883 with it: like Clyde's MCP index, a listing of this machine's add-ons is 92% of it. pi's own floor, about 1.3k with its four tools, sits below Clyde's 2.4k.

Listing a local model's MCP tools as one line per server (built-in tools keep their own line) took the first request from 6,954 to 2,486 tokens, and the read that overflowed 8192 before answered (`Version is 0.10.0`). It exposed two more limits, both live: ToolSearch matched a query only as one phrase (K2-Horizon's "rea string list binary" found nothing), and a hint that it could list a server's tools made the model load 50 of them, a 140,008-token request. With the hint gone and every query word matched, the lookup found its tools, but five `rea` definitions loaded at once still made a 8,679-token request: heavy MCP schemas need more than an 8192 window.

With both changes together (the window checks and the grouped index), the same kind of lookup ("which `rea` tool lists cross-references") stopped cleanly at 8192 once ToolSearch had loaded five `rea` tools (predicted 8,348, no request sent, `clyde -p` exit 1) and completed at 12288. Clyde's estimate against Ollama's own count, per request: 2,593 vs 2,583, 2,693 vs 2,703, 8,343 vs 8,496, 9,755 vs 9,969, so up to 2.2% under once heavy schemas are loaded; the fit check keeps a 5% margin for that.

Not measured: multi-step research (WebSearch/WebFetch) and coding tasks, answer quality beyond the lookups above, and the card's benchmark claims.
