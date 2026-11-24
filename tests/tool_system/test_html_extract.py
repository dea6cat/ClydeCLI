"""_html_extract: stdlib HTML to text and the mini selector."""

from __future__ import annotations

import unittest

from src.tool_system.tools import _html_extract


PAGE = """<html><head><title>T</title><style>body{color:red}</style></head>
<body>
<h1>Big Title</h1>
<p class="intro">Hello <b>world</b></p>
<script>var x = 1;</script>
<noscript>no js</noscript>
<ul><li>one</li><li>two</li></ul>
<a href="https://example.com/page">Example link</a>
<div id="main"><p class="item">first</p><p class="item">second</p></div>
</body></html>"""


class TestExtractText(unittest.TestCase):
    def test_drops_script_style_noscript(self):
        text = _html_extract.extract_text(PAGE)
        self.assertNotIn("var x", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("no js", text)

    def test_keeps_structure(self):
        text = _html_extract.extract_text(PAGE)
        self.assertIn("# Big Title", text)
        self.assertIn("Hello world", text)
        self.assertIn("- one", text)
        self.assertIn("- two", text)
        self.assertIn("[Example link](https://example.com/page)", text)

    def test_entities_unescaped(self):
        self.assertIn("Tom & Jerry", _html_extract.extract_text("<p>Tom &amp; Jerry</p>"))


class TestSelect(unittest.TestCase):
    def test_class_selector(self):
        text = _html_extract.select(PAGE, ".item")
        self.assertIn("first", text)
        self.assertIn("second", text)
        self.assertNotIn("Hello", text)

    def test_id_selector(self):
        self.assertIn("first", _html_extract.select(PAGE, "#main"))

    def test_tag_class(self):
        text = _html_extract.select(PAGE, "p.intro")
        self.assertIn("Hello world", text)
        self.assertNotIn("first", text)

    def test_descendant(self):
        text = _html_extract.select(PAGE, "div p")
        self.assertIn("first", text)
        self.assertIn("second", text)
        self.assertNotIn("Hello", text)

    def test_no_match_returns_empty(self):
        self.assertEqual("", _html_extract.select(PAGE, ".missing"))

    def test_unsupported_selector_raises(self):
        with self.assertRaises(ValueError):
            _html_extract.select(PAGE, "div > p")
        with self.assertRaises(ValueError):
            _html_extract.select(PAGE, "")


if __name__ == "__main__":
    unittest.main()
