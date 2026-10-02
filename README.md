<div align="center">

# ♠ ClydeCLI

**An AI coding agent for your terminal, written in Python.**

*"Yeah, I can fix that."*
<br>— Clyde

***

[![GitHub stars](https://img.shields.io/github/stars/dea6cat/ClydeCLI?style=for-the-badge&logo=github&color=yellow)](https://github.com/dea6cat/ClydeCLI/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)

</div>

***

## 🔥 What This Is

Name's Clyde. I live in your terminal. I read your files, run your commands, pull what I need off the web, and keep at it until the thing works. No speeches. I just fix it.

Under the hood it's a Python rebuild of the Claude Code architecture. Rebuilt a few times. Still runs.

- **A real agent loop.** It calls tools, streams its replies, remembers the session, and works over many turns.
- **A faithful port.** It keeps the proven architecture, rewritten in idiomatic Python.
- **Built to study and extend.** The code is readable and tested, and you add new skills by writing Markdown.

***

## ✨ Features

### Streaming Agent

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

### Skills

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

### Multiple Providers

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
| GLM (Zhipu) | `GLM_API_KEY` | |
| MiniMax | `MINIMAX_API_KEY` | via its Anthropic-compatible endpoint |
| Ollama (local) | none | native `/api/chat`, context sized to your RAM |
| LM Studio (local) | none | picked up when installed: models from its server or `lms ls`; the server starts on first use |
| Ollama Cloud | `OLLAMA_API_KEY` | |
| cardShuffle | none | not a provider: deals each turn to one of the models above (see below) |

No vendor SDKs. Every provider is plain HTTP from the standard library. Model lists come live
from each provider, not a hardcoded guess. Pick one with `provider:model`, switch mid-session
with `/model`, and the conversation carries over.

### Local Models That Fit

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

Models that don't fit aren't shown. Each row also has a rough speed (from the chip's memory bandwidth;
mixture-of-experts names like `30B-A3B` count only the active weights). Picking a row shows what the pull
costs before anything downloads: the download size against free disk, the memory it takes against the
budget and what's free right now, and what its rating means. Hard models default to no, and a download
bigger than the free disk is refused. After the pull, `/eval` is offered (again defaulting to no for hard
models, since loading is the heavy part); once it passes, `cardShuffle:free` can deal it.

Each model downloads with the app that runs it: ollama.com models through Ollama; MLX through LM Studio
(`lms get <url> --mlx`); Hugging Face GGUF through Ollama (`hf.co/<repo>:<quant>`), or LM Studio when
Ollama isn't running (`lms get <url>@<quant>`, pinned to exactly the file that was rated). MLX sizes are
exact (the repo's safetensors); GGUF sizes are exact per file; ollama.com sizes are estimated at Q4.

### cardShuffle

*Don't pick a card. I'll deal.*

`cardShuffle` shows up as a model, but it plays every turn with a real one: each new message is
dealt to a model that passed `/eval`, and that model keeps the turn through its tool rounds.

| Model | Deals |
|---|---|
| `cardShuffle:high-roller` | the strongest model first |
| `cardShuffle:house` | the middle card; in ♠ reading the table (plan mode), the strongest |
| `cardShuffle:free` | local Ollama / LM Studio models only, strongest first |
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

### Laya

*I read the table, not just the cards.*

ClydeCLI ships with [Laya](https://github.com/NandhaKishorM/laya), an open-weight (Apache 2.0) decision
model that runs on your machine: no key, no network, typed answers with probabilities instead of
prose. It's a required dependency, pinned to a release that pins its own weights. Its answers are
inputs to rules in Clyde's code, never the rules themselves, and it never decides permissions.

| Judgment | Type | What Clyde does with it |
|---|---|---|
| Is the dealt model repeating the same tool calls without progress? | yes/no | Acts: from the 6th tool call, every 3rd round; at 0.8 or above, cardShuffle hands the turn to the next card |
| How hard is this request? | score 0-3 | Shadow mode for `cardShuffle:house`: shown on the `♠ dealt` line and traced in `/debug`, not acted on until it's measured on real turns |

Laya's model is about 800 MB: `clyde setup` asks before downloading it, and Clyde itself only ever
loads it from the local cache, in the background, when a cardShuffle model is in use (about 15 s,
before the first turn needs it). Each judgment then takes about 0.1 s. `/doctor` shows whether it's
downloaded and loaded. Without it, cardShuffle plays exactly as described above.

Both judgments are tuned from evidence, not guesses. Every check is traced next to how its turn
ended, and `/laya` lines them up: stuck checks by band (below 0.50, up to the 0.80 threshold, above
it) with how many were re-dealt and how many turns still ran out of tool rounds, and difficulty bands
with their average tool rounds. Loops that keep slipping under 0.80 mean the threshold should come
down; re-deals that don't help mean it should go up. Difficulty moves out of shadow mode into
`cardShuffle:house` once harder bands clearly take more rounds.

### SkillSpector

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
DeepSeek, Ollama, LM Studio), with your current model (or, from the CLI, your default one). It can take
minutes, so it never runs at startup: only at plugin installs, on items the static stage flagged, and
on `/skills scan`. Ctrl+C skips it.

`DO_NOT_INSTALL` keeps an item away from the model until you allow that exact content (`/skills allow
<name>`, or `mcp:<server>`; a change brings the check back). `CAUTION` loads with a warning, and a scan
that fails warns and loads, so a broken scanner never locks you out of your own tools. `/skills scan`
rescans everything and shows each verdict with its findings; `/doctor` shows how many are held back.
An MCP server has already started by the time its tools are scanned: the scan decides whether the model
sees them. Turn scanning off with `CLYDE_SKILL_SCAN=off`.

### Interactive REPL

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

### CLI

```bash
clyde                          # Start REPL
clyde --model openai:gpt-5.4   # Start with a specific model
clyde -c                       # Continue the latest session in this directory
clyde --resume [id]            # Pick a recent session, or resume one by id
clyde -p "explain src/cli.py"  # One turn, no prompt: the answer on stdout, for scripts and CI
git diff | clyde -p "review"   # Piped input is added to the prompt
clyde setup                    # First-run onboarding (provider, other agents' hooks, PATH)
clyde login                    # Connect a provider, pick a default model
clyde hooks import             # Bring over hooks from Claude Code, Gemini CLI, Cursor, Copilot CLI
clyde mcp import               # Bring over MCP servers from Claude Code, Cursor, Gemini CLI, Codex, Copilot CLI
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
| `--max-turns N` | Tool rounds before giving up (default 20) |
| `--model provider:model` | As in the REPL; `cardShuffle:house` works too |

Exit status is 0 when it answered, 1 when it failed or ran out of rounds, 2 when there was nothing
to do. The session is saved, so `clyde -c` picks the conversation up interactively.

***

## 📊 Status

*What works, what doesn't. Straight answer.*

### Core Systems

| System | Status | Description |
|--------|--------|-------------|
| CLI Entry | ✅ | `clyde`, `login`, `logout`, `config`, `--model`, `--list-models`, `-c`, `--resume`, `-p` (headless: answer on stdout, JSON output, exit status) |
| Interactive REPL | ✅ | Rich output, history, tab completion, multiline, streaming |
| Multi-Provider | ✅ | 13 providers (incl. local Ollama and LM Studio), stdlib HTTP, live model lists, `provider:model` switching |
| Agent Loop | ✅ | Tool-calling loop with retries, reasoning control, history repair |
| Skill System | ✅ | SKILL.md slash-command skills with args + tool limits |
| Context Building | ✅ | Workspace snapshot, git status, a README excerpt, entry points, the code map and memory files go into the prompt: `~/.clyde/CLYDE.md` (user), `CLYDE.md` (project, shared) and `CLYDE.local.md` (project, personal, keep it gitignored). Files written for other agents are read too: `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.github/copilot-instructions.md` (one per folder, first found wins) |
| Permissions | ✅ | Bash asks for any command that is not read-only (dangerous patterns are refused), Write/Edit ask for docs files, Config asks before a change, WebFetch asks per domain. Answer "don't ask again" or add `permissions.allow` / `deny` rules (Claude Code syntax) to `~/.clyde/settings.json` |
| Sandbox | ✅ | Shell commands write only to the project, temp and package caches (macOS `sandbox-exec`, Linux `bwrap`); `unsandboxed: true` always asks |
| Sessions | ✅ | Auto-saved after each turn; `/resume` picker per workspace, `clyde -c` / `clyde --resume [id]` |
| Checkpoints | ✅ | `/rewind` undoes the model's file edits and/or the conversation back to before any of your messages; saved per session, so they survive `/resume` |
| Cost Tracking | ✅ | `/cost` shows input, output and cache tokens per model with an estimated $ total from catalog prices |
| Hooks | ✅ | PreToolUse / PostToolUse shell commands from `~/.clyde/settings.json` or `.toml`; also reads Gemini CLI, Cursor and Copilot CLI hook tables |
| Plugins | ✅ | `clyde plugin install` bundles of tools, skills, hooks and MCP servers (Claude Code layout) into `~/.clyde/plugins/`, enabled only after a yes |
| Self-checks | ✅ | After a Python edit, ruff (and mypy if configured) run on the file and new problems go back to the model; `/check` runs ruff, mypy and pytest |
| Tracing | ✅ | Every session writes `~/.clyde/traces/<session>.jsonl` (model and tool calls, timings, tokens, secrets redacted); `/debug` shows the last turn, `clyde --debug` streams it live |
| Compaction | ✅ | `/compact` on demand; runs automatically once history reaches 80% of the context window |
| cardShuffle | ✅ | A model that deals each turn to an `/eval`-ranked real model (high-roller, house, free, small), with fallback on errors, max tool turns and stuck loops |
| Local models | ✅ | `/models local` finds ollama.com, Hugging Face GGUF and MLX models that fit this machine, rated relax / balance / hard, confirmed before download through Ollama or LM Studio |
| SkillSpector | ✅ | Bundled scanner for skills, plugins and MCP servers from other agents: static always, LLM review when a usable model is connected; `DO_NOT_INSTALL` items held back until `/skills allow` |
| Laya | ✅ | Bundled local decision model: hands a stuck cardShuffle turn to the next card; scores difficulty in shadow mode; `/laya` shows the evidence |
| Pasting | ✅ | Ctrl+V pastes a copied image, a copied image path becomes the image, long pastes fold to `[Pasted text #N +X lines]` |

### Tools

| Category | Tools | Status |
|----------|-------|--------|
| Files | Read, Write, Edit, NotebookEdit, Glob, Grep | ✅ Working; Edit also lands a unique match that is off only by trailing whitespace or indentation |
| Data | Data | ✅ Profile CSV, TSV, Parquet, JSON and SQLite files (types, nulls, distinct counts, min/max, samples) and run read-only SQL across them with DuckDB, sandboxed to the workspace |
| System | Bash | ✅ Working; asks before commands that are not read-only, and runs in the OS sandbox |
| Web | WebFetch, WebSearch | ✅ Working |
| Interaction | AskUserQuestion, SendUserMessage | ✅ Working |
| Tasks | TodoWrite, TaskCreate/Get/List/Update/Output/Stop | ✅ Working |
| Planning & config | EnterPlanMode, ExitPlanMode, Config, Skill, ToolSearch, Sleep | ✅ Working |
| Agent | Agent | ✅ Runs a general-purpose sub-agent on a fresh conversation and returns its final answer; no custom agent types or background runs |
| Scheduling | CronCreate/List/Delete | ✅ Session-scoped; due jobs run as a turn while the REPL is idle at the prompt |
| Team | TeamCreate/Delete | 🟡 Writes a team file; no multi-agent execution |
| Worktree | EnterWorktree/ExitWorktree | ✅ Creates a git worktree on a new branch; exit keeps or removes it |
| MCP | MCP, ListMcpResources, ReadMcpResource, `mcp__<server>__<tool>` | ✅ Stdio, Streamable HTTP and HTTP+SSE servers from `~/.clyde/settings.json`; header auth or OAuth sign-in (`/mcp login`) |
| Code map | Map | ✅ query / path / explain / affected / god_nodes over a map of the repo, refreshed when ClydeCLI starts |
| LSP | LSP | ✅ Definition, references, hover, symbols and call hierarchy via a language server on PATH |

### Roadmap

- ✅ **Phase 0**: Installable, runnable CLI
- ✅ **Phase 1**: Core agent experience (REPL, sessions, slash commands)
- ✅ **Phase 2**: Real tool-calling loop, multi-provider
- ✅ **Phase 3**: Context, permissions, recovery (context building, saved permission rules, `/resume`, `/doctor`, compaction, hooks)
- ✅ **Phase 4**: MCP client (stdio, Streamable HTTP, HTTP+SSE), plugins, custom tools/skills/hooks, tracing and `/debug`
- ✅ **Phase 5**: Python-native differentiators: the Code Map, check-after-edit with ruff/mypy/pytest/uv, notebook tools, and the Data tool for data and ETL work
- ✅ **Phase 6**: Model play: cardShuffle routing across `/eval`-ranked models, local models that fit the machine (ollama.com, Hugging Face GGUF and MLX), Laya bundled for stuck-loop detection, and SkillSpector bundled to scan skills, plugins and MCP servers
- 🟡 **Next**: promote Laya's difficulty score from shadow mode into `cardShuffle:house` once `/laya` shows it separates easy turns from hard ones

**See [FEATURE_LIST.md](FEATURE_LIST.md) for detailed feature status and PR guidelines.**

***

## 🚀 Quick Start

*Three steps. I'll wait. Might light one while you do it.*

### Install

One line (installs uv if needed, then `clyde`, then runs `clyde setup`):

```bash
curl -fsSL https://raw.githubusercontent.com/dea6cat/ClydeCLI/main/install.sh | sh
```

It includes Laya, the bundled decision model, and SkillSpector, the bundled skill scanner, so the
install is about 850 MB (mostly PyTorch).
`clyde setup` connects a provider and picks a default model, asks before downloading Laya's model
(about 800 MB), lists the hooks, MCP servers and plugins you
already set up for other agents (Claude Code, Cursor, Gemini CLI, Codex, Copilot CLI) and imports
them only if you say yes, and offers to
put `clyde` on your PATH. Pass `--yes` for no prompts (hooks, MCP servers and plugins are never imported that way). Run it
again any time.

Or from source:

```bash
git clone https://github.com/dea6cat/ClydeCLI.git
cd ClydeCLI

# Create venv (uv recommended)
uv venv --python 3.14
source .venv/bin/activate

# Install
uv pip install -r requirements.txt
```

### Configure

#### Option 1: Just export a key (no login needed)

If a provider key is already in your environment (see the table above), run `clyde`. With no
default model saved, it picks one from whatever is connected (local Ollama first), tells you
which, and `/model` switches it.

#### Option 2: Interactive login

```bash
python -m src.cli login
```

This flow will:

1. ask you to choose a provider
2. ask for that provider's API key (shown as `*` while you type or paste)
3. fetch the provider's live model list and ask for a default model
4. save the key to `~/.clyde/keys.json` and the model to `~/.clyde/config.json`

For Ollama there's no key: it checks the server is up, and if you have no models yet it
suggests tool-capable ones that fit your RAM.

#### Option 3: Pick the model per session

`clyde --model openai:gpt-5.4` overrides the default for one session. A key exported in your
shell always wins over a saved one.

The config file only holds the default model and session settings:

```json
{
  "model": "anthropic:claude-sonnet-4-6",
  "session": {"auto_save": true, "max_history": 100}
}
```

Upgrading from an older config with per-provider `api_key` entries? The first run moves the
keys to `keys.json` and keeps your default provider's model.

### Run

```bash
python -m src.cli          # Start REPL
python -m src.cli --help   # Show help
```

That's all it takes: clone, configure, run.

***

## 💡 Usage

### REPL Commands

| Command      | Description           |
| ------------ | --------------------- |
| `/`          | Show commands & skills |
| `/help`      | Show all commands     |
| `/save`      | Save session          |
| `/load <id>` | Load session          |
| `/resume [id]` | Pick a recent session of this workspace to continue |
| `/multiline` | Toggle multiline mode |
| `/model [provider:model]` | Show or switch the model |
| `/models [all\|refresh]` | List models from every connected provider; hides ones `/eval` found broken (`all` shows them, `refresh` re-fetches the lists) |
| `/models local [ollama\|hf\|mlx] [words]` | Find local models on ollama.com and Hugging Face (GGUF, and MLX on Apple Silicon) that fit this machine, rated relax / balance / hard, and download one |
| `/eval [filter]` | Test listed models on a tool call and a round trip, then a hand of 11 graded tasks for those that pass; shows pass/fail, hand score, latency and tok/s, and remembers which ones don't work |
| `/think [level]` | Reasoning: off, low, medium, high, on, default |
| `/doctor`    | Diagnose environment, config, keys and permissions |
| `/mcp`       | Connected MCP servers and their tools |
| `/mcp login <server>` / `/mcp logout <server>` | OAuth sign-in (browser) for a remote MCP server, or forget its tokens |
| `/plugins`   | Loaded plugins and what each added |
| `/check`     | Run the project's ruff, mypy and pytest |
| `/debug [path]` | The last turn's model and tool calls, or the trace file path |
| `/skills scan` / `/skills allow <name>` | Rescan skills with SkillSpector (LLM review when your model allows) and show verdicts; let a held-back skill, plugin or `mcp:<server>` in |
| `/rewind` | Undo the model's file edits and/or the conversation back to before one of your messages |
| `/laya` | Laya's status, and how its stuck checks and difficulty scores lined up with how traced turns ended |
| `/cost`      | Tokens and estimated cost per model |
| `/context`   | Context window usage and auto-compact threshold |
| `/compact`   | Summarize the conversation to free context |
| `/clear`     | Clear history         |
| `/exit`      | Exit REPL             |

### Writing Skills

*Write it down once. I'll handle the rest.*

Skills are slash commands written in Markdown and stored under `.clyde/skills`. Each skill lives in its own directory, and its file must be named `SKILL.md`.

**1) Create a project skill**

```text
<project-root>/.clyde/skills/<skill-name>/SKILL.md
```

Example:

```md
---
description: Explains code with diagrams and analogies
when_to_use: Use when explaining how code works
allowed-tools:
  - Read
  - Grep
  - Glob
arguments: [path]
---

Explain the code in $path. Start with an analogy, then draw a diagram.
```

**2) Use it in the REPL**

```text
❯ /
❯ /<skill-name> <args>
```

Example:

```text
❯ /explain-code qsort.py
```

**Notes**

- User-level skills: `~/.clyde/skills/<skill-name>/SKILL.md`
- Skills you already have for other agents are read in place: `~/.claude/skills`, `~/.agents/skills`,
  `~/.codex/skills`, `~/.copilot/skills` and `~/.gemini/skills`. On a name clash `~/.clyde/skills` wins
- Tool limits: `allowed-tools` controls which tools the skill can use.
- Arguments: use `$ARGUMENTS`, `$0`, `$1`, or named args like `$path` (from `arguments`).
- Placeholder syntax: use `$path`, not `${path}`.

### Code Map

*I don't grep a city block by block. I look at the map.*

ClydeCLI gives whatever model you run a map of your repo: its symbols, calls and imports, built
from the code's syntax tree with no LLM involved (the map is built by
[graphify](https://github.com/safishamsi/graphify)):

- `clyde setup` offers to install the map builder (`uv tool install graphifyy`)
- Starting `clyde` inside a git repo refreshes the map in the background (about 2-3s for this repo)
  into `.clyde/code-map/map.json`, kept out of `git status` via `.git/info/exclude`. Set
  `CLYDE_MAP=off` to skip it
- The context prompt tells the model the map exists, lists the repo's most connected symbols, and
  points it at the **Map** tool before blind Grep/Glob searches:
  - `query` "how does auth work": the symbols and files that relate to a question
  - `explain` X: a symbol, where it lives, and what it connects to
  - `path` A B: how one symbol reaches another (`ClydeREPL → .chat() → run_agent_loop() → … → run_hooks()`)
  - `affected` X: what depends on X, before you change it
  - `god_nodes`: the architectural hubs; `update`: rebuild after big edits
- Because it is a plain tool plus prompt context, it works the same with every provider, local
  Ollama models included

### Hooks

Run your own shell commands before or after a tool call. Put them in `~/.clyde/settings.json`
or `~/.clyde/settings.toml` (both are read and merged), in Claude Code's format:

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/bin/check-command.sh"}]}
    ],
    "PostToolUse": [
      {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "ruff format --quiet ."}]}
    ]
  }
}
```

- `matcher` is a regex on the tool name; `""` or `"*"` matches every tool
- Shorthand works too: `{"PreToolUse": {"Bash": "cmd"}}` (a command or list per matcher), or a list
  of command strings for every tool. In TOML: `[hooks.PreToolUse]` then `Bash = "cmd"`
- Hook tables written for other agents are accepted as-is: Gemini CLI (`BeforeTool`/`AfterTool`,
  Gemini tool names like `run_shell_command` or `write_file` in the matcher), Cursor
  (`beforeShellExecution`, `beforeReadFile`, `afterFileEdit`) and Copilot CLI
  (`preToolUse`/`postToolUse` with `bash` and `timeoutSec`). Events ClydeCLI has no equivalent
  for (e.g. `stop`) are ignored
- The command gets the event as JSON on stdin: `hook_event_name`, `tool_name`, `tool_input`, `cwd`,
  plus `tool_response` for PostToolUse
- Exit 2 blocks the call (PreToolUse) or sends stderr back to the model (PostToolUse). So does a
  JSON reply on stdout that denies or blocks (`{"decision": "block", "reason": ...}`,
  `{"permission": "deny"}`, `{"permissionDecision": "deny"}`); anything else carries on. Each command times out after 60s (`"timeout"` overrides it)
- Already have hooks for another agent? `clyde hooks import` (also offered by `clyde setup`) finds
  them in `~/.claude/settings.json`, `~/.gemini/settings.json`, `~/.cursor/hooks.json` and
  `~/.copilot/hooks.json`, shows every command, and copies them only after you say yes
- Only your user settings are read; project `.clyde/settings.json` hooks are ignored, since a cloned
  repo could otherwise run commands on your machine

### MCP Servers

Add MCP servers under `mcpServers` in `~/.clyde/settings.json` (Claude Code's format): local ones
that ClydeCLI starts (stdio), and remote ones it reaches over HTTP:

```json
{
  "mcpServers": {
    "dart": {"command": "dart", "args": ["mcp-server"]},
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
               "env": {"GITHUB_TOKEN": "..."}},
    "linear": {"type": "http", "url": "https://mcp.linear.app/mcp",
               "headers": {"Authorization": "Bearer ${LINEAR_TOKEN}"}},
    "legacy": {"type": "sse", "url": "https://example.com/sse"}
  }
}
```

| Config | Transport |
|---|---|
| `command` (+ `args`, `env`) | stdio: newline-delimited JSON-RPC to a process ClydeCLI starts |
| `"type": "http"`, or Gemini CLI's `httpUrl` | Streamable HTTP: each message is a POST, replies come back as JSON or an event stream, and the server's `Mcp-Session-Id` rides on every later request |
| `"type": "sse"` | HTTP+SSE (the 2024-11-05 protocol): a stream stays open, its `endpoint` event names where to POST, replies arrive on the stream |
| just a `url` (Cursor's form) | Streamable HTTP first, falling back to HTTP+SSE when the server refuses the POST, as the spec advises |

`${VAR}` in a `url` or a header comes from your environment, so tokens can stay out of the file.
Remote servers sign in with headers (API keys, bearer tokens) or with OAuth. A server that wants
OAuth shows as "needs sign-in" until you run `/mcp login <server>` (or `clyde mcp login <server>`):
ClydeCLI finds the server's authorization server from its metadata (RFC 9728 / RFC 8414), registers
itself (RFC 7591, so there's no app to create), opens your browser on the sign-in page with PKCE, and
catches the redirect on `127.0.0.1`. Tokens are kept in `~/.clyde/mcp_oauth.json` (mode 600), sent
with every request and refreshed when they expire or the server rejects them; `/mcp logout <server>`
forgets them. A sign-in never starts on its own, and a server you give an `Authorization` header
keeps using that header.

- They start with the REPL; each tool shows up as `mcp__<server>__<tool>`, and `/mcp` lists them
- Resources are available through ListMcpResources / ReadMcpResource
- `clyde mcp import` (also offered by `clyde setup`) copies stdio and remote servers from Claude Code
  (`~/.claude.json`), Cursor, Gemini CLI, Codex (`config.toml`) and Copilot CLI after you say yes;
  env values are never printed and the settings file is kept at mode 600
- A project's own `.mcp.json` (Claude Code's format, at the repo root) adds its servers. A repository
  can put anything there, so each server starts only after you say yes, and the answer covers that
  exact entry: a changed command asks again. `${VAR}` and `${VAR:-default}` expand from your
  environment; your own settings win a name clash; `clyde -p` skips entries you haven't answered yet.
  Answers live in `~/.clyde/mcp_project_approvals.json`
- SkillSpector scans every server's tool list when it connects, local or remote (see SkillSpector)

### Modes

*Every hand plays differently. Pick how I play this one.*

Shift+Tab cycles the mode, shown under the prompt:

| Mode | What it does |
|---|---|
| `♠ hold` | The default. Asks before anything risky: non-read-only shell commands, doc edits, settings changes |
| `♠ reading the table` | Plan mode. Reads, searches and runs read-only commands, then presents a plan; anything that would change files is refused until the plan is in |
| `♠♠ all in` | Plays without asking, except major moves: `rm -r`/`-f`, `git push`, `git reset --hard`, `git clean -f`, `branch -D`, publishing, `curl … \| sh`, `docker rm`/`prune`, `kubectl delete`, `terraform apply`/`destroy`, `chmod -R`, `kill -9`, writing to secrets |

Deny rules and the always-refused commands (like `sudo`) apply in every mode, and writes outside the
project are refused in every mode.

### Data Files

*Let me look at the numbers before you build the pipeline.*

The Data tool lets any model look at data the way a data engineer would, instead of reading a
50 MB CSV line by line:

- `profile` a file: row count, columns and types, null percentage, approximate distinct counts,
  min/max/mean, and five sample rows. CSV, TSV, Parquet, JSON and JSONL go through DuckDB; a SQLite
  database shows its tables, columns and row counts
- `query` with SQL: `SELECT region, sum(amount) FROM 'sales/*.parquet' JOIN 'regions.csv' USING (id)
  GROUP BY 1`. Files are referenced by path (relative to the project, globs work) and can be joined;
  pass `database` to query a SQLite file instead

It only reads. DuckDB runs sandboxed: files inside the project only, no network, no extension
installs, settings locked, and only SELECT-type statements (checked with DuckDB's own parser, so
`COPY ... TO`, `ATTACH` or `CREATE` are refused). SQLite opens read-only behind an authorizer that
refuses anything but reads. Each call has a 60 s limit and returns at most 1,000 rows.

### Rewind

*Bad hand? Take it back.*

Every message you send opens a checkpoint. The first time the model changes a file in that turn
(Write, Edit, NotebookEdit), the file is saved as it was, or noted as new. `/rewind` lists your recent
messages with the files each one changed; pick one and choose:

| Choice | Does |
|---|---|
| `c` code and conversation (default) | Files go back to how they were before that message (files the model created are removed), the conversation is cut there, and your message comes back in the prompt to edit or resend |
| `f` files only | Just the files |
| `m` conversation only | Just the conversation, files untouched |

Checkpoints live in `~/.clyde/checkpoints/<session>/` (the newest 20 sessions), so they survive
`/resume`. Changes made by shell commands (`rm`, `mv`, scripts) aren't captured: there's no reliable
way to know what a command touches, so commit before risky runs. If the conversation was compacted
or cleared after a checkpoint, only its files can be rewound.

### Pasting

*Show me the cards. I'll read them.*

| Paste | What lands in the prompt |
|---|---|
| Ctrl+V with an image copied (a screenshot, an image copied from a browser) | `[Image #N]` |
| Cmd+V with an image file path copied (plain, quoted, `\ `-escaped or `file://`) | `[Image #N]` |
| Cmd+V with text over 2 lines or 800 characters | `[Pasted text #N +X lines]` |

Images and pasted texts share one counter. On send, each `[Image #N]` attaches that image (PNG,
JPEG, GIF or WebP) and each `[Pasted text #N …]` expands back to the full text; the transcript keeps
the short marker. Images travel with every provider and are saved with the session, so `/resume`
keeps them. An image over 5 MB is shrunk (JPEG, longest side 2048 px, with macOS's built-in `sips`;
elsewhere it's refused). When the model can't read images (the catalog says so, or Ollama doesn't
list vision), pasting says so, and sending drops the image with a note instead of failing; models
the catalog doesn't know get the image. Clipboard images use `osascript` on macOS and `wl-paste` or
`xclip` on Linux.

### Sandbox

*You can look at the whole table. You only touch your own chips.*

Every shell command the model runs goes through an OS sandbox: it can read anything and use the
network, but it can **write only** inside the project (and extra working directories), temp folders
and package caches (`~/.cache`, `~/Library/Caches`, npm, pnpm, yarn, bun, cargo, gradle, maven, Go,
Dart/Flutter pub). macOS uses the built-in `sandbox-exec`; Linux uses `bwrap` (install bubblewrap);
elsewhere commands run unsandboxed and `/doctor` says so. Your hooks aren't sandboxed: they're yours.

A blocked write fails with "Operation not permitted" plus a hint, so the model knows why. A command
that really has to write elsewhere (a global install, a dotfile) can ask to run with
`unsandboxed: true`, and that **always asks you**, even in all-in mode (`clyde -p` denies it).

```json
{"sandbox": {"enabled": true, "network": true, "allow_write": ["~/.local/bin"]}}
```

`network: false` blocks everything but localhost; `allow_write` adds folders; `enabled: false` turns it off.

### Permission Rules

Stop answering the same prompt. Add rules to `~/.clyde/settings.json` (Claude Code's syntax), or
pick **"Yes, and don't ask again"** at a prompt to save one:

```json
{"permissions": {"allow": ["Bash(npm test)", "Bash(git commit:*)", "Edit(docs/**)", "WebFetch(domain:docs.python.org)"],
                 "deny": ["Bash(rm -rf:*)"]}}
```

- `Bash(cmd)` is exact, `Bash(prefix:*)` matches whole leading words, bare `Bash` matches everything
- A compound command (`&&`, `;`, `|`) is allowed only if every part is; read-only parts like `cd` count
- `Edit(...)` / `Write(...)` take globs relative to the workspace; deny rules win and block without asking

### Plugins

A plugin is a folder that bundles extensions; Claude Code plugins mostly work as-is:

```text
<plugin>/.clyde-plugin/plugin.json   {"name", "version", "description"}  (.claude-plugin/ also works)
<plugin>/skills/<name>/SKILL.md      skills
<plugin>/hooks/hooks.json            PreToolUse / PostToolUse hooks
<plugin>/.mcp.json                   {"mcpServers": {...}} stdio servers
<plugin>/tools/*.py                  Python tools, same format as ~/.clyde/tools
```

- `clyde plugin install <folder-or-git-url>` shows what it contains and asks before enabling it
  (`--yes` installs it disabled); `clyde plugin list | enable | disable | remove` manage it
- Already use plugins in Claude Code, Codex or Cursor? `clyde plugin import` (also offered by
  `clyde setup`) lists every one it finds, what ClydeCLI can load from it and why any are skipped, and
  copies and enables each only after its own yes; plugins switched off in their agent default to no
- `${CLYDE_PLUGIN_ROOT}` (or `${CLAUDE_PLUGIN_ROOT}`) in hook and MCP commands is the plugin's folder
- Plugin tools and MCP servers never replace existing ones; clashes are skipped with a warning.
  Markdown `commands/` are not supported yet

### Self-Checks

- After ClydeCLI writes or edits a Python file, it runs ruff (and mypy, if the project configures it)
  on that file and hands only the problems the edit introduced back to the model in the same turn
- `/check` runs the project's ruff, mypy and pytest and prints a short summary
- Tools are found from `pyproject.toml`, config files and `uv.lock` (run with `uv run --no-sync`, the
  project's `.venv`, or PATH); ClydeCLI never installs them. Off: `CLYDE_CHECKS=off` or
  `{"checks": {"enabled": false}}` in `~/.clyde/settings.json`

### Tracing and /debug

- Each session writes `~/.clyde/traces/<session_id>.jsonl`: model requests (duration, tokens, stop
  reason or error), tool calls, hook blocks, permission prompts, compactions, MCP errors, Laya's
  judgments and how each turn ended (tool rounds, and whether it ran out). API keys
  and key-shaped values are redacted and long values cut to 500 characters
- `/debug` shows the last turn, `/debug path` the trace file, and `clyde --debug` prints events live
- Off: `CLYDE_TRACE=off` or `"session": {"trace": false}` in `~/.clyde/config.json`; the newest 50
  traces are kept

***

## 📦 Project Structure

```text
ClydeCLI/
├── src/
│   ├── cli.py              # CLI entry
│   ├── config.py           # config.json and default model
│   ├── agent/              # conversation, sessions, agent loop, cost tracking
│   ├── providers/          # LLM providers, the model catalog, cardShuffle, Laya, local model sources and fit
│   ├── repl/               # Interactive REPL
│   ├── command_system/     # slash commands (/doctor, /cost, /context, ...)
│   ├── context_system/     # workspace, git, README and CLYDE.md memory context; token estimation
│   ├── compact_service/    # /compact and auto-compaction
│   ├── output_styles/      # reply style prompts
│   ├── skills/             # SKILL.md loading and creation
│   ├── plugins.py          # plugin install and loading
│   ├── startup/            # setup report
│   └── tool_system/        # tool registry, permissions, validation, tools/
├── tests/                  # mirrors src/
├── .clyde/
│   └── skills/             # Project-local custom skills
└── FEATURE_LIST.md         # Current feature status
```

***

## 🤝 Contributing

*Pull up a chair. Pull requests welcome.*

```bash
# Quick dev setup
pip install -e .[dev]
python -m pytest tests/ -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

***

## 📖 Documentation

- **[SETUP_GUIDE.md](docs/guide/SETUP_GUIDE.md)**: detailed installation
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: development guide
- **[TESTING.md](docs/guide/TESTING.md)**: testing guide
- **[CHANGELOG.md](CHANGELOG.md)**: version history

***

## 🔒 Security

*Keep your keys where you keep your lighter. Close, and out of the repo.*

- Keep sensitive data out of Git
- Saved API keys live in `~/.clyde/keys.json`, plain text, readable only by you (mode 600)
- `.env` files are git-ignored
- Intended for local development

***

## 📄 License

MIT License. See [LICENSE](LICENSE).

***

## 🙏 Acknowledgments

- Based on the Claude Code architecture
- An independent educational project
- Not affiliated with Anthropic

***

<div align="center">

*"Okay. New plan."*

If I fixed something for you, a ⭐ helps. Or don't. I'll still be here.

**Written by dea6cat**

[⬆ Back to Top](#-clydecli)

</div>
