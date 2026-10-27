"""/brief and /orchestrate in the REPL.

/brief <request>   Clyde grills you one question at a time until the request is a complete spec.
/orchestrate <task>  list the harnesses and the models each really offers, pick the master, an optional advisor and the
                   workers, get briefed, run (workers side by side, each in its own git worktree, asking you before
                   any command), then decide whether the finished work lands in the outbox.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.prompt import Confirm, Prompt
from rich.table import Table

from src.agent import briefing
from src.agent.harness import RUNNABLE_KINDS, Harness, can_work, discover_all
from src.agent.orchestration import build_plan, format_plan, land, orchestrate
from src.ui.picker import Choice, pick

_NONE, _DONE = "-", "done"


def _need_model(repl: Any) -> bool:
    if repl.provider is None or not repl.model:
        repl.console.print("[red]This needs a model. Set one with /model first.[/red]")
        return False
    return True


def grill(repl: Any, state: briefing.BriefingState) -> briefing.BriefingState:
    """Ask questions until the spec is complete. An empty answer ends the interview with what is known."""
    console = repl.console
    while not state.complete:
        with console.status("[dim]Clyde is thinking…[/dim]", spinner="dots"):
            text, state = briefing.ask_next_question(repl.provider, repl.model, state)
        if state.complete:
            break
        console.print(f"\n[bold]{escape(text)}[/bold]")
        answer = Prompt.ask("[dim]Answer (empty to stop asking)[/dim]", console=console, default="", show_default=False).strip()
        briefing.save_state(state)
        if not answer:
            with console.status("[dim]Writing the spec…[/dim]", spinner="dots"):
                spec = briefing.synthesize_spec(repl.provider, repl.model, state)
            state = briefing.BriefingState(state.initial_request, state.questions_asked, state.answers, spec, True)
            break
        state = briefing.record_answer(state, answer)
        briefing.save_state(state)
    briefing.save_state(state)
    return state


def brief(repl: Any, arg: str) -> None:
    """/brief <request> | continue | spec | clear"""
    console = repl.console
    word = arg.strip().partition(" ")[0]
    if word == "clear":
        briefing.clear_state()
        console.print("Briefing cleared.")
        return
    state = briefing.load_state()
    if word == "spec":
        console.print(escape(state.spec) if state and state.complete and state.spec else "No completed spec yet. Run /brief <request>.")
        return
    if not _need_model(repl):
        return
    if word == "continue":
        if state is None or state.complete:
            console.print("No briefing in progress. Start one with /brief <request>.")
            return
    elif arg.strip():
        state = briefing.start_briefing(arg.strip())
    else:
        console.print("Usage: /brief <request> | continue | spec | clear")
        return
    state = grill(repl, state)
    console.print("\n[bold]Spec[/bold]\n" + escape(state.spec or ""))


def _rows(harnesses: list[Harness]) -> Table:
    table = Table(box=None, pad_edge=False, header_style="bold")
    for col in ("HARNESS", "KIND", "MODELS"):
        table.add_column(col)
    for h in harnesses:
        shown = ", ".join(m.model_id for m in h.models[:4]) + (f" … +{len(h.models) - 4}" if len(h.models) > 4 else "")
        kind = h.kind if h.kind in RUNNABLE_KINDS else f"{h.kind} (worker, files only)" if can_work(h) else f"{h.kind} (cannot run yet)"
        table.add_row(h.name, kind, shown or "no model list")
    return table


def _pick_model(repl: Any, title: str, runnable: list[Harness], *, optional: bool = False, finish: bool = False) -> tuple[str, str] | None | str:
    """(harness name, model id), None when cancelled, or _NONE / _DONE for the extra row."""
    choices = [Choice(f"{h.name}|{m.model_id}", f"{h.name.removeprefix('provider:')} / {m.model_id}",
                      "agent CLI" if h.kind == "cli" else "local" if m.local else "cloud")
               for h in runnable for m in h.models]
    if optional:
        choices.insert(0, Choice(_NONE, "no advisor", "skip the review step"))
    if finish:
        choices.insert(0, Choice(_DONE, "done adding workers", ""))
    value = pick(repl.console, title, choices, header=("MODEL", "WHERE"))
    if value in (None, _NONE, _DONE):
        return value
    name, _, model = value.partition("|")
    return name, model


def _parse_cap(text: str) -> float | None | str:
    """The cap in USD from what the user typed: None for empty (no cap), the number, or why it is not one."""
    text = text.strip().lstrip("$")
    if not text:
        return None
    try:
        cap = float(text)
    except ValueError:
        return "A number of dollars, like 2 or 0.50, or leave it empty for no limit."
    return cap if cap > 0 and cap < 1_000_000 else "More than zero, please."


def _ask_cap(console: Any) -> float | None:
    """Ask for the run's cost cap until it is empty (no cap) or a good number. Only models with a price count towards it."""
    while True:
        cap = _parse_cap(Prompt.ask("[dim]Stop the run if it costs more than (USD; empty for no limit; local models cost nothing, unpriced ones cannot be counted)[/dim]",
                                    console=console, default="", show_default=False))
        if not isinstance(cap, str):
            return cap
        console.print(f"[yellow]{cap}[/yellow]")


