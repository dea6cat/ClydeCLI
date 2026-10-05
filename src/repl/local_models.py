"""/models local [ollama|hf|mlx] [query]: find local models that fit this machine, rate how hard
they'd run (relax, balance, hard), and download the chosen one with the app that runs it: Ollama
for ollama.com models, LM Studio for MLX, and Ollama or else LM Studio for Hugging Face GGUF.
The machine's numbers come first and every download is confirmed with what it will cost, so
nothing heavy lands by surprise; /eval runs afterwards only when asked, so cardShuffle can deal it."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from src.providers import discover, fit, huggingface, mlx
from src.providers.base import ProviderError, post_stream
from src.providers.lmstudio import _lms, model_files
from src.providers.model_eval import HAND, evaluate, save_results

# Each source: search(query, budget) -> list[fit.Offer]. Add one by adding a module and a line here.
SOURCES: dict[str, Callable[[str, int], list[fit.Offer]]] = {
    "ollama": discover.search,
    "hf": huggingface.search,
    "mlx": mlx.search,   # Apple Silicon only
}
_SHOWN = 15            # rows from one source
_SHOWN_EACH = 8        # rows per source when searching them all
_RATING_STYLE = {"relax": "#4eba65", "balance": "#e0b341", "hard": "#d0202f"}


def _gb(n: int | None) -> str:
    return "unknown" if n is None else f"{n / fit.GB:.1f} GB"


def _machine(budget: int, chip: str) -> Text:
    """What this machine has, read before anything is searched or pulled."""
    from src.providers.ollama import _total_ram_bytes

    return Text.assemble(
        (f"{chip or 'This machine'}", "bold"), (f" · {_gb(_total_ram_bytes())} RAM", ""),
        (f" · {_gb(budget)} usable by models", "bold"), (f" · {_gb(fit.free_now_bytes())} free right now", ""),
        (f" · {_gb(fit.disk_free_bytes())} disk free\n", ""),
        ("relax ≤50% · balance ≤80% · hard ≤100% of the usable memory; speed is a rough estimate", "dim"))


def _confirm(repl: Any, offer: fit.Offer, budget: int, chip: str) -> bool:
    """Lay out what pulling `offer` costs on this machine and ask; hard models default to no."""
    disk, free = fit.disk_free_bytes(), fit.free_now_bytes()
    if disk is not None and offer.size_bytes > disk:
        repl.console.print(f"[red]Not enough disk:[/red] {offer.pull_tag} is {_gb(offer.size_bytes)}, "
                           f"and only {_gb(disk)} is free in {fit.models_dir()}.")
        return False
    loaded = offer.size_bytes + fit.OVERHEAD
    speed = fit.tokens_per_s(offer.size_bytes, chip, offer.name)
    lines = [
        Text.assemble(("Download ", ""), (offer.pull_tag, "bold"), ("  ", ""), (offer.rating, _RATING_STYLE[offer.rating])),
        Text(f"  download   {_gb(offer.size_bytes)} ({_gb(disk)} disk free)"),
        Text(f"  when run   ~{_gb(loaded)}, {fit.share(offer.size_bytes, budget):.0%} of the {_gb(budget)} models can use"
             + (f"; {_gb(free)} is free right now" if free is not None else "")),
        Text(f"  speed      ~{speed} tok/s" if speed else "  speed      unknown on this machine"),
        Text(f"  means      {fit.MEANING[offer.rating]}", style=_RATING_STYLE[offer.rating]),
    ]
    if free is not None and loaded > free:
        lines.append(Text(f"  right now  more than is free: close apps to free {_gb(loaded - free)} before running it", style="dim"))
    for line in lines:
        repl.console.print(line)
    with repl._esc.paused():
        return Confirm.ask("Download it?", default=offer.rating != "hard", console=repl.console)


def _count(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1e3 else str(n)


def _table(offers: list[fit.Offer], chip: str) -> Table:
    table = Table(box=None, pad_edge=False, show_edge=False, header_style="dim")
    table.add_column("#", justify="right")
    table.add_column("fit", no_wrap=True)
    table.add_column("from", style="dim", no_wrap=True)
    table.add_column("model", overflow="fold")
    for col in ("size", "~tok/s", "pulls"):
        table.add_column(col, justify="right", no_wrap=True)
    table.add_column("note", style="dim", no_wrap=True)
    for i, o in enumerate(offers, 1):
        speed = fit.tokens_per_s(o.size_bytes, chip, o.name)
        table.add_row(str(i), Text(o.rating, style=_RATING_STYLE[o.rating]), o.source, o.pull_tag, f"{o.size_bytes / fit.GB:.1f} GB",
                      str(speed) if speed else "-", _count(o.popularity), o.note)
    return table


def _runner(repl: Any, offer: fit.Offer) -> str | None:
    """The app that will download and run `offer`: "ollama" or "lmstudio", or None when neither can."""
    ollama = repl.registry.get("ollama")
    ollama_up = ollama is not None and ollama.is_available()
    if offer.source == "mlx":
        return "lmstudio" if _lms() else None
    if offer.source == "hf" and not ollama_up:
        return "lmstudio" if _lms() else None
    return "ollama" if ollama_up else None


_NO_RUNNER = {
    "mlx": "MLX models run in LM Studio, which isn't installed. Get it from lmstudio.ai, then try again.",
    "hf": "Hugging Face GGUF models need Ollama (running) or LM Studio. Start or install one, then try again.",
    "ollama": "ollama.com models need Ollama. Install it from ollama.com (or start it with `ollama serve`), then try again.",
}


def show(repl: Any, arg: str) -> None:
    """List what fits, then offer to download a row. A first word naming a source searches only it;
    otherwise every source this machine can run is searched, with the whole argument (possibly
    empty) as the query."""
    budget, chip = fit.budget_bytes(), fit.chip()
    first, _, rest = arg.strip().partition(" ")
    if first in SOURCES:
        names, query = [first], rest.strip()
    else:
        names, query = [n for n in SOURCES if n != "mlx" or chip.startswith("Apple")], arg.strip()
    shown = _SHOWN if len(names) == 1 else _SHOWN_EACH
    repl.console.print(_machine(budget, chip))
    with repl.console.status(f"[dim]Searching {', '.join(names)} for models that fit…[/dim]", spinner="dots"):
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            found = pool.map(lambda name: SOURCES[name](query, budget)[:shown], names)
            offers = [o for rows in found for o in rows]
    if not offers:
        repl.console.print(f"Nothing from {' or '.join(names)} fits {budget / fit.GB:.0f} GB" + (f" for '{query}'." if query else ".")
                           + " Try other search words.")
        return
    repl.console.print(_table(offers, chip))
    with repl._esc.paused():
        choice = Prompt.ask("Download which # (Enter to skip)", default="", show_default=False, console=repl.console).strip()
    if not choice:
        return
    if not choice.isdigit() or not 1 <= int(choice) <= len(offers):
        repl.console.print(f"No row {choice}.")
        return
    offer = offers[int(choice) - 1]
    runner = _runner(repl, offer)
    if runner is None:
        repl.console.print(_NO_RUNNER[offer.source])
        return
    if not _confirm(repl, offer, budget, chip):
        return
    if runner == "ollama":
        _pull_ollama(repl, offer)
    else:
        _get_lmstudio(repl, offer)


def lms_target(offer: fit.Offer) -> tuple[str, str]:
    """(what `lms get` takes, its format flag). A GGUF quant is pinned with `@<quant>`, so LM Studio
    downloads exactly the file that was rated, never a variant of its own choosing."""
    if offer.source == "mlx":
        return offer.pull_tag, "--mlx"
    repo, _, quant = offer.pull_tag.removeprefix("hf.co/").rpartition(":")
    return f"https://huggingface.co/{repo}@{quant}", "--gguf"


def _pull_ollama(repl: Any, offer: fit.Offer) -> None:
    """Pull through Ollama's API with progress."""
    ollama, tag = repl.registry["ollama"], offer.pull_tag
    try:
        with repl.console.status(f"[dim]Pulling {tag}…[/dim]", spinner="dots") as status:
            for line in post_stream(f"{ollama.host}/api/pull", {"model": tag, "stream": True}, provider="ollama"):
                event = json.loads(line) if line.strip() else {}
                if event.get("error"):
                    raise ProviderError("ollama", event["error"])
                total, done = event.get("total"), event.get("completed")
                progress = f" {done / total:.0%} of {total / fit.GB:.1f} GB" if total and done else ""
                status.update(f"[dim]Pulling {tag}: {event.get('status', '')}{progress}[/dim]")
    except (ProviderError, ValueError) as e:
        repl.console.print(f"[red]Download failed:[/red] {e}")
        return
    except KeyboardInterrupt:
        repl.console.print("Download stopped. Running it again resumes it.")
        return
    ollama.__dict__.pop("_models_cache", None)
    repl.console.print(f"[green]✓ Downloaded ollama:{tag}[/green]")
    _offer_eval(repl, ollama, tag, offer.rating)


