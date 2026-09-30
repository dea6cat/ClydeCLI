"""ClydeCLI-specific provider-layer behavior (the ported 2b tests cover the adapters' core)."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from src.agent.conversation import (
    Conversation as History,
    Message as HistoryMessage,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
)
from src.providers import anthropic as an, google as g, openai_compat as oc, registry
from src.providers.convert import append_response, to_canonical
from src.providers.toolcall_repair import recover_toolcalls
from src.providers.toolspec import ToolSpec
from src.providers.types import Conversation, Message, Role, ToolCall
from tests.fakes import FakeProvider

_SPEC = ToolSpec("Read", "Read a file.", {"type": "object", "additionalProperties": False,
                                            "properties": {"file_path": {"type": "string"}}})


def _sse(*events):
    return [f"data: {json.dumps(e)}\n" for e in events] + ["data: [DONE]\n"]


class TestConvert(unittest.TestCase):
    def test_roundtrip_of_tool_turns(self):
        h = History()
        h.add_user_message("read x")
        h.add_assistant_message([TextContentBlock(text="ok"),
                                 ToolUseContentBlock(id="t1", name="Read", input={"file_path": "x"}, signature="sig")])
        h.add_tool_result_message("t1", {"content": "hi"})
        conv = to_canonical(h, "SYS")
        self.assertEqual(conv.system_prompt, "SYS")
        self.assertEqual([m.role for m in conv.messages], [Role.USER, Role.ASSISTANT, Role.USER])
        self.assertEqual(conv.messages[1].tool_calls[0].signature, "sig")
        self.assertEqual(conv.messages[2].tool_results[0].content, '{"content": "hi"}')

    def test_internal_messages_are_skipped(self):
        h = History()
        marker = HistoryMessage(role="system", content=[TextContentBlock(text="[COMPACT BOUNDARY]")])
        marker._is_internal = True
        h.messages.append(marker)
        h.add_user_message("hi")
        self.assertEqual([m.text for m in to_canonical(h, "").messages], ["hi"])

    def test_append_plain_text_stays_a_string(self):
        h = History()
        append_response(h, Message.assistant(text="hello"))
        self.assertEqual(h.messages[-1].content, "hello")

    def test_append_tool_calls_become_blocks(self):
        h = History()
        append_response(h, Message.assistant(text="x", tool_calls=[ToolCall.new("Read", {"file_path": "a"}, id="t")]))
        self.assertIsInstance(h.messages[-1].content[1], ToolUseContentBlock)

    def test_session_roundtrip_keeps_thinking_and_signature(self):
        h = History()
        h.add_user_message("go")
        append_response(h, Message.assistant(thinking="hmm", tool_calls=[ToolCall.new("Read", {}, id="t", signature="s")]))
        restored = History.from_dict(json.loads(json.dumps(h.to_dict())))
        conv = to_canonical(restored, "")
        self.assertEqual(conv.messages[1].thinking, "hmm")
        self.assertEqual(conv.messages[1].tool_calls[0].signature, "s")

    def _tool_turn(self, h, *ids):
        h.add_assistant_message([ToolUseContentBlock(id=i, name="Read", input={}) for i in ids])

    def test_parallel_results_are_grouped(self):
        h = History()
        h.add_user_message("go")
        self._tool_turn(h, "a", "b")
        h.add_tool_result_message("a", "A")
        h.add_tool_result_message("b", "B")
        msgs = to_canonical(h, "").messages
        self.assertEqual(len(msgs), 3)
        self.assertEqual([r.tool_call_id for r in msgs[2].tool_results], ["a", "b"])

    def test_unanswered_call_gets_error_result(self):
        h = History()
        h.add_user_message("go")
        self._tool_turn(h, "a", "b")
        h.add_tool_result_message("a", "A")
        h.add_user_message("never mind")   # Ctrl-C left "b" unanswered
        msgs = to_canonical(h, "").messages
        results = msgs[2].tool_results
        self.assertEqual([r.tool_call_id for r in results], ["a", "b"])
        self.assertTrue(results[1].is_error)
        self.assertEqual(msgs[3].text, "never mind")

    def test_trimmed_history_starts_on_user_and_drops_orphans(self):
        h = History()
        h.add_tool_result_message("gone", "orphan")        # its call was trimmed away
        h.add_assistant_message("dangling assistant")
        h.add_user_message("hi")
        msgs = to_canonical(h, "").messages
        self.assertEqual([(m.role, m.text) for m in msgs], [(Role.USER, "hi")])

    def test_empty_assistant_turn_is_skipped(self):
        h = History()
        h.add_user_message("a")
        h.add_assistant_message("")
        h.add_user_message("b")
        self.assertEqual([m.text for m in to_canonical(h, "").messages], ["a", "b"])

    def test_flatten_tools_renders_text(self):
        h = History()
        h.add_user_message("go")
        self._tool_turn(h, "a")
        h.add_tool_result_message("a", "file body")
        msgs = to_canonical(h, "", flatten_tools=True).messages
        self.assertTrue(all(not m.tool_calls and not m.tool_results for m in msgs))
        self.assertIn("file body", msgs[-1].text)


class TestRegistry(unittest.TestCase):
    def test_all_providers_registered(self):
        reg = registry.build_registry()
        for name in ("openai", "anthropic", "google", "openrouter", "mistral", "nvidia", "deepseek",
                     "cerebras", "glm", "minimax", "ollama"):
            self.assertIn(name, reg)

    def test_glm_and_minimax_endpoints(self):
        reg = registry.build_registry()
        self.assertEqual(reg["glm"].base_url, "https://open.bigmodel.cn/api/paas/v4")
        self.assertIn("glm-5", reg["glm"].list_models())
        self.assertEqual(reg["minimax"].base_url, "https://api.minimaxi.com/anthropic")
        self.assertEqual(reg["minimax"].key_env, "MINIMAX_API_KEY")
        self.assertIn("MiniMax-M2.7", reg["minimax"].list_models())

    def test_resolve_explicit_bare_and_ambiguous(self):
        a = FakeProvider(name="a", models=("shared", "only-a"))
        b = FakeProvider(name="b", models=("shared",))
        reg = {"a": a, "b": b}
        self.assertEqual(registry.resolve(reg, "b:shared"), (b, "shared"))
        self.assertEqual(registry.resolve(reg, "only-a"), (a, "only-a"))
        self.assertIsNone(registry.resolve(reg, "shared"))
        self.assertIsNone(registry.resolve(reg, "missing"))

    def test_ollama_tag_resolves_as_bare_name(self):
        ollama = FakeProvider(name="ollama", models=("qwen3:8b",))
        self.assertEqual(registry.resolve({"ollama": ollama}, "qwen3:8b"), (ollama, "qwen3:8b"))

    def test_pick_default_prefers_local_ollama(self):
        self.assertEqual(registry.pick_default_model({"ollama": FakeProvider(name="ollama", models=("m1", "m2"))}),
                         "ollama:m1")
        self.assertIsNone(registry.pick_default_model({"ollama": FakeProvider(name="ollama", models=())}))


class TestWireDetails(unittest.TestCase):
    def test_openai_compat_omits_empty_tools_and_parses_usage(self):
        captured = {}

        def fake_stream(url, payload, **k):
            captured["p"] = payload
            return iter(_sse({"choices": [{"delta": {"content": "hi"}}]},
                             {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2,
                                                       "prompt_tokens_details": {"cached_tokens": 4}}}))

        p = oc.OpenAICompatProvider("openai", "https://x/v1", "OPENAI_API_KEY", stream_usage=True)
        with patch.object(oc, "post_stream", fake_stream), patch.dict(os.environ, {"OPENAI_API_KEY": "k"}):
            resp = p.stream(Conversation("S", [Message.user("q")]), "gpt-5.4", (), lambda c: None)
        self.assertNotIn("tools", captured["p"])
        self.assertEqual(captured["p"]["stream_options"], {"include_usage": True})
        self.assertEqual(resp.usage, {"input_tokens": 7, "output_tokens": 2, "cache_read_input_tokens": 4})

    def test_openai_compat_no_stream_options_unless_enabled(self):
        captured = {}
        p = oc.OpenAICompatProvider("mistral", "https://x/v1", "MISTRAL_API_KEY")
        with patch.object(oc, "post_stream", lambda url, payload, **k: captured.setdefault("p", payload) and iter(["data: [DONE]\n"])):
            p.stream(Conversation("S", [Message.user("q")]), "m", (_SPEC,), lambda c: None)
        self.assertNotIn("stream_options", captured["p"])
        self.assertEqual(captured["p"]["tools"][0]["function"]["parameters"], _SPEC.input_schema)

    def test_anthropic_stream_usage_and_custom_base_url(self):
        captured = {}
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 11, "cache_read_input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "yo"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
            {"type": "message_stop"},
        ]

        def fake_stream(url, payload, **k):
            captured["url"], captured["p"] = url, payload
            return iter(f"data: {json.dumps(e)}\n" for e in events)

        p = an.AnthropicProvider(name="minimax", base_url="https://api.minimaxi.com/anthropic",
                                 key_env="MINIMAX_API_KEY", models=["MiniMax-M2.7"])
        with patch.object(an, "post_stream", fake_stream), patch.dict(os.environ, {"MINIMAX_API_KEY": "k"}):
            resp = p.stream(Conversation("S", [Message.user("q")]), "MiniMax-M2.7", (), lambda c: None)
        self.assertEqual(captured["url"], "https://api.minimaxi.com/anthropic/v1/messages")
        self.assertNotIn("tools", captured["p"])
        self.assertEqual(resp.usage, {"input_tokens": 11, "cache_read_input_tokens": 5, "output_tokens": 3})
        self.assertEqual(resp.message.text, "yo")

    def test_gemini_uses_json_schema_field(self):
        decl = g.to_gemini((_SPEC,))[0]["functionDeclarations"][0]
        self.assertEqual(decl["parametersJsonSchema"], _SPEC.input_schema)
        self.assertNotIn("parameters", decl)
        self.assertEqual(g.to_gemini(()), [])


class TestStreamFailures(unittest.TestCase):
    def _anthropic(self, events):
        p = an.AnthropicProvider()
        lines = [f"data: {json.dumps(e)}\n" for e in events]
        with patch.object(an, "post_stream", lambda *a, **k: iter(lines)), \
                patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            return p.stream(Conversation("S", [Message.user("q")]), "claude-sonnet-4-6", (), lambda c: None)

    def test_anthropic_error_event_raises_retryable(self):
        from src.providers.base import ProviderError
        with self.assertRaises(ProviderError) as ctx:
            self._anthropic([{"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}])
        self.assertTrue(ctx.exception.retryable)

    def test_anthropic_truncated_stream_raises(self):
        from src.providers.base import ProviderError
        with self.assertRaises(ProviderError):
            self._anthropic([{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "par"}}])

    def test_openai_compat_error_chunk_and_truncation(self):
        from src.providers.base import ProviderError
        p = oc.OpenAICompatProvider("openai", "https://x/v1", "OPENAI_API_KEY")
        for lines in (_sse({"error": {"message": "overloaded"}}),
                      ['data: {"choices": [{"delta": {"content": "par"}}]}\n']):
            with patch.object(oc, "post_stream", lambda *a, _l=lines, **k: iter(_l)), \
                    patch.dict(os.environ, {"OPENAI_API_KEY": "k"}):
                with self.assertRaises(ProviderError):
                    p.stream(Conversation("S", [Message.user("q")]), "gpt-5.4", (), lambda c: None)

    def test_anthropic_sanitizes_foreign_tool_ids(self):
        conv = Conversation("S", [Message.user("q"),
                                  Message.assistant(tool_calls=[ToolCall("functions.read:0", "Read", {})]),
                                  Message.results([__import__("src.providers.types", fromlist=["ToolResult"]).ToolResult("functions.read:0", "ok")])])
        msgs = an.AnthropicProvider()._messages(conv)
        self.assertEqual(msgs[1]["content"][0]["id"], "functions_read_0")
        self.assertEqual(msgs[2]["content"][0]["tool_use_id"], "functions_read_0")


class TestToolCallRepair(unittest.TestCase):
    def test_recovers_fenced_json_call(self):
        text = 'Sure:\n```json\n{"name": "Read", "arguments": {"file_path": "a.py"}}\n```'
        self.assertEqual(recover_toolcalls(text, ["Read", "Write"]), [("Read", {"file_path": "a.py"})])

    def test_ignores_unknown_tools_and_prose(self):
        self.assertEqual(recover_toolcalls('```json\n{"name": "Nope"}\n```', ["Read"]), [])
        self.assertEqual(recover_toolcalls("just talking about Read", ["Read"]), [])


if __name__ == "__main__":
    unittest.main()
