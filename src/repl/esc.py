"""Esc cancels the running turn, like Ctrl+C.

While active, a background thread reads the terminal in cbreak mode. A lone Esc sends this
process SIGINT, so it takes exactly the path Ctrl+C does (KeyboardInterrupt in the main thread,
which also breaks out of a blocking network read). Escape sequences such as arrow keys, which
also start with Esc, are ignored. Prompts that need the keyboard mid-turn pause the watcher.
"""

from __future__ import annotations

import os
import select
import signal
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows: Ctrl+C only
    termios = tty = None  # type: ignore[assignment]

ESC = b"\x1b"
SEQUENCE_GAP = 0.05  # bytes that follow Esc this quickly belong to a key sequence (arrows, F-keys)


class EscWatcher:
    def __init__(self, stream=None) -> None:  # type: ignore[no-untyped-def]
        self._stream = stream or sys.stdin
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._saved = None

    def _usable(self) -> bool:
        try:
            return termios is not None and self._stream.isatty()
        except (AttributeError, ValueError):
            return False

    def _watch(self, fd: int) -> None:
        while not self._stop.is_set():
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                continue
            try:
                data = os.read(fd, 64)
            except OSError:
                return
            if data != ESC:
                continue
            more, _, _ = select.select([fd], [], [], SEQUENCE_GAP)
            if more:
                try:
                    os.read(fd, 64)  # the rest of an escape sequence: not a cancel
                except OSError:
                    return
                continue
            os.kill(os.getpid(), signal.SIGINT)
            return

    def start(self) -> None:
        if self._thread is not None or not self._usable():
            return
        fd = self._stream.fileno()
        try:
            self._saved = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except termios.error:
            self._saved = None
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, args=(fd,), daemon=True, name="esc-cancel")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(0.5)
        self._thread = None
        if self._saved is not None:
            try:
                termios.tcsetattr(self._stream.fileno(), termios.TCSADRAIN, self._saved)
            except termios.error:
                pass
            self._saved = None

    @contextmanager
    def active(self) -> Iterator[None]:
        """Watch for Esc for the duration of a turn or command."""
        self.start()
        try:
            yield
        finally:
            self.stop()

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Give the keyboard back (normal line input) while a prompt is open."""
        was_running = self._thread is not None
        self.stop()
        try:
            yield
        finally:
            if was_running:
                self.start()


WATCHER = EscWatcher()   # the one the REPL runs commands under; prompts pause it through this
