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


class TestReviewFixes(unittest.TestCase):
    def test_indented_paragraph_stays_one_line(self):
        # all whitespace in text nodes collapses; only _render's markers break lines
        self.assertEqual("Hello bold world", _html_extract.extract_text("<p>\n  Hello <b>bold</b>\n  world\n</p>"))

    def test_link_inside_inline_tag_keeps_target(self):
        self.assertEqual("[link](/x)", _html_extract.extract_text('<p><strong><a href="/x">link</a></strong></p>'))

    def test_link_inside_heading_keeps_target(self):
        self.assertEqual("## [head](/y)", _html_extract.extract_text('<h2><a href="/y">head</a></h2>'))

    def test_unclosed_p_does_not_nest_or_overflow(self):
        page = "<h1>Head</h1>" + "<p>para &amp; more" * 2000 + "<script>alert(1)</script>"
        text = _html_extract.extract_text(page)
        self.assertIn("# Head", text)
        self.assertIn("para & more", text)
        self.assertNotIn("alert(1)", text)

    def test_a_hostile_deep_page_drops_script_and_unescapes(self):
        # there is no plain-text fallback any more: every walk is iterative, so deep pages render like any other
        text = _html_extract.extract_text("<div>" * 3000 + "<p>Tom &amp; Jerry</p><script>alert(1)" + "<script>" * 5000)
        self.assertEqual("Tom & Jerry", text)

    def test_alternating_auto_close_tags_do_not_nest(self):
        # "<p>a<li>b" repeated must not build a 2000-deep tree: a new auto-close tag pops any auto-close tag on top
        text = _html_extract.extract_text("<p>a<li>b" * 2000)
        self.assertEqual(4000, len(text.splitlines()))


class TestThirdReview(unittest.TestCase):
    """Inline text is joined as the source spaced it, code blocks keep their lines, and nothing is quadratic."""

    def test_tags_inside_a_word_or_number_add_no_space(self):
        text = _html_extract.extract_text('<p>un<b>bold</b>ed and <a href="/x">link</a>. $<span>5</span>.99</p>')
        self.assertEqual("unbolded and [link](/x). $5.99", text)

    def test_a_code_block_keeps_its_lines_and_indentation(self):
        text = _html_extract.extract_text("<p>before</p><pre>def f():\n    return 1\n</pre><p>after</p>")
        self.assertEqual("before\ndef f():\n    return 1\nafter", text)

    def test_br_hr_and_block_containers_break_lines(self):
        self.assertEqual("line1\nline2\nx", _html_extract.extract_text("<p>line1<br>line2</p><hr><p>x</p>"))
        self.assertEqual("outer\ninner", _html_extract.select("<div>outer<div>inner</div></div>", "div"))
        self.assertEqual("Price: $5", _html_extract.extract_text("<p>Price: <label>$</label><mark>5</mark></p>"))

    def test_lists_start_at_the_margin_and_keep_their_marker(self):
        self.assertEqual("- a\n- b", _html_extract.extract_text("<ul><li>a<li>b</ul>"))
        self.assertEqual("- a\n  - b", _html_extract.extract_text("<ul><li>a<ul><li>b</li></ul></li></ul>"))
        self.assertEqual("- x", _html_extract.extract_text("<ul><li><p>x</p></li></ul>"))

    def test_an_empty_heading_prints_nothing(self):
        self.assertEqual("body", _html_extract.extract_text("<h1><img src=logo.png alt=Logo></h1><p>body</p>"))

    def test_select_on_a_deep_match_returns_only_the_match(self):
        page = "<div id=main><p>k</p>" + "<b>" * 3000 + "</div><p>secret-other</p>"
        self.assertNotIn("secret-other", _html_extract.select(page, "#main"))

    def test_a_deep_descendant_selector_is_linear(self):
        import time
        started = time.monotonic()
        _html_extract.select("<div>" * 20000 + "x", "div div")
        self.assertLess(time.monotonic() - started, 2.0)   # was about two minutes when each match re-walked its subtree


if __name__ == "__main__":
    unittest.main()
