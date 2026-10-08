"""Laya, ClydeCLI's bundled local decision model (github.com/NandhaKishorM/laya): typed choice,
score and noul judgments computed on this machine, no key, no network.

Laya's answers are inputs to policy that lives in Clyde's code, never the policy itself. Only a
judgment measured to separate cleanly acts: the stuck check (a noul) re-deals a cardShuffle turn.
Difficulty (a score, upstream's weaker area) starts in shadow mode: shown and traced, not acted on,
until traced turns show it separates easy turns from hard ones (card_shuffle.difficulty_verdict).
Laya never decides permissions.

Weights load only from the local cache (Laya pins their revision; about 800 MB, fetched by
`clyde setup` after a yes), in a background thread so no turn waits for the ~17 s cold load.
Every entry point returns None or False instead of raising.
"""
from __future__ import annotations

import os
import threading
import warnings
from typing import Any

# Never download from inside Clyde: a missing model is reported, and `clyde setup` fetches it.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# Laya pins nothing unless asked; without this it fetches the Hub's newest revision, which cached() never finds.
os.environ.setdefault("LAYA_REVISION", "reviewed")
# Laya's own calibration warnings would print into the middle of a turn; its answers are advisory anyway.
warnings.filterwarnings("ignore", module=r"laya(\.|$)")

REPO = "convaiinnovations/laya"
DOWNLOAD_SIZE = "about 800 MB"
_WARMUP = ({"request": "hello"}, {"warmup": {"type": "noul", "instructions": "Is `request` a greeting?"}})

_lock = threading.Lock()
_thread: threading.Thread | None = None
_router: Any = None
_error = ""


def cached() -> bool:
    """Whether Laya's pinned weights are in the local Hugging Face cache (checked without loading torch)."""
    try:
        from huggingface_hub import try_to_load_from_cache
        from laya import PINNED_REVISIONS

        return isinstance(try_to_load_from_cache(REPO, "model.safetensors", revision=PINNED_REVISIONS[REPO]), str)
    except Exception:
        return False


def _load() -> None:
    global _router, _error
    try:
        from laya import Router

        router = Router(preload=False)
        router.predict(*_WARMUP)   # loads the checkpoint now, not on the first real question
        _router = router
    except Exception as e:  # a broken install or cache must not break Clyde
        _error = f"{type(e).__name__}: {e}"[:200]


def warm() -> None:
    """Start loading Laya in the background if its weights are cached; no-op if started already."""
    global _thread
    with _lock:
        if _thread is not None or not cached():
            return
        _thread = threading.Thread(target=_load, name="laya-warm", daemon=True)
        _thread.start()


def wait_ready(timeout: float) -> bool:
    """Start loading if needed and wait up to `timeout` seconds; whether Laya can answer now."""
    warm()
    thread = _thread
    if _router is None and thread is not None:
        thread.join(timeout)
    return _router is not None


def status() -> str:
    """ready, loading, not started, not downloaded, or the load error."""
    if _router is not None:
        return "ready"
    if _error:
        return f"failed to load: {_error}"
    if _thread is not None:
        return "loading"
    return "not started" if cached() else "not downloaded"


def ask(state: Any, questions: dict[str, dict]) -> dict[str, dict] | None:
    """Laya's answers keyed like `questions`, or None while it is loading, unavailable or failing."""
    if _router is None:
        return None
    try:
        return _router.predict(state, questions)["answers"]
    except Exception:
        return None
