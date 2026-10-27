"""Agent CLIs as workers, against fake CLI scripts: what they are told, what they may see, what Clyde records."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import cli_workers
from src.agent.harness import Harness, HarnessModel
from src.agent.orchestration import build_plan, land, orchestrate
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply

# A stand-in CLI: records its argv, stdin and environment, then behaves as `mode` says.
FAKE = '''#!{python}
import json, os, sys, time
mode, record = {mode!r}, {record!r}
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
json.dump({{"argv": sys.argv[1:], "stdin": stdin, "env": dict(os.environ), "cwd": os.getcwd()}}, open(record, "w"))
if mode == "claude":
    open("x.txt", "w").write("hi\\n")
    print(json.dumps({{"type": "system", "subtype": "init"}}))
    print(json.dumps({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": "Write", "input": {{"file_path": "x.txt"}}}}]}}}}))
    print(json.dumps({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "t9", "name": "Bash", "input": {{"command": "ls"}}}}]}}}}))
    print(json.dumps({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t9", "is_error": True,
                       "content": "No such tool available: Bash"}}]}}}}))
    print("not json at all")
    print(json.dumps({{"type": "result", "is_error": False, "result": "done", "total_cost_usd": 0.0014,
                       "usage": {{"input_tokens": 4, "output_tokens": 126, "cache_read_input_tokens": 9864, "service_tier": "standard"}}}}))
elif mode == "claude-error":
    print(json.dumps({{"type": "result", "is_error": True, "result": "boom", "total_cost_usd": 0.0001, "usage": {{}}}}))
    sys.exit(1)
elif mode == "aider":
    open("y.txt", "w").write("yo\\n")
    open(".aider.tags.cache.v4", "w").write("noise")
    print("Applied edit to y.txt")
    print("Tokens: 1.2k sent, 87 received. Cost: $0.0021 message, $0.0021 session.")
elif mode == "aider-ask":
    print("Warning: Input is not a terminal (fd=0).")
    print("Aider v0.86.2")
    print("Model: mistral/m with ask edit format")
    print("Git repo: none")
    print("Repo-map: disabled")
    print()
    print("The patch looks right.")
    print("Tokens: 1.2k sent, 87 received. Cost: $0.0003 message, $0.0003 session.")
elif mode == "hang":
    time.sleep(60)
'''


def _fake_cli(root: Path, mode: str) -> tuple[str, Path]:
    """(path of a script that behaves as `mode`, the file it records its argv, stdin and env in)."""
    record = root / f"{mode}.json"
    path = root / f"fake-{mode}"
    path.write_text(FAKE.format(python=sys.executable, mode=mode, record=str(record)), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path), record


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


class CliWorkers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.worktree = self.root / "wt"
        self.worktree.mkdir()
        self.folder = self.root / "folder"
        self.folder.mkdir()
        self.events: list[tuple[str, str, object]] = []

    def _emit(self, kind, tool, tool_input):
        self.events.append((kind, tool, tool_input))

    def _claude(self, binary, cancel=None):
        return cli_workers.run_claude(binary, "haiku", "make x.txt, -starting with a dash", self.worktree, self.folder,
                                      cancel or threading.Event(), self._emit)

    def test_claude_gets_files_only_its_prompt_on_stdin_and_reports_cost_events_and_usage(self):
        binary, record = _fake_cli(self.root, "claude")
        result = self._claude(binary)
        seen = json.loads(record.read_text())
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Edit,Write,Glob,Grep")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertIn("--restricted", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertEqual(seen["stdin"], "make x.txt, -starting with a dash")   # never on the command line
        self.assertEqual(os.path.realpath(seen["cwd"]), os.path.realpath(self.worktree))
        self.assertEqual((result.ok, result.summary, result.usd), (True, "done", 0.0014))
        self.assertEqual(result.usage, {"input_tokens": 4, "output_tokens": 126, "cache_read_input_tokens": 9864})
        self.assertEqual(self.events, [("tool_use", "Write", {"file_path": "x.txt"}), ("tool_use", "Bash", {"command": "ls"}),
                                       ("tool_error", "Bash", {"error": "No such tool available: Bash"})])   # refused, and said so
        self.assertIn("not json at all", (self.folder / "output.log").read_text())
        self.assertEqual(stat.S_IMODE((self.folder / "output.log").stat().st_mode), 0o600)

    def test_a_failing_claude_is_not_ok_but_its_cost_is_still_reported(self):
        binary, _ = _fake_cli(self.root, "claude-error")
        result = self._claude(binary)
        self.assertEqual((result.ok, result.summary, result.usd), (False, "boom", 0.0001))
        self.assertFalse(self._claude(str(self.root / "missing")).ok)

    def test_a_stop_kills_the_cli(self):
        binary, _ = _fake_cli(self.root, "hang")
        cancel = threading.Event()
        timer = threading.Timer(0.5, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        result = self._claude(binary, cancel)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual((result.ok, result.summary), (False, "stopped"))

    def _aider(self, binary, model="mistral/ministral-3b-latest"):
        return cli_workers.run_aider(binary, model, "write y.txt", self.worktree, self.folder, threading.Event(), self._emit)

    def test_aider_gets_only_its_providers_saved_key_and_no_way_to_run_commands(self):
        binary, record = _fake_cli(self.root, "aider")
        stale = {"MISTRAL_API_KEY": "STALE", "OPENAI_API_KEY": "OTHER"}
        with patch.dict(os.environ, stale), patch("src.providers.keys.saved_key", return_value="SAVED"):
            result = self._aider(binary)
        seen = json.loads(record.read_text())
        self.assertEqual(seen["env"]["MISTRAL_API_KEY"], "SAVED")   # the saved key beats a stale export
        self.assertNotIn("OPENAI_API_KEY", seen["env"])             # no other provider's key
        for flag in ("--no-suggest-shell-commands", "--no-auto-commits", "--yes-always", "--no-gitignore"):
            self.assertIn(flag, seen["argv"])
        self.assertEqual((self.folder / "prompt.txt").read_text(), "write y.txt")
        self.assertEqual((result.ok, result.usd), (True, 0.0021))
        self.assertEqual(self.events, [("tool_use", "Edit", {"file_path": "y.txt"})])

    def test_aider_as_an_advisor_asks_without_git_and_returns_only_its_answer(self):
        binary, record = _fake_cli(self.root, "aider-ask")
        with patch("src.providers.keys.saved_key", return_value="K"):
            result = cli_workers.run_aider(binary, "mistral/m", "review this", self.worktree, self.folder, threading.Event(),
                                           self._emit, advisor=True)
        argv = json.loads(record.read_text())["argv"]
        self.assertEqual(argv[argv.index("--chat-mode") + 1], "ask")
        self.assertIn("--no-git", argv)
        self.assertEqual((result.ok, result.summary, result.usd), (True, "The patch looks right.", 0.0003))   # no banner, no cost line

    def test_aider_without_a_key_or_for_an_unknown_provider_does_not_start(self):
        binary, record = _fake_cli(self.root, "aider")
        with patch("src.providers.keys.saved_key", return_value=None), patch.dict(os.environ, {}, clear=True):
            self.assertIn("clyde login mistral", self._aider(binary, "mistral/m").summary)
        self.assertIn("isn't one Clyde has a key for", self._aider(binary, "weird/m").summary)
        self.assertFalse(record.exists())

    def test_aider_model_ids_are_the_connected_providers_in_litellm_form(self):
        self.assertEqual(cli_workers.litellm_models({"google": ["gemini-3.5-flash"], "mistral": ["m1"], "ollama": ["q"]}),
                         ["gemini/gemini-3.5-flash", "mistral/m1"])


class CliWorkerInARun(unittest.TestCase):
    def test_a_cli_worker_and_a_provider_worker_run_together_and_the_cli_cost_is_in_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "init")
            binary, _ = _fake_cli(root, "aider")
            providers = {"m": FakeProvider(reply('{"tasks": ["write y", "write b"]}'), reply("ok\nVERDICT: APPROVE"), name="m"),
                         "w": FakeProvider(reply(tool_calls=[("Write", {"file_path": "b.txt", "content": "B\n"})]), reply("wrote b"), name="w")}
            harnesses = [Harness("provider:m", "provider", models=[HarnessModel("m")]), Harness("provider:w", "provider", models=[HarnessModel("m")]),
                         Harness("aider", "cli", binary=binary, models=[HarnessModel("mistral/ministral-3b-latest")])]
            plan = build_plan("t", ("provider:m", "m"), None, [("aider", "mistral/ministral-3b-latest"), ("provider:w", "m")], harnesses)
            with patch("src.agent.runs.clyde_home", return_value=root / "home"), patch("src.providers.keys.saved_key", return_value="K"):
                outcome = orchestrate(plan, "spec", workspace=repo, parent=ToolContext(workspace_root=repo),
                                      registry=build_default_registry(), providers=providers)
                self.assertNotIsInstance(outcome, str, outcome)
                run = outcome.run
                kinds = [(e["who"], e["kind"]) for e in run.events()]
                self.assertIn(("worker-1", "constraint"), kinds)
                self.assertIn(("worker-1", "tool_use"), kinds)
                self.assertEqual([e["tools"] for e in run.events() if e["kind"] == "tools" and e["who"] == "worker-1"], [["Edit"]])   # aider: editing only
                self.assertEqual([r["usd"] for r in run.ledger() if r["who"] == "worker-1"], [0.0021])
                out = land(run, approve=True)
            self.assertEqual((out / "worker-1" / "files" / "y.txt").read_text(), "yo\n")
            self.assertEqual((out / "worker-2" / "files" / "b.txt").read_text(), "B\n")
            self.assertFalse(any(".aider" in str(p) for p in out.rglob("*")))   # aider's cache never lands


    def _advised(self, mode: str):
        """A run whose advisor is a fake Claude Code CLI behaving as `mode`; (outcome, run dir files, repo)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        repo = root / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        binary, record = _fake_cli(root, mode)
        providers = {"m": FakeProvider(reply('{"tasks": ["write b"]}'), reply("fine\nVERDICT: APPROVE"), name="m"),
                     "w": FakeProvider(reply(tool_calls=[("Write", {"file_path": "b.txt", "content": "B\n"})]), reply("wrote b"), name="w")}
        harnesses = [Harness("provider:m", "provider", models=[HarnessModel("m")]), Harness("provider:w", "provider", models=[HarnessModel("m")]),
                     Harness("claude", "cli", binary=binary, models=[HarnessModel("haiku")])]
        plan = build_plan("t", ("provider:m", "m"), ("claude", "haiku"), [("provider:w", "m")], harnesses)
        self.assertEqual(plan.advisor.ref, "claude:haiku")   # a CLI may advise
        with patch("src.agent.runs.clyde_home", return_value=root / "home"):
            outcome = orchestrate(plan, "spec", workspace=repo, parent=ToolContext(workspace_root=repo),
                                  registry=build_default_registry(), providers=providers)
        return outcome, record, repo, providers

    def test_an_agent_cli_can_be_the_advisor_with_no_tools_in_an_empty_folder(self):
        outcome, record, _repo, providers = self._advised("claude")
        self.assertNotIsInstance(outcome, str, outcome)
        run = outcome.run
        self.assertEqual((run.root / "advisor.md").read_text(), "done")   # the CLI's answer is the review
        seen = json.loads(record.read_text())
        self.assertEqual(seen["argv"][seen["argv"].index("--tools") + 1], "")   # no tools at all
        self.assertIn("You are the advisor", seen["stdin"])
        self.assertIn("wrote b", seen["stdin"])   # it was given the workers' results
        self.assertEqual(os.path.realpath(seen["cwd"]), os.path.realpath(run.root / "workers" / "advisor" / "cwd"))
        self.assertEqual([r["usd"] for r in run.ledger() if r["who"] == "advisor"], [0.0014])
        self.assertIn(("advisor", "constraint"), [(e["who"], e["kind"]) for e in run.events()])
        self.assertIn("Advisor review:\ndone", providers["m"].requests[-1]["conversation"].messages[0].text)
        self.assertEqual(outcome.notes, [])
        self.assertEqual([e["tools"] for e in run.events() if e["kind"] == "tools" and e["who"] == "advisor"], [[]])   # a CLI advisor has no tools
        land(run, approve=False)

    def test_an_advisor_that_fails_is_reported_and_the_report_still_comes(self):
        outcome, _record, _repo, _providers = self._advised("claude-error")
        self.assertEqual(outcome.verdict, "approve")
        self.assertEqual(len(outcome.notes), 1)
        self.assertIn("advisor (claude:haiku) failed", outcome.notes[0])
        land(outcome.run, approve=False)


if __name__ == "__main__":
    unittest.main()
