"""Sub-agents: custom types, foreground and background runs, and teams that actually run."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import agent_types
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.errors import ToolInputError
from src.tool_system.protocol import ToolCall
from tests.fakes import FakeProvider, reply

RUNNER = """---
name: test-runner
description: Runs the tests and reports failures
tools: Read, Grep
model: inherit
---
You only run tests. Report each failure with its file.
"""


class _Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.root = Path(tempfile.mkdtemp()).resolve()
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / ".clyde" / "agents").mkdir(parents=True)
        (self.root / ".clyde" / "agents" / "test-runner.md").write_text(RUNNER)
        (self.home / ".claude" / "agents").mkdir(parents=True)
        (self.home / ".claude" / "agents" / "runner-copy.md").write_text(RUNNER.replace("You only run", "IGNORED"))
        self.registry = build_default_registry(include_user_tools=False)

    def ctx(self, *responses):
        provider = FakeProvider(*responses)
        ctx = ToolContext(workspace_root=self.root)
        ctx.provider, ctx.model = provider, "fake-model"
        return ctx, provider

    def call(self, ctx, name, **tool_input):
        return self.registry.dispatch(ToolCall(name=name, input=tool_input, tool_use_id="t"), ctx)


class TestAgentTypes(_Base):
    def test_types_load_from_the_project_first_and_general_purpose_is_built_in(self):
        types = agent_types.load(self.root)
        self.assertEqual(sorted(types), ["general-purpose", "test-runner"])     # the user copy's name is taken
        runner = types["test-runner"]
        self.assertEqual(runner.tools, ("Read", "Grep"))
        self.assertIsNone(runner.model)                                        # inherit
        self.assertTrue(runner.prompt.startswith("You only run tests"))


class TestAgentTool(_Base):
    def test_a_custom_agent_gets_its_instructions_and_only_its_tools(self):
        ctx, provider = self.ctx(reply("all green"))
        result = self.call(ctx, "Agent", description="run tests", prompt="run the suite", subagent_type="test-runner")
        self.assertEqual(result.output["content"], "all green")
        request = provider.requests[0]
        self.assertIn("You only run tests", request["conversation"].system_prompt)
        self.assertEqual(sorted(t.name for t in request["tools"]), ["Grep", "Read"])

    def test_sub_agents_cannot_start_agents_or_teams(self):
        ctx, provider = self.ctx(reply("ok"))
        self.call(ctx, "Agent", description="x", prompt="do it")
        names = {t.name for t in provider.requests[0]["tools"]}
        self.assertFalse(names & {"Agent", "TeamCreate", "TeamDelete"})
        self.assertIn("Bash", names)

    def test_unknown_types_say_what_exists(self):
        ctx, _ = self.ctx()
        with self.assertRaisesRegex(ToolInputError, "available: general-purpose, test-runner"):
            self.call(ctx, "Agent", description="x", prompt="y", subagent_type="nope")

    def test_background_runs_return_at_once_and_taskoutput_waits(self):
        ctx, _ = self.ctx(reply("background answer"))
        started = self.call(ctx, "Agent", description="bg", prompt="work", run_in_background=True)
        task_id = started.output["task_id"]
        done = self.call(ctx, "TaskOutput", task_id=task_id, block=True, timeout=10)
        self.assertEqual(done.output["task"]["status"], "completed")
        self.assertEqual(done.output["task"]["output"], "background answer")

    def test_a_background_agent_cannot_be_prompted_so_asks_are_denied(self):
        ctx, _ = self.ctx(reply(tool_calls=[("Bash", {"command": "touch should-not-exist.txt"})]), reply("couldn't"))
        ctx.permission_handler = lambda *a: (_ for _ in ()).throw(AssertionError("prompted the user"))
        task_id = self.call(ctx, "Agent", description="bg", prompt="touch it", run_in_background=True).output["task_id"]
        done = self.call(ctx, "TaskOutput", task_id=task_id, block=True, timeout=10)
        self.assertEqual(done.output["task"]["status"], "completed")
        self.assertFalse((self.root / "should-not-exist.txt").exists())


class TestTeams(_Base):
    def test_members_run_in_parallel_and_teamdelete_reports_them(self):
        ctx, _ = self.ctx(*(reply("member done") for _ in range(2)))
        created = self.call(ctx, "TeamCreate", team_name="review", members=[
            {"name": "a", "prompt": "check src"}, {"name": "b", "prompt": "check tests", "subagent_type": "test-runner"}])
        members = created.output["members"]
        self.assertEqual([(m["name"], m["agent"]) for m in members], [("a", "general-purpose"), ("b", "test-runner")])
        outputs = [self.call(ctx, "TaskOutput", task_id=m["task_id"], block=True, timeout=10).output["task"] for m in members]
        self.assertEqual([o["output"] for o in outputs], ["member done", "member done"])
        with self.assertRaisesRegex(ToolInputError, "still active"):
            self.call(ctx, "TeamCreate", team_name="again", members=[{"name": "c", "prompt": "x"}])
        ended = self.call(ctx, "TeamDelete").output
        self.assertEqual([m["status"] for m in ended["members"]], ["completed", "completed"])
        self.assertIsNone(ctx.team)


if __name__ == "__main__":
    unittest.main()
