"""Python project checks: ruff/mypy on the files an edit touched, and the whole suite for /check.

After a successful Write/Edit/NotebookEdit of a Python file the agent loop lints just that file
before and after the change and hands the model only the problems the edit introduced, so it can
fix them in the same exchange. Tests are too slow for that; /check runs ruff + mypy + pytest.

Tools are detected, never installed: ruff runs when the project configures it or it is installed,
mypy and pytest only when configured. With uv.lock they run via `uv run --no-sync`, else from the
project's .venv, else from PATH. Off with CLYDE_CHECKS=off or {"checks": {"enabled": false}} in
~/.clyde/settings.json. The unprompted check after an edit uses only the user's own ruff on PATH unless the folder is
listed in {"trustedFolders": ["/path"]} there; /check always uses the project's tooling.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from .hooks import _read, settings_paths
from .trust import trusted

EDIT_TIMEOUT = 15      # per checker, per edit: bounds the stall a user would feel
SUITE_TIMEOUT = 600    # per checker, for /check
MAX_SHOWN = 10         # diagnostics shown per report
_MAX_MSG = 160

PY_SUFFIXES = {".py", ".pyi", ".ipynb"}   # ruff lints notebooks too; mypy only .py/.pyi
_MYPY_SUFFIXES = {".py", ".pyi"}


class Problem(NamedTuple):
    path: str
    line: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


@dataclass
class Tooling:
    """The project's detected checkers: tool name -> argv prefix that runs it."""
    root: Path
    tools: dict[str, list[str]] = field(default_factory=dict)
    via: str = "PATH"
    mypy_files_configured: bool = False


def checks_enabled() -> bool:
    if os.environ.get("CLYDE_CHECKS", "").lower() in {"off", "0", "false", "no"}:
        return False
    for path in settings_paths():
        try:
            data = _read(path)
        except (OSError, ValueError):
            continue
        section = data.get("checks") if isinstance(data, dict) else None
        if isinstance(section, dict) and section.get("enabled") is False:
            return False
    return True


def _system_tool(name: str, root: Path) -> list[str] | None:
    """A tool installed on the user's PATH, never one that lives inside the project."""
    exe = shutil.which(name)
    if not exe:
        return None
    try:
        return None if Path(exe).resolve().is_relative_to(root.resolve()) else [exe]
    except OSError:
        return None


def _pyproject(root: Path) -> dict:
    try:
        return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ponytail: Python only; another language gets its own detector returning a Tooling
def detect(root: Path, auto: bool = False) -> Tooling | None:
    """The Python tooling configured/installed for the project at root, or None if it isn't one.

    `auto` is for checks nobody asked for (after an edit, before the permission prompt). Running a project's own
    `.venv/bin/ruff`, `uv run`, or mypy (its config can load plugins from the project) would run the project's code,
    so an untrusted project gets only the user's own ruff from PATH. `/check` is a command the user typed: full tooling."""
    if not any((root / f).is_file() for f in ("pyproject.toml", "setup.py", "setup.cfg")):
        return None
    if auto and not trusted(root):
        ruff = _system_tool("ruff", root)
        return Tooling(root, tools={"ruff": ruff} if ruff else {}, via="PATH")
    tool_cfg = _pyproject(root).get("tool", {})
    venv_bin = root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    use_uv = (root / "uv.lock").is_file() and shutil.which("uv") is not None
    wanted = {
        "ruff": True,  # zero-config linter: run it whenever it's installed
        "mypy": "mypy" in tool_cfg or (root / "mypy.ini").is_file() or (root / ".mypy.ini").is_file(),
        "pytest": "pytest" in tool_cfg or (root / "pytest.ini").is_file() or (root / "tests").is_dir(),
    }
    found = Tooling(root, via="uv run" if use_uv else ".venv" if venv_bin.is_dir() else "PATH",
                    mypy_files_configured=bool(tool_cfg.get("mypy", {}).get("files")))
    for name, configured in wanted.items():
        if not configured:
            continue
        local = venv_bin / name
        if use_uv and (local.exists() or shutil.which(name)):
            found.tools[name] = ["uv", "run", "--no-sync", name]
        elif local.exists():
            found.tools[name] = [str(local)]
        elif exe := shutil.which(name):
            found.tools[name] = [exe]
    return found


_RUFF_RE = re.compile(r"^(.+?):(\d+):\d+: (\S+?):? (?:\[\*\] )?(.*)$")
_MYPY_RE = re.compile(r"^(.+?):(\d+):(?:\d+:)? error: (.*?)(?:  \[([\w-]+)\])?$")


def parse_ruff(out: str) -> list[Problem]:
    return [Problem(m[1], int(m[2]), m[3], m[4][:_MAX_MSG]) for line in out.splitlines() if (m := _RUFF_RE.match(line.strip()))]


def parse_mypy(out: str) -> list[Problem]:
    return [Problem(m[1], int(m[2]), m[4] or "error", m[3][:_MAX_MSG]) for line in out.splitlines() if (m := _MYPY_RE.match(line.strip()))]


