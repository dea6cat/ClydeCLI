"""The documentation tab is built from the repository's Markdown: links stay inside the site, nothing raw gets through, every source exists."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tools import build_docs
from tools.build_docs import PAGES, ROOT, Converter, build, inline, release_heading, resolve


class Markdown(unittest.TestCase):
    def test_raw_html_is_escaped_and_code_is_kept_literal(self):
        out = inline("a <script>x</script> and `<name> **not bold**`", "docs/usage.md")
        self.assertNotIn("<script>", out)
        self.assertIn("<code>&lt;name&gt; **not bold**</code>", out)

    def test_a_link_to_another_built_page_stays_on_the_site_and_other_files_go_to_github(self):
        self.assertEqual(resolve("features.md#hooks", "docs/usage.md"), "features.html#hooks")
        self.assertEqual(resolve("../CHANGELOG.md", "docs/usage.md"), "releases.html")
        self.assertEqual(resolve("../src/repl/core.py", "docs/usage.md"), f"{build_docs.REPO}/blob/main/src/repl/core.py")
        self.assertEqual(resolve("research/", "docs/usage.md"), f"{build_docs.REPO}/tree/main/docs/research")
        self.assertEqual(resolve("https://example.com/x", "docs/usage.md"), "https://example.com/x")

    def test_a_link_text_with_code_keeps_the_code(self):
        self.assertEqual(inline("[`/rewind` undoes](https://e.com/x)", "docs/usage.md"), '<a href="https://e.com/x"><code>/rewind</code> undoes</a>')

    def test_blocks(self):
        html = Converter("docs/usage.md").convert("# T\n\ntext **bold** *it*\nsecond line\n\n- a\n  - nested\n- b\n\n1. one\n2. two\n\n| H | I |\n|---|---|\n| 1 | 2 |\n\n```\n<x>\n```\n\n> quote")
        for part in ('<h1 id="t">', "text <strong>bold</strong> <em>it</em> second line", "<li>a<ul><li>nested</li></ul></li>",
                     "<ol><li>one</li><li>two</li></ol>", "<th>H</th>", "<td>2</td>", "<pre", "&lt;x&gt;", "<blockquote>"):
            self.assertIn(part, html)

    def test_an_escaped_pipe_stays_inside_its_table_cell(self):
        html = Converter("docs/usage.md").convert("| A | B |\n|---|---|\n| `/m [all\\|x]` | text |\n")
        self.assertIn("<td><code>/m [all|x]</code></td><td>text</td>", html)

    def test_repeated_headings_get_distinct_anchors(self):
        html = Converter("docs/usage.md").convert("## Added\n\n## Added")
        self.assertIn('id="added"', html)
        self.assertIn('id="added-1"', html)

    def test_a_release_heading_gets_a_version_anchor(self):
        self.assertEqual(release_heading("[0.8.0] - 2026-10-27"), ("v0-8-0", "0.8.0, 2026-10-27"))
        self.assertEqual(release_heading("[Unreleased]"), ("unreleased", "Unreleased"))
        self.assertIsNone(release_heading("Added"))


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.pages = build(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_source_is_built(self):
        for _, source, name, _ in PAGES:
            self.assertTrue((ROOT / source).is_file(), source)
            self.assertIn(f"{name}.html", self.pages)
        self.assertIn("releases.html", self.pages)
        self.assertIn("index.html", self.pages)

    def test_every_link_between_built_pages_lands_on_a_page_and_an_anchor_that_exist(self):
        ids = {p: set(re.findall(r'id="([^"]+)"', (self.out / p).read_text())) for p in self.pages}
        for page in self.pages:
            for target, anchor in re.findall(r'href="([^"#:/]*\.html)(#[^"]*)?"', (self.out / page).read_text()):
                self.assertIn(target, self.pages, f"{page} links to {target}")
                if anchor:
                    self.assertIn(anchor[1:], ids[target], f"{page} links to {target}{anchor}")

    def test_releases_lists_the_latest_version_with_its_anchor(self):
        text = (self.out / "releases.html").read_text()
        version = build_docs.latest_version((ROOT / "CHANGELOG.md").read_text())
        self.assertIn(f'id="v{version.replace(".", "-")}"', text)
        self.assertIn("github.com/dea6cat/ClydeCLI/releases", text)

    def test_the_search_index_covers_every_page(self):
        index = json.loads((self.out / "search.json").read_text())
        self.assertEqual(len(index), len(self.pages))
        self.assertTrue(all(e["title"] and e["text"] for e in index))

    def test_no_page_carries_a_script_from_the_markdown(self):
        for page in self.pages:
            self.assertEqual(len(re.findall(r"<script", (self.out / page).read_text())), 4, page)   # the template's own, and no more


if __name__ == "__main__":
    unittest.main()
