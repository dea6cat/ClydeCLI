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
>>> Explain tests/test_agent_loop.py
[streaming answer...]
• Read (tests/test_agent_loop.py) running...
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
clyde login                    # Connect a provider, pick a default model
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
| CLI Entry | ✅ | `clyde`, `login`, `logout`, `config`, `--model`, `--list-models` |
| Interactive REPL | ✅ | Rich output, history, tab completion, multiline, streaming |
| Multi-Provider | ✅ | 12 providers, stdlib HTTP, live model lists, `provider:model` switching |
| Agent Loop | ✅ | Tool-calling loop with retries, reasoning control, history repair |
| Skill System | ✅ | SKILL.md slash-command skills with args + tool limits |
| Context Building | 🟡 | Workspace snapshot, git status, a README excerpt, entry points (`[project.scripts]`, package.json `main`/`bin`) and memory files go into the prompt: `~/.clyde/CLAUDE.md` (user), `CLAUDE.md` (project, shared) and `CLAUDE.local.md` (project, personal, keep it gitignored); no deeper project indexing |
| Permissions | 🟡 | Interactive approval is wired into tool dispatch, but only Write and Edit ask; Bash only blocks a short list of dangerous patterns |
| Sessions | 🟡 | Manual `/save` and `/load`; no session picker, no auto-save |
| Compaction | ✅ | `/compact` on demand; runs automatically once history reaches 80% of the context window |

### Tools

| Category | Tools | Status |
|----------|-------|--------|
| Files | Read, Write, Edit, NotebookEdit, Glob, Grep | ✅ Working |
| System | Bash | ✅ Working |
| Web | WebFetch, WebSearch | ✅ Working |
| Interaction | AskUserQuestion, SendUserMessage | ✅ Working |
| Tasks | TodoWrite, TaskCreate/Get/List/Update/Output/Stop | ✅ Working |
| Planning & config | EnterPlanMode, ExitPlanMode, Config, Skill, ToolSearch, Sleep | ✅ Working |
| Agent | Agent | ✅ Runs a general-purpose sub-agent on a fresh conversation and returns its final answer; no custom agent types or background runs |
| Scheduling | CronCreate/List/Delete | 🟡 Stores jobs for the session; nothing runs them |
| Team | TeamCreate/Delete | 🟡 Writes a team file; no multi-agent execution |
| Worktree | EnterWorktree/ExitWorktree | ✅ Creates a git worktree on a new branch; exit keeps or removes it |
| MCP | MCP, ListMcpResources, ReadMcpResource | ⏳ Tools exist, but no MCP client is connected yet |
| LSP | LSP | ⏳ Tool exists, but no language-server client is connected yet |
| Not implemented | RemoteTrigger, REPL | ⏳ Stubs that return an error |

### Roadmap

- ✅ **Phase 0**: Installable, runnable CLI
- ✅ **Phase 1**: Core agent experience (REPL, sessions, slash commands)
- ✅ **Phase 2**: Real tool-calling loop, multi-provider
- 🟡 **Phase 3**: Context, permissions, recovery (partly done: see the table above)
- ⏳ **Phase 4**: MCP client, plugins, hooks (only custom tools from `~/.clyde/tools/` so far)
- ⏳ **Phase 5**: Python-native differentiators (not started)

**See [FEATURE_LIST.md](FEATURE_LIST.md) for detailed feature status and PR guidelines.**

***

## 🚀 Quick Start

*Three steps. I'll wait. Might light one while you do it.*

### Install

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
| `/multiline` | Toggle multiline mode |
| `/model [provider:model]` | Show or switch the model |
| `/models`    | List models from every connected provider |
| `/think [level]` | Reasoning: off, low, medium, high, on, default |
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
- Tool limits: `allowed-tools` controls which tools the skill can use.
- Arguments: use `$ARGUMENTS`, `$0`, `$1`, or named args like `$path` (from `arguments`).
- Placeholder syntax: use `$path`, not `${path}`.

***

## 📦 Project Structure

```text
ClydeCLI/
├── src/
│   ├── cli.py           # CLI entry
│   ├── providers/       # LLM providers
│   ├── repl/            # Interactive REPL
│   ├── skills/          # SKILL.md loading and creation
│   └── tool_system/     # Tool registry, loop, validation
├── tests/               # Core test suite
├── .clyde/
│   └── skills/          # Project-local custom skills
└── FEATURE_LIST.md      # Current feature status
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
