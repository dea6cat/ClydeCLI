# Features

[Back to the README](../README.md)

## Streaming Agent

*You see the answer as I write it. Nothing hidden.*

```text
>>> /stream on
>>> Explain tests/agent/test_agent_loop.py
[streaming answer...]
• Read (tests/agent/test_agent_loop.py) running...
  ↳ lines 1-180
>>> /render-last
```

- Direct replies stream straight from the API, and tool-driven agent loops stream too
- `/stream` toggles live output; `/render-last` re-renders the last reply as clean Markdown
- You can see each tool as it runs, and if streaming fails it falls back to the regular agent loop

## Skills

*Teach me a trick once. I'll remember it.*

```md
---
description: Explain code with diagrams and analogies
allowed-tools:
  - Read
  - Grep
  - Glob
arguments: [path]
---

Explain the code in $path. Start with an analogy, then draw a diagram.
```

- Each skill is a `SKILL.md` file and becomes a slash command
- Skills can live in the project or in your user folder, take named arguments, and limit which tools they may use

## Multiple Providers

*I'm not picky about who's on the other end of the wire.*

| Provider | Key | Notes |
|----------|-----|-------|
| Anthropic | `ANTHROPIC_API_KEY` | prompt caching, adaptive thinking |
| OpenAI | `OPENAI_API_KEY` | reasoning effort on o-series / GPT-5 |
| Google Gemini | `GEMINI_API_KEY` | thinking budgets / levels |
| OpenRouter | `OPENROUTER_API_KEY` | hundreds of models behind one key |
| DeepSeek | `DEEPSEEK_API_KEY` | reasoning replayed across tool turns |
| Mistral | `MISTRAL_API_KEY` | |
| NVIDIA | `NVIDIA_API_KEY` | |
| Cerebras | `CEREBRAS_API_KEY` | |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | OpenAI-compatible route; login asks for both, lists only tool-calling text models |
| Pollinations | `POLLINATIONS_API_KEY` | OpenAI-compatible; official tool-calling text models only (community models run on third-party servers) |
| GLM (Zhipu) | `GLM_API_KEY` | |
| MiniMax | `MINIMAX_API_KEY` | via its Anthropic-compatible endpoint |
| Ollama (local) | none | native `/api/chat`, context sized to your RAM |
| oMLX (local, Apple Silicon) | none | MLX models through [oMLX](https://github.com/jundot/omlx) (Apache-2.0). Installed into `~/.clyde/omlx` from its pinned source after a yes, started on first use with a key only Clyde holds and the `balanced` memory guard (`/settings` offers aggressive, fixed ceilings and off). Serves `~/.lmstudio/models` in place |
| Ollama Cloud | `OLLAMA_API_KEY` | |
| cardShuffle | none | not a provider: deals each turn to one of the models above (see below) |

No vendor SDKs. Every provider is plain HTTP from the standard library. Model lists come live
from each provider, not a hardcoded guess. Pick one with `provider:model`, switch mid-session
with `/model`, and the conversation carries over.

### Proxies and company networks

`/proxy` shows and sets how Clyde reaches the network; `/settings` has the same two rows (Network proxy, Company
certificate). Both are applied at start through the standard environment variables, so Clyde's requests, its MCP
servers, the oMLX downloader and Bash commands all take the same route.

| Command | Does |
|---|---|
| `/proxy system` | The default: whatever `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` say |
| `/proxy http://proxy.example.com:8080` | Send everything through that proxy |
| `/proxy off` | Go direct, even when the environment names a proxy |
| `/proxy ca corp-root.pem` | Add a company root certificate, for networks that inspect TLS; `/proxy ca off` removes it |

This machine's own servers (Ollama, oMLX on `localhost`) are always reached directly: a company proxy can't reach them.
A company certificate is added to the default roots, not put in their place, so public sites still verify. When a
certificate isn't trusted, the error says so and points to `/proxy ca`. SOCKS proxies aren't supported, and Clyde
doesn't store proxy passwords: for a proxy that needs one, export `HTTPS_PROXY=http://user:pass@host:port` in your
shell profile and keep the setting on `system`. `/doctor` shows the proxy in use (never its password) and the certificates.

## Local Models That Fit

*Know the table before you buy in.*

`/models local` searches ollama.com, Hugging Face GGUF repos and, on Apple Silicon, Hugging Face MLX
repos for the popular models that fit; add words to search for something (`/models local coder`), or
name one source (`/models local mlx qwen`). Before anything is searched, Clyde reads the machine: chip, RAM, the memory models may use
(about two thirds of RAM on Apple Silicon up to 36 GB, three quarters above or elsewhere), what's free
right now and free disk. Each result is offered at the largest size that fits, rated by how much of that
memory it takes when loaded:

| Rating | Uses | Means |
|---|---|---|
| relax | ≤ 50% | plenty of headroom: long context, other apps run normally |
| balance | ≤ 80% | comfortable, but close other heavy apps while it runs |
| hard | ≤ 100% | barely fits: short context, other apps slow down, macOS may swap |

If the app a model needs isn't installed (or Ollama isn't running), Clyde shows the install command, asks first, then installs, starts it and downloads the model.

