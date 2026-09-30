"""LM Studio: local models through its OpenAI-compatible server, picked up when LM Studio is installed.

Models are listed from the server when it runs (http://localhost:1234/v1, override with
LMSTUDIO_BASE_URL), or from `lms ls` when it doesn't. The server is started with `lms server start`
only when a request actually goes to an LM Studio model; LM Studio loads the model on first use.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .base import ProviderError, get_json
from .openai_compat import OpenAICompatProvider

DEFAULT_URL = "http://localhost:1234/v1"


def _lms() -> str | None:
    """The `lms` CLI that ships with LM Studio, if it is installed."""
    bundled = Path.home() / ".lmstudio" / "bin" / "lms"
    return shutil.which("lms") or (str(bundled) if bundled.is_file() else None)


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

    def _fetch_models(self) -> list[str]:
        if self._server_up():
            return super()._fetch_models()
        exe = _lms()
        if exe is None:
            return []
        try:
            done = subprocess.run([exe, "ls", "--json"], capture_output=True, text=True, timeout=20)
            downloaded = json.loads(done.stdout or "[]")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []
        return sorted(m["modelKey"] for m in downloaded if isinstance(m, dict) and m.get("type") == "llm" and m.get("modelKey"))

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
        return super().stream(conversation, model, tools, on_text, **kwargs)
