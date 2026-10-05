# ClydeCLI Feature List & PR Roadmap

> Capability list, roadmap, and PR guide for community contributors.
>
> Project positioning: **a Python rewrite based on the real Claude Code source structure**. It already provides a usable multi-provider chat CLI, a complete tool system framework, and an Agent Loop, and is filling in the key capabilities of native Claude Code in phases.

---

## Status Legend

| Status | Meaning |
|------|------|
| ✅ Implemented | A verifiable implementation exists in the current repository |
| 🟡 Partial | A skeleton, mirror layer, or partial capability exists, but the loop is not yet complete |
| ⏳ Planned | Direction is defined; PRs welcome |
| 🚫 Not started | No implementation yet |

---

## Project Highlights

- **Python rewrite**: Not just a UI imitation, but a rebuild following Claude Code's architectural approach.
- **Multi-model first**: 12 providers (Anthropic, OpenAI, Gemini, OpenRouter, DeepSeek, Mistral, NVIDIA, Cerebras, GLM, MiniMax, Ollama local and cloud) over stdlib HTTP, no vendor SDKs.
- **Usable CLI / REPL**: Basic interaction already works and is ready for continued iteration.
- **Complete tool system framework**: 30+ tool modules, an Agent Loop, and a permission system framework are implemented.
- **Built for community collaboration**: The Python ecosystem is easier to extend, well suited to tooling, automation, and data engineering scenarios.
- **Emphasis on authenticity**: Prioritizes completing core paths that actually run, rather than just growing the list of command/tool names.

---

## Core Systems

| Capability | Status | Current State |
|------|------|----------|
| CLI entry point | ✅ | `clyde`, `login`, `logout`, `config`, `setup`, `--model`, `-c`, `--resume`, `--version`; `clyde -p` runs one headless turn (answer on stdout, `--output-format json`, `--mode`, exit status) for scripts and CI |
| Interactive REPL | ✅ | Supports interactive output, history, Tab completion, multi-line input |
| Slash Commands | ✅ | `/help`, `/clear`, `/save`, `/load`, `/resume`, `/model`, `/models [local]`, `/eval`, `/rewind`, `/mcp [login\|logout]`, `/skills scan\|allow`, `/laya`, `/doctor`, `/cost`, `/compact`, `/debug`, `/exit` and more |
| Multi-provider abstraction | ✅ | Canonical types in, canonical response out; each adapter owns its wire format |
| Provider configuration management | ✅ | `provider:model` selection, `/model` switching, keys via env or `~/.clyde/keys.json` |
| Session persistence | ✅ | Supports saving/loading local sessions |
| Session message management | ✅ | Supports session history maintenance and serialization |
| Error recovery / re-login | ✅ | A rejected key (401, or a 400/403 that says the key is bad) offers a new key for the same provider, a switch of provider or model, or not now; the failed message is retried once, and a stale key exported in the shell is pointed out |
| Token / Cost tracking | ✅ | `/cost` shows input/output/cache tokens per model and an estimated USD total from list prices in `catalog.json` ("price unknown" for unpriced models, $0 for local Ollama); `/context` reports token usage |
| Context building | ✅ | `context_system` injects workspace / git / README excerpt + entry points / the code map / memory files: `CLYDE.md` (user `~/.clyde/CLYDE.md`, project, personal `CLYDE.local.md`), falling back to `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules` or `.github/copilot-instructions.md` |
| Claude Code Agent Loop | ✅ | agent_loop.py implemented, supports the tool-call loop |
| `/resume` session recovery experience | ✅ | Sessions auto-save after each turn; `/resume` picks from this workspace's recent sessions (or takes an id) and shows a recap; `clyde -c` / `clyde --resume [id]` on the CLI |
| `/compact` conversation compaction | ✅ | Manual `/compact`, plus automatic compaction before a turn once history reaches 80% of the context window |
| `/doctor` diagnostics | ✅ | Checks Python vs requires-python, dependencies, config and key store (mode 600, no secrets shown), providers with keys, current model, git, workspace and permission settings |
| Hook system | ✅ | PreToolUse / PostToolUse shell hooks from `~/.clyde/settings.json` or `.toml` (Claude Code, shorthand, Gemini CLI, Cursor or Copilot CLI format); no project-level hooks until there is a workspace trust prompt |
| Permission system | ✅ | Bash asks unless read-only (dangerous patterns refused), Write/Edit ask for docs, Config asks before setting, WebFetch asks per domain; saved `permissions.allow` / `deny` rules in Claude Code syntax and a "don't ask again" answer |
| Plugin system | ✅ | `clyde plugin install/import/list/enable/disable/remove` (import brings over Claude Code, Codex and Cursor plugins); plugins bundle tools, skills, hooks and MCP servers (Claude Code layout) and are enabled only after a yes |
| Self-checks | ✅ | ruff / mypy on edited Python files with only new problems fed back to the model; `/check` runs ruff, mypy and pytest (uv-aware) |
| Tracing / `/debug` | ✅ | Per-session JSONL traces with redaction, `/debug` for the last turn, `clyde --debug` live |
| Headless mode | ✅ | `clyde -p "<prompt>"`: piped stdin added, permission asks denied and listed, JSON output, exit 0/1/2, never hangs on an open stdin pipe |
| Edit checkpoints | ✅ | Every message opens a checkpoint; `/rewind` puts files (and/or the conversation) back to before it; survives `/resume`; shell-command changes aren't captured |
| Shell sandbox | ✅ | macOS `sandbox-exec` / Linux `bwrap`: the model's commands write only to the project, temp and package caches; `unsandboxed: true` always asks |
| cardShuffle | ✅ | A model that deals each turn to an `/eval`-ranked real model (high-roller, house, free, small); re-deals on errors, max tool turns and Laya-detected loops |
| Model evaluation | ✅ | `/eval`: a tool-call check, then an 11-task graded hand calibrated on live models; provider errors mid-hand don't count against a model |
| Local models | ✅ | `/models local [ollama\|hf\|mlx]`: models that fit this machine, rated relax / balance / hard, confirmed with their cost before downloading through Ollama or LM Studio |
| Laya (bundled) | ✅ | Local decision model: stops stuck cardShuffle turns; scores every turn's difficulty and steers `house` once the evidence promotes it; `/laya` shows the evidence and the verdict |
| SkillSpector (bundled) | ✅ | Scans skills, plugins, agents and MCP tool lists from other tools; `DO_NOT_INSTALL` items held back until `/skills allow` |
| Pasting | ✅ | Ctrl+V images, image paths, long text folded to `[Pasted text #N +X lines]`; text-only models warned; images over 5 MB shrunk |

