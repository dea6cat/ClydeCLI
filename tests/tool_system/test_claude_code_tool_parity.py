from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from src.agent.conversation import Conversation
from src.agent.agent_loop import run_agent_loop
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from tests.fakes import FakeProvider, reply


class TestClaudeCodeToolParity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.registry = build_default_registry(include_user_tools=False)
        self.ctx = ToolContext(workspace_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_registry_has_claude_code_tool_names(self) -> None:
        expected = [
            "Agent",
            "AskUserQuestion",
            "Bash",
            "Config",
            "CronCreate",
            "CronDelete",
            "CronList",
            "Edit",
            "EnterPlanMode",
            "EnterWorktree",
            "ExitPlanMode",
            "ExitWorktree",
            "Glob",
            "Grep",
            "LSP",
            "ListMcpResourcesTool",
            "MCP",
            "NotebookEdit",
            "PowerShell",
            "REPL",
            "Read",
            "ReadMcpResourceTool",
            "RemoteTrigger",
            "SendMessage",
            "SendUserMessage",
            "Skill",
            "Sleep",
            "StructuredOutput",
            "TaskCreate",
            "TaskGet",
            "TaskList",
            "TaskOutput",
            "TaskStop",
            "TaskUpdate",
            "TodoWrite",
            "ToolSearch",
            "WebFetch",
            "WebSearch",
            "Write",
        ]
        missing = [name for name in expected if self.registry.get(name) is None]
        self.assertEqual(missing, [])

    def test_send_user_message_is_user_visible_fallback(self) -> None:
        conversation = Conversation()
        conversation.add_user_message("hi")

        provider = FakeProvider(
            reply("", tool_calls=[("SendUserMessage", {"message": "hello", "status": "normal"}, "toolu_1")]),
            reply(""),
        )

        out = run_agent_loop(
            conversation=conversation,
            provider=provider,
            model="fake-model",
            tool_registry=self.registry,
            tool_context=self.ctx,
            verbose=False,
        )
        self.assertEqual(out.response_text, "hello")

    def test_tool_search_select(self) -> None:
        out = self.registry.dispatch(
            ToolCall(name="ToolSearch", input={"query": "select:Read"}),
            self.ctx,
        ).output
        self.assertEqual(out["matches"], ["Read"])

    def test_todo_write_roundtrip(self) -> None:
        out1 = self.registry.dispatch(
            ToolCall(
                name="TodoWrite",
                input={"todos": [{"content": "x", "status": "pending", "activeForm": "Doing x"}]},
            ),
            self.ctx,
        ).output
        self.assertEqual(out1["oldTodos"], [])
        self.assertEqual(len(out1["newTodos"]), 1)
        self.assertEqual(len(self.ctx.todos), 1)

        self.registry.dispatch(
            ToolCall(
                name="TodoWrite",
                input={"todos": [{"content": "x", "status": "completed", "activeForm": "Did x"}]},
            ),
            self.ctx,
        )
        self.assertEqual(self.ctx.todos, [])


if __name__ == "__main__":
    unittest.main()



class TestToolSchemasAreObjects(unittest.TestCase):
    def test_every_tool_schema_is_an_object_at_the_top(self) -> None:
        # Strict OpenAI-compatible servers (LM Studio) reject a tool whose parameters aren't type: object.
        from src.tool_system.defaults import build_default_registry

        bad = [s.name for s in build_default_registry().list_specs() if s.input_schema.get("type") != "object"]
        self.assertEqual(bad, [])

    def test_openai_wire_schemas_always_have_type_and_properties(self) -> None:
        from src.providers.toolspec import from_specs, to_openai
        from src.tool_system.defaults import build_default_registry

        for tool in to_openai(from_specs(build_default_registry().list_specs())):
            params = tool["function"]["parameters"]
            self.assertEqual(params["type"], "object", tool["function"]["name"])
            self.assertIsInstance(params["properties"], dict, tool["function"]["name"])
