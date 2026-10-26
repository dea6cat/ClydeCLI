"""`clyde -p "prompt"`: one turn without the interactive prompt, for scripts and CI.

The answer is the only thing on stdout; progress, tool calls, warnings and denials go to stderr,
so `clyde -p "..." > answer.md` and pipes stay clean. Piped stdin is added to the prompt
(`git diff | clyde -p "review this"`). Nobody is there to answer a prompt, so anything that would ask
for permission is denied and reported, and AskUserQuestion fails, telling the model there's no one
to ask. `--mode` picks the permission mode; `--output-format json` returns the answer with the
model, token usage, turns and session id; `stream-json` prints each message (the session file's shape) as one JSON
line while the turn runs, then that result line with `"type": "result"`, so a harness can read the whole trajectory, even
of a run it had to kill. Exit status: 0 answered, 1 failed or ran out of rounds,
2 nothing to do. The session is saved like any other, so `clyde -c` can continue it interactively.
"""

from __future__ import annotations

import io
import json
import select
import signal
import sys
from typing import Any, TextIO

from rich.console import Console

from src.agent.agent_loop import MAX_TOKENS_REPLY
from src.agent.conversation import message_dict
from src.providers import model_ref

MODES = ("hold", "plan", "all_in")
_STDIN_LIMIT = 2_000_000   # characters of piped input taken into the prompt
_STDIN_WAIT = 0.5          # seconds a prompt waits for piped input to start


def _piped(stdin: TextIO, wait: float | None) -> str:
    """Piped stdin, or "" for a terminal. With `wait`, stdin that stays silent that long is ignored:
    cron, `ssh` without -n and some CI runners hand over a pipe nobody ever closes, and reading it
    would hang forever."""
    if stdin.isatty():
        return ""
    try:
        fd = stdin.fileno()
    except (OSError, ValueError, io.UnsupportedOperation):
        return stdin.read(_STDIN_LIMIT)          # an in-memory stream: nothing to wait on
    if wait is not None and sys.platform != "win32":   # select() can't watch pipes on Windows
        ready, _, _ = select.select([fd], [], [], wait)
        if not ready:
            return ""
    return stdin.read(_STDIN_LIMIT)


def build_prompt(prompt: str, stdin: TextIO) -> str:
    """The prompt, with piped stdin appended (or used alone when the prompt is empty or "-", in which
    case stdin is waited for as long as it takes)."""
    prompt = "" if prompt.strip() == "-" else prompt.strip()
    piped = _piped(stdin, _STDIN_WAIT if prompt else None)
    if piped.strip() and prompt:
        return f"{prompt}\n\n<stdin>\n{piped.rstrip()}\n</stdin>"
    return prompt or piped.strip()


def _interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


class _OutOfTime(KeyboardInterrupt):
    """--time-limit ran out: an interrupt like SIGTERM, told apart in the result line."""


def _out_of_time(_signum: int, _frame: Any) -> None:
    raise _OutOfTime


def run(prompt: str, *, model: str | None = None, mode: str = "hold", output_format: str = "text",
        max_turns: int = 20, time_limit: float | None = None, max_tokens: int | None = None,
        stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Run one headless turn; return the process exit status."""
    from src.repl.core import ClydeREPL

    out = stdout or sys.stdout
    err = Console(stderr=True, soft_wrap=True)   # one log line per event, never wrapped
    text = build_prompt(prompt, stdin or sys.stdin)
    if not text:
        err.print("[red]Nothing to do:[/red] give a prompt, e.g. clyde -p \"explain src/cli.py\", or pipe input in.")
        return 2
    if time_limit and not hasattr(signal, "SIGALRM"):   # Windows has no alarm signal
        err.print("[red]--time-limit isn't supported on Windows[/red]; use the caller's timeout, which sends an interrupt.")
        return 2
    repl = ClydeREPL(model=model, console=err, headless=True)
    repl._set_mode(mode)
    denied: list[str] = []

    def deny(tool_name: str, message: str, suggestion: str | None) -> tuple[bool, bool]:
        denied.append(tool_name)
        err.print(f"[yellow]Denied {tool_name}[/yellow] (clyde -p can't ask; try --mode all_in, or an allow rule): ",
                  end="")
        err.print(message, markup=False, highlight=False)
        return False, False

    repl.tool_context.permission_handler = deny
    repl.tool_context.ask_user = None
    written: set[int] = set()

    def stream_messages(_event: Any = None) -> None:
        # Called on each tool event: the assistant message with its tool calls is in by then, its results land on the
        # next call, so a run killed mid-tool loses only that tool's result.
        for msg in repl.session.conversation.messages:
            if id(msg) not in written:
                written.add(id(msg))
                out.write(json.dumps({"type": "message", "message": message_dict(msg)}, ensure_ascii=False) + "\n")
                out.flush()

    if output_format == "stream-json":
        repl.on_event_hook = stream_messages
    # A CI cancel or a harness timeout sends SIGTERM: as an interrupt it reaches the running command, whose process group is
    # then killed (src/system/proc.py), and the result line still says what happened.
    previous = signal.signal(signal.SIGTERM, _interrupt)
    previous_alarm = signal.signal(signal.SIGALRM, _out_of_time) if time_limit else None
    if time_limit:
        signal.setitimer(signal.ITIMER_REAL, time_limit)
    try:
        repl.chat(text, max_turns=max_turns, max_tokens=max_tokens)
    except _OutOfTime:
        repl.last_error = f"time limit reached ({time_limit:g}s)"
    except KeyboardInterrupt:
        repl.last_error = "interrupted"
    finally:
        if time_limit:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_alarm)
        signal.signal(signal.SIGTERM, previous)

    result, error = repl.last_result, repl.last_error
    answer = result.response_text if result is not None else ""
    ran_out = bool(result is not None and result.ran_out)
    over_budget = answer == MAX_TOKENS_REPLY
    failed = error is not None or result is None or ran_out or over_budget
    if output_format in ("json", "stream-json"):
        payload: dict[str, Any] = {
            "result": answer, "is_error": failed,
            "error": error or ("ran out of tool rounds" if ran_out else f"token budget reached ({max_tokens})" if over_budget else None),
            "model": model_ref(repl.provider, repl.model), "num_turns": result.num_turns if result else 0,
            "usage": (result.usage if result else None) or {}, "denied": denied, "session_id": repl.session.session_id,
        }
        if output_format == "stream-json":
            stream_messages()
            payload = {"type": "result", **payload}
        out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    elif answer:
        out.write(answer.rstrip() + "\n")
    out.flush()
    return 1 if failed else 0