---

## Tool System

> **Major progress**: The repository now implements a complete tool system framework, including 30+ tool modules, an Agent Loop, schema validation, a permission framework, and more.

### Tool Framework

| Capability | Status | Current State |
|------|------|----------|
| Tool Registry | ✅ | Tool registration and discovery implemented |
| Tool Protocol | ✅ | Tool protocol and base class defined |
| Schema Validation | ✅ | Parameter validation system implemented |
| Agent Loop | ✅ | Complete tool-call loop implemented |
| Tool Context | ✅ | Tool context management implemented |
| Permission Framework | ✅ | Integrated into dispatch with saved allow/deny rules |
| Error Handling | ✅ | Tool error types and handling defined |
| Task Manager | ✅ | Task manager implemented |

### Implemented Tool Modules

| Tool Category | Tool Name | File | Status |
|---------|---------|------|------|
| File operations | FileReadTool | `read.py` | ✅ Implemented |
| File operations | FileWriteTool | `write.py` | ✅ Implemented |
| File operations | FileEditTool | `edit.py` | ✅ Exact match, then whitespace- and indent-tolerant unique match; misses point at the closest lines |
| File operations | GlobTool | `glob.py` | ✅ Implemented |
| File operations | GrepTool | `grep.py` | ✅ Implemented |
| Data | DataTool | `data.py` | ✅ Profile and read-only SQL over CSV, TSV, Parquet, JSON and SQLite (sandboxed DuckDB) |
| System operations | BashTool | `bash.py` | ✅ Runs in the OS sandbox (`sandbox.py`); `unsandboxed: true` always asks |
| Web tools | WebFetchTool | `web_fetch.py` | ✅ Implemented |
| Web tools | WebSearchTool | `web_search.py` | ✅ Implemented |
| Interaction tools | AskUserQuestionTool | `ask_user_question.py` | ✅ Implemented |
| Interaction tools | SendUserMessageTool | `send_user_message.py` | ✅ Implemented |
| Task management | TodoWriteTool | `todo_write.py` | ✅ Implemented |
| Task management | TaskStopTool | `task_stop.py` | ✅ Implemented |
| Task management | TasksV2Tool | `tasks_v2.py` | ✅ Implemented |
| Task management | TaskManager | `task_manager.py` | ✅ Implemented |
| Agent tools | AgentTool | `agent.py` | ✅ General-purpose or custom types (`.clyde/agents/*.md`, Claude Code format), foreground or background (`TaskOutput` / `TaskStop`); no nesting |
| Agent tools | BriefTool | `brief.py` | ✅ Implemented |
| Agent tools | TeamTool | `team.py` | ✅ Runs up to 8 sub-agents in parallel; `TeamDelete` stops the rest |
| Config tools | ConfigTool | `config.py` | ✅ Implemented |
| Plan mode | PlanModeTool | `plan_mode.py` | ✅ Implemented |
| Scheduled tasks | CronTool | `cron.py` | ✅ Session-scoped; due jobs run as a turn while the REPL is idle |
| MCP tools | MCPTool | `mcp.py`, `mcp_client.py`, `mcp_oauth.py` | ✅ Stdio, Streamable HTTP and HTTP+SSE servers from settings and approved project `.mcp.json`; OAuth sign-in with `/mcp login`; each tool registered as `mcp__<server>__<tool>` |
| MCP tools | MCPResourcesTool | `mcp_resources.py` | ✅ Lists and reads resources from connected servers |
| Skill system | SkillTool | `skill.py` | ✅ Implemented |
| Tool search | ToolSearchTool | `tool_search.py` | ✅ Implemented |
| Code map | MapTool | `code_map.py` | ✅ Map of the repo built from its syntax tree (no LLM, via graphify): query, path, explain, affected, god nodes; refreshed at startup and advertised in the context prompt |
| LSP integration | LSPTool | `lsp.py` | ✅ Starts the language server on PATH for the file type (pyright/pylsp, typescript-language-server, gopls, rust-analyzer, dart, clangd) |
| Worktree | WorktreeTool | `worktree.py` | ✅ Real git worktree on a `worktree-<name>` branch; exit can keep or remove it |
| Miscellaneous | SleepTool | `sleep.py` | ✅ Implemented |
| Miscellaneous | StructuredOutputTool | `structured_output.py` | ✅ Implemented |
| Miscellaneous | MiscTools | `misc.py` | ✅ SendMessage, PowerShell, NotebookEdit (the RemoteTrigger and REPL stubs were removed) |

