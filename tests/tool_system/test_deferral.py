"""Deferred tools: a core set is sent, the rest are named in an index and loaded on request."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.agent_loop import run_agent_loop
from src.agent.conversation import Conversation
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.deferral import CORE_TOOLS, advertised, hint, index_prompt, is_deferred
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolSpec
from tests.fakes import FakeProvider, reply


def _names(tools) -> set[str]:
    return {t.name for t in tools}


class TestDeferral(unittest.TestCase):
    def setUp(self):
        self.registry = build_default_registry(include_user_tools=False)
        self.specs = self.registry.list_specs()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ToolContext(workspace_root=Path(self.tmp.name))

    def test_only_core_tools_are_sent_until_others_are_loaded(self):
        sent = _names(advertised(self.specs, set()))
        self.assertTrue(sent <= {n for n in (s.name for s in self.specs)})
        self.assertTrue({"Bash", "Read", "Edit", "ToolSearch", "ExitPlanMode"} <= sent)
        self.assertNotIn("Sleep", sent)
        self.assertLess(len(sent), len(self.specs) // 2)
        self.assertIn("Sleep", _names(advertised(self.specs, {"sleep"})))   # loaded names are lowercase

    def test_every_core_name_exists_in_the_registry(self):
        # A typo here would silently defer a tool the model needs on every turn.
        self.assertEqual(CORE_TOOLS - {s.name.lower() for s in self.specs}, set())

    def test_the_escape_hatch_sends_everything_and_drops_the_index(self):
        with patch.dict(os.environ, {"CLYDE_ALL_TOOLS": "1"}):
            self.assertEqual(len(advertised(self.specs, set())), len(self.specs))
            self.assertEqual(index_prompt(self.specs), "")
            self.assertFalse(is_deferred("Sleep"))

    def test_the_index_names_deferred_tools_with_a_short_hint_and_no_core_ones(self):
        index = index_prompt(self.specs)
        self.assertIn("ToolSearch", index)
        self.assertIn("- Sleep:", index)
        self.assertNotIn("- Bash:", index)
        self.assertTrue(all(len(line) < 140 for line in index.splitlines()[2:]))

    def test_a_hint_stops_at_a_sentence_not_at_e_g_and_cuts_on_a_word(self):
        spec = ToolSpec("T", 'Get or set values (e.g. "model" as a key). Then more text.', {})
        self.assertTrue(hint(spec).startswith('Get or set values (e.g. "model"'))
        long = ToolSpec("T", "word " * 40, {})
        self.assertTrue(hint(long).endswith("word…") and len(hint(long)) <= 56)

    def test_tool_search_loads_deferred_tools_by_name_or_keyword(self):
        out = self.registry.dispatch(ToolCall(name="ToolSearch", input={"query": "select:Sleep,read, Nope"}), self.ctx).output
        self.assertEqual(out["matches"], ["Sleep", "Read"])
        self.assertEqual(out["loaded"], ["Sleep"])                       # Read is core: already sent
        self.assertEqual(out["not_found"], ["Nope"])
        self.assertEqual(self.ctx.loaded_tools, {"sleep"})
        out = self.registry.dispatch(ToolCall(name="ToolSearch", input={"query": "cron", "max_results": 2}), self.ctx).output
        self.assertTrue(set(out["loaded"]) <= {"CronCreate", "CronList", "CronDelete"} and out["loaded"])
        self.assertIn("sleep", self.ctx.loaded_tools)                    # earlier loads stay
        self.assertGreater(out["total_deferred_tools"], 20)


class TestAgentLoopDeferral(unittest.TestCase):
    def setUp(self):
        self.registry = build_default_registry(include_user_tools=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ToolContext(workspace_root=Path(self.tmp.name))

    def _run(self, provider):
        conversation = Conversation()
        conversation.add_user_message("go")
        run_agent_loop(conversation=conversation, provider=provider, model="m", tool_registry=self.registry,
                       tool_context=self.ctx, verbose=False)
        return conversation

    def test_the_first_request_omits_deferred_tools_and_lists_them_in_the_system_prompt(self):
        provider = FakeProvider(reply("hi"))
        self._run(provider)
        request = provider.requests[0]
        self.assertNotIn("Sleep", _names(request["tools"]))
        self.assertIn("- Sleep:", request["conversation"].system_prompt)
        self.assertIn("## More tools", request["conversation"].system_prompt)

    def test_a_tool_loaded_with_tool_search_is_sent_on_the_next_request(self):
        provider = FakeProvider(
            reply("", tool_calls=[("ToolSearch", {"query": "select:Sleep"}, "t1")]), reply("done"))
        self._run(provider)
        self.assertNotIn("Sleep", _names(provider.requests[0]["tools"]))
        self.assertIn("Sleep", _names(provider.requests[1]["tools"]))

    def test_calling_a_deferred_tool_by_name_still_runs_it_and_loads_it(self):
        provider = FakeProvider(
            reply("", tool_calls=[("Sleep", {"seconds": 0}, "t1")]), reply("done"))
        conversation = self._run(provider)
        self.assertIn("Sleep", _names(provider.requests[1]["tools"]))
        blocks = [b for m in conversation.messages if isinstance(m.content, list) for b in m.content if b.type == "tool_result"]
        self.assertEqual([(b.tool_use_id, b.is_error) for b in blocks], [("t1", False)])   # it ran, though never loaded

    def test_the_system_prompt_is_the_same_on_every_request_so_provider_caching_holds(self):
        provider = FakeProvider(
            reply("", tool_calls=[("ToolSearch", {"query": "select:Sleep"}, "t1")]), reply("done"))
        self._run(provider)
        first, second = (r["conversation"].system_prompt for r in provider.requests)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()


class TestLocalToolRouting(unittest.TestCase):
    def test_a_review_prompt_gets_only_the_reading_tools(self):
        from src.tool_system.deferral import local_tools
        self.assertEqual(local_tools("ok so I want you to review the implementation with totp token in this project"),
                         frozenset({"read", "grep", "glob", "toolsearch"}))

    def test_what_the_prompt_asks_for_adds_its_tools(self):
        from src.tool_system.deferral import local_tools
        self.assertLessEqual({"edit", "write"}, local_tools("fix the login bug"))
        self.assertLessEqual({"bash"}, local_tools("run the tests"))
        self.assertLessEqual({"webfetch", "websearch"}, local_tools("what changed in https://example.com/x"))
        self.assertNotIn("bash", local_tools("explain this function"))

    def test_only_replaces_the_core_set_in_the_request_and_the_index(self):
        from src.tool_system.deferral import local_tools
        specs = [ToolSpec(n, f"{n} things. More.", {}) for n in ("Read", "Edit", "Bash", "ToolSearch")]
        only = local_tools("explain this")
        self.assertEqual([s.name for s in advertised(specs, set(), only)], ["Read", "ToolSearch"])
        self.assertEqual([s.name for s in advertised(specs, {"edit"}, only)], ["Read", "Edit", "ToolSearch"])
        index = index_prompt(specs, only)
        self.assertIn("- Edit:", index)
        self.assertNotIn("- Read:", index)


class TestLoopHelpers(unittest.TestCase):
    def test_only_local_providers_get_the_small_tool_set(self):
        from types import SimpleNamespace as NS
        from src.agent.agent_loop import _small_local
        self.assertTrue(_small_local(NS(name="lmstudio", api_key="lm-studio")))
        self.assertTrue(_small_local(NS(name="ollama", api_key=None)))
        self.assertFalse(_small_local(NS(name="ollama", api_key="cloud-key")))   # Ollama's cloud models
        self.assertFalse(_small_local(NS(name="openrouter", api_key="k")))

    def test_the_prompt_is_the_users_last_message_not_a_tool_result_or_steering(self):
        from src.agent.agent_loop import _STEERING, _last_prompt
        from src.providers.types import Conversation, Message
        convo = Conversation("sys", [Message.user("review the login code"), Message.assistant("ok"), Message.results([]),
                                     Message.user(f"{_STEERING}use bash")])
        self.assertEqual(_last_prompt(convo), "review the login code")
        self.assertEqual(_last_prompt(Conversation("sys", [])), "")
