# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- cardShuffle council: `cardShuffle:<tier> council` (for example `/model cardShuffle:high-roller council`) asks the tier's top four
  models the same question at once, tools off, and Laya picks the best answer. `/council` shows every answer with its score and
  `/council up N` / `/council down N` records a vote in `~/.clyde/council_votes.jsonl` (kept on your machine). Models that fail
  or miss the 90 s deadline are left out; without Laya the answers come back unranked.

### Changed
- Clyde asks you to accept its licence before its first command: type `I accept` (Enter alone declines, status 3). Saved in
  `~/.clyde/license.json`, so installs that update from an earlier version are asked on their next run, once. `clyde license
  [accept]` shows or records it; `CLYDE_ACCEPT_LICENSE=1` accepts one scripted run. Changing the terms (`TERMS_VERSION`) asks
  everyone again.
- Licence: ClydeCLI is under the PolyForm Noncommercial License 1.0.0 (source-available; commercial use needs permission). Copies
  obtained before this change remain MIT.

### Fixed
- A provider's `Retry-After` (seconds or a date) is read: retries wait that long (up to 30 s); a longer ask skips the retries and
  cardShuffle benches the model for it instead of stalling the turn.
- cardShuffle benches a model that hit a quota (429: 90 s, 402: 1 h) or answered nothing (10 min), so later turns do not deal it
  again straight away, for the provider's `Retry-After` when it sent one. The idea comes from freellmapi's cooldowns.
- cardShuffle deals the next model when the dealt one returns no answer text and no tool call (usage still recorded).
- The project snapshot no longer walks a huge start folder such as `~` for minutes before the first request: one walk that skips
  ignored and hidden folders and stops after 1 s.

### Added
- Memory notes between sessions: `/remember [project] TEXT`, `/memory` and `/forget [project] N`, and a `Remember` tool the model uses when you ask it to remember
  something (hold mode asks first, plan mode refuses). Notes are markdown at `~/.clyde/memory.md` and `~/.clyde/memory/projects/`, never inside a
  repository, bounded (300 characters a note, 40 a file) and fenced as data in the prompt. The hand-written memory files (`CLYDE.md`, `CLAUDE.md`,
  `AGENTS.md`, `GEMINI.md`) are read exactly as before.
- `clyde update` installs the exact commit or release tag it just checked (not whatever `main` is a moment later), and `install.sh`
  accepts `CLYDE_REF=<tag or commit>` to pin an install; a ref with anything but letters, digits, `.`, `-`, `_` is refused before
  anything runs.
- Update channels: `clyde update --channel latest|stable` (saved as `update_channel`). `latest` follows `main`; `stable` follows the newest
  `vX.Y.Z` tag and never suggests a downgrade. The once-a-day check and its note follow the saved channel.
- `clyde update [--check]` updates Clyde the way it was installed. A once-a-day background check (cached in `~/.clyde/update_check.json`,
  off with `CLYDE_NO_UPDATE_CHECK=1`) adds one line at the next start when a newer version exists; nothing installs by itself.
  `uninstall`, `update` and `doctor` work without accepting the licence, so you can always leave.
- `clyde uninstall [--purge] [-y]` removes Clyde with the tool that installed it (uv tool, pipx or pip) after a confirmation. Your
  settings, saved keys and sessions stay unless you add `--purge`, which refuses a data folder that is not clearly Clyde's. A source
  checkout is not touched.
- `clyde doctor` (and the top of `/doctor`) reports how Clyde was installed (uv tool, pipx, source checkout or pip, with the git commit
  when known), whether several programs answer to `clyde` on PATH, whether Claude Code is installed, and the licence status.
- Saving a plan in a git repository adds `.clyde/plans/` to that clone's `.git/info/exclude` (local; no tracked file changes), so plans
  never get committed. The README now has a Plans section, and lists `/review`, `/status`, `/goal`, `/plan`, `clyde review` and
  `clyde sessions`. It notes that a custom `planFilePath` is not reloaded and not excluded.
- The plan you approve in plan mode now lives on disk per session (`.clyde/plans/<session>.md`) and its head (goal, next step,
  one line per phase with its status) goes back into the system prompt every turn, fenced as data, so it survives `/compact`
  and `--resume`. Plan mode asks for a fixed shape (goal, next step, phases with a Status, decisions, errors) and rules: log
  errors, never repeat a failed action, update the status. `/plan` shows it, `/plan done|start|pending N` sets a phase's
  status, `/plan clear` deletes it, `/status` shows the progress, and `/goal plan` makes "every phase is complete" the goal,
  which ends and clears itself when the last phase is done. Idea from planning-with-files (MIT).
- `clyde sessions list|search WORDS|archive ID|unarchive ID`: find old sessions of this folder by their text, and move ones you
  are done with out of `/resume` (to `sessions/archive/`; unarchive brings them back).
- `/status` shows the model, mode, directory, session, goal, terse and token totals. `/goal [text|clear]` sets a goal for the
  session that rides in the system prompt every turn (capped at 500 characters, in memory only).
- `/review` and `clyde review`: a read-only review of uncommitted changes (and the untracked files), `commit SHA`, or `base BRANCH`.
  The diff is capped per file, smallest first, and anything left out is named. `clyde review` prints and exits (2 outside a repo).
- The spinner now says what the turn is waiting for and runs a live timer through the whole wait, not only once the answer
  arrives: `Dealing… · 12s · waiting up to 30s for Laya to load`, then `asking Laya how hard this is`, `waiting for provider:model`,
  `retry 2 of 3 in 2s: HTTP 503…`, `running Bash`, and `compacting the conversation` (which had no spinner before).
