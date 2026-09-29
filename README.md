<div align="center">

# 🔧 ClydeCLI

**An AI coding agent for your terminal, written in Python.**

*"Yeah, I can fix that."*
<br>— Clyde

***

[![GitHub stars](https://img.shields.io/github/stars/dea6cat/ClydeCLI?style=for-the-badge&logo=github&color=yellow)](https://github.com/dea6cat/ClydeCLI/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)

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

```python
providers = ["Anthropic Claude", "OpenAI GPT", "Zhipu GLM"]  # + easy to extend
```

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
clyde              # Start REPL
clyde login        # Configure API
clyde --version    # Check version
clyde config       # View settings
```

***

## 📊 Status

*What works, what doesn't. Straight answer.*

| Component     | Status     | Count     |
| ------------- | ---------- | --------- |
| REPL Commands | ✅ Complete | 6+ built-ins |
| Tool System   | ✅ Complete | 30+ tools |
| Automated Tests | ✅ Present | Core suites for skills, providers, REPL, tools, context |
| Documentation | ✅ Complete | 10+ docs  |

### Core Systems

| System | Status | Description |
|--------|--------|-------------|
| CLI Entry | ✅ | `clyde`, `login`, `config`, `--version` |
| Interactive REPL | ✅ | Rich interactive output, history, tab completion, multiline |
| Multi-Provider | ✅ | Anthropic, OpenAI, GLM support |
| Session Persistence | ✅ | Save/load sessions locally |
| Agent Loop | ✅ | Tool calling loop implementation |
| Skill System | ✅ | SKILL.md-based slash-command skills with args + tool limits |
| Context Building | 🟡 | Initial prompt injection for workspace, git, and CLAUDE.md; deeper project understanding still needed |
| Permission System | 🟡 | Framework exists, needs integration |

### Tools (30+)

| Category | Tools | Status |
|----------|-------|--------|
| File Operations | Read, Write, Edit, Glob, Grep | ✅ Complete |
| System | Bash execution | ✅ Complete |
| Web | WebFetch, WebSearch | ✅ Complete |
| Interaction | AskUserQuestion, SendMessage | ✅ Complete |
| Task Management | TodoWrite, TaskManager, TaskStop | ✅ Complete |
| Agent Tools | Agent, Brief, Team | ✅ Complete |
| Configuration | Config, PlanMode, Cron | ✅ Complete |
| MCP | MCP tools and resources | ✅ Complete |
| Others | LSP, Worktree, Skill, ToolSearch | ✅ Complete |

### Roadmap

- ✅ **Phase 0**: Installable, runnable CLI
- ✅ **Phase 1**: Core agent MVP experience
- ✅ **Phase 2**: Real tool calling loop
- 🟡 **Phase 3**: Context, permissions, recovery (in progress)
- ⏳ **Phase 4**: MCP, plugins, extensibility
- ⏳ **Phase 5**: Python-native differentiators

**See [FEATURE_LIST.md](FEATURE_LIST.md) for detailed feature status and PR guidelines.**

***

## 🚀 Quick Start

*Three steps. I'll wait. Might light one while you do it.*

### Install

```bash
git clone https://github.com/dea6cat/ClydeCLI.git
cd ClydeCLI

# Create venv (uv recommended)
uv venv --python 3.11
source .venv/bin/activate

# Install
uv pip install -r requirements.txt
```

### Configure

#### Option 1: Interactive (Recommended)

```bash
python -m src.cli login
```

This flow will:

1. ask you to choose a provider: anthropic / openai / glm
2. ask for that provider's API key
3. optionally save a custom base URL
4. optionally save a default model
5. set the selected provider as default

The configuration is saved to `~/.clyde/config.json`. Example structure:

```json
{
  "default_provider": "glm",
  "providers": {
    "anthropic": {
      "api_key": "base64-encoded-key",
      "base_url": "https://api.anthropic.com",
      "default_model": "claude-sonnet-4-20250514"
    },
    "openai": {
      "api_key": "base64-encoded-key",
      "base_url": "https://api.openai.com/v1",
      "default_model": "gpt-4"
    },
    "glm": {
      "api_key": "base64-encoded-key",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "default_model": "glm-4.5"
    }
  }
}
```

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
- API keys are stored in the config encoded, not encrypted
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
