"""git for a repository the model can write to: its own config and hooks must never run code.

Clyde runs git in the workspace on its own (context, /review, worktrees, the map). A model that can
write .git/config could otherwise plant core.fsmonitor, a hooks path or an external diff and have the next git call
run it as the user. Every workspace git call goes through here; the flags turn those hooks off for that one process.
"""

from __future__ import annotations

import os

_SAFE = ["--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
         "-c", "core.pager=cat"]


def git_cmd(*args: str) -> list[str]:
    """The argv for `git <args>` with repository-local code execution switched off. A caller that diffs also
    passes --no-ext-diff --no-textconv itself: a config-defined diff program has no global off switch."""
    return ["git", *_SAFE, *args]


def git_env() -> dict[str, str]:
    """The environment for those calls: no prompts, no pager, no external diff program (GIT_EXTERNAL_DIFF)."""
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_SSH_COMMAND"}}
    return {**env, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}