---

## Services & Runtime

| Module | Status | Current State |
|------|------|----------|
| Provider Runtime | ✅ | Streaming, retries with backoff, cancellation, readable errors, reasoning controls |
| REPL Runtime | ✅ | Supports basic interaction, command dispatch, and message logging |
| Agent Loop Runtime | ✅ | Complete tool-call loop and result handling implemented |
| Tool Execution Engine | ✅ | Full loop of tool loading, execution, and result feedback implemented |
| Output Styles | ✅ | Output style loading system implemented |
| Session Persistence | ✅ | Session save/load available |
| Context Engine | ✅ | Context-building pipeline: workspace, git, README excerpt / entry points, code map, and `CLYDE.md` memory (reads `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, Cursor and Copilot files too) |
| Permission Engine | ✅ | Bash, Write/Edit, Config set and WebFetch ask; allow/deny rules from `~/.clyde/settings.json`; shell commands also run in the OS sandbox; no project-level rules yet |
| Compaction Engine | ✅ | Manual `/compact` and automatic at 80% of the context window |
| Hook Runtime | ✅ | Matching hooks run around every tool dispatch; exit 2 blocks (pre) or feeds stderr back (post) |
| MCP Runtime | ✅ | Stdlib JSON-RPC over stdio, Streamable HTTP and HTTP+SSE (with fallback); OAuth (discovery, client registration, PKCE, refresh); project `.mcp.json` behind a per-entry yes; tool lists scanned by SkillSpector |

---

## Test Coverage

| Test Type | Status | File |
|---------|------|------|
| Full suite | ✅ | 684 tests (`pytest`), all passing; live shakedown of every feature on 2026-10-02 |
| Tool system tests | ✅ | `test_tool_system_tools.py` (427 lines) |
| Agent Loop tests | ✅ | `test_agent_loop.py` (134 lines) |
| Claude Code tool parity tests | ✅ | `test_claude_code_tool_parity.py` (137 lines) |
| Provider tests | ✅ | `test_provider_layer.py` plus per-adapter streaming/reasoning/error suites |
| Output style tests | ✅ | `test_output_styles.py` (64 lines) |
| Config tests | ✅ | `test_config.py` |


## Roadmap

## Phase 0: Launchable, installable, usable ✅

Goal: make the project smooth for new users and contributors first.

- [x] Decouple the CLI startup path; `--help`, `--version`, and `config` should not depend on provider SDKs
- [x] Lazy-import providers so local features remain browsable when an SDK is missing
- [x] Pin and verify a Python 3.14+ development environment
- [x] Improve installation instructions and a minimal runnable example
- [x] Clean up statements in the README that do not match the current implementation

## Phase 1: Claude Code core experience MVP ✅

Goal: reproduce the most important first layer of the native Claude Code experience.

- [x] Unify the chat REPL, slash commands, and session store
- [x] Complete the tool system framework
- [x] Implement the Agent Loop
- [x] Unify error handling, retry, and re-login flows
- [x] Complete transcript persistence and recovery infrastructure
- [x] Establish a stable set of user commands

## Phase 2: Real tool-call loop ✅

Goal: move from a "mirrored tool list" to a "truly executable Python agent".

- [x] FileReadTool
- [x] FileWriteTool
- [x] FileEditTool
- [x] BashTool
- [x] AskUserQuestionTool
- [x] TodoWriteTool
- [x] WebFetchTool / WebSearchTool
- [x] Tool schemas, parameter validation, exception handling, call logging
- [x] Tool execution result feedback loop

## Phase 3: Context, permissions, recovery (done)

Goal: fill in Claude Code's engineering capabilities.

- [x] Complete workspace context building
- [x] Basic git status / file tree / `CLYDE.md` memory injection
- [x] README / entry file summary injection
- [x] Memory and history context management
- [x] Full permission system integration
- [x] `/resume`
- [x] `/compact`
- [x] `/doctor`
- [x] pre/post tool use hooks

## Phase 4: MCP, plugins, extension ecosystem (done)

Goal: upgrade the project from a monolithic CLI to an extensible platform.

- [x] MCP client/runtime (stdio)
- [x] Python plugin system
- [x] Custom commands / tools / hooks
- [x] Local model (Ollama) and third-party provider support
- [x] Better observability and debugging tools

## Phase 5: Distinctive strengths of the Python version

Goal: build features unique to the Python rewrite.

- [x] Notebook-friendly toolchain
- [x] Enhancements for data engineering / ETL scenarios (the Data tool: profile and read-only SQL over CSV, Parquet, JSON and SQLite via DuckDB)
- [x] Support for Chinese model providers (GLM, DeepSeek, MiniMax)
- [x] pytest / ruff / mypy / uv integration experience
- [x] Extension interfaces for in-house enterprise automation and workflows (plugins, hooks, MCP)
- [x] Code Map: a structural map of the repo any model can query

---

## PRs We're Looking For

### P0: Most welcome, easiest to merge

- Improved test coverage
- Documentation improvements
- Error handling improvements
- Performance optimizations

### P1: High-value foundational capabilities

- Deeper project indexing for context building
- Project-level permission rules, hooks and plugins behind the workspace trust prompt
- Workspace trust prompt, so project-level hooks can be enabled

### P2: Filling in key Claude Code experiences

- Linux sandbox testing on a machine with `bwrap`
- Performance monitoring and tuning

### P3: Python version highlights

- Enhanced notebook editing and reading
- More data formats for the Data tool (Excel, Avro) and write-back with confirmation
- pytest / ruff / mypy / uv integration
- More domestic and international model providers
- Pluggable tool system

---

## Suggested Modules to Claim for PRs

| Area | Suitable Contributions |
|------|--------------|
| CLI / UX | Command design, help text, interaction experience, error messages |
| Tools | Tool enhancements, new tool development, tool tests |
| Context | repo map, git status, project documentation injection, memory |
| Permissions | Permission integration, security policies, command restrictions |
| Providers | New providers, model selection, streaming compatibility |
| MCP / Plugins | MCP runtime completion, plugin loading, custom tool extensions |
| Quality | Tests, benchmarks, documentation, installation flow, CI |
| Performance | Performance optimization, memory management, concurrency |

---

## PR Submission Tips

- Prioritize real capabilities over piling up command names
- Keep each PR focused on a single module where possible
- Include a minimal test or runnable example with new features
- Update capability status when modifying the README
- Be careful with "completed" claims; prefer stating verifiable results

---

## Recommended Public Description

You can introduce the project like this:

> ClydeCLI is a Python rewrite based on the real Claude Code source structure. It already provides a multi-provider chat CLI, a complete tool system framework (30+ tools), and an Agent Loop with a working tool-call loop, and is now improving context building, the permission system, session recovery, compaction, MCP, and the plugin system. PRs are welcome around tool enhancements, runtime, permissions, context, and Python-native extension capabilities.

---

## One-Line Summary

**We already have a Python Agent Runtime with a complete tool system framework and Agent Loop; next we will improve context building, permission integration, and recovery capabilities to turn it into a Python agent platform with the full Claude Code experience.**
