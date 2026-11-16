"""How long a conversation's history is: the /settings value, and the first message (the request) always stays."""

from __future__ import annotations

import unittest

from src import config
from src.agent.session import Session
from src.conversation import Conversation


class TestHistory(unittest.TestCase):
    def test_past_the_cap_the_oldest_message_after_the_first_goes(self):
        conversation = Conversation(max_history=3)
        for text in ("the request", "one", "two", "three"):
            conversation.add_user_message(text)
        self.assertEqual([m.content for m in conversation.messages], ["the request", "two", "three"])

    def test_a_session_uses_the_history_setting_new_or_resumed(self):
        cfg = config.load_config()
        cfg["session"]["max_history"] = 7
        config.save_config(cfg)
        session = Session.create("p", "m")
        self.assertEqual(session.conversation.max_history, 7)
        session.save()
        cfg["session"]["max_history"] = 9
        config.save_config(cfg)
        self.assertEqual(Session.load(session.session_id).conversation.max_history, 9)


if __name__ == "__main__":
    unittest.main()
