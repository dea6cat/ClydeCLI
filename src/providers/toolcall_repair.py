"""Host-side tool-call repair for small local models.

A small model often emits a valid tool call in a malformed-but-recoverable shape: the
arguments as a JSON string, the real args nested under an 'arguments'/'args' key, the
tool name only inside that wrapper, or the whole call written as JSON in the message
text instead of the native tool_calls field. These helpers untangle those shapes. They
never invent a name or arguments; an unrecognizable shape yields empty args, which the
tool's own validation reports back to the model as a recoverable error.
"""
from __future__ import annotations

import json
import re

_NAME_KEYS = ("name", "tool", "action", "tool_name", "function")
_ARG_KEYS = ("arguments", "args", "parameters", "params", "input", "tool_input")
# Only these tools are ever unwrapped from a wrapper shape: their parameter names never
# collide with a wrapper key. Tools like MCP carry arbitrary schemas that may legitimately
# have a sole 'input'/'params' object, and unwrapping those would send the wrong shape.
_UNWRAP_TOOLS = frozenset({"Read", "Write", "Edit", "Glob", "Grep"})


def _as_arg_dict(value) -> dict:
    """A dict of arguments from `value`, re-parsing a stringified-JSON object; else {}."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value.strip())
        except (ValueError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _unwrap_nested(args: dict) -> tuple[dict, str] | None:
    """If `args` is only a wrapper around the real arguments (an args key plus at most a name
    key), return (inner_args, name_found_inside); else None."""
    for k in _ARG_KEYS:
        if k in args:
            inner = _as_arg_dict(args[k])
            extra = set(args) - {k} - set(_NAME_KEYS)
            if inner and not extra:
                wrapped_name = ""
                for nk in _NAME_KEYS:
                    v = args.get(nk)
                    if isinstance(v, str) and v.strip():
                        wrapped_name = v.strip()
                        break
                return inner, wrapped_name
    return None


def coerce_tool_args(name: str, args, known: tuple[str, ...] = ()) -> tuple[str, dict]:
    """Normalize a model's (name, arguments) into a clean (name, dict). A name found inside a
    wrapper overrides an empty or unknown outer name. Pure."""
    name = (name or "").strip()
    args = _as_arg_dict(args)
    unwrapped = _unwrap_nested(args)
    if unwrapped is None:
        return name, args
    inner, wrapped_name = unwrapped
    eff_name = name
    if wrapped_name and (not name or (known and name not in known)):
        eff_name = wrapped_name
    # A wrapper that repeats the called tool's own name is the model echoing the call it is making (seen from
    # Qwen2.5-Coder GGUF), so any tool can be unwrapped then: no real schema has a `name` equal to its tool.
    if eff_name in _UNWRAP_TOOLS or (name and wrapped_name == name):
        return eff_name, inner
    return name, args


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_PY_LITERALS = ((r"\bTrue\b", "true"), (r"\bFalse\b", "false"), (r"\bNone\b", "null"))
_FENCE_RE = re.compile(
    r"```(?:json|tool_call|tool_calls)?\s*\n?(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)


def loads_tolerant(s: str):
    """json.loads with a conservative repair pass (trailing commas, Python literals, one level
    of unclosed brace/bracket). Returns the parsed value or None; never raises. Repairs only
    apply after a strict parse fails, so valid JSON is never altered."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        pass
    repaired = _TRAILING_COMMA_RE.sub(r"\1", s)
    for pat, repl in _PY_LITERALS:
        repaired = re.sub(pat, repl, repaired)
    for _ in range(3):
        try:
            return json.loads(repaired)
        except (ValueError, TypeError):
            opens = repaired.count("{") - repaired.count("}")
            brackets = repaired.count("[") - repaired.count("]")
            if opens <= 0 and brackets <= 0:
                return None
            repaired = repaired + ("}" if opens > 0 else "]")
    return None


def recover_toolcalls(text: str, known) -> list[tuple[str, dict]]:
    """Recover tool calls a model emitted as JSON in its message text instead of the native
    tool_calls field. Returns (name, args) for each JSON object, in a fenced code block or as
    the whole message body, whose tool name is in `known`; [] if none. Bare JSON embedded
    mid-prose is intentionally not scanned (too risky)."""
    if not text or not any(k in text for k in known):
        return []
    calls: list[tuple[str, dict]] = []
    blobs = [m.group(1) for m in _FENCE_RE.finditer(text)]
    stripped = text.strip()
    if stripped[:1] in "{[":
        blobs.append(stripped)
    for blob in blobs:
        obj = loads_tolerant(blob)
        if obj is None:
            continue
        for item in (obj if isinstance(obj, list) else [obj]):
            if not isinstance(item, dict):
                continue
            name = ""
            for nk in _NAME_KEYS:
                v = item.get(nk)
                if isinstance(v, str) and v.strip():
                    name = v.strip()
                    break
            cname, cargs = coerce_tool_args(name, item, tuple(known))
            if cname in known:
                calls.append((cname, cargs))
    return calls
