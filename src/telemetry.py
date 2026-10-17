"""Opt-in, anonymous usage counters.

Off until the user turns it on (`clyde telemetry on`). Every event is checked against SCHEMA before it is written: a
field is a count, a flag or one of a fixed set of words, so a prompt, a path, a model's name or an error message cannot
be sent even by mistake. Events wait in a local file (`clyde telemetry show` prints exactly that file) and go out in one
batch to an HTTPS endpoint (DEFAULT_ENDPOINT, the Worker in worker/, unless the user set another), and only while telemetry is on. `off` deletes the queue.
CLYDE_TELEMETRY=off and DO_NOT_TRACK=1 always win. Nothing here can raise into a turn.
"""
from __future__ import annotations

import atexit
import json
import os
import platform
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from src.config import clyde_home

DEFAULT_ENDPOINT = "https://clyde-telemetry.bonnieclydesub.workers.dev/"   # worker/: a Cloudflare Worker that keeps daily counters only
QUEUE_LIMIT = 500
BATCH_TIMEOUT_S = 3

TOKENS = {"<1k", "1-2k", "2-4k", "4-8k", "8-16k", ">16k"}
SIZES = {"<=2B", "2-4B", "4-9B", "9-30B", ">30B", "unknown"}
KINDS = {"local", "hosted", "custom", "mixed", "none"}


# What a Bonnie user did: one word per action, counted only when it succeeded. src/bonnie/server.py maps each route to one of these.
BONNIE_FEATURES = {"prompt", "steer", "stop", "permission", "vote", "feedback", "theme", "theme_image", "theme_image_remove",
                   "artifact_reveal", "session_new", "session_open", "session_delete", "session_restore", "session_pin", "mode", "model",
                   "project", "dir_create", "attachment", "provider_connect", "provider_disconnect", "provider_custom",
                   "automation_create", "automation_pause", "automation_resume", "automation_delete", "automation_run"}


def _provider_words() -> set[str]:
    """Built-in provider names only: PROVIDER_KEY_ENV also holds the names of the user's own custom providers, which must never be sent."""
    from src.providers.keys import _BUILT_IN
    return {*_BUILT_IN, "custom", "cardShuffle"}


def _provider(value: Any) -> bool:
    return value in _provider_words()


# event -> field -> a set of allowed words, the type int (a count from 0 to 10 million), bool, or a check function.
SCHEMA: dict[str, dict[str, Any]] = {
    "run": {"surface": {"repl", "print", "bonnie", "acp"}, "outcome": {"done", "max_turns", "stuck"},
            "turns": int, "tool_calls": int, "tool_errors": int, "repeats_refused": int,
            "first_input_tokens": TOKENS, "index": {"names", "full", "none"}, "provider_kind": KINDS, "model_size": SIZES},
    "provider_error": {"provider": _provider, "kind": {"http_400", "http_401", "http_402", "http_403", "http_404", "http_429",
                                                     "http_5xx", "timeout", "connection", "ssl", "stalled", "other"}},
    "tune": {"outcome": {"kept", "applied", "declined", "failed"}, "memory_saved_pct": {"0", "1-5", "5-15", ">15"}},
    "bonnie_start": {},
    "bonnie_use": {"feature": BONNIE_FEATURES},
}
_surface = "repl"


def set_surface(name: str) -> None:
    global _surface
    _surface = name


def surface() -> str:
    return _surface


# --- consent and identity --------------------------------------------------

def _folder():
    return clyde_home() / "telemetry"


def _state_file():
    return clyde_home() / "telemetry.json"


def _read_state() -> dict:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(update: dict) -> None:
    _state_file().parent.mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps({**_read_state(), **update}, indent=2), encoding="utf-8")


def overridden() -> str | None:
    """Why the environment forces telemetry off, or None."""
    if os.environ.get("CLYDE_TELEMETRY", "").lower() in ("off", "0", "false", "no"):
        return "CLYDE_TELEMETRY=off"
    if os.environ.get("DO_NOT_TRACK", "").lower() in ("1", "true", "yes"):
        return "DO_NOT_TRACK"
    return None


def enabled() -> bool:
    return overridden() is None and (_read_state().get("enabled") is True or os.environ.get("CLYDE_TELEMETRY", "").lower() == "on")


def endpoint() -> str:
    return os.environ.get("CLYDE_TELEMETRY_URL") or str(_read_state().get("url") or "") or DEFAULT_ENDPOINT


