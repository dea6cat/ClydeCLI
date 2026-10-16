"""A lone surrogate in a message must not reach a provider as a \\ud83d escape: NVIDIA's API answers that with HTTP 400,
and because the text stays in the history every later request would fail the same way."""
from __future__ import annotations

import json
import unittest

from src.providers import base


def _body(text: str) -> bytes:
    return base._request("http://localhost/x", {"messages": [{"role": "user", "content": text}]}, {}).data


class TestRequestEncoding(unittest.TestCase):
    def test_a_lone_surrogate_is_sent_as_the_replacement_character(self):
        body = _body("bad \ud83d byte")
        self.assertNotIn(b"\\ud", body)
        self.assertEqual(json.loads(body.decode("utf-8"))["messages"][0]["content"], "bad � byte")

    def test_text_that_is_valid_is_sent_unchanged(self):
        text = "héllo ✓ 😀 日本語"
        self.assertEqual(json.loads(_body(text).decode("utf-8"))["messages"][0]["content"], text)

    def test_a_whole_conversation_with_one_bad_message_still_encodes(self):
        payload = {"messages": [{"content": "ok"}, {"content": "x\udcff"}, {"content": "fine"}], "stream": True}
        parsed = json.loads(base._request("http://localhost/x", payload, {}).data.decode("utf-8"))
        self.assertEqual([m["content"] for m in parsed["messages"]], ["ok", "x�", "fine"])


if __name__ == "__main__":
    unittest.main()
