"""LM Studio: local models through its OpenAI-compatible server, picked up when LM Studio is installed.

Models are listed from the server when it runs (http://localhost:1234/v1, override with
LMSTUDIO_BASE_URL), or from `lms ls` when it doesn't. The server is started with `lms server start`
only when a request actually goes to an LM Studio model; LM Studio loads the model on first use.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import fit
from .base import ProviderError, get_json
from .openai_compat import OpenAICompatProvider

DEFAULT_URL = "http://localhost:1234/v1"
# Context assumed before LM Studio has loaded a model; the real value comes from `lms ps`.
# ponytail: a guess until first load; LM Studio picks the loaded context from its own settings
UNLOADED_CONTEXT = 8192
_CONTEXT_TTL = 30
MAX_WINDOW = 32768      # past this a small local model loses the thread; compaction keeps the rest
WINDOW_FLOOR = 4096
GGUF_WINDOW = 8192      # ponytail: a GGUF's layer count isn't in `lms ls`; read the GGUF header to size it like an MLX model
KV_SHARE = 0.5          # of the budget left after weights and runtime overhead, the share the KV cache may take
LOAD_TTL_S = 3600       # LM Studio unloads a model Clyde loaded after an hour idle


def _lms() -> str | None:
    """The `lms` CLI that ships with LM Studio, if it is installed."""
    bundled = Path.home() / ".lmstudio" / "bin" / "lms"
    return shutil.which("lms") or (str(bundled) if bundled.is_file() else None)


MODELS_DIR = Path.home() / ".lmstudio" / "models"


def model_files(entry: dict) -> Path | None:
    """Where an `lms ls` entry lives under the models folder, or None when that can't be told for sure
    (catalog aliases like `qwen/qwen3.5-9b` don't name their folder, and the folder can be moved)."""
    root = MODELS_DIR.resolve()
    target = (root / str(entry.get("path", ""))).resolve()
    return target if root in target.parents and target.exists() else None


def kv_bytes_per_token(folder: Path | None) -> int | None:
    """fp16 KV cache bytes per token from a model folder's config.json (MLX/safetensors), or None when it can't be told."""
    try:
        cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        layers, heads = int(cfg["num_hidden_layers"]), int(cfg["num_attention_heads"])
        kv_heads = int(cfg.get("num_key_value_heads") or heads)
        head_dim = int(cfg.get("head_dim") or int(cfg["hidden_size"]) // heads)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return 2 * layers * kv_heads * head_dim * 2


class LMStudioProvider(OpenAICompatProvider):
    def __init__(self) -> None:
        super().__init__("lmstudio", os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_URL), "LMSTUDIO_API_KEY",
                         dynamic_models=True, stream_usage=True)

    @property
    def api_key(self) -> str:
        return os.environ.get(self.key_env, "") or "lm-studio"  # the local server accepts any key

    def _server_up(self) -> bool:
        try:
            get_json(f"{self.base_url}/models", headers=self._headers(), timeout=1, provider=self.name)
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        return _lms() is not None or self._server_up()

    def downloaded(self) -> list[dict]:
        """Every model on disk (`lms ls --json`), embedding models included."""
        exe = _lms()
        if exe is None:
            return []
        try:
            done = subprocess.run([exe, "ls", "--json"], capture_output=True, text=True, timeout=20)
            return [m for m in json.loads(done.stdout or "[]") if isinstance(m, dict) and m.get("modelKey")]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []

    def _fetch_models(self) -> list[str]:
        if self._server_up():
            return super()._fetch_models()
        return sorted(m["modelKey"] for m in self.downloaded() if m.get("type") == "llm")

    def context_window(self, model: str) -> int:
        """The context LM Studio actually loaded the model with (`lms ps`), cached briefly."""
        cached = getattr(self, "_ctx_cache", {}).get(model)
        if cached and time.monotonic() - cached[0] < _CONTEXT_TTL:
            return cached[1]
        window = self.planned_window(model)
        exe = _lms()
        if exe is not None:
            try:
                loaded = json.loads(subprocess.run([exe, "ps", "--json"], capture_output=True, text=True, timeout=15).stdout or "[]")
                match = next((m for m in loaded if isinstance(m, dict) and model in (m.get("modelKey"), m.get("identifier"))), None)
                if match and match.get("contextLength"):
                    window = int(match["contextLength"])
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        self._ctx_cache = {**getattr(self, "_ctx_cache", {}), model: (time.monotonic(), window)}
        return window

    def planned_window(self, model: str) -> int:
        """The window Clyde loads the model with: what fits the memory budget after the weights, KV cache included
        (CLYDE_CONTEXT_TOKENS or CLYDE_MODEL_CONTEXT_<MODEL> override). LM Studio's own default can be 34k tokens
        times 4 parallel slots, which swaps an 18 GB Mac."""
        from .ollama import _ctx_env_key
        for key in ("CLYDE_CONTEXT_TOKENS", f"CLYDE_MODEL_CONTEXT_{_ctx_env_key(model)}"):
            if os.environ.get(key, "").isdigit():
                return int(os.environ[key])
        entry = next((m for m in self.downloaded() if m.get("modelKey") == model), {})
        trained = int(entry.get("maxContextLength") or MAX_WINDOW)
        per_token = kv_bytes_per_token(model_files(entry)) if entry else None
        if per_token is None:
            return min(trained, GGUF_WINDOW)
        spare = max(0, fit.budget_bytes() - int(entry.get("sizeBytes") or 0) - fit.OVERHEAD)
        window = min(trained, MAX_WINDOW, int(spare * KV_SHARE / per_token)) // 1024 * 1024
        return max(WINDOW_FLOOR, window)

    def _loaded(self, model: str) -> bool:
        exe = _lms()
        try:
            loaded = json.loads(subprocess.run([exe, "ps", "--json"], capture_output=True, text=True, timeout=15).stdout or "[]")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return True   # can't tell: leave LM Studio to load it its own way
        return any(isinstance(m, dict) and model in (m.get("modelKey"), m.get("identifier")) for m in loaded)

    def ensure_loaded(self, model: str) -> None:
        """Load the model with the planned window and one slot unless it is already loaded (a model you loaded yourself keeps your settings)."""
        exe = _lms()
        if exe is None or time.monotonic() - getattr(self, "_ensured", {}).get(model, -1e9) < _CONTEXT_TTL or self._loaded(model):
            return
        try:
            subprocess.run([exe, "load", model, "-c", str(self.planned_window(model)), "--parallel", "1", "--ttl", str(LOAD_TTL_S), "-y"],
                           capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired):
            pass   # the server loads it on the first request anyway
        self._ctx_cache = {}
        self._ensured = {**getattr(self, "_ensured", {}), model: time.monotonic()}

    def estimate(self, model: str) -> int | None:
        """LM Studio's own estimate of the memory the model needs once loaded (`lms load --estimate-only`), in bytes."""
        exe = _lms()
        if exe is None:
            return None
        try:
            done = subprocess.run([exe, "load", model, "--estimate-only", "-y"], capture_output=True, text=True, timeout=30)
            out = done.stdout + done.stderr   # lms prints the estimate on stderr
        except (OSError, subprocess.TimeoutExpired):
            return None
        found = re.search(r"Estimated Total Memory:\s+([\d.]+)\s*(GiB|MiB)", out)
        return int(float(found.group(1)) * (1024 ** 3 if found.group(2) == "GiB" else 1024 ** 2)) if found else None

    def unload(self, model: str) -> None:
        """Free the model's memory (`lms unload`); a no-op when it isn't loaded or `lms` is missing."""
        exe = _lms()
        if exe is None:
            return
        try:
            subprocess.run([exe, "unload", model], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self._ctx_cache = {}

    def _ensure_server(self) -> None:
        if self._server_up():
            return
        exe = _lms()
        if exe is None:
            raise ProviderError(self.name, f"LM Studio's server isn't running at {self.base_url}; start it in LM Studio")
        try:
            subprocess.run([exe, "server", "start"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ProviderError(self.name, f"couldn't start LM Studio's server: {e}") from e
        if not self._server_up():
            raise ProviderError(self.name, f"LM Studio's server didn't come up at {self.base_url}; start it in LM Studio")

    def stream(self, conversation, model, tools, on_text, **kwargs):  # type: ignore[no-untyped-def]
        self._ensure_server()
        self.ensure_loaded(model)
        return super().stream(conversation, model, tools, on_text, **kwargs)