def valid_endpoint(url: str) -> bool:
    """https only; plain http just for this machine, so the reference receiver can be tried."""
    parts = urllib.parse.urlparse(url)
    return bool(parts.hostname) and (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")))


def turn_on() -> None:
    _write_state({"enabled": True, "id": _read_state().get("id") or uuid.uuid4().hex})


def asked() -> bool:
    return _read_state().get("asked") is True


def ask_once(console: Any, confirm: Callable[..., bool]) -> None:
    """The first-run question, shown only when there is an endpoint to send to and the user was never asked."""
    if asked() or overridden() or not endpoint():
        return
    console.print("\n[bold]Anonymous usage counters[/bold]: counts and fixed words only (how many tool calls failed, which size of model, "
                  "which kind of provider error), never prompts, paths, model names or error text. "
                  "`clyde telemetry show` prints exactly what is queued, and `clyde telemetry off` stops it.")
    if confirm("Share them to help improve Clyde?", default=False):
        turn_on()
    _write_state({"asked": True})


def turn_off() -> None:
    """Disable, and delete what was queued: opting out should not leave the data behind."""
    _write_state({"enabled": False})
    clear_queue()


def set_endpoint(url: str) -> None:
    _write_state({"url": url})


def reset_id() -> None:
    _write_state({"id": uuid.uuid4().hex})


# --- recording -------------------------------------------------------------

def _size_bucket(billions: float | None) -> str:
    if billions is None:
        return "unknown"
    return "<=2B" if billions <= 2 else "2-4B" if billions <= 4 else "4-9B" if billions <= 9 else "9-30B" if billions <= 30 else ">30B"


def token_bucket(tokens: int) -> str:
    return "<1k" if tokens < 1000 else "1-2k" if tokens < 2000 else "2-4k" if tokens < 4000 else "4-8k" if tokens < 8000 else "8-16k" if tokens < 16000 else ">16k"


def saved_bucket(pct: float) -> str:
    return "0" if pct <= 0 else "1-5" if pct <= 5 else "5-15" if pct <= 15 else ">15"


def describe(provider: Any, model: str) -> tuple[str, str]:
    """(provider_kind, model_size) for a provider and model: words from fixed sets, never the names themselves."""
    try:
        from src.providers import model_size
        from src.providers.keys import PROVIDER_KEY_ENV
        name = getattr(provider, "name", "")
        kind = ("mixed" if name == "cardShuffle" else "local" if name in ("ollama", "lmstudio", "mlx") and getattr(provider, "api_key", None) is None
                else "hosted" if name in PROVIDER_KEY_ENV or name == "ollama" else "custom")
        return kind, _size_bucket(model_size.billions(provider, model))
    except Exception:
        return "custom", "unknown"


def _ram_bucket() -> int:
    try:
        from src.providers.ollama import _total_ram_bytes
        gb = _total_ram_bytes() / 2 ** 30
    except Exception:
        return 0
    return max((b for b in (4, 8, 16, 32, 64, 128, 256) if gb >= b), default=0)


def _common() -> dict:
    from src import __version__
    machine = platform.machine().lower()
    return {"v": __version__, "id": _read_state().get("id", ""), "os": sys.platform if sys.platform in ("darwin", "linux", "win32") else "other",
            "arch": machine if machine in ("arm64", "x86_64", "aarch64", "amd64") else "other",
            "py": f"{sys.version_info.major}.{sys.version_info.minor}", "ram_gb": _ram_bucket(),
            "day": datetime.now(timezone.utc).date().isoformat()}


def _valid(event: str, fields: dict) -> bool:
    schema = SCHEMA.get(event)
    if schema is None or set(fields) - set(schema):
        return False
    for name, value in fields.items():
        rule = schema[name]
        ok = (value in rule if isinstance(rule, set) else
              rule(value) if callable(rule) and rule not in (int, bool) else
              isinstance(value, bool) if rule is bool else
              isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000_000)
        if not ok:
            return False
    return True


def schema_json() -> dict:
    """SCHEMA as plain data (words as sorted lists, counts as "int", flags as "bool"), for the Worker that re-checks every event.

    `_common` lists the fields every event carries; worker/schema.json is this output and a test keeps the two equal.
    """
    def rule(r: Any) -> Any:
        if isinstance(r, set):
            return sorted(r)
        if r in (int, bool):
            return r.__name__
        if r is _provider:
            return sorted(_provider_words())
        raise ValueError(f"no plain-data form for {r!r}")

    common = {"os": ["darwin", "linux", "other", "win32"], "arch": ["aarch64", "amd64", "arm64", "other", "x86_64"],
              "ram_gb": [0, 4, 8, 16, 32, 64, 128, 256]}
    return {"_common": common, **{event: {field: rule(r) for field, r in fields.items()} for event, fields in SCHEMA.items()}}


def record(event: str, **fields: Any) -> bool:
    """Queue an event when telemetry is on and the event fits SCHEMA. True when it was queued. Never raises."""
    try:
        if not enabled() or not _valid(event, fields):
            return False
        _folder().mkdir(parents=True, exist_ok=True)
        queue = _folder() / "queue.jsonl"
        lines = queue.read_text(encoding="utf-8").splitlines() if queue.exists() else []
        lines = (lines + [json.dumps({"event": event, **fields, **_common()}, sort_keys=True)])[-QUEUE_LIMIT:]
        queue.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _flush_at_exit()
        return True
    except Exception:
        return False


def queued() -> list[dict]:
    try:
        return [json.loads(line) for line in (_folder() / "queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def clear_queue() -> None:
    try:
        (_folder() / "queue.jsonl").unlink()
    except OSError:
        pass


def provider_error_kind(error: Any) -> str:
    status, text = getattr(error, "status", None), str(error).lower()
    if isinstance(status, int):
        return {400: "http_400", 401: "http_401", 402: "http_402", 403: "http_403", 404: "http_404", 429: "http_429"}.get(
            status, "http_5xx" if 500 <= status < 600 else "other")
    for word, kind in (("certificate", "ssl"), ("ssl", "ssl"), ("no response", "stalled"), ("stalled", "stalled"),
                       ("timed out", "timeout"), ("timeout", "timeout"), ("connection", "connection")):
        if word in text:
            return kind
    return "other"


def provider_error(error: Any) -> None:
    name = getattr(error, "provider", "")
    record("provider_error", provider=name if _provider(name) else "custom", kind=provider_error_kind(error))


# --- sending ---------------------------------------------------------------

def flush() -> tuple[bool, str]:
    """Send the queue as one batch. (sent, why not). The queue is deleted only after the server accepted it."""
    try:
        if not enabled():
            return False, "telemetry is off"
        url = endpoint()
        if not url:
            return False, "no endpoint is set, so nothing leaves this machine"
        if not valid_endpoint(url):
            return False, "the endpoint must be https"
        events = queued()
        if not events:
            return False, "nothing queued"
        request = urllib.request.Request(url, data=json.dumps({"events": events}).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "clyde-telemetry"})
        with urllib.request.urlopen(request, timeout=BATCH_TIMEOUT_S) as response:
            if not 200 <= response.status < 300:
                return False, f"the server answered {response.status}"
        clear_queue()
        return True, f"sent {len(events)} event{'s' * (len(events) != 1)}"
    except Exception as e:
        return False, f"could not send: {type(e).__name__}"


_registered = False


def _flush_at_exit() -> None:
    global _registered
    if not _registered and endpoint():
        _registered = True
        atexit.register(flush)


# --- the `clyde telemetry` command ----------------------------------------

def command(console: Any, action: str, value: str | None = None) -> int:
    """status | on | off | show | send | endpoint [URL] | reset-id."""
    def status() -> None:
        why, url = overridden(), endpoint()
        console.print(f"Telemetry is [bold]{'ON' if enabled() else 'off'}[/bold]" + (f" (forced off by {why})" if why else ""))
        console.print(f"  endpoint: {url or 'none set, so nothing leaves this machine'}")
        console.print(f"  queued:   {len(queued())} event(s); `clyde telemetry show` prints exactly what would be sent")

    if action == "on":
        if overridden():
            console.print(f"[yellow]Not turned on:[/yellow] {overridden()} is set.")
            return 1
        turn_on()
        console.print("Telemetry is on. Only counts, flags and fixed words are queued; never prompts, paths, model names or error text.")
        status()
    elif action == "off":
        turn_off()
        console.print("Telemetry is off and the queue is deleted.")
    elif action == "show":
        status()
        events = queued()
        console.print("\n".join(json.dumps(e, sort_keys=True) for e in events) if events else "  (nothing queued)", markup=False, highlight=False)
        console.print("\nWhat can be recorded, and nothing else:")
        for name, fields in SCHEMA.items():
            console.print(f"  {name}: " + (", ".join(fields) or "(no fields)"), markup=False, highlight=False)
        console.print("  every event also carries: version, install id, os, arch, python, ram bucket, day", markup=False, highlight=False)
    elif action == "send":
        ok, why = flush()
        console.print(("Sent: " if ok else "Not sent: ") + why, markup=False)
        return 0 if ok else 1
    elif action == "endpoint":
        if value is None:
            console.print(endpoint() or "none set")
        elif not valid_endpoint(value):
            console.print("[red]The endpoint must be an https URL.[/red]")
            return 2
        else:
            set_endpoint(value)
            console.print(f"Endpoint set to {value}")
    elif action == "reset-id":
        reset_id()
        console.print("New install id.")
    else:
        status()
    return 0
