# Usage

[Back to the README](../README.md)

## REPL Commands

| Command      | Description           |
| ------------ | --------------------- |
| `/`          | Show commands & skills |
| `/help`      | Show all commands     |
| `/save`      | Save session          |
| `/load <id>` | Load session          |
| `/resume [id]` | Pick a recent session of this workspace to continue |
| `/multiline` | Toggle multiline mode |
| `/model [provider:model]` | Show or switch the model |
| `/login [provider]` | Connect a provider or replace its key (`custom` adds any OpenAI-compatible API), then switch to its model |
| `/models [all\|refresh]` | List models from every connected provider; hides ones `/eval` found broken (`all` shows them, `refresh` re-fetches the lists) |
| `/models local [best\|ollama\|hf\|mlx] [words]` | Find local models on ollama.com and Hugging Face (GGUF, and MLX on Apple Silicon) that fit this machine, rated relax / balance / hard, and download one |
| `/eval [filter]` | Test listed models on a tool call and a round trip, then a hand of 11 graded tasks for those that pass; shows pass/fail, hand score, latency and tok/s, and remembers which ones don't work |
| `/think [level]` | Reasoning: off, low, medium, high, on, default |
| `/doctor`    | Diagnose environment, config, keys and permissions |
| `/mcp`       | Connected MCP servers and their tools |
| `/mcp login <server>` / `/mcp logout <server>` | OAuth sign-in (browser) for a remote MCP server, or forget its tokens |
| `/plugins`   | Loaded plugins and what each added |
| `/check`     | Run the project's ruff, mypy and pytest |
| `/review [commit SHA \| base BRANCH]` | Read-only review of uncommitted changes (and untracked files), one commit, or this branch against its base |
| `/status`    | Model, mode, directory, session, goal, terse and token totals, plus plan progress |
| `/goal [text\|plan\|clear]` | A goal for this session, kept in the system prompt every turn (500 characters at most); `plan` makes it "every phase of the saved plan is complete" and it clears itself when the last phase is done |
| `/remember [project] TEXT` | Keep a note between sessions, about you (default) or this project. The model can save one too when you ask it to remember something |
| `/memory` / `/forget [project] N` | List the notes with numbers; drop one |
| `/plan [done\|start\|pending N \| clear]` | Show the saved plan; set phase N's status; or delete the plan |
| `/debug [path]` | The last turn's model and tool calls, or the trace file path |
| `/skills scan` / `/skills allow <name>` | Rescan skills with SkillSpector (LLM review when your model allows) and show verdicts; let a held-back skill, plugin or `mcp:<server>` in |
| `/rewind` | Undo the model's file edits and/or the conversation back to before one of your messages |
| `/laya` | Laya's status, and how its stuck checks and difficulty scores lined up with how traced turns ended |
| `/cost`      | Tokens and estimated cost per model |
| `/context`   | Context window usage and auto-compact threshold |
| `/compact`   | Summarize the conversation to free context |
| `/clear`     | Clear history         |
| `/exit`      | Exit REPL             |

## Writing Skills

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

## Code Map

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

## Hooks

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

## MCP Servers

