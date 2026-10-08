"""Connecting model providers from Bonnie's page: what to show for each one (with a short how-to), whether it is connected,
and a connect that tests the key before it is saved.

Keys are stored by src/providers/keys.py, the same place `clyde login` writes (~/.clyde/keys.json, mode 0600). A key is
only ever received here, never sent back: the page gets a masked form. Error text never repeats the key.
"""
from __future__ import annotations

import os
import re
from typing import Any

from src.providers import build_registry, keys
from src.providers.registry import SUGGESTED_MODELS

# id -> how to get its key. `live`: its model list is fetched with the key, so an empty list means the key was refused
# (the others list a fixed set of models and cannot tell). `prefix`: what its keys usually start with, shown as a soft hint only.
GUIDE: dict[str, dict[str, Any]] = {
    "anthropic": {"label": "Anthropic", "url": "https://platform.claude.com/settings/keys", "live": True, "prefix": "sk-ant-"},
    "openai": {"label": "OpenAI", "url": "https://platform.openai.com/api-keys", "live": True, "prefix": "sk-"},
    "google": {"label": "Google (Gemini)", "url": "https://aistudio.google.com/apikey", "live": True, "prefix": "AIza"},
    "openrouter": {"label": "OpenRouter", "url": "https://openrouter.ai/keys", "live": True, "prefix": "sk-or-"},
    "mistral": {"label": "Mistral", "url": "https://console.mistral.ai/api-keys", "live": True, "prefix": ""},
    "nvidia": {"label": "NVIDIA", "url": "https://build.nvidia.com/settings/api-keys", "live": True, "prefix": "nvapi-"},
    "deepseek": {"label": "DeepSeek", "url": "https://platform.deepseek.com/api_keys", "live": True, "prefix": "sk-"},
    "cerebras": {"label": "Cerebras", "url": "https://cloud.cerebras.ai/platform", "live": True, "prefix": "csk-"},
    "glm": {"label": "GLM (Zhipu)", "url": "https://open.bigmodel.cn/usercenter/apikeys", "live": False, "prefix": ""},
    "minimax": {"label": "MiniMax", "url": "https://platform.minimax.io/console/access", "live": False, "prefix": ""},
    "cloudflare": {"label": "Cloudflare Workers AI", "url": "https://dash.cloudflare.com/profile/api-tokens", "live": False, "prefix": "",
                   "note": "It also needs your Cloudflare account ID; `wrangler whoami` prints it."},
    "pollinations": {"label": "Pollinations", "url": "https://enter.pollinations.ai", "live": False, "prefix": ""},
    "ollama-cloud": {"label": "Ollama Cloud", "url": "https://ollama.com/settings/keys", "live": True, "prefix": "",
                     "note": "Only for Ollama's hosted models. A local Ollama needs no key."},
}
LOCAL = {"ollama": ("Ollama", "https://ollama.com/download", "Install it, then run `ollama serve`. Clyde finds it on its own."),
         "lmstudio": ("LM Studio", "https://lmstudio.ai", "Install it, load a model and start its local server. Clyde finds that too.")}
MAX_KEY = 512
_KEY = re.compile(r"^[\x21-\x7e]{8,%d}$" % MAX_KEY)   # printable ASCII, no spaces


def _key_name(provider: str) -> str:
    return "ollama" if provider == "ollama-cloud" else provider


def _env(provider: str) -> str:
    return keys.PROVIDER_KEY_ENV[_key_name(provider)]


def _known(provider: Any) -> bool:
    return provider in GUIDE or provider in keys.custom_providers()


def _extra(provider: str) -> dict | None:
    found = keys.PROVIDER_EXTRA_ENV.get(provider)
    return {"label": found[1], "set": bool(os.environ.get(found[0]))} if found else None


