"""`clyde -p "prompt"`: one turn without the interactive prompt, for scripts and CI.

The answer is the only thing on stdout; progress, tool calls, warnings and denials go to stderr,
so `clyde -p "..." > answer.md` and pipes stay clean. Piped stdin is added to the prompt
(`git diff | clyde -p "review this"`). Nobody is there to answer a prompt, so anything that would ask
for permission is denied and reported, and AskUserQuestion fails, telling the model there's no one
to ask. `--mode` picks the permission mode; `--output-format json` returns the answer with the
model, token usage, turns and session id. Exit status: 0 answered, 1 failed or ran out of rounds,
2 nothing to do. The session is saved like any other, so `clyde -c` can continue it interactively.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from rich.console import Console

from src.agent.agent_loop import MAX_TURNS_REPLY
from src.providers import model_ref

MODES = ("hold", "plan", "all_in")
_STDIN_LIMIT = 2_000_000   # characters of piped input taken into the prompt


def build_prompt(prompt: str, stdin: TextIO) -> str:
    """The prompt, with piped stdin appended (or used alone when the prompt is empty or "-")."""
    piped = "" if stdin.isatty() else stdin.read(_STDIN_LIMIT)
    prompt = "" if prompt.strip() == "-" else prompt.strip()
    if piped.strip() and prompt:
        return f"{prompt}\n\n<stdin>\n{piped.rstrip()}\n</stdin>"
    return prompt or piped.strip()


def run(prompt: str, *, model: str | None = None, mode: str = "hold", output_format: str = "text",
        max_turns: int = 20, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Run one headless turn; return the process exit status."""
    from src.repl.core import ClydeREPL

    out = stdout or sys.stdout
    err = Console(stderr=True)
    text = build_prompt(prompt, stdin or sys.stdin)
    if not text:
        err.print("[red]Nothing to do:[/red] give a prompt, e.g. clyde -p \"explain src/cli.py\", or pipe input in.")
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
    repl.chat(text, max_turns=max_turns)

    result, error = repl.last_result, repl.last_error
    answer = result.response_text if result is not None else ""
    ran_out = answer == MAX_TURNS_REPLY
    failed = error is not None or result is None or ran_out
    if output_format == "json":
        payload: dict[str, Any] = {
            "result": answer, "is_error": failed, "error": error or ("ran out of tool rounds" if ran_out else None),
            "model": model_ref(repl.provider, repl.model), "num_turns": result.num_turns if result else 0,
            "usage": (result.usage if result else None) or {}, "denied": denied, "session_id": repl.session.session_id,
        }
        out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    elif answer:
        out.write(answer.rstrip() + "\n")
    out.flush()
    return 1 if failed else 0
