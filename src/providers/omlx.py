"""oMLX (github.com/jundot/omlx, Apache-2.0): MLX models on Apple Silicon through its OpenAI-compatible server.

Clyde installs it from a pinned source checkout into ~/.clyde/omlx (install(), with the user's yes) and starts it as
`omlx serve` on localhost:8000 when a request goes to an oMLX model. The server always runs with a key only Clyde holds
(~/.clyde/omlx/api_key, 0600): without one oMLX opens every endpoint, admin included, to anything that can reach the port,
a web page in the browser among them. OMLX_API_KEY overrides it for a server you run yourself.

`--memory-guard balanced` (the default; /settings offers aggressive, fixed ceilings and off) keeps at least 3 GB free for other apps and follows their use live; `safe` reserves at least
6 GB, which on an 18 GB Mac left a 1.6 GB ceiling that refused a 4 GB model with 8 GB free. oMLX's SSD cache tier (on by default, ~/.omlx/cache)
restores a prompt's KV state after a restart or an eviction instead of recomputing it; a warm repeat is no faster than
any server that caches prompts in memory.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from src.config import clyde_home

from . import fit
from .base import ProviderError, get_json, post_json
from .openai_compat import OpenAICompatProvider

DEFAULT_URL = "http://localhost:8000/v1"
REPO = "https://github.com/jundot/omlx.git"
VERSION = "v0.7.2"      # pinned: cache and lazy-load behaviour shift between releases
PYTHON = "3.13"         # oMLX supports 3.11 to 3.13
START_TIMEOUT_S = 90
_TTL = 30
MAX_WINDOW = 32768      # past this a small local model loses the thread; compaction keeps the rest
WINDOW_FLOOR = 4096
UNKNOWN_WINDOW = 8192   # no config.json to size the KV cache from (a GGUF)
KV_SHARE = 0.5          # of the budget left after weights and runtime overhead, the share the KV cache may take


def supported() -> bool:
    """oMLX runs only on Apple Silicon Macs."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def home() -> Path:
    return clyde_home() / "omlx"


def _exe() -> str | None:
    """The `omlx` command: Clyde's own install first, then one on PATH (Homebrew, the app's shim)."""
    own = home() / "venv" / "bin" / "omlx"
    return str(own) if own.is_file() else shutil.which("omlx")


def _key_file() -> Path:
    return home() / "api_key"


def server_key() -> str:
    """The key Clyde starts the server with, made on first use (0600 from the start)."""
    path = _key_file()
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pass
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    return key


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


def fixed_window(model: str) -> int | None:
    """The window the user fixed: an environment override, else the one saved by /settings."""
    from src import config
    from .ollama import _ctx_env_key
    for key in ("CLYDE_CONTEXT_TOKENS", f"CLYDE_MODEL_CONTEXT_{_ctx_env_key(model)}"):
        if os.environ.get(key, "").isdigit():
            return int(os.environ[key])
    return config.get_context_tokens()


GUARD = "balanced"
_CUSTOM_SHARES = (0.4, 0.5, 0.6)   # of RAM: a fixed ceiling, picked from a list since /settings cycles through choices


def memory_guard_choices() -> tuple[str, ...]:
    """What /settings offers for oMLX's memory guard: balanced (the default), aggressive, a few fixed ceilings, off."""
    from .ollama import _total_ram_bytes
    ram_gb = _total_ram_bytes() / 1024 ** 3
    return (GUARD, "aggressive", *dict.fromkeys(f"custom {int(ram_gb * share)} GB" for share in _CUSTOM_SHARES), "off")


def memory_guard_args(choice: str | None) -> list[str]:
    """`omlx serve` arguments for a /settings choice; anything unknown is the default."""
    if choice in ("aggressive", "off"):
        return ["--memory-guard", choice]
    if choice and choice.startswith("custom ") and choice.removeprefix("custom ").removesuffix(" GB").isdigit():
        return ["--memory-guard-gb", choice.removeprefix("custom ").removesuffix(" GB")]
    return ["--memory-guard", GUARD]


def stop_server() -> bool:
    """Stop the server Clyde started (its pid is saved at start), so the next request starts it with new settings.
    A server you started yourself is never touched. True when one was stopped."""
    pid_file = home() / "server.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pid_file.unlink(missing_ok=True)
    name = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True).stdout.strip()
    if not name.endswith("omlx-server"):   # gone, or the pid now belongs to something else
        return False
    os.kill(pid, 15)
    return True


LMSTUDIO_MODELS = Path.home() / ".lmstudio" / "models"


def settings_file() -> Path:
    return Path.home() / ".omlx" / "settings.json"


