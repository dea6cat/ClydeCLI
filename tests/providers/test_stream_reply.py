"""The three ways the per-adapter stream code had drifted, checked through the adapters themselves."""
import json
import os
import unittest
from unittest.mock import patch

from src.providers import google, omlx
from src.providers.base import ProviderError
from src.providers.toolspec import ToolSpec
from src.providers.types import Conversation

_READ = ToolSpec(name="Read", description="read a file", input_schema={"type": "object", "properties": {"file_path": {"type": "string"}}})


def _sse(*events):
    return iter([f"data: {e if isinstance(e, str) else json.dumps(e)}\n" for e in events])


class TestGemini(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "k"})
        env.start()
        self.addCleanup(env.stop)

    def _stream(self, *events):
        with patch.object(google, "post_stream", lambda *a, **k: _sse(*events)):
            return google.GoogleProvider().stream(Conversation(system_prompt="s"), "gemini-2.0-flash", (), lambda _c: None)

    def test_a_reply_cut_off_at_the_output_limit_reads_as_cut_off(self):
        response = self._stream({"candidates": [{"content": {"parts": [{"text": "half an ans"}]}, "finishReason": "MAX_TOKENS"}]})
        self.assertEqual(response.done_reason, "length")   # what the agent loop asks the model to continue

    def test_a_stream_that_stops_before_the_finish_reason_is_a_retryable_error(self):
        with self.assertRaises(ProviderError) as caught:
            self._stream({"candidates": [{"content": {"parts": [{"text": "half an ans"}]}}]})
        self.assertTrue(caught.exception.retryable)


class TestOMLX(unittest.TestCase):
    def test_a_tool_call_written_as_text_is_recovered(self):
        said = '```json\n{"name": "Read", "arguments": {"file_path": "a.py"}}\n```'
        events = ({"choices": [{"delta": {"content": said}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}, "[DONE]")
        provider = omlx.OMLXProvider()
        with patch("src.providers.openai_compat.post_stream", lambda *a, **k: _sse(*events)), \
                patch.object(provider, "_ensure_server"), patch.object(provider, "ensure_loaded"):
            response = provider.stream(Conversation(system_prompt="s"), "some-mlx-model", (_READ,), lambda _c: None)
        self.assertEqual([(c.name, c.arguments) for c in response.message.tool_calls], [("Read", {"file_path": "a.py"})])


if __name__ == "__main__":
    unittest.main()
