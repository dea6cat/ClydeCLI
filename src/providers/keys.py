"""Provider API keys: the provider -> env var map, plus on-disk persistence.

Providers read their keys lazily from os.environ, so connecting a provider is just
setting the right env var and, to make it stick, writing it to ~/.clyde/keys.json
(chmod 600). A key exported in the real shell environment always wins over a saved one.
"""
from __future__ import annotations

import json
import os
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


def is_connected(provider: str) -> bool:
    env = PROVIDER_KEY_ENV.get(provider)
    if not env:
        return False
    if os.environ.get(env):
        return True
    return provider == "google" and bool(os.environ.get("GOOGLE_API_KEY"))


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
