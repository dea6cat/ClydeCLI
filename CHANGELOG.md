# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Laya's difficulty score promotes itself into `cardShuffle:house`: it's scored on every cardShuffle
  turn, and once shadow turns show the harder half (split at the median score) takes at least 1.5x
  and one more tool round than the easier half, with 10+ turns each, house starts harder requests on
  stronger cards. `/laya` shows the split and the verdict
- `/login [provider]` in the REPL: connect a provider or replace its key without leaving, then
  switch to its model
- Custom providers: `clyde login` / `/login` -> `custom` adds any OpenAI-compatible API by name,
  base URL and key (saved under `"providers"` in settings.json); it then works like a built-in one
- `clyde -p "<prompt>"`: one headless turn for scripts and CI; the answer on stdout, piped stdin
  added, permission asks denied and listed, `--output-format json`, `--mode`, `--max-turns`, exit
  status 0/1/2
- Edit checkpoints and `/rewind`: undo the model's file edits and/or the conversation back to before
  any message; saved per session, so they survive `/resume`
- Shell sandbox: the model's commands run under macOS `sandbox-exec` or Linux `bwrap` and write only
  to the project, temp and package caches; `unsandboxed: true` always asks
- Sub-agents: custom agent types from `.clyde/agents/` or `.claude/agents/` (Claude Code format),
  background runs collected with `TaskOutput` (now able to wait) and cancelled with `TaskStop`, and
  `TeamCreate` running several members in parallel
- Data tool: profile and read-only SQL over CSV, TSV, Parquet, JSON and SQLite, sandboxed DuckDB
- MCP over Streamable HTTP and HTTP+SSE (bare `url` tries HTTP, then SSE), OAuth sign-in
  (`/mcp login`, `clyde mcp login`) and a project's `.mcp.json` behind a yes per exact entry
- cardShuffle: a model that deals each turn to an `/eval`-ranked real model, with high-roller,
  house, free and small tiers, and fallback on errors, max tool turns and stuck loops
- `/eval` plays an 11-task graded hand after the tool-call check; strength ranks cardShuffle's deck
- `/models local [ollama|hf|mlx]`: find local models that fit this machine, rated relax / balance
  / hard, confirm their cost, and download through Ollama or LM Studio
- Laya, bundled: local judgments that stop a looping cardShuffle turn; `/laya` lines them up with
  how turns ended
- SkillSpector, bundled: scans skills, plugins, agents and MCP tool lists from other tools;
  `/skills scan` and `/skills allow`
- Pasting: Ctrl+V images, image paths become `[Image #N]`, long pastes fold to
  `[Pasted text #N +X lines]`; images reach every provider and survive `/resume`
- Re-login: a rejected key offers re-entering it for the same provider, then retries the message
- Stdlib-only provider layer (no vendor SDKs): Anthropic, OpenAI, Google Gemini, OpenRouter,
  DeepSeek, Mistral, NVIDIA, Cerebras, GLM, MiniMax, Ollama (local, native `/api/chat`) and
  Ollama Cloud
- `provider:model` selection: `clyde --model`, `/model`, `/models`, `clyde --list-models`
- Live model lists from each provider's API, cached for 60s
- `/think off|low|medium|high|on|default` reasoning control, with streamed reasoning shown dimmed
- Retries with backoff on 429/5xx/connection errors, and one-line readable provider errors
- `clyde logout <provider>`; Ollama login suggests tool-capable models that fit your RAM
- Initial context injection pipeline for workspace snapshot, git status, and `CLAUDE.md`
- Tests covering the new context system integration
- `EnterWorktree` creates a real git worktree on a `worktree-<name>` branch under `.clyde/worktrees`;
  `ExitWorktree` takes `action: remove` to delete it (git refuses if it has uncommitted changes)
- Automatic compaction: before each turn, history at 80% or more of the model's context window is
  summarized the same way as `/compact`; `/context` shows the threshold
- `Edit` accepts an `old_string` that differs from the file only in trailing whitespace or
  indentation (re-indenting `new_string`) when the match is unique; a miss shows the closest lines
  to re-copy (ported from 2B)
