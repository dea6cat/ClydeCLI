"""Queue, steer and stop for one running Clyde, shared by every front end that drives a turn from another
thread (the ACP server, `clyde luv bonnie`).

Turns run on the main thread. Stop reaches it the way Esc does: the open connections are aborted and the
process sends itself SIGINT, which surfaces as KeyboardInterrupt in the turn. Steer text is picked up by the
agent loop at its next round boundary, between a model reply's tool results and the next model call.
"""
from __future__ import annotations

import collections
import os
import queue
import signal
import threading


def interrupt_turn() -> None:
    """Cancel the turn running on the main thread, exactly as Esc does."""
    from src.providers.base import abort_all_connections

    abort_all_connections()
    os.kill(os.getpid(), signal.SIGINT)


class RunControl:
    def __init__(self) -> None:
        self.prompts: queue.Queue[str | None] = queue.Queue()   # run in order, one at a time, by whoever owns the main thread
        self.busy = False                                        # a turn is running; only then does stop interrupt anything
        self._steer: collections.deque[str] = collections.deque()
        self._lock = threading.Lock()

    def queue(self, text: str) -> None:
        """Run `text` as its own turn after the current one and anything queued before it."""
        self.prompts.put(text)

    def steer(self, text: str) -> None:
        """Hand `text` to the running turn at its next round boundary."""
        self._steer.append(text)

    def take_steer(self) -> str | None:
        """All pending steering as one message, or None. Called by the agent loop."""
        with self._lock:
            texts = [self._steer.popleft() for _ in range(len(self._steer))]
        return "\n\n".join(texts) if texts else None

    def stop(self) -> None:
        """Cancel the running turn and drop steering meant for it. Queued prompts stay queued."""
        self._steer.clear()
        if self.busy:
            interrupt_turn()