def _get_lmstudio(repl: Any, offer: fit.Offer) -> None:
    """Download with `lms get` (LM Studio's own progress bar shows), then find the new model."""
    lmstudio = repl.registry.get("lmstudio")
    target, fmt = lms_target(offer)
    lmstudio.__dict__.pop("_models_cache", None)
    before = set(lmstudio.list_models())
    repl.console.print(f"[dim]Downloading through LM Studio: lms get {target} {fmt}[/dim]")
    try:
        with repl._esc.paused():
            done = subprocess.run([_lms(), "get", target, fmt, "-y"])
    except KeyboardInterrupt:
        repl.console.print("Download stopped.")
        return
    if done.returncode != 0:
        repl.console.print(f"[red]Download failed[/red] (lms exited with {done.returncode}).")
        return
    lmstudio.__dict__.pop("_models_cache", None)
    new = sorted(set(lmstudio.list_models()) - before)
    if len(new) != 1:
        repl.console.print("[green]✓ Downloaded.[/green] Find it under lmstudio in /models, then run /eval lmstudio on it.")
        return
    repl.console.print(f"[green]✓ Downloaded lmstudio:{new[0]}[/green]")
    _offer_eval(repl, lmstudio, new[0], offer.rating)


def _offer_eval(repl: Any, provider: Any, model: str, rating: str) -> None:
    """Ask before /eval loads the model (the heavy part); hard models default to no."""
    ref = f"{provider.name}:{model}"
    with repl._esc.paused():
        test = Confirm.ask(f"Run /eval on it now? It loads the model ({rating})", default=rating != "hard", console=repl.console)
    if not test:
        repl.console.print(f"Skipped. Run /eval {ref} when you're ready; cardShuffle deals it only after it passes.")
        return
    with repl.console.status(f"[dim]Running /eval on {ref}…[/dim]", spinner="dots"):
        score = evaluate(provider, model, ref)
    save_results([score])
    if score.passed:
        repl.console.print(f"[green]✓ {ref} passed /eval[/green] · hand {score.strength}/{len(HAND)} · "
                           f"use it with /model {ref}, or let cardShuffle:free deal it")
    else:
        repl.console.print(f"[yellow]{ref} is installed but failed /eval ({score.short_note or score.error}),[/yellow] "
                           "so cardShuffle won't deal it.")


