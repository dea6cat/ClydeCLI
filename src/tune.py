"""`clyde tune`: the best Ollama setup for what the user does, without losing the quality they rely on.

Ollama reads flash attention and the KV-cache type from the server's environment at startup and never
reports them, so every setting is tried on a throwaway `ollama serve` on a free port: the user's own
server is never reconfigured. For each candidate it measures memory and speed, then runs Clyde's own
model eval (tool call, round trip, a few graded tasks) and drops any candidate that scores below the
baseline by more than the profile allows. Among what is left it picks by the profile's priority, and
only if the gain is worth restarting Ollama. Applying the winner is left to the user.
"""
from __future__ import annotations

import difflib
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
from rich.prompt import Confirm
from rich.table import Table

from src import tune_profile
from src.providers import model_eval
from src.providers.base import ProviderError, get_json, post_json
from src.providers.ollama import OllamaProvider, _ctx_env_key, _total_ram_bytes, local
from src.tune_profile import Profile

FLASH = {"OLLAMA_FLASH_ATTENTION": "1"}
# Bytes per cache element against f16, from ggml's block layouts: q8_0 is 8.5 bits, q4_0 4.5 bits.
_KV_SHRINK = {"q8_0": 8.5 / 16, "q4_0": 4.5 / 16}
MEMORY_SLACK = 0.02       # a candidate may not use more than this much extra memory: the point is no more resources
RAM_FRACTION = 0.75       # the share of RAM a model may take (macOS wires about this much for the GPU)
WORTH_MEMORY = 0.05       # worth a restart if it frees this share of memory,
WORTH_CONTEXT = 0.10      # or opens this much more window,
WORTH_SPEED = 0.05        # or runs this much faster
EVAL_RUNS = 1             # the eval only guards tool calling and graded tasks; the probe below catches subtler loss
RECALL_TOKENS = 6000      # how much text the buried-fact probe reads, capped at 70% of the smallest window tested
_STARTUP_S = 20
_PROMPT = "Summarize in one paragraph: " + "The quick brown fox jumps over the lazy dog. " * 120
# Fixed prompts answered greedily (temperature 0, fixed seed): the same model gives the same reply, so any
# difference between two settings is the setting. A lossy cache shows up here long before a graded task fails.
_PROBES = (
    "Write a Python function that merges two sorted lists into one sorted list. Code only.",
    "Explain in three sentences why the sky is blue.",
    "List the first twelve prime numbers and their sum.",
    "Write a Dart class Point with x and y, a distance method, and operator ==.",
)
_NEEDLE = "MAGENTA-4417"


@dataclass(frozen=True)
class Candidate:
    label: str
    env: dict[str, str]
    ctx: int


@dataclass(frozen=True)
class Result:
    memory_bytes: int
    prompt_tps: float
    gen_tps: float


@dataclass(frozen=True)
class Quality:
    passes: int                   # eval runs where the model made and used a tool call
    strength: int                 # graded tasks solved, summed over the runs
    answers: tuple[str, ...] = ()  # greedy replies to _PROBES
    recalled: bool = True         # found the fact buried in a long prompt


@dataclass
class Row:
    cand: Candidate
    perf: Result
    quality: Quality | None = None
    why: str = ""   # why it was dropped; empty means it passed every gate


def kv(kind: str) -> dict[str, str]:
    return {**FLASH, "OLLAMA_KV_CACHE_TYPE": kind}


