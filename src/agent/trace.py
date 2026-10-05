"""Per-session trace: model requests, tool calls, hook blocks, permission prompts, compactions and
MCP connect errors, appended as JSON Lines to ~/.clyde/traces/<session_id>.jsonl.

Nothing is recorded until start() names the session. Opt out with CLYDE_TRACE=off or
`"trace": false` under `session` in ~/.clyde/config.json. Writing never breaks a turn: an
OSError is swallowed. Secrets are redacted and long strings truncated before anything is written.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

MAX_CHARS = 500     # longer strings are truncated in the trace
KEEP_FILES = 50     # newest trace files kept; older ones are pruned at start()
MAX_BYTES = 20_000_000   # one session's trace stops growing here (a marker line says so)
_REDACTED = "[redacted]"
_SECRET_NAME = re.compile(r"api[_-]?key|(access|auth|refresh|bearer|session)[_-]?token|^token$|secret|password|passwd|"
                          r"authorization|credential|cookie", re.I)
_SECRET_VALUE = re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,}|nvapi-[A-Za-z0-9_-]{12,}|"
                           r"gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]{12,})")

_session_id: str | None = None
_write = False
_live = False


def traces_dir() -> Path:
    return Path.home() / ".clyde" / "traces"


def trace_path(session_id: str | None = None) -> Path | None:
    sid = session_id or _session_id
    return traces_dir() / f"{sid}.jsonl" if sid else None


def start(session_id: str, *, enabled: bool = True, live: bool = False) -> None:
    """Trace this session from now on (switching sessions calls it again). `live` echoes each event to stderr."""
    global _session_id, _write, _live
    _session_id, _live = session_id, live
    _write = enabled and os.environ.get("CLYDE_TRACE", "").lower() not in {"off", "0", "false"}
    if _write:
        _prune()


def active() -> bool:
    """Whether events are being recorded (to the file or, under --debug, to stderr)."""
    return _session_id is not None and (_write or _live)


def _prune() -> None:
    try:
        files = sorted(traces_dir().glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP_FILES:]:
            old.unlink()
    except OSError:
        pass


def _known_secrets() -> list[str]:
    from src.providers.keys import PROVIDER_KEY_ENV

    return [v for name in PROVIDER_KEY_ENV.values() if len(v := os.environ.get(name, "")) >= 8]


def redact(value: Any, secrets: list[str] | None = None) -> Any:
    """A JSON-safe copy of value with secret-named fields, key-shaped strings and saved API keys
    replaced, and strings over MAX_CHARS truncated."""
    secrets = _known_secrets() if secrets is None else secrets
    if isinstance(value, dict):
        return {str(k): _REDACTED if _SECRET_NAME.search(str(k)) and v else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    for secret in secrets:
        text = text.replace(secret, _REDACTED)
    text = _SECRET_VALUE.sub(_REDACTED, text)
    return text if len(text) <= MAX_CHARS else f"{text[:MAX_CHARS]}… [{len(text)} chars]"


def record(event: str, **fields: Any) -> None:
    """Append one event to the session trace (and echo it to stderr under --debug)."""
    if not active():
        return
    entry = {"ts": datetime.now().isoformat(timespec="milliseconds"), "event": event, **redact(fields)}
    if _live:
        print(f"[trace] {format_event(entry)}", file=sys.stderr)
    if not _write:
        return
    try:
        path = traces_dir() / f"{_session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if f.tell() >= MAX_BYTES:
                f.write(json.dumps({"ts": entry["ts"], "event": "truncated", "max_bytes": MAX_BYTES}) + "\n")
    except OSError:
        pass


def _estimate_tokens(conversation: Any) -> int:
    chars = len(getattr(conversation, "system_prompt", "") or "")
    for m in getattr(conversation, "messages", []):
        chars += len(m.text or "") + len(m.thinking or "")
        chars += sum(len(tc.name) + len(str(tc.arguments)) for tc in m.tool_calls)
        chars += sum(len(tr.content) for tr in m.tool_results)
    return chars // 4


def model_call(provider: Any, model: str, conversation: Any, call: Callable[[], Any]) -> Any:
    """Run one model request (`call`), recording it; the request's own errors propagate untouched."""
    if not active():
        return call()
    info = {"provider": getattr(provider, "name", str(provider)), "model": model,
            "messages": len(getattr(conversation, "messages", [])), "est_input_tokens": _estimate_tokens(conversation)}
    t0 = time.monotonic()
    try:
        response = call()
    except BaseException as e:
        record("model_request", **info, duration_ms=_ms(t0), error=f"{type(e).__name__}: {e}")
        raise
    record("model_request", **info, duration_ms=_ms(t0), usage=response.usage, stop_reason=response.done_reason,
           tool_calls=len(response.message.tool_calls))
    return response


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def format_event(e: dict) -> str:
    """One compact line for an event."""
    kind = e.get("event")
    if kind == "model_request":
        usage = e.get("usage") or {}
        tokens = f"in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')}" if usage else f"~in={e.get('est_input_tokens')}"
        tail = f"error={e['error']}" if e.get("error") else f"stop={e.get('stop_reason')} tools={e.get('tool_calls')}"
        return f"model {e.get('provider')}:{e.get('model')} msgs={e.get('messages')} {tokens} {e.get('duration_ms')}ms {tail}"
    if kind == "tool_call":
        err = " ERROR" if e.get("is_error") else ""
        return f"tool {e.get('name')} {e.get('duration_ms')}ms {e.get('result_chars')} chars{err} {e.get('input', '')}"
    rest = " ".join(f"{k}={v}" for k, v in e.items() if k not in {"ts", "event"})
    return f"{kind} {rest}"


def read_events(session_id: str | None = None) -> list[dict]:
    path = trace_path(session_id)
    if path is None or not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def last_turn_report(session_id: str | None = None) -> str:
    """The events since the last turn started, one line each, with totals."""
    events = read_events(session_id)
    starts = [i for i, e in enumerate(events) if e.get("event") == "turn"]
    if not starts:
        return "No turns traced yet."
    turn = events[starts[-1] + 1:]
    lines = [f"Last turn ({events[starts[-1]]['ts']}):"] + [f"  {format_event(e)}" for e in turn]
    models = [e for e in turn if e.get("event") == "model_request"]
    tools = [e for e in turn if e.get("event") == "tool_call"]
    tokens_in = sum((e.get("usage") or {}).get("input_tokens", 0) for e in models)
    tokens_out = sum((e.get("usage") or {}).get("output_tokens", 0) for e in models)
    lines.append(f"Totals: {len(models)} model call(s) {sum(e.get('duration_ms', 0) for e in models)}ms "
                 f"in={tokens_in} out={tokens_out} · {len(tools)} tool call(s) "
                 f"{sum(e.get('duration_ms', 0) for e in tools)}ms {sum(1 for e in tools if e.get('is_error'))} error(s)")
    return "\n".join(lines)