- `/doctor`: checks Python, dependencies, config, the key store (mode 600, no secrets shown),
  providers with keys, the current model, git, and workspace/permission settings
- `/resume` picks a recent session of the current workspace; `clyde -c` continues the latest one
  and `clyde --resume [id]` opens the picker or loads a session by id
- `/cost` reports input, output and cache tokens per model with an estimated $ total; prices live
  in the model catalog, local Ollama is $0 and unpriced models say "price unknown"
- NotebookEdit replaces, inserts or deletes cells in `.ipynb` files (by cell id or `cell-N`)
- The Agent tool runs a real sub-agent on a fresh conversation with every tool except Agent, and
  returns only its final answer
- Cron jobs run: due jobs fire as a turn while the REPL is idle (5-field cron expressions,
  session-scoped, one-shot jobs removed after running)
- The LSP tool talks to a language server on PATH (pyright/pylsp, typescript-language-server,
  gopls, rust-analyzer, dart, clangd): definition, references, hover, symbols, call hierarchy
- The context prompt includes a README excerpt and the project's entry points, and loads
  `CLAUDE.local.md` for personal project memory
- PreToolUse / PostToolUse hooks: shell commands from `~/.clyde/settings.json` run around tool
  calls; exit 2 blocks the call or feeds stderr back to the model. Hooks can also live in
  `settings.toml`, use a shorthand, or be written in Gemini CLI, Cursor or Copilot CLI format,
  including their JSON deny/block replies
- `install.sh` (`curl … | sh`) installs uv and `clyde`, then runs the new `clyde setup` onboarding:
  connect a provider, import other agents' hooks after a yes, and put `clyde` on PATH
- `clyde hooks import` copies hooks from Claude Code, Gemini CLI, Cursor and Copilot CLI settings
- Skills in `~/.agents`, `~/.codex`, `~/.copilot` and `~/.gemini` skill folders are loaded in place
- MCP client (stdlib, stdio): servers from `mcpServers` in `~/.clyde/settings.json` start with the
  REPL, their tools are registered as `mcp__<server>__<tool>`, resources work through
  ListMcpResources / ReadMcpResource, and `/mcp` shows status
- Code map and the Map tool: a map of the repo's symbols, calls and imports (built from the syntax
  tree with no LLM, via graphify) that any model can query for related symbols, paths between
  symbols, explanations and change impact. The map refreshes in the background into
  `.clyde/code-map/map.json` when `clyde` starts in a git repo, the context prompt points the model at it, and `clyde setup` offers to install the builder
- Saved permission rules: `permissions.allow` / `deny` in `~/.clyde/settings.json` with Claude Code's
  syntax (`Bash(git commit:*)`, `Edit(docs/**)`, `WebFetch(domain:…)`), and a "don't ask again" answer
  at the prompt that saves one. WebFetch now asks per domain
- Plugins: `clyde plugin install <dir|git-url>` (plus list / enable / disable / remove) for bundles of
  tools, skills, hooks and MCP servers in Claude Code's layout, enabled only after a yes; `/plugins`
- `clyde plugin import` (and `clyde setup`) brings over plugins installed for Claude Code, Codex and
  Cursor, one yes per plugin; manifests in `.codex-plugin/`, `.cursor-plugin/` or the plugin root are read
- Self-checks: after a Python edit, ruff (and mypy when configured) run on the file and only new
  problems go back to the model; `/check` runs ruff, mypy and pytest, via `uv run` when there is a
  `uv.lock`
- Tracing: per-session JSONL traces in `~/.clyde/traces/` with secrets redacted, `/debug` for the
  last turn and `clyde --debug` for live output
- `clyde mcp import` (and `clyde setup`) brings over stdio MCP servers from Claude Code, Cursor,
  Gemini CLI, Codex and Copilot CLI after a yes

- `/eval [filter]` tests every listed model (or the ones matching the filter) with a real tool call
  and a round trip, and ranks them with latency and tokens per second. Results are saved to
  `~/.clyde/model_evals.json`; `/models` then hides models with no tool calling or no access (credit and
  rate-limit failures stay listed), `/models all` shows everything and `/models refresh` re-fetches the lists

