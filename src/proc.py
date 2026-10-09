"""subprocess.run that also ends the child's own children when it is interrupted or times out."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def run_group(argv: list[str], *, timeout: float | None = None, **kwargs: Any) -> subprocess.CompletedProcess:
    """Like `subprocess.run`, but the child leads its own process group and the whole group is killed on Ctrl-C or timeout.

    `subprocess.run` kills only the direct child, so `bash -c "server &"` would outlive a Ctrl-C.
    """
    with subprocess.Popen(argv, start_new_session=True, **kwargs) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except BaseException as exc:   # KeyboardInterrupt included: that is the point
            _kill_group(proc)
            if isinstance(exc, subprocess.TimeoutExpired):
                exc.stdout, exc.stderr = proc.communicate()
            raise
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
