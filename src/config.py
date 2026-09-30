"""Configuration management for ClydeCLI.

~/.clyde/config.json holds non-secret settings: the default model as `provider:model`
and session options. API keys live separately in ~/.clyde/keys.json (see
src/providers/keys.py); a key exported in the shell always wins over a saved one.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Optional


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    config_dir = Path.home() / ".clyde"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def get_default_config() -> dict[str, Any]:
    """Generate default configuration."""
    return {
        "model": None,
        "session": {
            "auto_save": True,
            "max_history": 100,
        },
    }


def _decode_legacy_key(encoded_key: str) -> str:
    """Keys in the pre-keys.json config were base64-encoded; fall back to the raw value."""
    try:
        return base64.b64decode(encoded_key.encode(), validate=True).decode()
    except Exception:
        return encoded_key


def _migrate_legacy(config: dict[str, Any]) -> bool:
    """Move a pre-keys.json config (per-provider api_key/base_url/default_model plus
    default_provider) to the current layout: keys into keys.json, the default provider's model
    into `model`. Returns True when something changed."""
    if "providers" not in config and "default_provider" not in config:
        return False
    from src.providers import keys

    try:
        keys._load()
    except keys.KeysFileError as e:
        print(f"Warning: not migrating old provider settings: {e}")
        return False
    providers = config.pop("providers", None) or {}
    default_provider = config.pop("default_provider", None)
    for name, entry in providers.items():
        if isinstance(entry, dict) and entry.get("api_key"):
            keys.save_if_missing(name, _decode_legacy_key(entry["api_key"]))
    if not config.get("model") and default_provider in providers:
        model = (providers[default_provider] or {}).get("default_model") or ""
        model = model.removeprefix("zai/")   # old GLM entries used a LiteLLM-style prefix
        if model:
            config["model"] = f"{default_provider}:{model}"
    config.setdefault("model", None)
    return True


def load_config() -> dict[str, Any]:
    """Load configuration from file, creating or migrating it as needed."""
    config_path = get_config_path()

    if not config_path.exists():
        config = get_default_config()
        save_config(config)
        return config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return get_default_config()

    if "providers" in config or "default_provider" in config:
        # Keep the original (base URLs, anything not carried over) before rewriting it.
        backup = config_path.with_name("config.json.bak")
        if not backup.exists():
            try:
                fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(config_path.read_text(encoding="utf-8"))
            except OSError:
                pass
    if _migrate_legacy(config):
        save_config(config)
    return config


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file (mode 0600)."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    else:
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.chmod(config_path, 0o600)


def get_default_model() -> Optional[str]:
    """The saved default model as `provider:model`, or None."""
    return load_config().get("model") or None


def set_default_model(model_ref: Optional[str]) -> None:
    """Persist the default model (`provider:model`); None clears it."""
    config = load_config()
    config["model"] = model_ref
    save_config(config)