- LM Studio as a local provider: when LM Studio is installed, its downloaded models show up in
  `/models` (from its server, or `lms ls` when the server is off), and the server is started with
  `lms server start` the first time an LM Studio model is used

- Esc cancels the running reply, tool call or command the same way Ctrl+C does; arrow keys and
  other escape sequences don't, and prompts that need the keyboard pause it

- Every message you send is shown with the machine time (5:47 PM), each reply ends with how long it
  took and when it finished ("♠ Shuffled for 2m 45s · 5:47 PM"), and each tool result shows its duration

- Modes on Shift+Tab, shown under the prompt: `♠ hold` (asks before risky actions), `♠ reading the
  table` (plan mode, now enforced: changes are refused until the plan is presented) and `♠♠ all in`
  (no questions except major moves such as recursive deletes, pushes or hard resets)

### Changed
- Images: models known not to read images get a warning on paste and the text only on send; images
  over 5 MB are shrunk (macOS `sips`) instead of refused
- `check_permissions` is an optional tool hook, no longer part of the `Tool` protocol
- Memory files are now `CLYDE.md` and `CLYDE.local.md` (`/init` writes these). Files made for other agents
  still load: `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules` and
  `.github/copilot-instructions.md`, one per folder with `CLYDE.md` first
- API keys moved from base64 entries in `config.json` to `~/.clyde/keys.json` (mode 600), with
  shell env vars taking precedence; old configs migrate automatically on first run
- The agent loop uses one code path for every provider; conversation history (including
  reasoning and tool-call signatures) is re-expressed per provider on each request
- Compaction no longer calls a nonexistent `chat_async`, and its summary context never starts on
  an orphaned tool result
- Requires Python 3.14
- Skill frontmatter parsing now supports inline list syntax such as `arguments: [path]`
- README and contributor docs now prefer `uv`-based setup instructions
- Documentation now distinguishes provider-level streaming interfaces from the current turn-based CLI output
- Bash asks for approval before commands that are not clearly read-only; dangerous patterns are
  refused outright. Config asks before changing a setting
- Sessions are saved after every turn (honouring `session.auto_save`); before, only `/save` saved
- OpenAI and Gemini usage no longer counts cached tokens twice
- The LSP tool takes Claude Code's `operation`/`filePath`/`line`/`character` input instead of a
  raw method and params
- Source modules are grouped by purpose (`src/agent/`, `src/startup/`, `src/output_styles/`,
  token estimation under `src/context_system/`), and `tests/` mirrors `src/`; run unittest with
  `python -m unittest discover -s tests -t .`

### Removed
- The RemoteTrigger and REPL tools: stubs that only ever returned "not implemented"

### Fixed
- Laya never answered the first turns of a session, and never in `clyde -p`: its 15 s cold load
  started with the turn that needed it. The first cardShuffle turn now waits for it, once, up to 30 s
- A stalled cloud provider no longer holds a turn for 10 minutes: a stream that sends nothing for
  180 s fails with "no response" (not retried; cardShuffle re-deals). Local servers keep 600 s
- `clyde -p` no longer hangs when stdin is a pipe nobody closes (cron, `ssh` without `-n`, CI)
- MCP and OAuth requests send ClydeCLI's User-Agent; some servers' bot protection refused Python's
- SkillSpector's "CAUTION" with no findings now says the scan was partial, and why
- `/models local` no longer offers embedding or reranker models, draft or F32 helper files, and
  sizes a quantization by its largest file
- `/eval`'s hand found no dot-files (`.env`); provider errors no longer count as wrong answers
- Plan mode was only a flag; tools could still edit files while it was on
- `/clear` (and `/reset`, `/new`) clears the screen too and redraws the banner
- The thinking spinner comes back after a permission or question prompt, and when a tool runs after
  streamed text; before, the rest of the turn ran with nothing on screen
- Bash results show the last line the command printed (or its error) after the exit code
- The permission prompt shows its y / a / n keys; they were printed as Rich markup and vanished,
  leaving only numbers