- End-to-end tests (`tests/e2e`, opt in with `CLYDE_E2E=1`): a real `clyde` in a pseudo-terminal against a scripted fake model, in a throwaway HOME.
- `/terse [on|off]` (a picker when bare): a built-in `terse` output style that asks for shorter replies, saved and applied to
  new sessions. On a local Qwen2.5-Coder 3B it cut output tokens by about 55% and reply time by about a third on three
  prompts; answers stay correct but briefer. Off by default.
- Lower per-request overhead: only 17 core tools (Bash, Read, Write, Edit, Glob, Grep, web, todo, Agent, Skill, plan mode...)
  are sent with every request; the other 39, MCP tools included, are listed by name in a short "More tools" section of the
  system prompt and loaded when the model calls `ToolSearch` (or calls the tool by name). A first request in a Dart/Flutter
  project with an MCP server went from about 13.8k to 5.6k input tokens. `CLYDE_ALL_TOOLS=1` sends every tool as before.
- The status line under the prompt shows the model in use in its right corner (`provider:model`); with cardShuffle it reads
  `cardShuffle:house → provider:model`, following the model the latest turn was dealt to.
- Two new providers, both over their OpenAI-compatible endpoints: Cloudflare Workers AI (`cloudflare`: an API token plus
  your account id, which `/login` asks for and saves in settings.json) and Pollinations (`pollinations`: one `sk_` key). Each lists
  only tool-calling text models; Pollinations leaves out community models, which run on their owners' servers.
- Every choose-one-from-a-list question is now an arrow-key picker (Up/Down, PageUp/PageDown, Home/End, type to
  filter, Enter to pick, Esc to cancel, the current choice marked ✔): `/login` (provider, protocol, model),
  `/model` and `/models` (same picker; `/models all` and `/models refresh` still work), `/models local`, `/skills` (Enter runs the chosen skill), `/resume`, `/rewind` and the rejected-key menu. Without a terminal
  (pipes, ACP) they fall back to a numbered question.
- `/models local` offers to install Ollama (Homebrew on macOS, ollama.com script on Linux) or LM Studio
  (Homebrew cask) when the chosen model needs one that isn't there, or to start Ollama when it isn't
  running. It shows the exact command and asks first (default no), then goes on with the download.
- `/purge [name]`: delete local models (Ollama and LM Studio) from disk, all of them or only those whose
  name matches; lists what goes and the space freed, and asks first (default no).
- `clyde --acp`: Clyde as an Agent Client Protocol agent on stdio, so ACP editors (Zed, JetBrains
  through an adapter) can run it, with streamed replies, tool calls and permission asks
- The footer after each reply shows the turn's tokens in and out, the estimated cost when the model
  is priced, and the provider's remaining quota when its responses carry rate-limit headers
- `/eval` warns in red when a model solves a smaller share of the hand than at its last grade
- Custom providers can speak the Anthropic API (`/login` -> custom asks for the protocol), which
  also covers a second Anthropic account under its own name
- `$XDG_CONFIG_HOME/clyde` is used when that variable is set and no `~/.clyde` predates it
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
- Hold mode now asks before every file change (Write, Edit, NotebookEdit), code files included, not just `.md` files; a saved
  allow rule or all-in mode skips the question, and `clyde -p` in hold denies them as it does other asks.
- The status-line corner for cardShuffle drops the `cardShuffle:` prefix before it cuts the tier name when the terminal is narrow
  (`high-roller → nvidia:meta/muse-glimmer-30b`, not `…fle:high-roller → …`).
- Reading a secret file (`.env`, keys, `.ssh`, credentials) asks first, even in all-in mode, as editing
  one already did; allow and deny rules now cover Read and Grep
- Clyde's persona tells it not to open with agreement and to say when the user is wrong
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
- A turn that ends with no answer text (a reasoning model that spends it all thinking, or hits its output limit) printed only the footer.
  It now says so, with the output-token count, and suggests asking again, `/think off` or another model.
- A command or skill typed by its exact name alone (`/cost`, `/doctor`, `/check`, a skill like `/hello`) listed matching
  commands instead of running; only `/name args` ran it. It also made Enter in the `/skills` picker do nothing useful.
- `/model provider:name` for a model the provider does not list now warns instead of silently saving it as the default.
- Skills whose `description: >` (or `|`) block text spanned several lines showed just `>`: frontmatter block scalars are now read.
- Pollinations out of credits: it answers with a normal chat message instead of an error, so Clyde showed the notice as the
  model's reply, kept it in the conversation, and `/eval` could mark the model as failing. It is now a `❌ HTTP 402` line
  with the top-up link, nothing is added to the conversation, and `/eval` counts it as a transient failure.
- `/login` (and `clyde login` inside a session) ignored typing: the Esc watcher was still reading the keyboard while
  its prompts were open, so keystrokes never reached them.
- `/models local` skips Hugging Face quants of base (not chat-tuned) models, such as `Qwen2.5-Coder-7B` next to its
  `-Instruct` sibling: they write tool calls as prose and ignore tool results, so they always failed `/eval`.
- A tool call whose arguments repeat the call itself (`{'name': 'add_numbers', 'arguments': {...}}`, as Qwen2.5-Coder
  GGUF sends through Ollama) is now unwrapped for every tool, not only the built-in ones, and `/eval` applies the
  same repair, so such models are no longer marked as failing.
- `/models local` no longer lists models without tool calling: Hugging Face GGUF and MLX repos whose chat
  template never mentions tools are dropped, and models that already failed `/eval` here are hidden
  (ollama.com's tool tag alone let `command-r7b` through).
- A single trace file stops growing at 20 MB (with a `truncated` marker), so a long session can't fill the disk
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
