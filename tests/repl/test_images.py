"""Pasted images: path detection, history round trip, and each provider's wire format."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.conversation import Conversation, ImageContentBlock
from src.providers.anthropic import AnthropicProvider
from src.providers.convert import to_canonical
from src.providers.google import GoogleProvider
from src.providers.ollama import OllamaProvider
from src.providers.openai_compat import OpenAICompatProvider
from src.repl.images import image_path


class TestImagePath(unittest.TestCase):
    def test_copied_paths_resolve_to_the_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "my shot.png"
            image.write_bytes(b"png")
            for pasted in (str(image), f"'{image}'", str(image).replace(" ", "\\ "), f"file://{tmp}/my%20shot.png"):
                self.assertEqual(image_path(pasted), image, pasted)

    def test_other_text_is_not_an_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            text_file = Path(tmp) / "notes.txt"
            text_file.write_text("hi")
            for pasted in ("hello world", str(text_file), f"{tmp}/missing.png", f"{tmp}/a.png\nmore"):
                self.assertIsNone(image_path(pasted), pasted)


class TestImageMessages(unittest.TestCase):
    def setUp(self):
        self.history = Conversation()
        self.history.add_user_message("look [Image #1]", [ImageContentBlock(media_type="image/jpeg", data="QUJD")])

    def test_survives_session_round_trip(self):
        restored = Conversation.from_dict(self.history.to_dict())
        self.assertEqual(to_canonical(restored, "sys").messages[0].images, [("image/jpeg", "QUJD")])

    def test_providers_send_the_image(self):
        conv = to_canonical(self.history, "sys")
        anthropic = AnthropicProvider.__new__(AnthropicProvider)._messages(conv)[0]["content"][1]
        self.assertEqual(anthropic["source"], {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"})
        openai = OpenAICompatProvider.__new__(OpenAICompatProvider)._messages(conv)[1]["content"][1]
        self.assertEqual(openai["image_url"]["url"], "data:image/jpeg;base64,QUJD")
        self.assertEqual(OllamaProvider.__new__(OllamaProvider)._messages(conv)[1]["images"], ["QUJD"])
        google = GoogleProvider.__new__(GoogleProvider)._contents(conv)[0]["parts"][1]
        self.assertEqual(google["inlineData"], {"mimeType": "image/jpeg", "data": "QUJD"})


if __name__ == "__main__":
    unittest.main()