def listing(registry: dict) -> dict:
    """Every provider the page can set up, with its state: connected (from a saved key or the shell) and a masked key."""
    saved = keys.saved_providers()
    custom = keys.custom_providers()   # also registers their env vars
    rows = []
    for pid, guide in GUIDE.items():
        value = os.environ.get(_env(pid), "")
        rows.append({"id": pid, **guide, "kind": "key", "env": _env(pid), "connected": bool(value), "extra": _extra(pid),
                     "source": ("saved" if _key_name(pid) in saved else "shell") if value else None, "masked": keys.mask(value) if value else ""})
    for pid, (label, url, how) in LOCAL.items():
        provider = registry.get(pid)
        rows.append({"id": pid, "label": label, "url": url, "kind": "local", "how": how, "connected": bool(provider and provider.is_available())})
    mine = []
    for name, url in custom.items():
        value = os.environ.get(keys.PROVIDER_KEY_ENV[name], "")
        mine.append({"id": name, "label": name, "base_url": url, "protocol": keys.protocol(name), "connected": bool(value), "masked": keys.mask(value)})
    return {"providers": rows, "custom": mine}


def _clean_key(value: Any) -> str:
    key = value.strip() if isinstance(value, str) else ""
    if not _KEY.match(key):
        raise ValueError("That doesn't look like a whole key. Copy it again, with no spaces around it.")
    return key


def _test(provider: str, key: str, extra: str | None) -> tuple[list[str], bool]:
    """Try `key` for `provider` without saving it: (models, verified). The environment is put back if it fails."""
    extra_env = (keys.PROVIDER_EXTRA_ENV.get(provider) or ("",))[0]
    names = [n for n in (_env(provider), extra_env) if n]
    before = {n: os.environ.get(n) for n in names}
    try:
        os.environ[_env(provider)] = key
        if extra_env and extra:
            os.environ[extra_env] = extra
        found = build_registry().get(provider)
        if found is None or not found.is_available():
            raise ValueError("That service isn't available right now.")
        try:
            models = found.list_models()
        except Exception:   # the adapters hide the cause; a refused key is the likely one
            models = []
        live = GUIDE.get(provider, {}).get("live", True)
        if live and not models:
            raise ValueError("That key didn't work. Check you copied all of it, that it is for this service, and that the account can use it.")
        return models, live
    except BaseException:
        for name, old in before.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        raise


def connect(repl: Any, provider: Any, key: Any, extra: Any = None) -> dict:
    """Test a key, then save it as `clyde login` does and refresh the registry the REPL uses. Raises ValueError with a sentence for the page."""
    if not _known(provider):
        raise ValueError("Unknown provider.")
    clean = "none" if key == "none" and provider in keys.custom_providers() else _clean_key(key)
    need = keys.PROVIDER_EXTRA_ENV.get(provider)
    extra_value = extra.strip() if isinstance(extra, str) else ""
    if need and not (extra_value or os.environ.get(need[0])):
        raise ValueError(f"{need[1]} is needed too.")
    models, verified = _test(provider, clean, extra_value or None)
    keys.connect(_key_name(provider), clean)
    if need and extra_value:
        problem = keys.connect_setting(provider, extra_value)
        if problem:
            raise ValueError(f"The key worked but the account ID couldn't be saved: {problem}")
    repl.registry = build_registry()
    suggested = SUGGESTED_MODELS.get(provider)
    return {"verified": verified, "models": models[:60], "suggested": suggested if suggested in models else (models[0] if models else suggested)}


def disconnect(repl: Any, provider: Any) -> dict:
    """Forget a saved key. `from_shell` is true when the key was exported in the shell instead, which comes back on the next launch."""
    if not _known(provider):
        raise ValueError("Unknown provider.")
    saved = _key_name(provider) in keys.saved_providers()
    if not saved and not os.environ.get(_env(provider)):
        raise ValueError("That provider has no key.")
    keys.disconnect(_key_name(provider))
    repl.registry = build_registry()
    return {"from_shell": not saved}


def add_custom(repl: Any, name: Any, protocol: Any, base_url: Any, key: Any) -> dict:
    """Add an OpenAI- or Anthropic-compatible service and its key; undone again when the key fails."""
    if not all(isinstance(v, str) for v in (name, protocol, base_url)):
        raise ValueError("Give a name, a protocol and a base URL.")
    name = name.strip().lower()
    text = key.strip() if isinstance(key, str) else ""
    clean = _clean_key(text) if text else "none"   # a keyless server still gets a Bearer header
    problem = keys.add_custom(name, base_url.strip(), protocol)
    if problem:
        raise ValueError(problem[0].upper() + problem[1:] + ".")
    try:
        return connect(repl, name, clean)
    except ValueError:
        keys.remove_custom(name)
        raise