def adopt_lmstudio_models() -> bool:
    """Let oMLX serve the models LM Studio downloaded, where they are: its folder (publisher/model, a layout oMLX reads)
    joins oMLX's model folders in ~/.omlx/settings.json, next to oMLX's own. Nothing is copied or moved. True when the
    folder was added; a settings file that can't be read is left alone."""
    if not LMSTUDIO_MODELS.is_dir():
        return False
    path = settings_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return False
    model = data.setdefault("model", {}) if isinstance(data, dict) else None
    if not isinstance(model, dict):
        return False
    dirs = model.get("model_dirs") or [str(Path.home() / ".omlx" / "models")]   # [] means oMLX's own folder: keep it
    if str(LMSTUDIO_MODELS) in dirs:
        return False
    model["model_dirs"] = [*dirs, str(LMSTUDIO_MODELS)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def install(log: Callable[[str], None] = print) -> str | None:
    """Install oMLX from its pinned release into ~/.clyde/omlx: a git checkout, a Python 3.13 venv made by uv, and the
    native Metal kernels when Xcode's Metal toolchain is there (without them some model families fall back to much
    slower paths). The `omlx` command it provides, or None; `log` gets one line per step."""
    root, uv, git = home(), shutil.which("uv"), shutil.which("git")
    if uv is None or git is None:
        log("oMLX needs uv and git to install (Clyde's installer sets up uv).")
        return None
    src, venv = root / "src", root / "venv"
    python = venv / "bin" / "python"
    steps = [
        ("Downloading oMLX " + VERSION, [git, "clone", "--quiet", "--depth", "1", "--branch", VERSION, REPO, str(src)]),
        ("Making its Python " + PYTHON + " environment", [uv, "venv", "--quiet", "--seed", "--python", PYTHON, str(venv)]),
        ("Installing it (a few minutes)", [uv, "pip", "install", "--quiet", "--python", str(python), "-e", str(src)]),
    ]
    if src.exists():   # a run cut short: pick up where it stopped
        steps = steps[1:] if not venv.exists() else steps[2:]
    for label, argv in steps:
        log(label + "…")
        done = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        if done.returncode != 0:
            log(f"{label} failed: {(done.stderr or done.stdout).strip()[-400:]}")
            return None
    if subprocess.run(["xcrun", "-f", "metal"], capture_output=True, text=True, timeout=30).returncode == 0:
        log("Building its Metal kernels (a few minutes)…")
        done = subprocess.run(["make", "-C", str(src), "kernels", f"PYTHON={python}"], capture_output=True, text=True, timeout=1800)
        if done.returncode != 0:   # oMLX still runs, on its generic paths
            log("The Metal kernels didn't build; oMLX runs without them, slower for GLM, MiniMax and Qwen3.5 models.")
    else:
        log("No Metal toolchain (full Xcode), so oMLX runs without its native kernels: slower for GLM, MiniMax and Qwen3.5 models.")
    return _exe()


class OMLXProvider(OpenAICompatProvider):
    def __init__(self) -> None:
        super().__init__("omlx", os.environ.get("OMLX_BASE_URL", DEFAULT_URL), "OMLX_API_KEY",
                         dynamic_models=True, stream_usage=True)
        # Set by the REPL: () -> may Clyde download and install oMLX? None never installs (editors, scripts, Bonnie).
        self.confirm_install: Callable[[], bool] | None = None

    @property
    def api_key(self) -> str:
        return os.environ.get(self.key_env, "") or (server_key() if _exe() is not None else "")

    @property
    def _admin(self) -> str:
        return self.base_url.removesuffix("/v1") + "/admin/api"

    def _server_up(self) -> bool:
        try:
            get_json(f"{self.base_url}/models", headers=self._headers(), timeout=1, provider=self.name)
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        return _exe() is not None or self._server_up()

    def _status(self) -> list[dict]:
        """The server's models with load state, path, size and native context (admin API), cached briefly; [] when it is down."""
        cached = getattr(self, "_status_cache", None)
        if cached and time.monotonic() - cached[0] < _TTL:
            return cached[1]
        try:
            data = get_json(f"{self._admin}/models", headers=self._headers(), timeout=5, provider=self.name)
        except Exception:
            return []
        models = [m for m in (data.get("models") if isinstance(data, dict) else data) or [] if isinstance(m, dict)]
        self._status_cache = (time.monotonic(), models)
        return models

    def _entry(self, model: str) -> dict:
        return next((m for m in self._status() if m.get("id") == model), {})

    def context_window(self, model: str) -> int:
        """The window oMLX serves the model with (`max_model_len` in /v1/models), else the one Clyde plans."""
        try:
            data = get_json(f"{self.base_url}/models", headers=self._headers(), timeout=5, provider=self.name)
            served = next((m.get("max_model_len") for m in data.get("data", []) if m.get("id") == model), None)
        except Exception:
            served = None
        return int(served) if served else self.planned_window(model)

    def planned_window(self, model: str) -> int:
        """The window Clyde serves the model with: what fits the memory budget after the weights, KV cache included
        (CLYDE_CONTEXT_TOKENS or CLYDE_MODEL_CONTEXT_<MODEL> override)."""
        if (fixed := fixed_window(model)) is not None:
            return fixed
        entry = self._entry(model)
        trained = int(entry.get("model_context_length") or MAX_WINDOW)
        per_token = kv_bytes_per_token(Path(entry["model_path"])) if entry.get("model_path") else None
        if per_token is None:
            return min(trained, UNKNOWN_WINDOW)
        spare = max(0, fit.budget_bytes() - int(entry.get("estimated_size") or 0) - fit.OVERHEAD)
        window = min(trained, MAX_WINDOW, int(spare * KV_SHARE / per_token)) // 1024 * 1024
        return max(WINDOW_FLOOR, window)

    def _call(self, url: str, payload: dict, method: str = "POST") -> None:
        post_json(url, payload, headers=self._headers(), timeout=600, provider=self.name, method=method)

    def ensure_loaded(self, model: str) -> None:
        """Give the model Clyde's planned window, then load it, once per model and window (oMLX would load it on the
        first request anyway, with its own default window)."""
        planned = self.planned_window(model)
        if (model, planned) in getattr(self, "_ensured", set()):
            return
        quoted = urllib.parse.quote(model, safe="")
        try:
            self._call(f"{self._admin}/models/{quoted}/settings", {"max_context_window": planned}, method="PUT")
            if not self._entry(model).get("loaded"):
                self._call(f"{self.base_url}/models/{quoted}/load", {})
        except ProviderError:
            return   # the request itself still goes through; oMLX loads the model with its own settings
        self._status_cache = None
        self._ensured = {*getattr(self, "_ensured", set()), (model, planned)}

    def estimate(self, model: str) -> int | None:
        """oMLX's estimate of the memory the model needs once loaded, in bytes."""
        size = self._entry(model).get("estimated_size")
        return int(size) if size else None

    def unload(self, model: str) -> None:
        """Free the model's memory; a no-op when the server is down or the model isn't loaded."""
        try:
            self._call(f"{self.base_url}/models/{urllib.parse.quote(model, safe='')}/unload", {})
        except ProviderError:
            pass
        self._status_cache = None
        self._ensured = {e for e in getattr(self, "_ensured", set()) if e[0] != model}

    def _ensure_server(self) -> None:
        """Start `omlx serve` in the background with Clyde's key, installing oMLX first (with a yes) when it's missing."""
        if self._server_up():
            return
        if os.environ.get(self.key_env):
            raise ProviderError(self.name, f"no oMLX server at {self.base_url}; start yours (OMLX_API_KEY is set, so Clyde doesn't start one)")
        exe = _exe()
        if exe is None:
            by_hand = f"install it from {REPO.removesuffix('.git')} or with Homebrew, then try again"
            # Downloading and building oMLX needs a yes; where nobody can be asked (confirm_install is None) it never happens.
            if self.confirm_install is None or not self.confirm_install():
                raise ProviderError(self.name, f"oMLX isn't installed; {by_hand}")
            exe = install()
            if exe is None:
                raise ProviderError(self.name, f"couldn't install oMLX; {by_hand}")
        adopt_lmstudio_models()   # read at start, so before it
        port = urllib.parse.urlparse(self.base_url).port or 8000
        log = home() / "server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        from src import config
        with open(log, "ab") as out:   # the key goes in the environment: a command line shows in every user's `ps`
            server = subprocess.Popen([exe, "serve", "--port", str(port), *memory_guard_args(config.get_omlx_memory_guard())],
                                      env={**os.environ, self.key_env: server_key()},
                                      stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)
        (home() / "server.pid").write_text(str(server.pid), encoding="utf-8")
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._server_up():
                return
            time.sleep(1)
        raise ProviderError(self.name, f"oMLX's server didn't come up at {self.base_url}; see {log}")

    def stream(self, conversation, model, tools, on_text, **kwargs):  # type: ignore[no-untyped-def]
        self._ensure_server()
        self.ensure_loaded(model)
        return super().stream(conversation, model, tools, on_text, **kwargs)
