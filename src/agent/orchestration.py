"""Orchestration: Clyde coordinates a master, an advisor and workers, each a real model call.

Clyde (the orchestrator) takes the briefed spec. The master splits it into one task per worker; every worker is a
sub-agent loop on its own git worktree, with its own transcript, spend and approvals, running at the same time as the
others. The advisor reviews what the workers produced, the master writes the report, and nothing leaves the
worktrees until the user approves: then the changes land as real files in the outbox (see `land`).

A role is a connected provider and one of the models it really lists (agent/harness.py). Other agent CLIs are
discovered but cannot be run yet. Local models (Ollama, oMLX) run their workers one at a time: this Mac cannot hold
two at once. Everything a run does is written under ~/.clyde/runs/<id>/ as it happens (agent/runs.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.agent.agent_types import GENERAL, AgentType
from src.agent.conversation import Conversation as History
from src.agent import cli_workers
from src.agent.harness import LOCAL_PROVIDERS, RUNNABLE_KINDS, Harness, can_work, discover_all, harness_by_name
from src.agent.runs import Run, outbox_dir
from src.providers.base import stream_with_retry
from src.providers.types import Conversation, Message
from src.security.git_safe import git_cmd, git_env
from src.tool_system.context import ToolContext
from src.tool_system.permissions import ToolPermissionContext
from src.tool_system.tools.agent import run_agent

_PATCH_CHARS = 20_000      # of one worker's patch shown to the advisor
_SUMMARY_CHARS = 6_000     # of one worker's final answer shown to the advisor and the master

SPLIT_SYSTEM = """You are the master of a small team. Split the spec into one self-contained task per worker. Each worker
has its own copy of the repository and cannot see the others' work, so tasks must not depend on each other and must
not edit the same files. Answer with only JSON: {"tasks": ["task for worker 1", ...]} with exactly the requested count."""
REVIEW_SYSTEM = """You are the advisor. Review the workers' results against the spec: is each task done, is anything
missing or risky, do the changes collide. Be specific and short. You cannot run anything; judge from the summaries and patches."""
REPORT_SYSTEM = """You are the master. Write the final report for the user in a few short paragraphs: what was done, what
the advisor flagged, what remains. End with a last line that is exactly VERDICT: APPROVE or VERDICT: REVISE."""
WORKER_PROMPT = """You work alone in your own git worktree; the rest of the team cannot see it. Do your task with the
tools you have, then finish with a short summary of what you changed and anything you could not do. Do not ask the
user questions: decide, and say what you assumed."""


@dataclass(frozen=True)
class RoleAssignment:
    role: str  # "master", "advisor", "worker"
    harness: Harness
    model: str

    @property
    def provider_name(self) -> str:
        return self.harness.name.removeprefix("provider:")

    @property
    def ref(self) -> str:
        return f"{self.provider_name}:{self.model}"


@dataclass(frozen=True)
class OrchestrationPlan:
    task: str
    master: RoleAssignment
    advisor: RoleAssignment | None = None
    workers: list[RoleAssignment] = field(default_factory=list)


@dataclass(frozen=True)
class Outcome:
    run: Run
    report: str
    verdict: str        # "approve", "revise" or "none" (the master gave none)
    failed: list[str]   # workers that did not finish
    notes: list[str] = field(default_factory=list)   # things the user should know: a split that fell back


Picks = tuple[str, str]   # (harness name, model id)


def build_plan(task: str, master: Picks | None, advisor: Picks | None, workers: list[Picks],
               harnesses: list[Harness] | None = None) -> OrchestrationPlan | str:
    """A plan from role picks, or the reason it can't be built."""
    harnesses = discover_all() if harnesses is None else harnesses

    def assign(role: str, pick: Picks) -> RoleAssignment | str:
        name, model = pick
        harness = harness_by_name(harnesses, name)
        if harness is None:
            return f"{role.capitalize()} '{name}' not found. Run /harness list."
        if role != "worker" and harness.kind not in RUNNABLE_KINDS:
            return f"{name} is a {harness.kind} harness; the {role} needs a provider model (an agent CLI can be a worker)."
        if not can_work(harness):
            return f"{name} is a {harness.kind} harness Clyde can't run as a {role} yet."
        if model not in [m.model_id for m in harness.models]:
            return f"{name} has no model '{model}'. Run /harness {name}."
        return RoleAssignment(role, harness, model)

    if master is None:
        return "No master picked."
    if not workers:
        return "No workers picked."
    made = [assign("master", master), *([assign("advisor", advisor)] if advisor else []), *(assign("worker", w) for w in workers)]
    for item in made:
        if isinstance(item, str):
            return item
    return OrchestrationPlan(task=task, master=made[0], advisor=made[1] if advisor else None,
                             workers=made[2 if advisor else 1:])


