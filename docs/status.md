# Status

[Back to the README](../README.md)

*What works, what doesn't. Straight answer.*

## Core Systems

| System | Status | Description |
|--------|--------|-------------|
| CLI Entry | ✅ | `clyde`, `login`, `logout`, `config`, `--model`, `--list-models`, `-c`, `--resume`, `-p` (headless: answer on stdout, JSON output, exit status) |
| Interactive REPL | ✅ | Rich output, history, tab completion, multiline, streaming |
| Multi-Provider | ✅ | 13 providers (incl. local Ollama and LM Studio), stdlib HTTP, live model lists, `provider:model` switching |
| Agent Loop | ✅ | Tool-calling loop with retries, reasoning control, history repair |
| Skill System | ✅ | SKILL.md slash-command skills with args + tool limits |
| Context Building | ✅ | Workspace snapshot, git status, a README excerpt, entry points, the code map and memory files go into the prompt: `~/.clyde/CLYDE.md` (user), `CLYDE.md` (project, shared) and `CLYDE.local.md` (project, personal, keep it gitignored). Files written for other agents are read too: `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.github/copilot-instructions.md` (one per folder, first found wins) |
| Permissions | ✅ | Bash asks for any command that is not read-only (dangerous patterns are refused), Write/Edit/NotebookEdit ask before every change in hold mode, Config asks before a change, WebFetch asks per domain and WebSearch asks before each search (showing the query). Answer "don't ask again" or add `permissions.allow` / `deny` rules (Claude Code syntax) to `~/.clyde/settings.json` |
| Shell asks | ✅ | Commands that are not read-only ask; so does any command that names a folder outside the project, even in all-in mode. No OS sandbox |
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
| whichllm | ✅ | Bundled benchmark ranking of local models in `/models local`: the best models that fit this machine, with quality, speed range and license in the download confirmation |
| SkillSpector | ✅ | Bundled scanner for skills, plugins and MCP servers from other agents: static always, LLM review when a usable model is connected; `DO_NOT_INSTALL` items held back until `/skills allow` |
| Laya | ✅ | Optional local decision model (`clyde-cli[laya]`): hands a stuck cardShuffle turn to the next card; scores every turn's difficulty and steers `house` once `/laya`'s evidence shows it separates easy turns from hard ones |
| IDE integration | ✅ | `clyde --acp` speaks the Agent Client Protocol, so editors that support it (Zed, JetBrains through an ACP adapter) run Clyde as their agent: streamed replies, tool calls and permission asks in the editor |
| Pasting | ✅ | Ctrl+V pastes a copied image, a copied image path becomes the image, long pastes fold to `[Pasted text #N +X lines]` |

## Tools

| Category | Tools | Status |
|----------|-------|--------|
| Files | Read, Write, Edit, NotebookEdit, Glob, Grep | ✅ Working; Edit also lands a unique match that is off only by trailing whitespace or indentation, and says so in its result, in the one-line summary and in the trace |
| Data | Data | ✅ Profile CSV, TSV, Parquet, JSON and SQLite files (types, nulls, distinct counts, min/max, samples) and run read-only SQL across them with DuckDB, sandboxed to the workspace |
| System | Bash | ✅ Working; asks before commands that are not read-only or that name a folder outside the project |
| Web | WebFetch, WebSearch | ✅ Working |
| Interaction | AskUserQuestion, SendUserMessage | ✅ Working |
| Tasks | TodoWrite, TaskCreate/Get/List/Update/Output/Stop | ✅ Working |
| Planning & config | EnterPlanMode, ExitPlanMode, Config, Skill, ToolSearch, Sleep | ✅ Working |
| Agent | Agent | ✅ Sub-agents on a fresh conversation: general-purpose or custom types (`.clyde/agents/*.md`, Claude Code's format), in the foreground or background (`TaskOutput` collects, `TaskStop` cancels) |
| Scheduling | CronCreate/List/Delete | ✅ Session-scoped; due jobs run as a turn while the REPL is idle at the prompt |
| Team | TeamCreate/Delete | ✅ Runs several sub-agents in parallel, each on its own prompt and type; `TaskOutput` collects their answers |
| Worktree | EnterWorktree/ExitWorktree | ✅ Creates a git worktree on a new branch; exit keeps or removes it |
| MCP | MCP, ListMcpResources, ReadMcpResource, `mcp__<server>__<tool>` | ✅ Stdio, Streamable HTTP and HTTP+SSE servers from `~/.clyde/settings.json`; header auth or OAuth sign-in (`/mcp login`) |
| Code map | Map | ✅ query / path / explain / affected / god_nodes over a map of the repo, refreshed when ClydeCLI starts |
| LSP | LSP | ✅ Definition, references, hover, symbols and call hierarchy via a language server on PATH |

## Roadmap

- ✅ **Phase 0**: Installable, runnable CLI
- ✅ **Phase 1**: Core agent experience (REPL, sessions, slash commands)
- ✅ **Phase 2**: Real tool-calling loop, multi-provider
- ✅ **Phase 3**: Context, permissions, recovery (context building, saved permission rules, `/resume`, `/doctor`, compaction, hooks)
- ✅ **Phase 4**: MCP client (stdio, Streamable HTTP, HTTP+SSE), plugins, custom tools/skills/hooks, tracing and `/debug`
- ✅ **Phase 5**: Python-native differentiators: the Code Map, check-after-edit with ruff/mypy/pytest/uv, notebook tools, and the Data tool for data and ETL work
- ✅ **Phase 6**: Model play: cardShuffle routing across `/eval`-ranked models, local models that fit the machine (ollama.com, Hugging Face GGUF and MLX), Laya bundled for stuck-loop detection, and SkillSpector bundled to scan skills, plugins and MCP servers
- ✅ **Laya's difficulty in `cardShuffle:house`**: promotes itself from shadow mode once `/laya`'s evidence shows it separates easy turns from hard ones
- ✅ **IDE integration** through the Agent Client Protocol (`clyde --acp`)

**See [FEATURE_LIST.md](../FEATURE_LIST.md) for detailed feature status and PR guidelines.**
