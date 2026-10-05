"""Provider API keys: the provider -> env var map, plus on-disk persistence.

Providers read their keys lazily from os.environ, so connecting a provider is just
setting the right env var and, to make it stick, writing it to ~/.clyde/keys.json
(chmod 600). A key exported in the real shell environment always wins over a saved one.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Provider name -> the environment variable its adapter reads. Ollama's key is only for
# Ollama Cloud; local Ollama needs none.
PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "glm": "GLM_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}


_BUILT_IN = frozenset(PROVIDER_KEY_ENV)
PROTOCOLS = ("openai", "anthropic")
_PROTOCOL: dict[str, str] = {}   # custom provider -> the API it speaks, filled by custom_providers()
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


def _settings_file() -> Path:
    return Path.home() / ".clyde" / "settings.json"


def custom_providers() -> dict[str, str]:
    """Services the user added (OpenAI- or Anthropic-compatible): name -> base URL, from "providers" in
    ~/.clyde/settings.json. Each one's key env var is registered in PROVIDER_KEY_ENV, so saving,
    loading, logout and trace redaction treat it like a built-in provider."""
    try:
        raw = json.loads(_settings_file().read_text(encoding="utf-8")).get("providers", {})
    except (OSError, ValueError, AttributeError):
        return {}
    found = {name: cfg["base_url"] for name, cfg in (raw.items() if isinstance(raw, dict) else [])
             if name not in _BUILT_IN and _NAME.match(str(name)) and isinstance(cfg, dict)
             and str(cfg.get("base_url", "")).startswith(("http://", "https://"))}
    for name in found:
        PROVIDER_KEY_ENV.setdefault(name, "CLYDE_" + name.upper().replace("-", "_") + "_API_KEY")
        _PROTOCOL[name] = raw[name].get("protocol") if raw[name].get("protocol") in PROTOCOLS else "openai"
    return found


def protocol(name: str) -> str:
    """The API a custom provider speaks: openai (default) or anthropic."""
    return _PROTOCOL.get(name, "openai")


def add_custom(name: str, base_url: str, protocol: str = "openai") -> str | None:
    """Save a custom provider; returns why it can't be added, or None."""
    if not _NAME.match(name):
        return "use 2-31 lowercase letters, digits or dashes, starting with a letter"
    if name in _BUILT_IN or name in ("ollama-cloud", "lmstudio", "cardShuffle", "custom"):
        return f"{name} is a built-in provider"
    if not base_url.startswith(("http://", "https://")):
        return "the base URL must start with http:// or https://"
    if protocol not in PROTOCOLS:
        return f"the protocol must be one of {', '.join(PROTOCOLS)}"
    entry = {"base_url": base_url.rstrip("/")} | ({"protocol": protocol} if protocol != "openai" else {})
    problem = _edit_providers(lambda providers: providers.__setitem__(name, entry))
    custom_providers()
    return problem


def remove_custom(name: str) -> str | None:
    """Delete a custom provider from settings.json; returns why it couldn't, or None."""
    problem = _edit_providers(lambda providers: providers.pop(name, None))
    if problem is None and name not in _BUILT_IN:
        PROVIDER_KEY_ENV.pop(name, None)
    return problem


def _edit_providers(change) -> str | None:
    """Apply `change` to the "providers" object in settings.json, keeping every other key."""
    path = _settings_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        return f"can't read {path}: {e}"
    if not isinstance(data, dict):
        return f"{path} is not a JSON object"
    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        return f'"providers" in {path} is not a JSON object'
    change(providers)
    if not providers:
        del data["providers"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)  # settings may hold MCP tokens
    return None


def keys_file() -> Path:
    return Path.home() / ".clyde" / "keys.json"


class KeysFileError(RuntimeError):
    """keys.json exists but can't be read as a JSON object. Raised instead of treating it as
    empty, so a write never silently wipes the other providers' saved keys."""


def _load() -> dict:
    path = keys_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise KeysFileError(f"can't read {path}: {e}. Fix or remove the file.") from e
    if not isinstance(data, dict):
        raise KeysFileError(f"{path} is not a JSON object. Fix or remove the file.")
    return data


def _write(data: dict) -> None:
    """Atomic write, created 0600 from the start (never world-readable, even briefly)."""
    path = keys_file()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".keys-", suffix=".tmp")   # mkstemp creates 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_into_env() -> None:
    """Populate os.environ from saved keys, without clobbering a key already exported in the
    shell (that one is authoritative). A broken keys file is reported, not fatal."""
    custom_providers()   # registers their env vars, so their saved keys load too
    try:
        saved = _load()
    except KeysFileError as e:
        print(f"Warning: {e}", file=sys.stderr)
        return
    for provider, key in saved.items():
        env = PROVIDER_KEY_ENV.get(provider)
        if env and key:
            os.environ.setdefault(env, key)


def connect(provider: str, key: str) -> None:
    """Set the provider's key for this session and persist it for future ones."""
    os.environ[PROVIDER_KEY_ENV[provider]] = key
    data = _load()
    data[provider] = key
    _write(data)


def save_if_missing(provider: str, key: str) -> bool:
    """Persist a key only when none is saved yet (used by the config.json migration)."""
    data = _load()
    if data.get(provider) or provider not in PROVIDER_KEY_ENV:
        return False
    data[provider] = key
    _write(data)
    return True


def disconnect(provider: str) -> bool:
    """Remove a saved key and unset it for this session. True if one was saved."""
    data = _load()
    existed = provider in data
    if existed:
        del data[provider]
        _write(data)
    env = PROVIDER_KEY_ENV.get(provider)
    if env:
        os.environ.pop(env, None)
    return existed


def saved_providers() -> set:
    try:
        return set(_load().keys())
    except KeysFileError:
        return set()


def mask(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 8:
        return "•" * len(k)
    return f"{k[:4]}…{k[-4:]}"
