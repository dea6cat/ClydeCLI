<div align="center">

# 🔧 ClydeCLI

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
| Ollama Cloud | `OLLAMA_API_KEY` | |

No vendor SDKs. Every provider is plain HTTP from the standard library. Model lists come live
from each provider, not a hardcoded guess. Pick one with `provider:model`, switch mid-session
with `/model`, and the conversation carries over.

### Interactive REPL

```text
>>> Hello!
Assistant: Still here. What's broken?

>>> /help         # Show commands
>>> /             # Show all commands & skills
>>> /save         # Save session
>>> /multiline    # Multi-paragraph input
>>> Tab           # Auto-complete
>>> /explain-code qsort.py   # Run a skill
```

### CLI

```bash
clyde                          # Start REPL
clyde --model openai:gpt-5.4   # Start with a specific model
clyde -c                       # Continue the latest session in this directory
clyde --resume [id]            # Pick a recent session, or resume one by id
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

***

## 📊 Status

*What works, what doesn't. Straight answer.*

### Core Systems

| System | Status | Description |
|--------|--------|-------------|
| CLI Entry | ✅ | `clyde`, `login`, `logout`, `config`, `--model`, `--list-models`, `-c`, `--resume` |
| Interactive REPL | ✅ | Rich output, history, tab completion, multiline, streaming |
| Multi-Provider | ✅ | 12 providers, stdlib HTTP, live model lists, `provider:model` switching |
| Agent Loop | ✅ | Tool-calling loop with retries, reasoning control, history repair |
| Skill System | ✅ | SKILL.md slash-command skills with args + tool limits |
| Context Building | ✅ | Workspace snapshot, git status, a README excerpt, entry points, the code map and memory files go into the prompt: `~/.clyde/CLAUDE.md` (user), `CLAUDE.md` (project, shared) and `CLAUDE.local.md` (project, personal, keep it gitignored) |
| Permissions | ✅ | Bash asks for any command that is not read-only (dangerous patterns are refused), Write/Edit ask for docs files, Config asks before a change, WebFetch asks per domain. Answer "don't ask again" or add `permissions.allow` / `deny` rules (Claude Code syntax) to `~/.clyde/settings.json` |
| Sessions | ✅ | Auto-saved after each turn; `/resume` picker per workspace, `clyde -c` / `clyde --resume [id]` |
| Cost Tracking | ✅ | `/cost` shows input, output and cache tokens per model with an estimated $ total from catalog prices |
| Hooks | ✅ | PreToolUse / PostToolUse shell commands from `~/.clyde/settings.json` or `.toml`; also reads Gemini CLI, Cursor and Copilot CLI hook tables |
| Plugins | ✅ | `clyde plugin install` bundles of tools, skills, hooks and MCP servers (Claude Code layout) into `~/.clyde/plugins/`, enabled only after a yes |
| Self-checks | ✅ | After a Python edit, ruff (and mypy if configured) run on the file and new problems go back to the model; `/check` runs ruff, mypy and pytest |
| Tracing | ✅ | Every session writes `~/.clyde/traces/<session>.jsonl` (model and tool calls, timings, tokens, secrets redacted); `/debug` shows the last turn, `clyde --debug` streams it live |
| Compaction | ✅ | `/compact` on demand; runs automatically once history reaches 80% of the context window |

### Tools

| Category | Tools | Status |
|----------|-------|--------|
| Files | Read, Write, Edit, NotebookEdit, Glob, Grep | ✅ Working; Edit also lands a unique match that is off only by trailing whitespace or indentation |
| System | Bash | ✅ Working; asks before commands that are not read-only |
| Web | WebFetch, WebSearch | ✅ Working |
| Interaction | AskUserQuestion, SendUserMessage | ✅ Working |
| Tasks | TodoWrite, TaskCreate/Get/List/Update/Output/Stop | ✅ Working |
| Planning & config | EnterPlanMode, ExitPlanMode, Config, Skill, ToolSearch, Sleep | ✅ Working |
| Agent | Agent | ✅ Runs a general-purpose sub-agent on a fresh conversation and returns its final answer; no custom agent types or background runs |
| Scheduling | CronCreate/List/Delete | ✅ Session-scoped; due jobs run as a turn while the REPL is idle at the prompt |
| Team | TeamCreate/Delete | 🟡 Writes a team file; no multi-agent execution |
| Worktree | EnterWorktree/ExitWorktree | ✅ Creates a git worktree on a new branch; exit keeps or removes it |
| MCP | MCP, ListMcpResources, ReadMcpResource, `mcp__<server>__<tool>` | ✅ Stdio servers from `~/.clyde/settings.json`; no HTTP/SSE servers yet |
| Code map | Map | ✅ query / path / explain / affected / god_nodes over a map of the repo, refreshed when ClydeCLI starts |
| LSP | LSP | ✅ Definition, references, hover, symbols and call hierarchy via a language server on PATH |
| Not implemented | RemoteTrigger, REPL | ⏳ Stubs that return an error |

### Roadmap

- ✅ **Phase 0**: Installable, runnable CLI
- ✅ **Phase 1**: Core agent experience (REPL, sessions, slash commands)
- ✅ **Phase 2**: Real tool-calling loop, multi-provider
- ✅ **Phase 3**: Context, permissions, recovery (context building, saved permission rules, `/resume`, `/doctor`, compaction, hooks)
- ✅ **Phase 4**: MCP client (stdio), plugins, custom tools/skills/hooks, tracing and `/debug`
- 🟡 **Phase 5**: Python-native differentiators: the Code Map, check-after-edit with ruff/mypy/pytest/uv and notebook tools are in; data-engineering/ETL tooling is not

**See [FEATURE_LIST.md](FEATURE_LIST.md) for detailed feature status and PR guidelines.**

***

## 🚀 Quick Start

*Three steps. I'll wait. Might light one while you do it.*

### Install

One line (installs uv if needed, then `clyde`, then runs `clyde setup`):

```bash
curl -fsSL https://raw.githubusercontent.com/dea6cat/ClydeCLI/main/install.sh | sh
```

`clyde setup` connects a provider and picks a default model, lists the hooks, MCP servers and plugins you
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
| `/models`    | List models from every connected provider |
| `/think [level]` | Reasoning: off, low, medium, high, on, default |
| `/doctor`    | Diagnose environment, config, keys and permissions |
| `/mcp`       | Connected MCP servers and their tools |
| `/plugins`   | Loaded plugins and what each added |
| `/check`     | Run the project's ruff, mypy and pytest |
| `/debug [path]` | The last turn's model and tool calls, or the trace file path |
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

Add stdio MCP servers under `mcpServers` in `~/.clyde/settings.json` (Claude Code's format):

```json
{
  "mcpServers": {
    "dart": {"command": "dart", "args": ["mcp-server"]},
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
               "env": {"GITHUB_TOKEN": "..."}}
  }
}
```

- They start with the REPL; each tool shows up as `mcp__<server>__<tool>`, and `/mcp` lists them
- Resources are available through ListMcpResources / ReadMcpResource
- `clyde mcp import` (also offered by `clyde setup`) copies stdio servers from Claude Code
  (`~/.claude.json`), Cursor, Gemini CLI, Codex (`config.toml`) and Copilot CLI after you say yes;
  env values are never printed and the settings file is kept at mode 600
- Only stdio servers from your user settings for now: HTTP/SSE servers and project `.mcp.json`
  files are skipped

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
  reason or error), tool calls, hook blocks, permission prompts, compactions and MCP errors. API keys
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
│   ├── providers/          # LLM providers and the model catalog
│   ├── repl/               # Interactive REPL
│   ├── command_system/     # slash commands (/doctor, /cost, /context, ...)
│   ├── context_system/     # workspace, git, README and CLAUDE.md context; token estimation
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

*Bring a wrench. Pull requests welcome.*

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
