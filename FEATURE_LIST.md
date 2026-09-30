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
| CLI entry point | ✅ | Supports `clyde`, `login`, `config`, `--version` |
| Interactive REPL | ✅ | Supports interactive output, history, Tab completion, multi-line input |
| Slash Commands | ✅ | Supports `/help`, `/clear`, `/save`, `/load`, `/multiline`, `/exit` |
| Multi-provider abstraction | ✅ | Canonical types in, canonical response out; each adapter owns its wire format |
| Provider configuration management | ✅ | `provider:model` selection, `/model` switching, keys via env or `~/.clyde/keys.json` |
| Session persistence | ✅ | Supports saving/loading local sessions |
| Session message management | ✅ | Supports session history maintenance and serialization |
| Error recovery / re-login | 🟡 | Basic authentication error handling and reconfiguration flow exist |
| Token / Cost tracking | 🟡 | `/cost` and `/context` report token usage; no per-model pricing |
| Context building | 🟡 | A basic `context_system` exists, supporting workspace / git / `CLAUDE.md` injection; still missing README summaries, memory, compact |
| Claude Code Agent Loop | ✅ | agent_loop.py implemented, supports the tool-call loop |
| `/resume` session recovery experience | 🚫 | No dedicated recovery flow or UI yet |
| `/compact` conversation compaction | 🟡 | Manual `/compact` summarizes older history; no automatic compaction |
| `/doctor` diagnostics | 🚫 | No environment, config, permission, or dependency diagnostic command yet |
| Hook system | 🚫 | No pre/post tool use hooks yet |
| Permission system | 🟡 | Approval prompts wired into tool dispatch; only Write/Edit ask, Bash blocks dangerous patterns |

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
| Permission Framework | 🟡 | Integrated into dispatch; per-tool coverage is still thin |
| Error Handling | ✅ | Tool error types and handling defined |
| Task Manager | ✅ | Task manager implemented |

### Implemented Tool Modules

| Tool Category | Tool Name | File | Status |
|---------|---------|------|------|
| File operations | FileReadTool | `read.py` | ✅ Implemented |
| File operations | FileWriteTool | `write.py` | ✅ Implemented |
| File operations | FileEditTool | `edit.py` | ✅ Implemented |
| File operations | GlobTool | `glob.py` | ✅ Implemented |
| File operations | GrepTool | `grep.py` | ✅ Implemented |
| System operations | BashTool | `bash.py` | ✅ Implemented |
| Web tools | WebFetchTool | `web_fetch.py` | ✅ Implemented |
| Web tools | WebSearchTool | `web_search.py` | ✅ Implemented |
| Interaction tools | AskUserQuestionTool | `ask_user_question.py` | ✅ Implemented |
| Interaction tools | SendUserMessageTool | `send_user_message.py` | ✅ Implemented |
| Task management | TodoWriteTool | `todo_write.py` | ✅ Implemented |
| Task management | TaskStopTool | `task_stop.py` | ✅ Implemented |
| Task management | TasksV2Tool | `tasks_v2.py` | ✅ Implemented |
| Task management | TaskManager | `task_manager.py` | ✅ Implemented |
| Agent tools | AgentTool | `agent.py` | 🟡 Batches tool calls; no sub-agent |
| Agent tools | BriefTool | `brief.py` | ✅ Implemented |
| Agent tools | TeamTool | `team.py` | 🟡 Writes a team file only |
| Config tools | ConfigTool | `config.py` | ✅ Implemented |
| Plan mode | PlanModeTool | `plan_mode.py` | ✅ Implemented |
| Scheduled tasks | CronTool | `cron.py` | 🟡 Stores jobs; nothing runs them |
| MCP tools | MCPTool | `mcp.py` | ⏳ No MCP client connected |
| MCP tools | MCPResourcesTool | `mcp_resources.py` | ⏳ No MCP client connected |
| Skill system | SkillTool | `skill.py` | ✅ Implemented |
| Tool search | ToolSearchTool | `tool_search.py` | ✅ Implemented |
| LSP integration | LSPTool | `lsp.py` | ⏳ No LSP client connected |
| Worktree | WorktreeTool | `worktree.py` | 🟡 Empty folder, not a git worktree |
| Miscellaneous | SleepTool | `sleep.py` | ✅ Implemented |
| Miscellaneous | StructuredOutputTool | `structured_output.py` | ✅ Implemented |
| Miscellaneous | MiscTools | `misc.py` | 🟡 SendMessage, PowerShell work; RemoteTrigger, NotebookEdit, REPL are stubs |

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
| Context Engine | 🟡 | Basic context-building pipeline connected, supporting workspace, git, and `CLAUDE.md` prompt injection |
| Permission Engine | 🟡 | Integrated for Write/Edit; other tools don't ask yet |
| Compaction Engine | 🟡 | Manual `/compact`; no automatic trigger |
| Hook Runtime | 🚫 | No settings-driven hook execution yet |
| MCP Runtime | 🚫 | MCP tools exist but no client is ever connected |

---

## Test Coverage

| Test Type | Status | File |
|---------|------|------|
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

## Phase 3: Context, permissions, recovery (in progress)

Goal: fill in Claude Code's engineering capabilities.

- [ ] Complete workspace context building
- [x] Basic git status / file tree / `CLAUDE.md` injection
- [ ] README / entry file summary injection
- [ ] Memory and history context management
- [ ] Full permission system integration
- [ ] `/resume`
- [ ] `/compact`
- [ ] `/doctor`
- [ ] pre/post tool use hooks

## Phase 4: MCP, plugins, extension ecosystem

Goal: upgrade the project from a monolithic CLI to an extensible platform.

- [ ] Complete MCP client/runtime
- [ ] Python plugin system
- [ ] Custom commands / tools / hooks
- [x] Local model (Ollama) and third-party provider support
- [ ] Better observability and debugging tools

## Phase 5: Distinctive strengths of the Python version

Goal: build features unique to the Python rewrite.

- [ ] Notebook-friendly toolchain
- [ ] Enhancements for data engineering / ETL scenarios
- [x] Support for Chinese model providers (GLM, DeepSeek, MiniMax)
- [ ] pytest / ruff / mypy / uv integration experience
- [ ] Extension interfaces for in-house enterprise automation and workflows

---

## PRs We're Looking For

### P0: Most welcome, easiest to merge

- Improved test coverage
- Documentation improvements
- Error handling improvements
- Performance optimizations

### P1: High-value foundational capabilities

- Automatic context building
- Full permission system integration
- `/resume` implementation
- `/compact` implementation
- `/doctor` implementation

### P2: Filling in key Claude Code experiences

- Hook system
- Full MCP support
- Token/Cost statistics
- Performance monitoring and tuning

### P3: Python version highlights

- Enhanced notebook editing and reading
- Enhanced data file tools
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
