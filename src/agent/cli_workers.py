"""Other agent CLIs as orchestration workers: Claude Code and aider, run non-interactively in the worker's worktree.

A CLI in print mode cannot stop and ask the user, so the phase-1 contract (edits inside the worktree are free, commands
need a yes) is kept by what the CLI is allowed to use: files only, no commands, nothing from the user's own settings.
Claude Code gets `--restricted` and a fixed tool list; aider gets `--no-suggest-shell-commands` and never auto-commits.
Each run's raw output is kept in the worker's folder, and the CLI's own cost report goes in the ledger when it gives one.

A CLI gets only the one API key its model needs, taken from `clyde login` (not from a possibly stale export).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.providers import keys

_TIMEOUT_S = 900   # one worker; a CLI that runs longer is killed
_CLAUDE_TOOLS = "Read,Edit,Write,Glob,Grep"
CLAUDE_MODELS = ("haiku", "sonnet", "opus")   # aliases Claude Code accepts; it has no command that lists models
# Clyde's provider name -> the prefix litellm (aider) puts on that provider's model ids.
_LITELLM = {"mistral": "mistral", "openrouter": "openrouter", "google": "gemini", "deepseek": "deepseek",
            "openai": "openai", "anthropic": "anthropic"}

Emit = Callable[[str, str, Any], None]   # (kind, tool name, tool input)


@dataclass(frozen=True)
class CliResult:
    ok: bool
    summary: str
    usage: dict[str, int] | None = None
    usd: float | None = None


def litellm_models(provider_models: dict[str, list[str]]) -> list[str]:
    """aider's model ids for the providers Clyde has connected: `mistral/ministral-3b-latest`."""
    return [f"{_LITELLM[p]}/{m}" for p, models in provider_models.items() if p in _LITELLM for m in models]


def constraint(name: str) -> str:
    return {"claude": "files only: Read, Edit, Write, Glob, Grep; no commands, none of your own Claude settings",
            "aider": "files only: no shell commands, no commits"}[name]


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _spawn(argv: list[str], cwd: Path, env: dict[str, str], log: Path, cancel: threading.Event,
           on_line: Callable[[str], None], stdin_text: str | None = None) -> tuple[int | None, bool]:
    """Run `argv` to the end, feeding each output line to `on_line`; (return code, whether it was killed)."""
    killed = threading.Event()
    with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True) as proc:
        def watch() -> None:
            deadline = time.monotonic() + _TIMEOUT_S
            while proc.poll() is None:
                if cancel.wait(0.2) or time.monotonic() > deadline:
                    killed.set()
                    _kill(proc)
                    return

        threading.Thread(target=watch, daemon=True).start()
        if stdin_text is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except OSError:
                pass
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            for line in proc.stdout or ():
                out.write(line)
                on_line(line)
        code = proc.wait()
    return code, killed.is_set()


def run_claude(binary: str, model: str, prompt: str, worktree: Path, folder: Path, cancel: threading.Event, emit: Emit) -> CliResult:
    argv = [binary, "-p", "--model", model, "--output-format", "stream-json", "--verbose", "--restricted", "--tools", _CLAUDE_TOOLS,
            "--setting-sources", "project", "--permission-mode", "acceptEdits", "--no-session-persistence"]
    seen: dict[str, Any] = {}
    asked: dict[str, str] = {}   # tool_use id -> tool name, so a refused call can be reported as the error it is

    def on_line(line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        content = (event.get("message") or {}).get("content")
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if event.get("type") == "assistant":
            for block in blocks:
                if block.get("type") == "tool_use":
                    asked[str(block.get("id"))] = str(block.get("name"))
                    emit("tool_use", str(block.get("name")), block.get("input"))
        elif event.get("type") == "user":
            for block in blocks:
                if block.get("type") == "tool_result" and block.get("is_error"):   # e.g. Bash: no such tool, in a files-only run
                    emit("tool_error", asked.get(str(block.get("tool_use_id")), "?"), {"error": str(block.get("content"))[:150]})
        elif event.get("type") == "result":
            seen.update(event)

    try:
        code, killed = _spawn(argv, worktree, dict(os.environ), folder / "output.log", cancel, on_line, stdin_text=prompt)
    except OSError as e:
        return CliResult(False, f"could not start claude: {e}")
    wanted = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    usage = {k: v for k, v in (seen.get("usage") or {}).items() if isinstance(v, int) and k in wanted}
    cost = seen.get("total_cost_usd")
    ok = code == 0 and not killed and seen.get("is_error") is False
    summary = str(seen.get("result") or "") or ("stopped" if killed else f"claude ended with code {code} and no result")
    return CliResult(ok, summary, usage or None, float(cost) if isinstance(cost, (int, float)) else None)


_APPLIED = re.compile(r"^Applied edit to (.+?)\s*$")
_COST = re.compile(r"Cost: \$([0-9.]+) message")


def _aider_key(model: str) -> tuple[str, str] | str:
    """(env var, key) for the provider of an aider model id, or why there isn't one."""
    provider = next((p for p, prefix in _LITELLM.items() if model.startswith(prefix + "/")), None)
    key_env = keys.PROVIDER_KEY_ENV.get(provider or "")
    if provider is None or key_env is None:
        return f"aider can't run '{model}': its provider isn't one Clyde has a key for"
    key = keys.saved_key(provider) or os.environ.get(key_env)
    return (key_env, key) if key else f"no key for {provider}: run `clyde login {provider}`"


def run_aider(binary: str, model: str, prompt: str, worktree: Path, folder: Path, cancel: threading.Event, emit: Emit) -> CliResult:
    got = _aider_key(model)
    if isinstance(got, str):
        return CliResult(False, got)
    # Only this one provider's key, so a worker can't spend or leak another; the rest of the environment is kept.
    env = {k: v for k, v in os.environ.items() if k not in set(keys.PROVIDER_KEY_ENV.values())}
    env[got[0]] = got[1]
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    argv = [binary, "--model", model, "--message-file", str(folder / "prompt.txt"), "--yes-always", "--no-auto-commits",
            "--no-dirty-commits", "--no-gitignore", "--no-check-update", "--no-analytics", "--no-show-model-warnings",
            "--no-pretty", "--no-stream", "--no-suggest-shell-commands", "--no-detect-urls", "--no-auto-lint", "--no-auto-test",
            "--chat-history-file", str(folder / "aider.chat.md"), "--input-history-file", str(folder / "aider.input"),
            "--llm-history-file", str(folder / "aider.llm.log")]
    tail: list[str] = []
    cost: list[float] = []

    def on_line(line: str) -> None:
        tail.append(line)
        del tail[:-40]
        applied = _APPLIED.match(line)
        if applied:
            emit("tool_use", "Edit", {"file_path": applied.group(1)})
        priced = _COST.search(line)
        if priced:
            cost.append(float(priced.group(1)))

    try:
        code, killed = _spawn(argv, worktree, env, folder / "output.log", cancel, on_line)
    except OSError as e:
        return CliResult(False, f"could not start aider: {e}")
    summary = "".join(tail).strip()[-1500:] or ("stopped" if killed else f"aider ended with code {code} and no output")
    return CliResult(code == 0 and not killed, summary, None, cost[-1] if cost else None)