def candidates(base_ctx: int, trained: int, profile: Profile) -> list[Candidate]:
    """The settings to try. A cheaper cache can also carry a longer window, when the model was trained for one."""
    out = [Candidate("default", {}, base_ctx), Candidate("flash attention", FLASH, base_ctx)]
    for kind in ("q8_0", "q4_0") if profile.allow_q4 else ("q8_0",):
        out.append(Candidate(f"flash + {kind} KV", kv(kind), base_ctx))
        longer = min(trained, int(base_ctx / _KV_SHRINK[kind]) // 1024 * 1024)
        if longer >= base_ctx * (1 + WORTH_CONTEXT):
            out.append(Candidate(f"flash + {kind} KV, {longer:,} window", kv(kind), longer))
    return out


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


def _haystack(tokens: int) -> str:
    filler = "The archive lists routine shipments between depots. " * (tokens * 4 // 52 + 1)
    middle = len(filler) // 2
    return f"{filler[:middle]}The vault passcode is {_NEEDLE}. {filler[middle:]}\n\nWhat is the vault passcode? Answer with the passcode only."


def _greedy(host: str, model: str, ctx: int, prompt: str, predict: int) -> str:
    reply = post_json(f"{host}/api/generate", {
        "model": model, "prompt": prompt, "stream": False, "keep_alive": "2m",
        "options": {"num_ctx": ctx, "num_predict": predict, "temperature": 0, "seed": 1},
    }, timeout=600, provider="ollama")
    return str(reply.get("response") or "")


def grade(host: str, model: str, ctx: int, recall_tokens: int) -> Quality:
    """Clyde's own model eval, then the fixed greedy probes and the buried-fact check at this window."""
    provider = OllamaProvider(host=host)
    provider.pin_context(model, ctx)
    scores = [model_eval.evaluate(provider, model, model) for _ in range(EVAL_RUNS)]
    answers = tuple(_greedy(host, model, ctx, p, 120) for p in _PROBES)
    recalled = _NEEDLE in _greedy(host, model, ctx, _haystack(recall_tokens), 20)
    return Quality(sum(s.passed for s in scores), sum(s.strength or 0 for s in scores), answers, recalled)


def fidelity(base: Quality, got: Quality) -> float:
    """How alike the greedy answers are, 0 to 1: 1 means the setting changed nothing the model says."""
    pairs = list(zip(base.answers, got.answers))
    return sum(difflib.SequenceMatcher(None, a, b).ratio() for a, b in pairs) / len(pairs) if pairs else 1.0


def perf_gate(base: Result, perf: Result, profile: Profile, ram: int) -> str:
    """Why a candidate fails on memory or speed, or ''. Quality is only worth measuring for those that pass."""
    if not (perf.gen_tps and perf.memory_bytes):
        return "no reading"
    if perf.memory_bytes > base.memory_bytes * (1 + MEMORY_SLACK):
        return "uses more memory"
    if ram and perf.memory_bytes + profile.headroom_gb * 2 ** 30 > ram * RAM_FRACTION:
        return f"leaves less than {profile.headroom_gb} GB free"
    if perf.gen_tps < base.gen_tps * (1 - profile.max_slowdown):
        return f"{1 - perf.gen_tps / base.gen_tps:.0%} slower"
    return ""


def quality_gate(base: Quality, got: Quality, profile: Profile) -> str:
    """Why quality is lower than the baseline's by more than the profile allows, or ''."""
    if got.passes < base.passes:
        return "lost tool calling"
    if base.recalled and not got.recalled:
        return "lost long-context recall"
    alike = fidelity(base, got)
    if alike < profile.min_fidelity:
        return f"answers drift from the baseline ({alike:.0%} alike)"
    if got.strength < base.strength - profile.tolerance * EVAL_RUNS:
        return f"quality dropped ({got.strength} vs {base.strength} tasks)"
    return ""


def worth_it(base: Row, row: Row) -> bool:
    """Whether the gain justifies restarting Ollama with new settings."""
    return (row.perf.memory_bytes <= base.perf.memory_bytes * (1 - WORTH_MEMORY)
            or row.cand.ctx >= base.cand.ctx * (1 + WORTH_CONTEXT)
            or row.perf.gen_tps >= base.perf.gen_tps * (1 + WORTH_SPEED))


_PRIORITY_KEY: dict[str, Callable[[Row], tuple]] = {
    "context": lambda r: (r.cand.ctx, r.perf.gen_tps, -r.perf.memory_bytes),
    "speed": lambda r: (r.perf.gen_tps, r.cand.ctx, -r.perf.memory_bytes),
    "reliability": lambda r: (r.quality.strength if r.quality else 0, -r.perf.memory_bytes, r.cand.ctx),
}


def choose(rows: list[Row], profile: Profile) -> Row:
    """The best row that passed every gate and is worth the restart; the baseline (rows[0]) when none is."""
    base = rows[0]
    for row in rows[1:]:
        if not row.why and not worth_it(base, row):
            row.why = "no real gain"
    passed = [r for r in rows[1:] if not r.why]
    return max(passed, key=_PRIORITY_KEY[profile.priority], default=base)


def apply_hint(env: dict[str, str], model: str, ctx: int, base_ctx: int) -> str:
    """How to make a setting permanent where this machine runs Ollama."""
    lines = []
    if platform.system() == "Darwin":
        lines += [f"launchctl setenv {k} {v}" for k, v in env.items()]
        lines.append("then quit and reopen the Ollama app (if you start it with `ollama serve`, export the same variables first).")
    else:
        lines.append("sudo systemctl edit ollama, and under [Service] add: " + " ".join(f'Environment="{k}={v}"' for k, v in env.items()))
        lines.append("then sudo systemctl restart ollama.")
    if ctx != base_ctx:
        lines.append(f"For the longer window, also set export CLYDE_MODEL_CONTEXT_{_ctx_env_key(model)}={ctx} in your shell profile.")
    return "\n".join(lines)


def unload_loaded(console: Console, provider: OllamaProvider) -> bool:
    """The user's own Ollama may hold a model in memory, which would skew the readings. Say so, and unload it after a yes."""
    if not provider.is_available():
        return True
    loaded = [m.get("name") or m.get("model") for m in get_json(f"{provider.host}/api/ps", provider="ollama").get("models") or []]
    if not loaded:
        return True
    console.print(f"[yellow]Your Ollama has {', '.join(map(str, loaded))} loaded.[/yellow] To keep the test fair, Clyde will unload it "
                  "while it runs two temporary servers on other ports. Your Ollama keeps running and loads the model again on its next request.")
    if not Confirm.ask("Unload it and continue?", default=True):
        return False
    for name in loaded:
        post_json(f"{provider.host}/api/generate", {"model": name, "keep_alive": 0}, timeout=30, provider="ollama")
    return True


def pick_model(provider: OllamaProvider, wanted: str | None) -> str:
    """The model to test: the one asked for, else the smallest installed (quickest to load several times)."""
    installed = provider.installed()
    if wanted:
        if wanted not in installed:
            raise ProviderError("ollama", f"{wanted} is not installed (clyde --list-models shows what is)")
        return wanted
    if not installed:
        raise ProviderError("ollama", "no models installed; pull one first, e.g. ollama pull qwen3:4b")
    return min(installed, key=installed.get)


def _show(console: Console, rows: list[Row], chosen: Row) -> None:
    base = rows[0].quality
    table = Table(show_header=True, header_style="bold")
    for col in ("Setting", "Window", "Memory", "Gen tok/s", "Quality", "Result"):
        table.add_column(col)
    for r in rows:
        q = f"{r.quality.strength} tasks, {fidelity(base, r.quality):.0%} alike" if r.quality and base else "-"
        verdict = "[green]chosen[/green]" if r is chosen else "baseline" if r is rows[0] else (r.why or "ok, not the best")
        table.add_row(r.cand.label, f"{r.cand.ctx:,}", f"{r.perf.memory_bytes / 2 ** 30:.2f} GB", f"{r.perf.gen_tps:.1f}", q, verdict)
    console.print(table)


def run(console: Console, model: str | None = None, ctx: int | None = None, reask: bool = False,
        serve: Callable[[dict[str, str]], ContextManager[str]] = _serve) -> int:
    if not shutil.which("ollama"):
        console.print("[red]ollama is not installed or not on PATH.[/red]")
        return 1
    try:
        profile = (None if reask else tune_profile.load()) or tune_profile.ask(console)
    except (EOFError, KeyboardInterrupt):
        console.print("[red]clyde tune asks what you use the model for; run it in a terminal.[/red]")
        return 1
    provider, ram = local(), _total_ram_bytes()
    rows: list[Row] = []
    name, plan, recall_tokens = model, [], 0
    try:
        if not unload_loaded(console, provider):
            console.print("Stopped. Nothing was changed.")
            return 1
        i = 0
        while i == 0 or i < len(plan):
            label = plan[i].label if plan else "default"
            with console.status(f"Testing {label}…"), serve(plan[i].env if plan else {}) as host:
                if not plan:
                    private = OllamaProvider(host=host)
                    name = pick_model(private, model)
                    base_ctx = ctx or private.context_window(name)
                    plan = candidates(base_ctx, private.trained_context(name), profile)
                    recall_tokens = min(RECALL_TOKENS, int(base_ctx * 0.7))
                    console.print(f"Tuning [bold]{name}[/bold] for {', '.join(profile.uses)} (priority: {profile.priority}). "
                                  f"{len(plan)} settings, each loaded and graded: this takes a few minutes.")
                    _generate(host, name, base_ctx, 1, "Hi")   # the first load of a model reads low on memory; measure the second
                    continue
                cand = plan[i]
                row = Row(cand, measure(host, name, cand.ctx))
                if rows:
                    row.why = perf_gate(rows[0].perf, row.perf, profile, ram)
                if i == 0 or not row.why:
                    row.quality = grade(host, name, cand.ctx, recall_tokens)
                    if i:
                        row.why = quality_gate(rows[0].quality, row.quality, profile)
                rows.append(row)
            i += 1
    except ProviderError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    chosen = choose(rows, profile)
    _show(console, rows, chosen)
    if chosen is rows[0]:
        console.print("[bold]Keep your current setup.[/bold] Nothing tested was better without costing memory, speed or quality.")
    else:
        console.print(f"[bold]Recommended: {chosen.cand.label}.[/bold]\n{apply_hint(chosen.cand.env, name, chosen.cand.ctx, rows[0].cand.ctx)}")
    tune_profile.save(profile, {"model": name, "ctx": chosen.cand.ctx, "env": chosen.cand.env})
    return 0
