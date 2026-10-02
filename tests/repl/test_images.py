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


class TestPastedText(unittest.TestCase):
    def setUp(self):
        from src.repl.core import ClydeREPL

        self.repl = ClydeREPL.__new__(ClydeREPL)
        self.repl._pastes = {1: ImageContentBlock(data="QUJD")}

    def test_long_paste_collapses_and_expands_back(self):
        text = "\n".join(f"line {i}" for i in range(146))
        marker = self.repl._collapse_text(text)
        self.assertEqual(marker, "[Pasted text #2 +145 lines]")
        self.assertEqual(self.repl._expand_pastes(f"fix [Image #1] {marker}"), f"fix [Image #1] {text}")

    def test_short_paste_stays_inline(self):
        self.assertEqual(self.repl._collapse_text("a\nb"), "a\nb")
        self.assertEqual(len(self.repl._pastes), 1)


if __name__ == "__main__":
    unittest.main()


class TestImageSupport(unittest.TestCase):
    def _repl(self, model: str, provider=None):
        from rich.console import Console
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console = Console(record=True, width=200)
        repl.provider = provider or type("P", (), {"name": "openai"})()
        repl.model = model
        repl._pastes = {}
        return repl

    def test_the_catalog_and_ollama_say_which_models_read_images(self):
        self.assertFalse(self._repl("gpt-3.5-turbo")._reads_images())
        self.assertTrue(self._repl("claude-sonnet-4-6")._reads_images())
        self.assertIsNone(self._repl("some-unknown-model")._reads_images())            # unknown: don't block
        vision = type("O", (), {"name": "ollama", "reads_images": lambda self, m: m == "llava"})()
        self.assertTrue(self._repl("llava", vision)._reads_images())
        self.assertFalse(self._repl("qwen3", vision)._reads_images())

    def test_pasting_for_a_text_only_model_warns_but_keeps_the_marker(self):
        from unittest.mock import Mock, patch
        repl, buffer = self._repl("gpt-3.5-turbo"), Mock()
        with patch("prompt_toolkit.application.run_in_terminal", side_effect=lambda f: f()):
            repl._insert_image(buffer, b"\x89PNG small", "image/png")
        buffer.insert_text.assert_called_once_with("[Image #1]")
        self.assertIn("can't read images", repl.console.export_text())

    def test_an_oversized_image_is_shrunk_or_refused(self):
        from unittest.mock import Mock, patch
        repl, buffer = self._repl("claude-sonnet-4-6"), Mock()
        big = b"x" * (6 * 1024 * 1024)
        with patch("prompt_toolkit.application.run_in_terminal", side_effect=lambda f: f()), \
                patch("src.repl.core.shrink", return_value=b"\xff\xd8\xff small jpeg"):
            repl._insert_image(buffer, big, "image/png")
        self.assertEqual(repl._pastes[1].media_type, "image/jpeg")
        self.assertIn("shrank it", repl.console.export_text())
        buffer = Mock()
        with patch("prompt_toolkit.application.run_in_terminal", side_effect=lambda f: f()), \
                patch("src.repl.core.shrink", return_value=None):
            repl._insert_image(buffer, big, "image/png")
        buffer.insert_text.assert_not_called()
        self.assertIn("couldn't be shrunk", repl.console.export_text())

    def test_shrink_needs_macos_sips(self):
        from unittest.mock import patch
        from src.repl.images import shrink
        with patch("sys.platform", "linux"):
            self.assertIsNone(shrink(b"anything"))
