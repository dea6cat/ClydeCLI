"""Live HTTP responses, so a stop can close them all at once.

A flag can't wake a thread blocked in a C-level socket read; the socket has to be closed. Every live response
registers here so abort_all_connections() can close them all at once. A close mid-read raises OSError/ValueError in
the blocked thread, which the provider HTTP helpers turn into their cancel error when the caller asked to cancel.
"""
from __future__ import annotations

import threading

_active: set = set()
_lock = threading.Lock()


def register(resp) -> None:
    with _lock:
        _active.add(resp)


def unregister(resp) -> None:
    with _lock:
        _active.discard(resp)


def abort_all_connections() -> None:
    """Close every live HTTP response so any thread blocked reading one raises at once."""
    with _lock:
        conns = list(_active)
        _active.clear()
    for resp in conns:
        try:
            resp.close()
        except Exception:   # already closed or half-torn-down: closing is all that was wanted
            pass
