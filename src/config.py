"""Configuration management for ClydeCLI.

~/.clyde/config.json holds non-secret settings: the default model as `provider:model`
and session options. API keys live separately in ~/.clyde/keys.json (see
src/providers/keys.py); a key exported in the shell always wins over a saved one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from src.safe_write import read_json_safely, write_json_safely


def clyde_home() -> Path:
    """Clyde's own folder: ~/.clyde, or $XDG_CONFIG_HOME/clyde when that is set and either already exists or
    no ~/.clyde predates it, so an existing install never loses its keys and sessions."""
    legacy = Path.home() / ".clyde"
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    # ponytail: one folder for config, data and state; split into XDG_DATA_HOME/XDG_STATE_HOME if asked
    if xdg and Path(xdg).is_absolute() and ((Path(xdg) / "clyde").exists() or not legacy.exists()):
        return Path(xdg) / "clyde"
    return legacy


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    config_dir = clyde_home()
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


def load_config() -> dict[str, Any]:
    """Load configuration from file, creating it when missing."""
    config_path = get_config_path()

    if not config_path.exists():
        config = get_default_config()
        save_config(config)
        return config

    try:
        config = read_json_safely(config_path)   # a cut-off file falls back to the last good copy
    except Exception as e:
        print(f"Error loading config: {e}")
        return get_default_config()

    return config


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file (mode 0600)."""
    write_json_safely(get_config_path(), config, private=True)   # a crash mid-write leaves the old file, and the last good one is kept as config.json.prev


def get_default_model() -> Optional[str]:
    """The saved default model as `provider:model`, or None."""
    return load_config().get("model") or None


def set_default_model(model_ref: Optional[str]) -> None:
    """Persist the default model (`provider:model`); None clears it."""
    config = load_config()
    config["model"] = model_ref
    save_config(config)


def get_output_style() -> Optional[str]:
    """The saved output style name (see src/output_styles), or None for the default."""
    return load_config().get("output_style") or None


def set_output_style(name: Optional[str]) -> None:
    """Persist the output style; None clears it."""
    config = load_config()
    if name:
        config["output_style"] = name
    else:
        config.pop("output_style", None)
    save_config(config)


MIN_CONTEXT_TOKENS = 1024


def get_context_tokens() -> Optional[int]:
    """The context window the user fixed for local models (/settings), or None to size it automatically.
    CLYDE_CONTEXT_TOKENS and CLYDE_MODEL_CONTEXT_<MODEL> still win."""
    value = load_config().get("context_tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= MIN_CONTEXT_TOKENS else None


def context_env_var(model: str) -> str:
    """The environment variable that fixes one model's window: CLYDE_MODEL_CONTEXT_<MODEL>."""
    return "CLYDE_MODEL_CONTEXT_" + "".join(c if c.isalnum() else "_" for c in model.upper())


def window_override(model: str) -> Optional[int]:
    """A window set in the environment: CLYDE_CONTEXT_TOKENS for every model, else this model's own variable."""
    for name in ("CLYDE_CONTEXT_TOKENS", context_env_var(model)):
        if os.environ.get(name, "").isdigit():
            return int(os.environ[name])
    return None


def fixed_window(model: str) -> Optional[int]:
    """The window the user fixed for a local model: an environment override, else the one saved by /settings."""
    override = window_override(model)
    return override if override is not None else get_context_tokens()


def set_context_tokens(tokens: Optional[int]) -> None:
    """Persist the context window for local models; None goes back to automatic. ValueError below the minimum."""
    if tokens is not None and tokens < MIN_CONTEXT_TOKENS:
        raise ValueError(f"context window must be at least {MIN_CONTEXT_TOKENS} tokens")
    config = load_config()
    if tokens is None:
        config.pop("context_tokens", None)
    else:
        config["context_tokens"] = tokens
    save_config(config)


def get_omlx_memory_guard() -> str | None:
    """The memory guard the user picked for oMLX's server in /settings, or None for the default (balanced)."""
    value = load_config().get("omlx_memory_guard")
    return value if isinstance(value, str) else None


def set_omlx_memory_guard(choice: str) -> None:
    """Persist oMLX's memory guard. It takes effect when Clyde next starts its oMLX server."""
    config = load_config()
    config["omlx_memory_guard"] = choice
    save_config(config)


UPDATE_CHANNELS = ("latest", "stable")


def get_update_channel() -> str:
    """Which releases `clyde update` follows: "latest" (every commit on main, the default) or "stable" (tagged releases)."""
    channel = load_config().get("update_channel")
    return channel if channel in UPDATE_CHANNELS else "latest"


def set_update_channel(channel: str) -> None:
    """Persist the update channel. ValueError for anything but latest or stable."""
    if channel not in UPDATE_CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(UPDATE_CHANNELS)}")
    config = load_config()
    config["update_channel"] = channel
    save_config(config)
