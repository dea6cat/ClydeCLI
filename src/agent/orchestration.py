"""Orchestration: master/advisor/worker roles over discovered harnesses.

Clyde sits at the center. The user picks:
- Master: owns the request, approves edits, final say
- Advisor: consults, reviews worker output, suggests changes (read-leaning)
- Workers: execute, read + edit

Each role can use the same harness with a different model. Clyde opens each
harness in its assigned role and coordinates between them.

Workers run in parallel. Their output goes to the advisor for review, then
to the master for approval before anything is written.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.agent.briefing import BriefingState
from src.agent.harness import Harness, discover_all, harness_by_name


@dataclass(frozen=True)
class RoleAssignment:
    """One role in the orchestration."""
    role: str  # "master", "advisor", "worker"
    harness: Harness
    model: str


@dataclass(frozen=True)
class OrchestrationPlan:
    """The full orchestration setup."""
    task: str
    master: RoleAssignment | None = None
    advisor: RoleAssignment | None = None
    workers: list[RoleAssignment] = field(default_factory=list)
    briefing_state: BriefingState | None = None
    status: str = "planning"  # planning, running, complete, stopped


@dataclass(frozen=True)
class WorkerResult:
    """Result from one worker."""
    worker: RoleAssignment
    output: str
    is_error: bool = False


def select_models_for_harness(harness: Harness) -> list[str]:
    """Return the model ids a harness offers."""
    return [m.model_id for m in harness.models] or ["default"]


def build_plan(
    task: str,
    master_name: str | None,
    master_model: str | None,
    advisor_name: str | None,
    advisor_model: str | None,
    worker_pairs: list[tuple[str, str]],
    briefing_state: BriefingState | None = None,
) -> OrchestrationPlan | str:
    """Build an orchestration plan from role selections. Returns plan or error string."""
    harnesses = discover_all()
    master = None
    advisor = None
    workers: list[RoleAssignment] = []

    if master_name:
        h = harness_by_name(harnesses, master_name)
        if h is None:
            return f"Master harness '{master_name}' not found. Run /harness list."
        model = master_model or (select_models_for_harness(h)[0] if h.models else "default")
        master = RoleAssignment(role="master", harness=h, model=model)

    if advisor_name:
        h = harness_by_name(harnesses, advisor_name)
        if h is None:
            return f"Advisor harness '{advisor_name}' not found. Run /harness list."
        model = advisor_model or (select_models_for_harness(h)[0] if h.models else "default")
        advisor = RoleAssignment(role="advisor", harness=h, model=model)

    for w_name, w_model in worker_pairs:
        h = harness_by_name(harnesses, w_name)
        if h is None:
            return f"Worker harness '{w_name}' not found. Run /harness list."
        model = w_model or (select_models_for_harness(h)[0] if h.models else "default")
        workers.append(RoleAssignment(role="worker", harness=h, model=model))

    if not master:
        return "No master assigned. Pick a master harness with /orchestrate --master <name> <model>."

    return OrchestrationPlan(
        task=task,
        master=master,
        advisor=advisor,
        workers=workers,
        briefing_state=briefing_state,
        status="planning",
    )


def format_plan(plan: OrchestrationPlan) -> str:
    """Format an orchestration plan for display."""
    lines = [f"# Orchestration Plan: {plan.task}", ""]
    if plan.master:
        lines.append(f"**Master:** {plan.master.harness.name} / {plan.master.model}")
    if plan.advisor:
        lines.append(f"**Advisor:** {plan.advisor.harness.name} / {plan.advisor.model}")
    if plan.workers:
        lines.append("**Workers:**")
        for w in plan.workers:
            lines.append(f"  - {w.harness.name} / {w.model}")
    lines.append("")
    lines.append(f"Status: {plan.status}")
    return "\n".join(lines)


async def run_worker(worker: RoleAssignment, task: str, advisor_input: str = "") -> WorkerResult:
    """Run one worker harness on a task. Placeholder: actual harness invocation comes next."""
    # This is a stub. Real implementation would launch the harness as a sub-process
    # or send the task to its model via the provider.
    return WorkerResult(
        worker=worker,
        output=f"[worker {worker.harness.name}/{worker.model}] processed: {task[:80]}...",
        is_error=False,
    )


async def orchestrate(plan: OrchestrationPlan) -> str:
    """Run the orchestration: workers in parallel, advisor reviews, master approves."""
    if plan.status != "planning":
        return f"Orchestration already {plan.status}."

    # Run all workers in parallel
    worker_tasks = [run_worker(w, plan.task) for w in plan.workers]
    worker_results = await asyncio.gather(*worker_tasks) if worker_tasks else []

    # Advisor reviews (if advisor exists)
    advisor_review = ""
    if plan.advisor:
        all_output = "\n".join(r.output for r in worker_results)
        advisor_review = f"[advisor {plan.advisor.harness.name}/{plan.advisor.model}] reviewed worker output:\n{all_output[:500]}..."

    # Master approves
    master_decision = f"[master {plan.master.harness.name}/{plan.master.model}] approved execution."

    return (
        f"# Orchestration Complete\n\n"
        f"**Task:** {plan.task}\n\n"
        f"**Workers:** {len(worker_results)} completed\n\n"
        f"**Advisor Review:**\n{advisor_review or '(none)'}\n\n"
        f"**Master Decision:**\n{master_decision}"
    )
