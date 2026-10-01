"""/models local <source> [query]: find local models that fit this machine, rate how hard they'd
run (relax, balance, hard), and pull the chosen one through Ollama. The machine's numbers come
first and every pull is confirmed with what it will cost, so nothing heavy lands by surprise;
/eval runs afterwards only when asked, so cardShuffle can deal the model."""

from __future__ import annotations

import json
from typing import Any, Callable

from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from src.providers import discover, fit, huggingface
from src.providers.base import ProviderError, post_stream
from src.providers.model_eval import HAND, evaluate, save_results

# Each source: search(query, budget) -> list[fit.Offer]. Add one by adding a module and a line here.
SOURCES: dict[str, Callable[[str, int], list[fit.Offer]]] = {
    "ollama": discover.search,
    "hf": huggingface.search,
}
_SHOWN = 15
_RATING_STYLE = {"relax": "#4eba65", "balance": "#e0b341", "hard": "#d0202f"}
_USAGE = "Usage: /models local ollama|hf [search words]   e.g. /models local hf qwen coder"


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
        Text.assemble(("Pull ", ""), (offer.pull_tag, "bold"), ("  ", ""), (offer.rating, _RATING_STYLE[offer.rating])),
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
    table.add_column("model", overflow="fold")
    for col in ("size", "~tok/s", "pulls"):
        table.add_column(col, justify="right", no_wrap=True)
    table.add_column("note", style="dim", no_wrap=True)
    for i, o in enumerate(offers, 1):
        speed = fit.tokens_per_s(o.size_bytes, chip, o.name)
        table.add_row(str(i), Text(o.rating, style=_RATING_STYLE[o.rating]), o.pull_tag, f"{o.size_bytes / fit.GB:.1f} GB",
                      str(speed) if speed else "-", _count(o.popularity), o.note)
    return table


def show(repl: Any, arg: str) -> None:
    """List what fits from one source, then offer to pull a row."""
    source, _, query = arg.strip().partition(" ")
    search = SOURCES.get(source)
    if search is None:
        repl.console.print(_USAGE)
        return
    budget, chip = fit.budget_bytes(), fit.chip()
    repl.console.print(_machine(budget, chip))
    with repl.console.status(f"[dim]Searching {source} for models that fit…[/dim]", spinner="dots"):
        offers = search(query.strip(), budget)[:_SHOWN]
    if not offers:
        repl.console.print(f"Nothing from {source} fits {budget / fit.GB:.0f} GB" + (f" for '{query.strip()}'." if query.strip() else ".")
                           + " Try other search words, or the other source.")
        return
    repl.console.print(_table(offers, chip))
    with repl._esc.paused():
        choice = Prompt.ask("Pull which # (Enter to skip)", default="", show_default=False, console=repl.console).strip()
    if not choice:
        return
    if not choice.isdigit() or not 1 <= int(choice) <= len(offers):
        repl.console.print(f"No row {choice}.")
        return
    offer = offers[int(choice) - 1]
    if _confirm(repl, offer, budget, chip):
        pull(repl, offer.pull_tag, offer.rating)


def pull(repl: Any, tag: str, rating: str) -> None:
    """Pull `tag` through Ollama with progress, then offer to /eval it (loading it is the heavy part)."""
    ollama = repl.registry.get("ollama")
    if ollama is None or not ollama.is_available():
        repl.console.print("Ollama isn't running. Start it with `ollama serve`, then try again.")
        return
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
        repl.console.print(f"[red]Pull failed:[/red] {e}")
        return
    except KeyboardInterrupt:
        repl.console.print("Pull stopped. Running it again resumes the download.")
        return
    ollama.__dict__.pop("_models_cache", None)
    repl.console.print(f"[green]✓ Pulled ollama:{tag}[/green]")
    with repl._esc.paused():
        test = Confirm.ask(f"Run /eval on it now? It loads the model ({rating})", default=rating != "hard", console=repl.console)
    if not test:
        repl.console.print(f"Skipped. Run /eval ollama:{tag} when you're ready; cardShuffle deals it only after it passes.")
        return
    with repl.console.status(f"[dim]Running /eval on ollama:{tag}…[/dim]", spinner="dots"):
        score = evaluate(ollama, tag, f"ollama:{tag}")
    save_results([score])
    if score.passed:
        repl.console.print(f"[green]✓ ollama:{tag} passed /eval[/green] · hand {score.strength}/{len(HAND)} · "
                           f"use it with /model ollama:{tag}, or let cardShuffle:free deal it")
    else:
        repl.console.print(f"[yellow]ollama:{tag} is installed but failed /eval ({score.short_note or score.error}),[/yellow] "
                           "so cardShuffle won't deal it.")