- OpenRouter `:batch` variants are no longer listed; they reject chat requests
- LM Studio models use the context LM Studio actually loaded them with (`lms ps`) for auto-compaction
- The test suite runs against a temporary home instead of the real `~/.clyde` and `~/.claude`
- `~/.claude/skills` no longer overrides a same-named skill in `~/.clyde/skills`
- `/clear` and `/compact` acted on the previous conversation after loading a session
- Loading a corrupt session file no longer crashes the REPL
- An `Edit` whose `new_string` dropped the final newline no longer merges the next line into it

## [0.1.0] - 2026-04-01

### Added

#### Core Features
- Multi-provider support for Anthropic, OpenAI, and GLM (Zhipu AI)
- Interactive REPL with prompt-toolkit integration
- Rich interactive terminal output
- Session persistence and management
- Configuration management with basic API key obfuscation

#### CLI Commands
- `clyde` - Start the interactive REPL
- `clyde login` - Interactive API key configuration
- `clyde config` - View current configuration
- `clyde --version` - Show version information

#### Provider Implementations
- **Anthropic Provider**: Claude integration with chat + streaming interfaces
- **OpenAI Provider**: GPT integration with chat + streaming interfaces
- **GLM Provider**: GLM integration with chat + streaming interfaces

#### REPL Features
- Command history with persistent storage
- Auto-suggestions from history
- Slash commands: `/help`, `/exit`, `/clear`, `/save`, `/load`, `/multiline`
- Skill slash commands backed by `SKILL.md`
- Syntax highlighting with Rich library
- Tab completion and multi-line input support

#### Configuration System
- JSON-based configuration storage
- Base64-encoded API keys for basic obfuscation
- Provider-specific settings (API key, base URL, default model)
- Session auto-save option

#### Session Management
- Unique session ID generation
- Conversation history tracking
- Session save/load functionality
- Conversation clear operation

#### Code Quality
- Type hints for all public functions
- Abstract base class for provider implementations
- Data classes for structured data (ChatMessage, ChatResponse)
- Error handling and validation

#### Testing
- Unit tests for core components
- Integration tests for providers
- End-to-end tests for REPL functionality
- Test coverage for configuration management

### Technical Details

#### Architecture
- Modular provider system with base abstraction
- Conversation management with message history
- Configuration management layer
- REPL engine with prompt-toolkit

#### Dependencies
- `anthropic>=0.18.0` - Anthropic SDK
- `openai>=1.0.0` - OpenAI SDK
- `zhipuai>=2.0.0` - Zhipu AI SDK
- `prompt-toolkit>=3.0.0` - Interactive REPL
- `rich>=13.0.0` - Terminal formatting
- `python-dotenv>=1.0.0` - Environment variables

#### File Structure
```
src/
├── providers/          # LLM provider implementations
│   ├── base.py        # Abstract base class
│   ├── anthropic_provider.py
│   ├── openai_provider.py
│   └── glm_provider.py
├── repl/              # Interactive REPL
│   └── core.py
├── agent/             # Session management
│   ├── session.py
│   └── conversation.py
├── config.py          # Configuration management
└── cli.py             # CLI commands
```

### Known Limitations

- Context building is still in early MVP form and needs deeper project summarization
- Permission enforcement exists as a framework but is not fully integrated everywhere
- `/resume`, `/compact`, and `/doctor` are not implemented yet
- The current CLI uses turn-based output even though providers expose streaming interfaces

### Migration Notes

This is the initial MVP release. No migration needed.

### Future Roadmap

- [ ] Context enrichment and project-memory improvements
- [ ] Full permission integration
- [ ] `/resume`, `/compact`, `/doctor`
- [ ] Token usage and cost tracking
- [ ] MCP and plugin-system enhancements

---

## Release Notes

### v0.1.0 - MVP Release

This is the first public release of ClydeCLI, a complete reimplementation of Claude Code. This MVP includes:

- Full multi-provider support
- Interactive REPL
- Session management
- Configuration system
- Tool system and agent loop foundations
- Type-safe implementation

The focus was on building a solid foundation with clean architecture, comprehensive testing, and good developer experience. All core features are working and tested.

**Special Thanks**: This project is inspired by Claude Code and aims to provide an open-source alternative for learning and experimentation.

---

[0.1.0]: https://github.com/dea6cat/ClydeCLI/releases/tag/v0.1.0
