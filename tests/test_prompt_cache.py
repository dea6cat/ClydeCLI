import os
import unittest
from unittest.mock import patch

from src.providers import anthropic as A
from src.providers.toolspec import ToolSpec
from src.providers.types import Conversation

_TOOLS = (ToolSpec("Read", "Read a file.", {"type": "object", "properties": {"file_path": {"type": "string"}}}),
          ToolSpec("Grep", "Search files.", {"type": "object", "properties": {"pattern": {"type": "string"}}}))


class Cache(unittest.TestCase):
    def test_system_and_tools_cached(self):
        captured = {}

        def fake_post(url, payload, **k):
            captured["p"] = payload
            return {"content": [{"type": "text", "text": "ok"}]}

        with patch.object(A, "post_json", fake_post), patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
            A.AnthropicProvider().send(Conversation(system_prompt="SYS"), "claude-sonnet-5", _TOOLS)
        p = captured["p"]
        self.assertEqual(p["system"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(p["tools"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", p["tools"][0])


if __name__ == "__main__":
    unittest.main()
