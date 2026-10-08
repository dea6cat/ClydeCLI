"""Bonny's markdown renderer: the page's own JavaScript, run under Node against a minimal fake DOM.

The renderer is the page's `markdown()`; the test slices it out of PAGE, so what is tested is what ships. Skipped without Node."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest

from src.bonny.page import PAGE

_FAKE_DOM = r"""
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
class Node_ {
  constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.className = ""; }
  append(...xs) { for (const x of xs) this.kids.push(x); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
  replaceChildren() {}
  get html() {
    const kids = this.kids.map((k) => (typeof k === "string" ? esc(k) : k.html)).join("");
    if (this.tag === "#frag") return kids;
    const cls = this.className ? ` class="${this.className}"` : "";
    const extra = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${esc(v)}"`).join("");
    return `<${this.tag}${cls}${extra}>${kids}</${this.tag}>`;
  }
}
globalThis.document = { createElement: (t) => new Node_(t), createDocumentFragment: () => new Node_("#frag") };
"""


def _slice() -> str:
    start = PAGE.index("function h(tag")
    end = PAGE.index('const col = $("col")')
    return PAGE[start:end]


def render(texts: list[str]) -> list[str]:
    script = _FAKE_DOM + _slice() + "\nconst cases = " + json.dumps(texts) + \
        "\nconsole.log(JSON.stringify(cases.map((t) => markdown(t).html)));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestMarkdown(unittest.TestCase):
    def test_a_table_becomes_a_table_with_one_header_row(self):
        html, = render(["| Goal | Path |\n| :--- | ---: |\n| **Quick** | OpenRouter |\n| Speed | Groq |"])
        self.assertIn('<div class="tablewrap"><table><thead>', html)
        self.assertEqual(len(re.findall(r"<th[ >]", html)), 2)
        self.assertEqual(html.count("<tr>"), 3)
        self.assertIn("<th>Goal</th>", html)
        self.assertIn('<th class="r">Path</th>', html)           # ---: right-aligns
        self.assertIn("<td><strong>Quick</strong></td>", html)    # cells get inline formatting
        self.assertNotIn("|", html)

    def test_the_screenshot_case_a_table_without_outer_pipes_and_a_heading_before_it(self):
        html, = render(["### Quick Summary Table\nGoal | Why?\n--- | ---\nQuick Start | One key"])
        self.assertIn("<h4>Quick Summary Table</h4>", html)
        self.assertIn("<td>Quick Start</td><td>One key</td>", html)

    def test_escaped_pipes_stay_in_the_cell_and_short_rows_are_padded(self):
        html, = render(["| a | b |\n|---|---|\n| x \\| y |"])
        self.assertIn("<td>x | y</td><td></td>", html)

    def test_pipes_without_a_separator_row_are_just_text(self):
        html, = render(["a | b\nc | d"])
        self.assertNotIn("<table", html)
        self.assertTrue(html.startswith("<p>"))

    def test_numbered_and_nested_lists(self):
        html, = render(["1. First\n2. Second\n   - nested a\n   - nested b\n3. Third"])
        self.assertIn("<ol><li>First</li><li>Second<ul><li>nested a</li><li>nested b</li></ul></li><li>Third</li></ol>", html)

    def test_a_blank_line_between_items_keeps_one_list(self):
        html, = render(["- a\n\n- b"])
        self.assertEqual(html.count("<ul>"), 1)

    def test_heading_levels_rules_quotes_and_emphasis(self):
        html, = render(["# One\n## Two\n### Three\n\n---\n\n> quoted *note*\n\nplain **bold** and *italic*"])
        for expected in ("<h2>One</h2>", "<h3>Two</h3>", "<h4>Three</h4>", "<hr></hr>", "<blockquote><p>quoted <em>note</em></p></blockquote>",
                         "<strong>bold</strong>", "<em>italic</em>"):
            self.assertIn(expected, html)

    def test_a_fenced_block_is_code_even_if_it_holds_a_table(self):
        html, = render(["```\n| a | b |\n|---|---|\n```"])
        self.assertIn("<pre><code>", html)
        self.assertNotIn("<table", html)

    def test_markup_in_a_reply_stays_text_and_only_http_links_become_links(self):
        html, = render(["| x |\n|---|\n| <img src=x onerror=alert(1)> |\n\n<script>alert(1)</script> [bad](javascript:alert(1)) [ok](https://example.com)"])
        self.assertNotIn("<img", html)
        self.assertNotIn("<script", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn('href="javascript', html)
        self.assertIn('href="https://example.com/"', html)

    def test_unmatched_stars_and_lone_pipes_do_not_break_a_paragraph(self):
        html, = render(["2 * 3 and a | pipe"])
        self.assertEqual(html, "<p>2 * 3 and a | pipe</p>")


if __name__ == "__main__":
    unittest.main()
