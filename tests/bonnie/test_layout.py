"""Bonnie's layout: the conversation uses all the width beside the menu; only the composer and its heading stay centred."""
from __future__ import annotations

import re
import unittest

from src.bonnie.page import PAGE


def _rule(selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", PAGE)
    assert match, f"no rule for {selector}"
    return match.group(1)


class TestLayout(unittest.TestCase):
    def test_the_frame_and_the_conversation_are_not_capped(self):
        for selector in (".frame", ".col"):
            self.assertNotIn("max-width", _rule(selector), selector)

    def test_the_frame_has_no_side_hairlines_of_its_own(self):
        self.assertNotIn("border-left", _rule(".frame"))   # the menu already draws the divider
        self.assertNotIn("border-right", _rule(".frame"))

    def test_the_composer_and_its_heading_stay_centred_at_a_readable_width(self):
        for selector in (".box", ".hero"):
            rule = _rule(selector)
            self.assertIn("max-width: 720px", rule, selector)
            self.assertIn("margin: 0 auto", rule, selector)


if __name__ == "__main__":
    unittest.main()