Add MCP servers under `mcpServers` in `~/.clyde/settings.json` (Claude Code's format): local ones
that ClydeCLI starts (stdio), and remote ones it reaches over HTTP:

```json
{
  "mcpServers": {
    "dart": {"command": "dart", "args": ["mcp-server"]},
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
               "env": {"GITHUB_TOKEN": "..."}},
    "linear": {"type": "http", "url": "https://mcp.linear.app/mcp",
               "headers": {"Authorization": "Bearer ${LINEAR_TOKEN}"}},
    "legacy": {"type": "sse", "url": "https://example.com/sse"}
  }
}
```

| Config | Transport |
|---|---|
| `command` (+ `args`, `env`) | stdio: newline-delimited JSON-RPC to a process ClydeCLI starts |
| `"type": "http"`, or Gemini CLI's `httpUrl` | Streamable HTTP: each message is a POST, replies come back as JSON or an event stream, and the server's `Mcp-Session-Id` rides on every later request |
| `"type": "sse"` | HTTP+SSE (the 2024-11-05 protocol): a stream stays open, its `endpoint` event names where to POST, replies arrive on the stream |
| just a `url` (Cursor's form) | Streamable HTTP first, falling back to HTTP+SSE when the server refuses the POST, as the spec advises |

`${VAR}` in a `url` or a header comes from your environment, so tokens can stay out of the file.
Remote servers sign in with headers (API keys, bearer tokens) or with OAuth. A server that wants
OAuth shows as "needs sign-in" until you run `/mcp login <server>` (or `clyde mcp login <server>`):
ClydeCLI finds the server's authorization server from its metadata (RFC 9728 / RFC 8414), registers
itself (RFC 7591, so there's no app to create), opens your browser on the sign-in page with PKCE, and
catches the redirect on `127.0.0.1`. Tokens are kept in `~/.clyde/mcp_oauth.json` (mode 600), sent
with every request and refreshed when they expire or the server rejects them; `/mcp logout <server>`
forgets them. A sign-in never starts on its own, and a server you give an `Authorization` header
keeps using that header.

- They start with the REPL; each tool shows up as `mcp__<server>__<tool>`, and `/mcp` lists them
- Resources are available through ListMcpResources / ReadMcpResource
- `clyde mcp import` (also offered by `clyde setup`) copies stdio and remote servers from Claude Code
  (`~/.claude.json`), Cursor, Gemini CLI, Codex (`config.toml`) and Copilot CLI after you say yes;
  env values are never printed and the settings file is kept at mode 600
- A project's own `.mcp.json` (Claude Code's format, at the repo root) adds its servers. A repository
  can put anything there, so each server starts only after you say yes, and the answer covers that
  exact entry: a changed command asks again. `${VAR}` and `${VAR:-default}` expand from your
  environment; your own settings win a name clash; `clyde -p` skips entries you haven't answered yet.
  Answers live in `~/.clyde/mcp_project_approvals.json`
- SkillSpector scans every server's tool list when it connects, local or remote (see SkillSpector)

## Modes

*Every hand plays differently. Pick how I play this one.*

Shift+Tab cycles the mode, shown under the prompt:

| Mode | What it does |
|---|---|
| `♠ hold` | The default. Asks before anything that changes things: every file edit, non-read-only shell commands, settings changes |
| `♠ reading the table` | Plan mode. Reads, searches and runs read-only commands, then presents a plan; anything that would change files is refused until the plan is in |
| `♠♠ all in` | Plays without asking, except major moves: `rm -r`/`-f`, `git push`, `git reset --hard`, `git clean -f`, `branch -D`, publishing, `curl … \| sh`, `docker rm`/`prune`, `kubectl delete`, `terraform apply`/`destroy`, `chmod -R`, `kill -9`, writing to secrets |

Deny rules and the always-refused commands (like `sudo`) apply in every mode, and writes outside the
project are refused in every mode.

## Updates

`clyde update` moves Clyde to the newest version of its channel with the tool that installed it (uv tool, pipx or pip); a
source checkout is updated with `git pull`. `clyde update --check` only reports (exit 0 current, 1 newer exists, 2 could not
check).

| Channel | Follows | Set with |
|---|---|---|
| `latest` (default) | every commit on `main` | `clyde update --channel latest` |
| `stable` | the newest `vX.Y.Z` release tag; never downgrades you | `clyde update --channel stable` |

The channel is saved in `~/.clyde/config.json` (`update_channel`). `stable` follows the `vX.Y.Z` release tags; if it finds none it says so and changes nothing.
Once a day a background thread asks GitHub for the newest commit and caches the answer in `~/.clyde/update_check.json`; the next
start shows one line when you are behind. It never delays start-up and never installs anything by itself. Turn the check off
with `CLYDE_NO_UPDATE_CHECK=1`. It does not run for `-p`, `--acp` or other commands.

**What is verified.** Clyde installs from source, so there are no signed binaries or checksum manifests like Claude Code's.
What you get instead: `clyde update` installs the exact commit (or release tag) it just checked, so the install cannot differ from
what it reported; `CLYDE_REF` pins the installer the same way; and `clyde doctor` shows which commit you run. Trust rests on
GitHub over HTTPS and the commit hash. The one-line installer is `curl | sh`: read it first if that matters to you.

## Memory

Clyde has two kinds of memory, and both go into every turn.

- **Memory files you write.** Clyde reads `CLYDE.md`, `CLAUDE.md`, `AGENTS.md` and `GEMINI.md` (and `.cursorrules` and Copilot's
  instructions) from your project and from `~/.clyde/`, the first name that exists in each place. This is how it worked before
  and it still does, so files written for other agents keep working.
- **Notes Clyde keeps for you.** Say "remember that I prefer short answers" and the model saves a note with its `Remember` tool,
  or type `/remember TEXT` yourself (`/remember project TEXT` for a note about the codebase). `/memory` lists the notes with
  numbers and `/forget N` drops one. In hold mode Clyde asks before the model saves a note, and plan mode refuses it.

Notes are plain markdown, one bullet each, that you can edit by hand: `~/.clyde/memory.md` for you, and one file per project under
`~/.clyde/memory/projects/`, so nothing is written into your repositories. Each note is at most 300 characters, each file holds 40,
and about 2,000 characters ride in the prompt, fenced as data: a note is context about you, never an instruction that overrides what
you ask or Clyde's safety rules. Clyde does not learn anything on its own; a note exists only because you or you-approved-the-model
saved it. The saved session, plan and memory notes together are what carry over from one conversation to the next.

## Plans

When the model presents a plan with `ExitPlanMode` and you approve it, the plan is saved to
`.clyde/plans/<session id>.md` and its head (goal, next step, one line per phase with its status) goes back into the
system prompt on every turn, fenced as data. So the plan survives `/compact`, `/clear` and `--resume`. Plan mode asks
for a fixed shape: `## Goal`, `## Next Step`, `### Phase N: name` blocks each with a `- **Status:** pending | in_progress | complete`
line, then decisions and errors. `/plan` shows it, `/plan done|start|pending N` changes a phase, `/status` shows the
progress, and `/goal plan` turns "every phase is complete" into a goal that ends itself.
(The idea comes from [planning-with-files](https://github.com/OthmanAdi/planning-with-files), MIT.)

- **Kept out of git automatically.** The first time a plan is saved in a git repository, `.clyde/plans/` is added to that
  clone's `.git/info/exclude`. It is local to your clone: no `.gitignore` or other tracked file is changed. Outside a
  repository nothing is added.
- **A custom `planFilePath` is not tracked.** If the model gives `ExitPlanMode` its own `planFilePath`, the plan is written
  there (inside the project, as every write must be), but Clyde does not reload it into later turns, `/plan` does not see
  it, and it is not added to `.git/info/exclude`. Only the default per-session file is.
- A saved plan file over 200 KB is ignored, and only its head (about 2,500 characters) rides in the prompt.

## Data Files

*Let me look at the numbers before you build the pipeline.*

The Data tool lets any model look at data the way a data engineer would, instead of reading a
50 MB CSV line by line:

- `profile` a file: row count, columns and types, null percentage, approximate distinct counts,
  min/max/mean, and five sample rows. CSV, TSV, Parquet, JSON and JSONL go through DuckDB; a SQLite
  database shows its tables, columns and row counts
- `query` with SQL: `SELECT region, sum(amount) FROM 'sales/*.parquet' JOIN 'regions.csv' USING (id)
  GROUP BY 1`. Files are referenced by path (relative to the project, globs work) and can be joined;
  pass `database` to query a SQLite file instead

It only reads. DuckDB runs sandboxed: files inside the project only, no network, no extension
installs, settings locked, and only SELECT-type statements (checked with DuckDB's own parser, so
`COPY ... TO`, `ATTACH` or `CREATE` are refused). SQLite opens read-only behind an authorizer that
refuses anything but reads. Each call has a 60 s limit and returns at most 1,000 rows.

## Rewind

*Bad hand? Take it back.*

Every message you send opens a checkpoint. The first time the model changes a file in that turn
(Write, Edit, NotebookEdit), the file is saved as it was, or noted as new. `/rewind` lists your recent
messages with the files each one changed; pick one and choose:

| Choice | Does |
|---|---|
| `c` code and conversation (default) | Files go back to how they were before that message (files the model created are removed), the conversation is cut there, and your message comes back in the prompt to edit or resend |
| `f` files only | Just the files |
| `m` conversation only | Just the conversation, files untouched |

Checkpoints live in `~/.clyde/checkpoints/<session>/` (the newest 20 sessions), so they survive
`/resume`. Changes made by shell commands (`rm`, `mv`, scripts) aren't captured: there's no reliable
way to know what a command touches, so commit before risky runs. If the conversation was compacted
or cleared after a checkpoint, only its files can be rewound.

## Sub-agents

*Deal more hands at once.*

The model can hand a self-contained task to a sub-agent with a fresh conversation (the Agent tool),
and get back only its final answer. Sub-agents come in types: `general-purpose` has every tool; a
custom type is a Markdown file in Claude Code's format, read from the project's `.clyde/agents/` or
`.claude/agents/`, then `~/.clyde/agents/` or `~/.claude/agents/`:

```markdown
---
name: test-runner
description: Runs the test suite and reports failures with their likely cause
tools: Bash, Read, Grep        # optional allow-list
model: inherit                 # or provider:model
---
You run tests. Report each failure with the file, the assertion and the likely cause.
```

With `run_in_background` a sub-agent returns a task id at once; `TaskOutput` reads its answer
(`block: true` waits) and `TaskStop` cancels it. `TeamCreate` starts several members in parallel,
each with its own prompt and type, and `TeamDelete` stops any still running. Background agents can't
prompt you mid-turn, so anything that would ask is denied; sub-agents can't start agents or teams of
their own; agents written for other tools pass the same SkillSpector gate as skills.

## Pasting

*Show me the cards. I'll read them.*

| Paste | What lands in the prompt |
|---|---|
| Ctrl+V with an image copied (a screenshot, an image copied from a browser) | `[Image #N]` |
| Cmd+V with an image file path copied (plain, quoted, `\ `-escaped or `file://`) | `[Image #N]` |
| Cmd+V with text over 2 lines or 800 characters | `[Pasted text #N +X lines]` |

Images and pasted texts share one counter. On send, each `[Image #N]` attaches that image (PNG,
JPEG, GIF or WebP) and each `[Pasted text #N …]` expands back to the full text; the transcript keeps
the short marker. Images travel with every provider and are saved with the session, so `/resume`
keeps them. An image over 5 MB is shrunk (JPEG, longest side 2048 px, with macOS's built-in `sips`;
elsewhere it's refused). When the model can't read images (the catalog says so, or Ollama doesn't
list vision), pasting says so, and sending drops the image with a note instead of failing; models
the catalog doesn't know get the image. Clipboard images use `osascript` on macOS and `wl-paste` or
`xclip` on Linux.

## Shell commands and folders

*You can look at the whole table. You only touch your own chips.*

Clyde asks before it changes anything. Every shell command that is not read-only asks first, and so does any command (even a
read-only one) that names a file or folder outside the project and its extra working directories: an absolute path, `~`, `$HOME`
or `..`. Temp folders don't count. Those asks stay on in all-in mode, and so does the ask before touching `.git/config` or
`.git/hooks`. Read, Write, Edit, NotebookEdit, Glob, Grep and a shell's `cwd` ask too when they name a file or folder outside the project:
one yes covers that file (or that folder and what is under it) for the rest of the session, a no does not. Read and Grep of a key or `.env`
file ask as well (`clyde -p` denies every ask).

There is no OS sandbox. Clyde used to run shell commands under macOS `sandbox-exec`, which Apple has deprecated; one macOS release
could have broken every command, so the permission prompt is the guard instead. The catch: once you approve a command, it can write
anywhere you can. Read what it says before you press yes.

## Permission Rules

Stop answering the same prompt. Add rules to `~/.clyde/settings.json` (Claude Code's syntax), or
pick **"Yes, and don't ask again"** at a prompt to save one:

```json
{"permissions": {"allow": ["Bash(npm test)", "Bash(git commit:*)", "Edit(docs/**)", "WebFetch(domain:docs.python.org)"],
                 "deny": ["Bash(rm -rf:*)"]}}
```

- `Bash(cmd)` is exact, `Bash(prefix:*)` matches whole leading words, bare `Bash` matches everything
- A compound command (`&&`, `;`, `|`) is allowed only if every part is; read-only parts like `cd` count
- `Edit(...)` / `Write(...)` take globs relative to the workspace; deny rules win and block without asking

## Plugins

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

## Self-Checks

- After ClydeCLI writes or edits a Python file, it runs ruff (and mypy, if the project configures it)
  on that file and hands only the problems the edit introduced back to the model in the same turn
- `/check` runs the project's ruff, mypy and pytest and prints a short summary
- Tools are found from `pyproject.toml`, config files and `uv.lock` (run with `uv run --no-sync`, the
  project's `.venv`, or PATH); ClydeCLI never installs them. Off: `CLYDE_CHECKS=off` or
  `{"checks": {"enabled": false}}` in `~/.clyde/settings.json`

## Tracing and /debug

- Each session writes `~/.clyde/traces/<session_id>.jsonl`: model requests (duration, tokens, stop
  reason or error), tool calls, hook blocks, permission prompts, compactions, MCP errors, Laya's
  judgments and how each turn ended (tool rounds, and whether it ran out). API keys
  and key-shaped values are redacted and long values cut to 500 characters
- `/debug` shows the last turn, `/debug path` the trace file, and `clyde --debug` prints events live
- Off: `CLYDE_TRACE=off` or `"session": {"trace": false}` in `~/.clyde/config.json`; the newest 50
  traces are kept
