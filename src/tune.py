"""`clyde tune`: does flash attention plus a q8_0 KV cache help Ollama on this machine?

Ollama reads both settings from the server's environment at startup and never reports them, so the
check runs its own throwaway `ollama serve` per setting on a free port: the server you are using is
never touched. Each run loads the model at the window Clyde pins for it, then reports memory (from
/api/ps) and speed (from Ollama's own timings). Applying a winner is left to the user, because it
means changing how their Ollama starts.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, ContextManager, Iterator

from rich.console import Console
from rich.table import Table

from src.providers.base import ProviderError, get_json, post_json
from src.providers.ollama import OllamaProvider, local

BASELINE = "default"
TUNED = "flash attention + q8_0 KV"
SETTINGS = {
    BASELINE: {},
    TUNED: {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"},
}
# Tuned must stay within this fraction of the baseline's generation speed, and save at least this
# fraction of its memory, to be recommended: a smaller saving is not worth restarting Ollama for.
MAX_SLOWDOWN = 0.10
MIN_SAVING = 0.05
_STARTUP_S = 20
_PROMPT = "Summarize in one paragraph: " + "The quick brown fox jumps over the lazy dog. " * 120


@dataclass(frozen=True)
class Result:
    memory_bytes: int
    prompt_tps: float
    gen_tps: float


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _serve(extra_env: dict[str, str]) -> Iterator[str]:
    """A private `ollama serve` on a free port with extra_env set; stopped on exit."""
    host = f"127.0.0.1:{_free_port()}"
    # The user's own OLLAMA_* settings must not leak into the baseline; the model folder must carry over.
    env = {k: v for k, v in os.environ.items() if not k.startswith("OLLAMA_") or k == "OLLAMA_MODELS"}
    proc = subprocess.Popen(["ollama", "serve"], env={**env, **extra_env, "OLLAMA_HOST": host},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + _STARTUP_S
        while True:
            try:
                get_json(f"http://{host}/api/version", timeout=2, provider="ollama")
                break
            except ProviderError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise ProviderError("ollama", "the temporary server did not start") from None
                time.sleep(0.3)
        yield f"http://{host}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _generate(host: str, model: str, ctx: int, predict: int, prompt: str) -> dict:
    return post_json(f"{host}/api/generate", {
        "model": model, "prompt": prompt, "stream": False, "keep_alive": "2m",
        "options": {"num_ctx": ctx, "num_predict": predict, "temperature": 0},
    }, timeout=600, provider="ollama")


def _rate(count: int | None, nanoseconds: int | None) -> float:
    return (count or 0) / (nanoseconds / 1e9) if nanoseconds else 0.0


def measure(host: str, model: str, ctx: int) -> Result:
    """Load the model at `ctx`, warm it, then time one generation. Memory is what Ollama reports loaded."""
    _generate(host, model, ctx, 1, "Hi")   # a different prompt, so the timed one is not served from the prompt cache
    timed = _generate(host, model, ctx, 128, _PROMPT)
    loaded = get_json(f"{host}/api/ps", provider="ollama").get("models") or []
    memory = next((int(m.get("size") or 0) for m in loaded if model in (m.get("name"), m.get("model"))), 0)
    return Result(memory, _rate(timed.get("prompt_eval_count"), timed.get("prompt_eval_duration")),
                  _rate(timed.get("eval_count"), timed.get("eval_duration")))


def verdict(base: Result, tuned: Result) -> tuple[bool, str]:
    """Whether to recommend the tuned setting, and why. It must save memory without a real slowdown."""
    if not (base.gen_tps and tuned.gen_tps and base.memory_bytes and tuned.memory_bytes):
        return False, "A run produced no timings or memory reading, so there is nothing to compare."
    saved = base.memory_bytes - tuned.memory_bytes
    slowdown = 1 - tuned.gen_tps / base.gen_tps
    if saved <= 0:
        return False, "It did not lower memory for this model (some architectures ignore a quantized cache)."
    if saved < MIN_SAVING * base.memory_bytes:
        return False, f"It saves only {saved / 2**20:.0f} MB ({saved / base.memory_bytes:.0%}); this model's cache is already small."
    if slowdown > MAX_SLOWDOWN:
        return False, f"It saves {saved / 2**20:.0f} MB but generation is {slowdown:.0%} slower."
    return True, f"It saves {saved / 2**20:.0f} MB, which buys a longer window at the same RAM; generation speed {-slowdown:+.0%}."


def apply_hint() -> str:
    """How to make the tuned setting permanent where this machine runs Ollama."""
    if platform.system() == "Darwin":
        return ("macOS Ollama app: run `launchctl setenv OLLAMA_FLASH_ATTENTION 1` and "
                "`launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0`, then quit and reopen Ollama.\n"
                "Started with `ollama serve` or brew: export the same two variables before it starts.")
    return ("systemd: `sudo systemctl edit ollama`, add under [Service] "
            "Environment=\"OLLAMA_FLASH_ATTENTION=1\" and Environment=\"OLLAMA_KV_CACHE_TYPE=q8_0\", "
            "then `sudo systemctl restart ollama`.")


def pick_model(provider: OllamaProvider, wanted: str | None) -> str:
    """The model to test: the one asked for, else the smallest installed (quickest to load twice)."""
    installed = provider.installed()
    if wanted:
        if wanted not in installed:
            raise ProviderError("ollama", f"{wanted} is not installed (clyde --list-models shows what is)")
        return wanted
    if not installed:
        raise ProviderError("ollama", "no models installed; pull one first, e.g. ollama pull qwen3:4b")
    return min(installed, key=installed.get)


def run(console: Console, model: str | None = None, ctx: int | None = None,
        serve: Callable[[dict[str, str]], ContextManager[str]] = _serve) -> int:
    if not shutil.which("ollama"):
        console.print("[red]ollama is not installed or not on PATH.[/red]")
        return 1
    provider = local()
    name, window, results = model, ctx, {}
    try:
        if provider.is_available() and get_json(f"{provider.host}/api/ps", provider="ollama").get("models"):
            console.print("[yellow]Your Ollama has a model loaded; stop it first for a fair memory reading.[/yellow]")
        for label, env in SETTINGS.items():
            with console.status(f"Running {label}…"), serve(env) as host:
                if len(results) == 0:
                    private = OllamaProvider(host=host)
                    name = pick_model(private, model)
                    window = ctx or private.context_window(name)
                    console.print(f"Testing [bold]{name}[/bold] at a {window:,}-token window on two private Ollama "
                                  "servers (yours is not touched). The model loads twice.")
                results[label] = measure(host, name, window)
    except ProviderError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    table = Table(show_header=True, header_style="bold")
    for col in ("Setting", "Memory", "Prompt tok/s", "Generate tok/s"):
        table.add_column(col)
    for label, r in results.items():
        table.add_row(label, f"{r.memory_bytes / 2**30:.2f} GB", f"{r.prompt_tps:.0f}", f"{r.gen_tps:.1f}")
    console.print(table)
    recommend, why = verdict(results[BASELINE], results[TUNED])
    console.print(f"[bold]{'Recommended' if recommend else 'Not recommended'}:[/bold] {why}")
    if recommend:
        console.print(f"\n{apply_hint()}")
    return 0