def format_plan(plan: OrchestrationPlan) -> str:
    lines = [f"Master:  {plan.master.ref}"]
    if plan.advisor:
        lines.append(f"Advisor: {plan.advisor.ref}")
    lines += [f"Worker {i}: {w.ref}" for i, w in enumerate(plan.workers, 1)]
    if any(r.provider_name in LOCAL_PROVIDERS for r in _roles(plan)):
        lines.append("A local model is in this plan: workers will run one at a time.")
    return "\n".join(lines)


def _roles(plan: OrchestrationPlan) -> list[RoleAssignment]:
    return [plan.master, *([plan.advisor] if plan.advisor else []), *plan.workers]


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(git_cmd(*args), cwd=cwd, env=git_env(), capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def repo_root(start: Path) -> Path | str:
    """The git repository around `start`, or why workers can't get their own copy."""
    try:
        root = Path(_git(start, "rev-parse", "--show-toplevel").strip())
        _git(root, "rev-parse", "--verify", "HEAD")
    except (RuntimeError, OSError):
        return "Workers each get their own git worktree: run this inside a git repository that has a commit."
    return root


def _model_text(provider: Any, model: str, system: str, prompt: str, run: Run, who: str) -> str:
    """One tool-free model call; its spend goes in the run's ledger."""
    response = stream_with_retry(provider, Conversation(system_prompt=system, messages=[Message.user(prompt)]),
                                 model, (), lambda _c: None, reasoning="off")
    run.spend(who, f"{provider.name}:{model}", response.usage)
    return response.message.text or ""


def _split(text: str, count: int) -> list[str] | None:
    """The master's per-worker tasks, or None when the answer isn't `count` non-empty strings."""
    start, end = text.find("{"), text.rfind("}")
    try:
        tasks = json.loads(text[start:end + 1])["tasks"] if 0 <= start < end else None
    except (ValueError, KeyError, TypeError):
        return None
    ok = isinstance(tasks, list) and len(tasks) == count and all(isinstance(t, str) and t.strip() for t in tasks)
    return [t.strip() for t in tasks] if ok else None


def _worker_context(parent: ToolContext, worktree: Path, run: Run, name: str, cancel: threading.Event,
                    provider: Any, model: str) -> ToolContext:
    """A fresh context bounded to the worker's worktree. Edits inside it are free (nothing lands until the user
    approves the outbox); commands, and anything outside the worktree, ask through the run's approvals."""
    perms = parent.permission_context
    return ToolContext(
        workspace_root=worktree,
        permission_context=ToolPermissionContext.from_iterables(perms.deny_names, perms.deny_prefixes, workspace_root=worktree),
        hooks=parent.hooks,
        permission_rules=parent.permission_rules,
        worktree_root=worktree,
        permission_handler=run.permission_handler(name, cancel),
        ask_user=None,
        provider=provider,
        model=model,
    )


_NOISE = ":(exclude).aider*"   # aider's caches and histories are never the worker's work


def _snapshot(worktree: Path) -> tuple[str, list[str]]:
    """(patch, changed files) of everything the worker did, tracked or new."""
    _git(worktree, "add", "-A", "--", ".", _NOISE)
    patch = _git(worktree, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "HEAD", "--", ".", _NOISE)
    return patch, _changed_files(worktree)


def _changed_files(tree: Path) -> list[str]:
    try:
        return [f for f in _git(tree, "diff", "--cached", "--name-only", "-z", "HEAD", "--", ".", _NOISE).split("\0") if f]
    except (RuntimeError, OSError):
        return []


def _work_cli(run: Run, name: str, role: RoleAssignment, prompt: str, worktree: Path, cancel: threading.Event) -> Any:
    """An agent CLI as the worker: run it in the worktree under its file-only contract, record what it reports."""
    run.event(name, "constraint", note=cli_workers.constraint(role.provider_name))
    runner = {"claude": cli_workers.run_claude, "aider": cli_workers.run_aider}[role.provider_name]

    def emit(kind: str, tool: str, tool_input: Any) -> None:
        run.event(name, kind, tool=tool, input=json.dumps(tool_input or {}, default=str)[:200])

    result = runner(role.harness.binary or role.provider_name, role.model, prompt, worktree, run.worker_dir(name), cancel, emit)
    run.spend(name, role.ref, result.usage, result.usd, always=True)
    return result


def _work(run: Run, name: str, role: RoleAssignment, provider: Any, prompt: str, worktree: Path,
          parent: ToolContext, registry: Any, cancel: threading.Event) -> dict[str, Any]:
    """One worker, start to end. Never raises: a failure is recorded and returned."""
    out: dict[str, Any] = {"name": name, "ok": False, "summary": "", "patch": "", "files": []}
    history = History()
    run.event(name, "started", model=role.ref, worktree=str(worktree))

    def on_event(event: Any) -> None:
        if event.kind in ("tool_use", "tool_error"):
            run.event(name, event.kind, tool=event.tool_name, input=json.dumps(event.tool_input or {}, default=str)[:200])

    try:
        if role.harness.kind == "cli":
            result = _work_cli(run, name, role, prompt, worktree, cancel)
            out["summary"] = result.summary
            out["ok"] = result.ok
        else:
            context = _worker_context(parent, worktree, run, name, cancel, provider, role.model)
            agent = AgentType(GENERAL, "orchestrated worker",
                              prompt=f"{WORKER_PROMPT}\nYour worktree is {worktree}. Work only there and use paths relative to it.")
            result, _ = run_agent(registry, context, agent, prompt, cancel=cancel, conversation=history, on_event=on_event)
            out["summary"] = result.response_text or ""
            run.spend(name, role.ref, result.usage)
            out["ok"] = True
        out["patch"], out["files"] = _snapshot(worktree)
        out["ok"] = out["ok"] and not cancel.is_set()
    except Exception as e:   # a provider error, a stopped request: the run goes on without this worker
        out["summary"] = f"{type(e).__name__}: {e}"
    folder = run.worker_dir(name)
    (folder / "summary.md").write_text(out["summary"], encoding="utf-8")
    (folder / "transcript.json").write_text(json.dumps(history.to_dict(), indent=2, default=str), encoding="utf-8")
    if out["patch"]:
        (folder / "changes.patch").write_text(out["patch"], encoding="utf-8")
    run.event(name, "finished" if out["ok"] else "failed", files=len(out["files"]))
    return out


def orchestrate(plan: OrchestrationPlan, spec: str, *, workspace: Path, parent: ToolContext, registry: Any,
                providers: dict[str, Any], on_approval: Callable[[dict[str, Any]], bool] | None = None,
                cancel: threading.Event | None = None) -> Outcome | str:
    """Run the plan to the point where the user decides. `on_approval(ask)` answers a worker's request from the
    caller's thread (None: every request is denied). Returns an Outcome, or the reason it could not start."""
    root = repo_root(workspace)
    if isinstance(root, str):
        return root
    cancel = cancel or threading.Event()
    names = [f"worker-{i + 1}" for i in range(len(plan.workers))]
    run = Run.create(plan.task, {"master": plan.master.ref, "advisor": plan.advisor.ref if plan.advisor else None,
                                 "workers": [{"name": n, "model": w.ref} for n, w in zip(names, plan.workers)]})
    run.update(spec=spec, repo=str(root), workspaces={})

    def provider_of(role: RoleAssignment) -> Any:
        return None if role.harness.kind == "cli" else providers[role.provider_name]   # a CLI brings its own model access

    try:
        run.event("master", "splitting")
        notes: list[str] = []
        ask = f"Workers: {len(names)}\n\nSpec:\n{spec}"
        split = _split(_model_text(provider_of(plan.master), plan.master.model, SPLIT_SYSTEM, ask, run, "master"), len(names))
        if split is None:   # small models often wrap or skip the JSON: say so once and ask again
            split = _split(_model_text(provider_of(plan.master), plan.master.model, SPLIT_SYSTEM,
                                       ask + "\n\nYour last answer was not the JSON asked for. Answer with only the JSON.", run, "master"), len(names))
        if split is None:
            notes.append("The master gave no usable split, so every worker got the whole spec and may have done the same work.")
            run.event("master", "split_fallback", note=notes[-1])
            split = [spec] * len(names)
        run.event("master", "split", tasks=split)

        workspaces: dict[str, dict[str, str]] = {}
        for name in names:
            tree = run.root / "workspaces" / name
            branch = f"clyde-run-{run.id}-{name}"
            _git(root, "worktree", "add", "-q", "-b", branch, str(tree), "HEAD")
            workspaces[name] = {"path": str(tree), "branch": branch}
        run.update(workspaces=workspaces)

        run.set_status("running")
        serial = any(w.provider_name in LOCAL_PROVIDERS for w in plan.workers)
        if serial:
            run.event("clyde", "serialized", note="a local model is among the workers: one at a time")
        with ThreadPoolExecutor(max_workers=1 if serial else len(names)) as pool:
            futures = [pool.submit(_work, run, n, w, provider_of(w), f"{t}\n\nThe overall spec, for context only. The other workers cover the rest: do only your task above.\n{spec}",
                                   Path(workspaces[n]["path"]), parent, registry, cancel)
                       for n, w, t in zip(names, plan.workers, split)]
            while not all(f.done() for f in futures):
                try:
                    for ask in run.pending():
                        run.answer(ask["id"], bool(on_approval and on_approval(ask)))
                    time.sleep(0.2)
                except KeyboardInterrupt:   # Ctrl-C: tell every worker to stop, then wait for them to wind down
                    cancel.set()
            results = [f.result() for f in futures]
        if cancel.is_set():
            run.set_status("stopped")
            _cleanup(run)
            return Outcome(run, "Stopped before the review.", "none", [r["name"] for r in results if not r["ok"]], notes)

        run.set_status("reviewing")
        digest = "\n\n".join(
            f"## {r['name']} ({'finished' if r['ok'] else 'FAILED'}), files: {', '.join(r['files']) or 'none'}\n"
            f"{r['summary'][:_SUMMARY_CHARS]}\n\n```diff\n{r['patch'][:_PATCH_CHARS]}\n```" for r in results)
        review = ""
        if plan.advisor:
            run.event("advisor", "reviewing")
            review = _model_text(provider_of(plan.advisor), plan.advisor.model, REVIEW_SYSTEM,
                                 f"Spec:\n{spec}\n\nWorkers:\n{digest}", run, "advisor")
            (run.root / "advisor.md").write_text(review, encoding="utf-8")
            run.event("advisor", "reviewed")
        run.event("master", "reporting")
        report = _model_text(provider_of(plan.master), plan.master.model, REPORT_SYSTEM,
                             f"Spec:\n{spec}\n\nWorkers:\n{digest}\n\nAdvisor review:\n{review or '(no advisor)'}", run, "master")
        (run.root / "report.md").write_text(report, encoding="utf-8")
        run.event("master", "reported")
        last = report.strip().splitlines()[-1].strip(" *_`#.").upper() if report.strip() else ""   # models bold it
        verdict = {"VERDICT: APPROVE": "approve", "VERDICT: REVISE": "revise"}.get(last, "none")
        run.update(verdict=verdict)
        run.set_status("awaiting_approval")
        return Outcome(run, report, verdict, [r["name"] for r in results if not r["ok"]], notes)
    except Exception as e:
        run.event("clyde", "error", error=f"{type(e).__name__}: {e}")
        run.set_status("failed")
        _cleanup(run)
        return f"The run failed: {type(e).__name__}: {e} (see {run.root})"


def _cleanup(run: Run) -> None:
    """Remove the run's worktrees and their branches; the patches and files are already saved."""
    state = run.state()
    repo = Path(state.get("repo", ""))
    for info in (state.get("workspaces") or {}).values():
        try:
            _git(repo, "worktree", "remove", "--force", info["path"])
            _git(repo, "branch", "-D", info["branch"])
        except (RuntimeError, OSError, KeyError):
            pass


def land(run: Run, approve: bool) -> Path | None:
    """The user's decision. Approved: each worker's changed files and patch, plus the spec and report, are copied
    to ~/.clyde/outbox/<run>/ and that path is returned. Either way the worktrees go away; the project itself is
    never touched (apply a worker's changes with `git apply <outbox>/<worker>/changes.patch`)."""
    state = run.state()
    target: Path | None = None
    if approve:
        target = outbox_dir() / run.id
        target.mkdir(parents=True, exist_ok=True)
        (target / "spec.md").write_text(state.get("spec", ""), encoding="utf-8")
        if (run.root / "report.md").is_file():
            shutil.copy2(run.root / "report.md", target / "report.md")
        for name, info in (state.get("workspaces") or {}).items():
            tree, dest = Path(info["path"]), target / name
            patch = run.root / "workers" / name / "changes.patch"
            if patch.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(patch, dest / "changes.patch")
            for rel in _changed_files(tree):
                src = tree / rel
                if src.is_file() and not src.is_symlink() and ".." not in Path(rel).parts and not Path(rel).is_absolute():
                    (dest / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest / "files" / rel)
    run.event("user", "landed" if approve else "discarded", outbox=str(target) if target else None)
    run.set_status("done" if approve else "stopped")
    _cleanup(run)
    return target