@dataclass(frozen=True)
class Installed:
    """A model on disk. `remove` is None when it can't be deleted from here, with `why` saying so."""
    provider: str
    name: str
    size: int
    remove: Callable[[], None] | None
    why: str = ""

    @property
    def ref(self) -> str:
        return f"{self.provider}:{self.name}"


def _remove_files(path: Any) -> None:
    """Delete a model folder, or a single file plus its folder once nothing else is left in it."""
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()
    for folder in (path.parent, path.parent.parent):   # ponytail: stray non-model files keep the folder; fine
        try:
            folder.rmdir()
        except OSError:
            return


def installed(repl: Any) -> list[Installed]:
    """Every model Ollama and LM Studio have on this machine."""
    found: list[Installed] = []
    ollama = repl.registry.get("ollama")
    if ollama is not None and ollama.is_available():
        found += [Installed("ollama", name, size, lambda n=name: ollama.delete_model(n)) for name, size in ollama.installed().items()]
    lmstudio = repl.registry.get("lmstudio")
    if lmstudio is not None:
        for entry in lmstudio.downloaded():
            files = model_files(entry)
            found.append(Installed("lmstudio", entry["modelKey"], int(entry.get("sizeBytes") or 0),
                                   (lambda f=files: _remove_files(f)) if files else None,
                                   "" if files else "its folder can't be found; remove it in LM Studio's My Models"))
    return found


def purge(repl: Any, arg: str) -> None:
    """/purge deletes every local model; /purge <name> only those whose name (or provider:name) contains it.
    Always confirmed with the space it frees, defaulting to no."""
    query = arg.strip().lower()
    models = [m for m in installed(repl) if query in m.ref.lower()]
    if not models:
        repl.console.print(f"No local model matches '{arg.strip()}'." if query else "No local models found in Ollama or LM Studio.")
        return
    removable = [m for m in models if m.remove]
    for m in models:
        repl.console.print(f"  {m.ref}  [dim]{_gb(m.size)}" + (f" · skipped: {m.why}" if not m.remove else "") + "[/dim]")
    if not removable:
        return
    freed = sum(m.size for m in removable)
    with repl._esc.paused():
        if not Confirm.ask(f"Delete {len(removable)} model(s) from disk, freeing {_gb(freed)}? This can't be undone",
                           default=False, console=repl.console):
            return
    current = f"{repl.provider.name}:{repl.model}"
    for m in removable:
        try:
            m.remove()
        except Exception as e:
            repl.console.print(f"[red]Couldn't delete {m.ref}:[/red] {e}")
            continue
        repl.console.print(f"[green]✓ Deleted {m.ref}[/green]")
        if m.ref == current:
            repl.console.print("[yellow]That was the active model; pick another with /model.[/yellow]")
    for name in ("ollama", "lmstudio"):
        if (provider := repl.registry.get(name)) is not None:
            provider.__dict__.pop("_models_cache", None)
