# Implementation Plan: user-feedback fixes

## Overview
The eight fixes from `replica/fixes.md`: what Claude Code, Codex CLI and Kilo Code users most complain about, applied to ClydeCLI. Each is the smallest change that solves the complaint (ponytail), on one branch, `user-feedback-fixes`, one commit per task.

## Architecture Decisions
- **Secret reads** go through the registry's existing permission flow. `_SECRET_NAMES` already guards edits; reads reuse it rather than adding a new policy layer.
- **Regression warning:** `/eval` keeps the previous grade next to the new one. cardShuffle needs no change, since it already ranks by the current grade, so a dropped model moves down by itself.
- **Usage line:** extends `_turn_footer` and reuses `cost_tracker.estimate_usd`. Rate-limit headers are captured where every HTTP response already passes (`base.post_stream`), so no adapter changes.
- **XDG:** one helper, `clyde_home()`, replaces the `Path.home() / ".clyde"` repeated in 18 files.
  - It uses `$XDG_CONFIG_HOME/clyde` only when `~/.clyde` doesn't exist yet or the XDG folder already does, so an existing install never loses its keys and sessions.
  - One folder, not a config, data and state split. ponytail: split it if anyone asks.
- **Anthropic-compatible custom providers:** the `custom` login gets a protocol question; the registry builds an `AnthropicProvider` for those.
- **Trace cap:** stop appending to a trace file past a size limit, writing one "truncated" marker.
- **Anti-sycophancy:** one sentence in `CLYDE_PERSONA`.
- **ACP:** `clyde --acp` speaks the Agent Client Protocol (newline-delimited JSON-RPC on stdio, protocolVersion 1).
  - It reuses headless mode's `ClydeREPL(headless=True)` and its `chat()`, with listeners for text and tool events.
  - Permission asks become `session/request_permission`.
  - Minimal scope: `initialize`, `session/new`, `session/prompt`, `session/cancel` and the three update kinds. No `session/load`, no client file system or terminal delegation.

## Task List
See `tasks/todo.md`.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| The XDG switch strands an existing `~/.clyde` | High | XDG is used only when `~/.clyde` is absent or the XDG folder already exists; tests cover both |
| The secret-read prompt breaks `clyde -p` and sub-agents | Med | They already deny asks openly; an allow rule (`Read(.env)`) or all-in mode with a yes covers deliberate use |
| The ACP spec was read from the docs summary, not the full JSON schema | Med | Only documented fields are used; a test drives the server with a fake client over pipes. No editor is available here to try it live |
| Rate-limit header names differ per provider | Low | Show any `*ratelimit*remaining*` header; show nothing when absent |

## Open Questions
- **ACP has never been run against a real editor** (Zed, or JetBrains through an adapter). Needs your machine.
