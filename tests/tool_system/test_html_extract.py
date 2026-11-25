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

    def test_unsupported_selector_raises_on_empty_page(self):
        with self.assertRaises(ValueError):
            _html_extract.select("<html></html>", "a > b")

    def test_nested_matches_dont_repeat_text(self):
        self.assertEqual("x", _html_extract.select("<div><div><p>x</p></div></div>", "div p"))


class TestStructure(unittest.TestCase):
    def test_link_inside_p_kept(self):
        self.assertIn("[docs](/docs)", _html_extract.extract_text('<p>See <a href="/docs">docs</a></p>'))

    def test_nested_list_indented(self):
        lines = _html_extract.extract_text("<ul><li>one<ul><li>inner</li></ul></li></ul>").splitlines()
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[1].startswith("  "))
        self.assertIn("inner", lines[1])

    def test_heading_does_not_fuse_with_following_text(self):
        lines = _html_extract.extract_text("<h2>Install</h2>Run the command").splitlines()
        self.assertEqual(["## Install", "Run the command"], lines)

    def test_deep_nesting_does_not_raise(self):
        deep = "<div>" * 1500 + "bottom" + "</div>" * 1500
        text = _html_extract.extract_text(deep)
        self.assertIn("bottom", text)


if __name__ == "__main__":
    unittest.main()