`/purge` deletes local models from Ollama and oMLX to free disk: bare, it removes all of them; `/purge qwen` only those
whose name matches. It lists what goes and the space freed, and asks first.

Models that don't fit aren't shown. Each row also has a rough speed (from the chip's memory bandwidth;
mixture-of-experts names like `30B-A3B` count only the active weights). Picking a row shows what the pull
costs before anything downloads: the download size against free disk, the memory it takes against the
budget and what's free right now, and what its rating means. Hard models default to no, and a download
bigger than the free disk is refused. After the pull, `/eval` is offered (again defaulting to no for hard
models, since loading is the heavy part); once it passes, `cardShuffle:free` can deal it.

Each model downloads with the app that runs it: ollama.com models and Hugging Face GGUF through Ollama
(`hf.co/<repo>:<quant>`, pinned to exactly the file that was rated); MLX through oMLX's own downloader, into
`~/.omlx/models` as `publisher/model` and served as `omlx:<model>` (Ctrl-C cancels it in oMLX too). MLX sizes are
exact (the repo's safetensors); GGUF sizes are exact per file; ollama.com sizes are estimated at Q4.

**A second opinion on weak replies.** Small local models slip: an empty answer, a pretend tool call
(`[TOOL_SEARCH]` written out as text), leaked special tokens, or a short refusal that says it cannot reach files or run
anything (a model that was not trained for tool use does that instead of calling the tool). These are plain text checks;
Laya's fit score was tried as a trigger and dropped, because it flagged correct answers and passed wrong ones.
When one does and a cloud provider is connected, Clyde asks once per session, naming the model and what is sent (your
request and the local reply), and on yes has that cloud model check the reply. If it is right you see nothing; otherwise
its corrected answer follows and replaces the local one in the history, labelled with the model's name. Say no and nothing
leaves the machine for the rest of the session. `CLYDE_CLOUD_REVIEW=off` turns it off. Each review is traced as a
`cloud_review` event. Hosted models' replies are never reviewed.

## cardShuffle

*Don't pick a card. I'll deal.*

`cardShuffle` shows up as a model, but it plays every turn with a real one: each new message is
dealt to a model that passed `/eval`, and that model keeps the turn through its tool rounds.

| Model | Deals |
|---|---|
| `cardShuffle:high-roller` | the strongest model first |
| `cardShuffle:house` | the middle card; in ♠ reading the table (plan mode), the strongest |
| `cardShuffle:free` | local Ollama / oMLX models only, strongest first |
| `cardShuffle:small` | the weakest, fastest model first |

Strength comes from `/eval`: every model that passes the basic tool check then plays a hand of eleven
exactly graded tasks. Four separate weak models from capable ones (chained file reads, spotting a bug,
version ordering, a Python gotcha); seven, calibrated on live models, separate the strong ones (totals
across files with distractors, a config chain with a stale note, a closure trap, parallel scheduling,
a modular sequence, date arithmetic, a logic puzzle). A model ranks by the share it solved, ties go to
the faster model, and a provider error mid-hand (credits, rate limits) leaves its earlier score alone
instead of counting as wrong answers. If the dealt model errors,
or runs out of tool turns (`[Max tool turns reached]`), the turn goes to the next card. A
`♠ dealt <model>` line shows who is playing, and `/cost` counts each real model. No key, no config:
run `/eval`, then `/model cardShuffle:house`.

**Council.** Add the word `council` to a tier (`/model cardShuffle:high-roller council`) and a turn goes to the
tier's top four models at once, with tools off. Laya rates the answers against your message, the best one is
printed, and `/council` shows all four with their scores. `/council up 2` or `/council down 2` votes on an
answer; votes are written to `~/.clyde/council_votes.jsonl` on your machine and go nowhere else. A model that
errors or takes longer than 90 seconds is left out, without Laya the strongest model's answer is shown
unranked, and the answer appears when the council is done, not as it streams. On the command line, quote it:
`clyde --model "cardShuffle:high-roller council"`. Laya scores how well an answer fits your message, not
whether it is true.

## Bonnie

*The same Clyde, in a browser.*

`clyde luv bonnie` starts Bonnie, Clyde's luv accomplice, on `localhost` (only this computer can reach it) and opens your browser. It runs the same
engine as the terminal, so it has every tool, your sessions, memory, skills and cardShuffle; Bonnie adds her own
voice and a plainer way to use them. Start her on a model with `clyde --model <provider:model> luv bonnie`
(Bonnie opens at `http://localhost:8080`; `clyde luv bonnie 7090` picks another port, and if 8080 is taken she moves to a free one and says so. `--no-open` skips the browser.) Bonnie prints a one-time link (`http://localhost:8080/?k=...`): open that once and your browser keeps a session cookie. The bare address is refused, so no other program on the machine, and no command the model runs, can fetch the page and its API token. The other way round, `bonnie luv clyde` starts the terminal Clyde, the same as `clyde`, and takes the same options.

Everything the page does goes through a small local API: queue prompts, steer or stop a running turn, list and
reopen sessions, answer permission cards, change mode or model, vote on council answers. Requests need a
per-run token and a matching Host and Origin, and the server never listens on anything but your machine. One
turn runs at a time; prompts queue behind it. The page is a sidebar of your sessions (click one to reopen it and keep talking),
Search and Computer modes (Search is read-only), a model and permissions picker, permission cards for anything that
needs a yes, queue, steer and stop buttons, and the council popup with up and down votes. It is one file with no
outside requests.

Search turns search the web first (DuckDuckGo, no key) and hand the numbered results to the model, which cites them as
links; the page lists those sources under the answer. If the search is blocked or finds nothing, the answer says it is
unsourced. While a turn runs, the page shows what Clyde is waiting on and for how long.

Under each answer sits a row of actions: copy, export as Markdown, good and poor ratings (saved on your machine in
`~/.clyde/answer_feedback.jsonl` as a hash of the question, never its text), the council popup when a council ran, a sources
chip that opens the list of what the answer cites and what else the search found, and a menu with Try again. Sessions in
the sidebar show when they were last used, so two with the same first message can be told apart. A trash icon on each session (always visible on touch screens) deletes it: it moves to the archive folder and an Undo appears for a few seconds; `clyde sessions unarchive <id>` brings it back later.

**Attachments:** the paperclip next to the message box (or dragging files onto the page, or pasting a screenshot) attaches images
(PNG, JPEG, GIF, WebP) and text or code files, up to six per message. Images go to the model the way the terminal's pasted images
do, so a model that can't see pictures is named instead of silently ignoring them, and one over 5 MB is shrunk on macOS. Text files are
put into the message. Your sent message shows thumbnails and file names, and reopening the session shows them again. PDFs and other
binary files aren't supported yet; Bonnie says so when you try.

**Artifacts** in the sidebar lists the files Clyde wrote or edited in this project, newest first, with filters for pages, documents,
images and code. Clicking one previews it beside the list: pages in a sandboxed frame (scripts off unless you turn them on, and even
then they can't reach Bonnie, your files or the network), Markdown rendered, images shown, code and text as text. Each has Download and
Show in folder, and a card appears in the chat the moment Clyde writes a file. The list is built from your saved sessions, so earlier work
shows up too. Files made by shell commands aren't included, and only files inside the project are ever read.

Bonnie looks like the site (its two fonts, hairlines, corner-cut controls) and the look is yours to change. **Customize** in
the sidebar opens a panel that changes the page as you go: a theme (Auto follows light or dark; Paper, Night, Felt, Slate),
any of seven colours, a full background image with dim, blur and see-through panels, cut, round or square corners, the font,
your own greeting, and a box for custom CSS, the way old profile pages let you. A theme code, plain text, lets you copy a look
or paste someone else's. Everything is saved in `~/.clyde/bonnie/` on your machine, and the background image never leaves it
(PNG, JPEG, GIF or WebP up to 8 MB, checked by content; SVG is refused). Custom CSS can't load anything from other sites.

**Notify me** (top bar) shows a browser notification when an answer is ready, while the Bonnie tab is in the background. Turning it on asks
your browser for permission once; the notification names your question, not the answer, so nothing private shows on a lock screen, and a
stopped turn stays silent. The choice is kept in the browser next to the permission, which belongs to the page's address
(`localhost:8080`), so if Bonnie starts on another port you turn it on again there.

**Pin** a session with the pin on its row and it stays at the top of the sidebar. **Automations** run a prompt on a schedule
(every N minutes or hours, every day, or on chosen days) in the project they were made in, each run in a session of its own, with
Pause, Run now and Delete. They run only while Bonnie is open, a run missed while she was closed is skipped, and they only read
and report unless you allow edits when you make one, because nobody is there to approve a change. The project in the sidebar is a
button: it opens a folder chooser where you browse, make a new folder where you want it, and use it; tools, permissions and new
sessions follow. On a phone the model and permission pickers sit behind **Options**, so the message box is one row. MCP servers and
hooks are loaded for the folder Bonnie started in, so restart her to pick up a new project's own.

**Providers** in the sidebar connects a model service without the terminal. Each provider is a card; a short guide walks you through
getting a key (with a link to its key page), pasting it (hidden, with a check that it looks whole), and testing it. A key is tested
before it is saved, so a wrong one is refused with a plain reason and nothing is stored. Saved keys go where `clyde login` puts them
(`~/.clyde/keys.json`, readable only by you) and are never sent back to the page, only a masked form. You can replace or disconnect a
key, add any OpenAI- or Anthropic-compatible service, and pick a connected model with one click. Ollama and oMLX show whether
they are running. Services that can't check a key without sending a message are saved as "unverified" and say so.

## Laya

*I read the table, not just the cards.*

ClydeCLI works with [Laya](https://github.com/NandhaKishorM/laya), an open-weight (Apache 2.0) decision
model that runs on your machine: no key, no network, typed answers with probabilities instead of
prose. It's an optional extra (`clyde setup` offers it, or install `clyde-cli[laya]`), pinned to a release that pins its own weights;
without it everything else works and cardShuffle simply has no stuck-model check. Its answers are
inputs to rules in Clyde's code, never the rules themselves, and it never decides permissions.

| Judgment | Type | What Clyde does with it |
|---|---|---|
| Is the dealt model repeating the same tool calls without progress? | yes/no | Acts: from the 6th tool call, every 3rd round; at 0.8 or above, cardShuffle hands the turn to the next card |
| How hard is this request? | score 0-3 | Scored on every cardShuffle turn and shown on the `♠ dealt` line. Starts in shadow mode (traced, not acted on); once the evidence below promotes it, `house` starts harder requests on stronger cards and easier ones on faster cards |

Laya costs about 640 MB of packages (mostly PyTorch) and then about 800 MB for its model: `clyde setup` asks before adding either, and Clyde itself only ever
loads it from the local cache, in the background, when a cardShuffle model is in use (about 15 s).
The first cardShuffle turn of a session waits for that load (up to 30 s, once), so Laya answers from
the first turn on, in `clyde -p` too. Each judgment then takes about 0.1 s. `/doctor` shows whether it's
downloaded and loaded. Without it, cardShuffle plays exactly as described above.

Both judgments are tuned from evidence, not guesses. Every check is traced next to how its turn
ended, and `/laya` lines them up: stuck checks by band (below 0.50, up to the 0.80 threshold, above
it) with how many were re-dealt and how many turns still ran out of tool rounds. Loops that keep
slipping under 0.80 mean the threshold should come down; re-deals that don't help mean it should go up.

Difficulty promotes itself. Laya's scores sit in a narrow band (about 1.3 to 1.9 for everything from
"hi" to a large refactor), so `/laya` splits the shadow-scored turns at their median and compares the
two halves' average tool rounds. Once each half has at least 10 finished turns and the harder half
takes at least 1.5 times as many rounds, and one round more, difficulty starts acting in
`cardShuffle:house`: a request's score is placed among past scores, and that share picks how far up
the deck the first card is (plan mode still gets the strongest). Only shadow turns count as evidence,
so turns it already steered can't argue for or against it. `/laya` says which state it's in and what
it still needs.

## whichllm

*I know which card is worth playing, and whether it fits the table.*

`/models local` ranks models with [whichllm](https://github.com/Andyyyy64/whichllm) (MIT, by Andyyyy64),
bundled as [our fork](https://github.com/dea6cat/whichLocalLLM). Size alone says what fits; whichllm says which
of the models that fit is the best, from merged real benchmarks (LiveBench, Artificial Analysis, Aider,
Chatbot Arena) with the evidence behind each score graded, and sizes each model's memory from its
architecture. The fork takes the machine from Clyde instead of detecting it, so the memory budget and
ratings match everything else in `/models local`.

| Where | What it adds |
|---|---|
| `/models local best` (and the default search) | the top-ranked GGUF models that fit this machine, ready to download |
| The download confirmation | a `details` line: benchmark quality and where it comes from, an estimated speed range with its confidence, the license |

The ranking follows what you said you use local models for at setup (`clyde tune` asks): coding if coding is
among your uses, general otherwise or if you skipped the questions.

The first run builds its model list from Hugging Face and the leaderboards in the background, which takes about
5 minutes; the group joins `/models local` when it is ready, and the list refreshes the same way every 6 hours (the
old list keeps working meanwhile). If it can't be reached the group is left out and the other sources work as before.
The speed is an estimate, not a measurement.

## SkillSpector

*I check every card before it hits the table.*

ClydeCLI loads skills, plugins and MCP servers written for other agents, and they run with your trust.
So it ships with [SkillSpector](https://github.com/NVIDIA/SkillSpector) (NVIDIA, Apache 2.0, pinned to
v2.12.0) and scans each one before the model gets it: 71 patterns across prompt injection, data
exfiltration, privilege escalation, supply chain, MCP tool poisoning and more.

| What | When | How |
|---|---|---|
| Skills (yours, other agents', plugins', the project's) | when ClydeCLI first sees one, and again whenever it changes | static scan, about 2 s; cached by content hash |
| MCP servers | when they connect | their tool list is scanned (each tool as a skill, so the tool-poisoning checks read its description and parameters) |
| Plugins | at `clyde plugin install` and `clyde plugin import`, before "Enable it?" | static scan plus the LLM review |

The static stage always runs (`--no-llm`, offline). The LLM review runs when ClydeCLI has a connected
model SkillSpector can use (Anthropic, or any OpenAI-compatible endpoint: NVIDIA, OpenRouter, OpenAI,
DeepSeek, Ollama, oMLX), with your current model (or, from the CLI, your default one). It can take
minutes, so it never runs at startup: only at plugin installs, on items the static stage flagged, and
on `/skills scan`. Ctrl+C skips it.

`DO_NOT_INSTALL` keeps an item away from the model until you allow that exact content (`/skills allow
<name>`, or `mcp:<server>`; a change brings the check back). `CAUTION` loads with a warning, and a scan
that fails warns (once per item, on stderr and as a `scan_failed` event in the trace) and loads, so a broken scanner never locks you
out of your own tools. If you would rather have nothing than something unscanned, set `CLYDE_SKILL_SCAN=closed`: an item whose scan
failed is then held back. `/skills scan`
rescans everything and shows each verdict with its findings; `/doctor` shows how many are held back.
An MCP server has already started by the time its tools are scanned: the scan decides whether the model
sees them. Turn scanning off with `CLYDE_SKILL_SCAN=off` (everything then loads unscanned, which is also how to let in an item that
`closed` holds back because the scanner keeps failing on it).

## Interactive REPL

```text
>>> Hello!
Assistant: Still here. What's broken?

>>> /help         # Show commands
>>> /             # Show all commands & skills
>>> /save         # Save session
>>> /multiline    # Multi-paragraph input
>>> Tab           # Auto-complete
>>> Esc           # Stop the current reply or command (Ctrl+C works too)
>>> Shift+Tab     # Cycle modes: ♠ hold · ♠ reading the table · ♠♠ all in
>>> Ctrl+V        # Paste a copied image as [Image #N]
>>> Cmd+V         # Paste text; long pastes fold to [Pasted text #N +X lines]
>>> /explain-code qsort.py   # Run a skill
```

## CLI

```bash
clyde                          # Start REPL
clyde --model openai:gpt-5.4   # Start with a specific model
clyde -c                       # Continue the latest session in this directory
clyde --resume [id]            # Pick a recent session, or resume one by id
clyde -p "explain src/cli.py"  # One turn, no prompt: the answer on stdout, for scripts and CI
clyde --acp                    # Agent Client Protocol on stdio, for editors such as Zed
clyde acp install zed          # Add Clyde to Zed's settings as an external agent (shows the change, asks first)
git diff | clyde -p "review"   # Piped input is added to the prompt
clyde setup                    # First-run onboarding (provider, other agents' hooks, PATH)
clyde login                    # Connect a provider, pick a default model
clyde hooks import             # Bring over hooks from Claude Code, Gemini CLI, Cursor, Copilot CLI
clyde mcp import               # Bring over MCP servers from Claude Code, Cursor, Gemini CLI, Codex, Copilot CLI
clyde update [--check] [--channel latest|stable]  # Move Clyde to the newest version of its channel, the way it was installed
clyde uninstall [--purge] [-y] # Remove Clyde the way it was installed (uv tool, pipx, pip); --purge also deletes ~/.clyde: settings, keys, sessions
clyde tune [--ask] [--model NAME] [--ctx N]  # Ollama: best memory/speed/context setup for how you use it, quality-gated; prints how to apply it
clyde doctor                   # How Clyde is installed: method, version, PATH, other installs, Claude Code, licence
clyde review [commit SHA | base BRANCH]  # Read-only review of your changes; prints and exits (2 outside a git repo)
clyde sessions list|search WORDS|archive ID|unarchive ID  # This folder's sessions: find by text, hide old ones from /resume
clyde plugin install <dir|url> # Install a plugin (then list / enable / disable / remove)
clyde plugin import            # Bring over plugins installed for Claude Code, Codex or Cursor
clyde --debug                  # Print trace events live while you work
clyde logout openai            # Forget a saved key
clyde --list-models            # Every model you can use right now
clyde config                   # View settings
clyde --version                # Check version
```

`clyde -p` runs one turn without the interactive prompt. Only the answer goes to stdout; progress,
tool calls and warnings go to stderr, so `> file` and pipes stay clean. Nobody is there to answer
a question, so anything that would ask for permission is denied (and listed), and the model is told
it can't ask you anything. Options:

| Option | Does |
|---|---|
| `--mode hold\|plan\|all_in` | Permission mode (default `hold`). `all_in` lets edits and commands through but still denies major moves (`rm -r`, `git push`, ...) |
| `--output-format json` | `{"result", "is_error", "error", "model", "num_turns", "usage", "denied", "session_id"}` |
| `--output-format stream-json` | One `{"type": "message", "message": {...}}` line per message as the turn runs (the session file's shape: text, thinking, tool calls and their results), then the `json` fields as `{"type": "result", ...}`. A run killed partway keeps every line written before |
| `--max-turns N` | Tool rounds before giving up (default 20) |
| `--time-limit SECONDS` | Stop the run after this long (startup not counted), even mid-command; error `time limit reached`, exit 1. Not on Windows (no alarm signal) |
| `--max-tokens N` | Stop once the run has used more than N tokens (prompt, cached prompt and output, over every model call), after that round's tools; error `token budget reached`, exit 1. A provider that reports no usage is counted by estimate (about 4 characters a token) |
| `--model provider:model` | As in the REPL; `cardShuffle:house` works too |

Exit status is 0 when it answered, 1 when it failed, ran out of rounds or got SIGTERM, 2 when there was nothing
to do. SIGTERM (a cancelled CI job, a harness timeout) stops the command a tool is running, along with whatever it started. The session is saved, so `clyde -c` picks the conversation up interactively.
