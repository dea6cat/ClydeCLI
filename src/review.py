"""`/review` and `clyde review`: a read-only code review of uncommitted changes, one commit, or a branch against its base.

The diff comes from git (arguments only, never a shell) and is capped per file, smallest first, so a huge change cannot
overflow the context; whatever is left out is named in the prompt, never dropped silently.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

MAX_DIFF_CHARS = 60_000
_GIT_TIMEOUT = 30
_USAGE = "usage: /review [commit SHA | base BRANCH]"
_FILE_START = re.compile(r"^(?=diff --git )", re.MULTILINE)

_PROMPT = """Review the code change below. Do not edit any file; this is a read-only review.

Report, most serious first: bugs and wrong behaviour, security problems, missing error handling, missing or weak tests,
then smaller issues. Give each finding as `file:line - problem - suggested fix`. Say so plainly if you find nothing serious.
Read the surrounding files when the diff alone is not enough to judge a change.

Change under review: {what}

{diff}
"""


class ReviewError(ValueError):
    """The review cannot start: bad target, not a git repository, or nothing to review."""


def parse_target(args: str) -> tuple[str, str]:
    """('uncommitted', '') for no arguments, ('commit', SHA) or ('base', BRANCH)."""
    words = args.split()
    if not words:
        return "uncommitted", ""
    if len(words) != 2 or words[0] not in ("commit", "base"):
        raise ReviewError(_USAGE)
    if words[1].startswith("-"):
        raise ReviewError(f"not a commit or branch name: {words[1]}")
    return words[0], words[1]


def _git(cwd: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_GIT_TIMEOUT)
    except FileNotFoundError as e:
        raise ReviewError("git is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise ReviewError(f"git {args[0]} took longer than {_GIT_TIMEOUT}s") from e
    if done.returncode != 0:
        lines = done.stderr.strip().splitlines()
        raise ReviewError(lines[-1] if lines else f"git {args[0]} failed")
    return done.stdout


def _verified(cwd: Path, ref: str) -> str:
    """The ref as a full commit id, or a ReviewError when it names nothing."""
    try:
        return _git(cwd, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()
    except ReviewError as e:
        raise ReviewError(f"no such commit or branch: {ref}") from e


def _raw_diff(kind: str, value: str, cwd: Path) -> tuple[str, str, str]:
    """(what is under review, the raw diff text, a note kept outside the size cap)."""
    if kind == "commit":
        sha = _verified(cwd, value)
        return f"commit {sha[:12]}", _git(cwd, "show", "--format=%h %s%n%n%b", sha, "--"), ""
    if kind == "base":
        base = _verified(cwd, value)
        return f"the current branch against {value}", _git(cwd, "diff", f"{base}...HEAD", "--"), ""
    _git(cwd, "rev-parse", "--is-inside-work-tree")
    diff = _git(cwd, "diff", "HEAD", "--")
    names = [n for n in _git(cwd, "ls-files", "--others", "--exclude-standard").splitlines() if n]
    note = "New files git does not track yet (not in the diff; read them): " + ", ".join(names) if names else ""
    return "uncommitted changes", diff, note


def cap_diff(diff: str, limit: int = MAX_DIFF_CHARS) -> str:
    """The diff cut to `limit` characters by whole files, smallest first; a final line names the files left out."""
    if len(diff) <= limit:
        return diff
    head, *files = _FILE_START.split(diff)
    kept: list[str] = []
    left_out: list[str] = []
    used = len(head)
    for chunk in sorted(files, key=len):
        if used + len(chunk) <= limit:
            kept.append(chunk)
            used += len(chunk)
        else:
            left_out.append(chunk.split("\n", 1)[0].removeprefix("diff --git "))
    return head + "".join(kept) + f"\n[{len(left_out)} file(s) left out for size; read them with Read and git diff: {', '.join(left_out)}]"


def build_review_prompt(args: str, cwd: str | Path) -> str:
    """The prompt for a review of `args` (see parse_target) in the git repository at `cwd`."""
    kind, value = parse_target(args)
    what, diff, note = _raw_diff(kind, value, Path(cwd))
    if not diff.strip() and not note:
        raise ReviewError("nothing to review: " + ("no uncommitted changes" if kind == "uncommitted" else "the diff is empty"))
    body = f"```diff\n{cap_diff(diff).rstrip()}\n```" if diff.strip() else ""
    return _PROMPT.format(what=what, diff="\n\n".join(part for part in (body, note) if part))