def _run(argv: list[str], root: Path, timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "NO_COLOR": "1"})
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout:g}s"
    except OSError as e:
        return -1, str(e)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _rel(path: str, root: Path) -> str:
    try:
        return (root / path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path


def lint_files(tooling: Tooling, files: list[Path], timeout: float = EDIT_TIMEOUT) -> list[Problem]:
    """ruff (and mypy, if configured) on just these files; problems in other files are dropped."""
    root, problems = tooling.root, []
    targets = [_rel(str(f), root) for f in files]
    if "ruff" in tooling.tools:
        _, out = _run([*tooling.tools["ruff"], "check", "--no-fix", "--output-format=concise", *targets], root, timeout)
        problems += parse_ruff(out)
    mypy_targets = [t for t, f in zip(targets, files) if f.suffix in _MYPY_SUFFIXES]
    if "mypy" in tooling.tools and mypy_targets:
        _, out = _run([*tooling.tools["mypy"], "--no-error-summary", *mypy_targets], root, timeout)
        problems += parse_mypy(out)
    wanted = set(targets)
    return [p._replace(path=_rel(p.path, root)) for p in problems if _rel(p.path, root) in wanted]


def new_problems(before: list[Problem], after: list[Problem]) -> list[Problem]:
    """Problems in `after` that `before` didn't have, matched on file+code+message (lines shift)."""
    remaining = Counter((p.path, p.code, p.message) for p in before)
    fresh = []
    for p in after:
        key = (p.path, p.code, p.message)
        if remaining[key]:
            remaining[key] -= 1
        else:
            fresh.append(p)
    return fresh


def format_problems(problems: list[Problem], limit: int = MAX_SHOWN) -> str:
    lines = [str(p) for p in problems[:limit]]
    if len(problems) > limit:
        lines.append(f"(+{len(problems) - limit} more)")
    return "\n".join(lines)


class EditCheck:
    """Baseline one edited file before a tool call, then report what the edit introduced."""

    def __init__(self, root: Path, path: Path) -> None:
        self.tooling = detect(root, auto=True)
        self.path = path
        self.before: list[Problem] = []
        if self.tooling and self.tooling.tools and path.is_file():
            self.before = lint_files(self.tooling, [path])

    def report(self) -> str | None:
        if not self.tooling or not self.tooling.tools or not self.path.is_file():
            return None
        fresh = new_problems(self.before, lint_files(self.tooling, [self.path]))
        if not fresh:
            return None
        return f"{len(fresh)} new problem(s) after this edit; fix them:\n{format_problems(fresh)}"


def edit_check_for(tool_name: str, tool_input: dict, root: Path) -> EditCheck | None:
    """An EditCheck when this call writes a Python file and checks are on, else None."""
    raw = tool_input.get("notebook_path" if tool_name == "NotebookEdit" else "file_path")
    if tool_name not in {"Write", "Edit", "NotebookEdit"} or not isinstance(raw, str):
        return None
    path = Path(raw)
    if path.suffix not in PY_SUFFIXES or not checks_enabled():
        return None
    return EditCheck(root, path if path.is_absolute() else root / path)


def _pytest_summary(out: str) -> list[str]:
    failed = [line for line in out.splitlines() if line.startswith(("FAILED ", "ERROR "))]
    tail = next((line.strip("= ") for line in reversed(out.splitlines()) if line.strip()), "")
    return [*failed[:MAX_SHOWN], *([f"(+{len(failed) - MAX_SHOWN} more)"] if len(failed) > MAX_SHOWN else []), tail]


def run_suite(root: Path, timeout: float = SUITE_TIMEOUT) -> str:
    """ruff + mypy + pytest over the whole project, as a compact summary for /check."""
    tooling = detect(root)
    if tooling is None:
        return "No Python project here (no pyproject.toml, setup.py or setup.cfg)."
    if not tooling.tools:
        return "No ruff, mypy or pytest found for this project (checks never install tools)."
    lines = [f"Checks (via {tooling.via}):"]
    for name, parse, args in (("ruff", parse_ruff, ["check", "--no-fix", "--output-format=concise", "."]),
                              ("mypy", parse_mypy, ["--no-error-summary"] + ([] if tooling.mypy_files_configured else ["."])),
                              ("pytest", None, ["-q"])):
        if name not in tooling.tools:
            continue
        code, out = _run([*tooling.tools[name], *args], root, timeout)
        if parse is None:
            lines.append(f"{'✓' if code == 0 else '✗'} pytest: " + "\n    ".join(_pytest_summary(out)))
            continue
        problems = parse(out)
        if code == 0 and not problems:
            lines.append(f"✓ {name}: clean")
        elif problems:
            lines.append(f"✗ {name}: {len(problems)} problem(s)\n    " + format_problems(problems).replace("\n", "\n    "))
        else:
            lines.append(f"✗ {name}: exit {code}: " + (out.strip().splitlines() or [""])[-1][:_MAX_MSG])
    return "\n".join(lines)
