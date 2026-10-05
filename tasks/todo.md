# Tasks: user-feedback fixes

Verification for every task: `.venv/bin/python -m pytest -q` passes, and `uvx ruff check` reports no new problems in the touched files.

## Phase 1: Small fixes

- [x] **Task 1: Secret files ask before they're read** (S)
  - Read, and Grep on a path, against `.env`, keys, `.ssh` or credentials asks first, even in all-in mode.
  - Deny rules apply to Read and Grep.
  - Normal files don't prompt.
  - Files: `src/tool_system/registry.py`, `src/tool_system/permission_rules.py`, plus a test.
- [x] **Task 2: Anti-sycophancy line in the persona** (XS)
  - `CLYDE_PERSONA` says not to open with agreement and to say when the user is wrong.
  - Files: `src/output_styles/styles.py`.
- [x] **Task 3: Trace files have a size cap** (S)
  - Past the cap, events stop being written to that file and one `truncated` marker is written.
  - Files: `src/agent/trace.py`, plus a test.

### Checkpoint A
- [x] Full suite passes.

## Phase 2: Features

- [x] **Task 4: Anthropic-compatible custom providers** (S)
  - `custom` login asks openai or anthropic; it's saved as `"protocol"`; the registry builds `AnthropicProvider` for anthropic.
  - Old entries default to openai.
  - Files: `src/providers/keys.py`, `src/providers/registry.py`, `src/cli.py`, plus a test.
- [x] **Task 5: XDG base directory** (M)
  - `clyde_home()` uses `$XDG_CONFIG_HOME/clyde` when set and (`~/.clyde` is absent, or the XDG folder exists); otherwise `~/.clyde`.
  - All 18 call sites use it.
  - Files: `src/config.py` and the call sites, plus a test.
- [x] **Task 6: `/eval` warns when a model's grade drops** (S)
  - The saved result keeps the previous share and date.
  - The `/eval` table note shows `↓ was 11/11 (Sep 12)`, and a summary line names the models that dropped.
  - Files: `src/providers/model_eval.py`, `src/repl/core.py`, plus a test.
- [x] **Task 7: Per-turn usage line** (M)
  - The footer adds tokens in and out and the cost estimate when known.
  - Remaining rate limit comes from response headers when the provider sends them.
  - Files: `src/providers/base.py`, `src/repl/core.py`, plus a test.

### Checkpoint B
- [x] Full suite passes, and a live `clyde -p` turn still works.

## Phase 3: IDE

- [x] **Task 8: Agent Client Protocol (`clyde --acp`)** (L, split in two)
  - 8a. `src/acp.py`: JSON-RPC stdio loop, `initialize`, `session/new` and `session/prompt`, streaming `agent_message_chunk`, `tool_call` and `tool_call_update` through listener hooks on `ClydeREPL`, and `session/cancel`.
  - 8b. Permission asks map to `session/request_permission`; `--acp` wired into `cli.py`; README section.
  - Test: a fake client drives a full prompt turn over pipes, with a fake provider.

### Checkpoint C
- [x] Full suite passes, docs are updated, merged to main, and clyde is reinstalled.