def _approval(repl: Any, status: Any):
    def ask(row: dict[str, Any]) -> bool:
        status.stop()
        repl.console.print(f"\n[bold yellow]{escape(row['who'])}[/bold yellow] wants to use [bold]{escape(row['tool'])}[/bold]:\n{escape(row['message'][:800])}")
        allowed = Confirm.ask("Allow?", console=repl.console, default=False)
        status.start()
        return allowed
    return ask


def orchestrate_cmd(repl: Any, arg: str) -> None:
    """/orchestrate <task>"""
    console = repl.console
    task = arg.strip()
    if not task:
        console.print("Usage: /orchestrate <task>\nClyde lists harnesses and models, you pick who leads and who works, "
                      "Clyde briefs you, the team runs, and finished work lands in the outbox once you approve.\n"
                      "Watch a run from another terminal with: clyde station")
        return
    if not _need_model(repl):
        return
    workspace = Path(repl.tool_context.workspace_root)

    harnesses = discover_all()
    leaders = [h for h in harnesses if h.kind in RUNNABLE_KINDS and h.models]
    workers_pool = [h for h in harnesses if can_work(h) and h.models]
    console.print(_rows([h for h in harnesses if h.kind in RUNNABLE_KINDS or h.kind == "cli"]))
    if not leaders:
        console.print("[red]No connected provider has models to run. Connect one with `clyde login`.[/red]")
        return

    master = _pick_model(repl, "Master (leads the team)", leaders)
    if master is None:
        return
    advisor = _pick_model(repl, "Advisor (reviews the workers)", workers_pool, optional=True)
    if advisor is None:
        return
    workers: list[tuple[str, str]] = []
    while True:
        picked = _pick_model(repl, f"Worker {len(workers) + 1}", workers_pool, finish=bool(workers))
        if picked is None:
            return
        if picked == _DONE:
            break
        workers.append(picked)
    plan = build_plan(task, master, None if advisor == _NONE else advisor, workers)
    if isinstance(plan, str):
        console.print(f"[red]{escape(plan)}[/red]")
        return
    console.print("\n" + escape(format_plan(plan)))

    state = grill(repl, briefing.start_briefing(task))
    console.print("\n[bold]Spec[/bold]\n" + escape(state.spec or ""))
    if not Confirm.ask("Run the team on this spec?", console=console, default=True):
        return

    cap = _ask_cap(console)
    from src.agent import panes
    from src.providers import build_registry
    show_panes = bool(panes.tmux_path()) and Confirm.ask("Open a tmux pane for each team member?", console=console, default=False)
    console.print("[dim]Workers run side by side. Watch from another terminal: clyde station (or clyde station web for the browser)[/dim]")
    status = console.status("[dim]Team working…[/dim]", spinner="dots")
    status.start()
    try:
        outcome = orchestrate(plan, state.spec or task, workspace=workspace, parent=repl.tool_context, registry=repl.tool_registry,
                              providers=build_registry(), on_approval=_approval(repl, status),
                              cost_cap=cap, on_start=(lambda run: console.print(f"[dim]{escape(panes.open_panes(run))}[/dim]")) if show_panes else None)
    finally:
        status.stop()
    if isinstance(outcome, str):
        console.print(f"[red]{escape(outcome)}[/red]")
        return
    run = outcome.run
    usd, unpriced = run.total_spend()
    console.print("\n[bold]Report[/bold]\n" + escape(outcome.report))
    for note in outcome.notes:
        console.print(f"[yellow]{escape(note)}[/yellow]")
    if outcome.failed:
        console.print(f"[yellow]Did not finish: {', '.join(outcome.failed)}[/yellow]")
    console.print(f"[dim]Run {run.id} · spend ≈ ${usd:.4f}" + (f" (+{unpriced} call(s) with no price)" if unpriced else "") + f" · {run.root}[/dim]")
    if run.state().get("status") == "stopped":
        return
    if Confirm.ask("Land the finished work in the outbox?", console=console, default=outcome.verdict == "approve"):
        out = land(run, approve=True)
        console.print(f"Landed in [bold]{out}[/bold]. Apply a worker's changes with: git apply {out}/worker-1/changes.patch")
    else:
        land(run, approve=False)
        console.print("Discarded. The run's transcripts and ledger stay in " + str(run.root))
