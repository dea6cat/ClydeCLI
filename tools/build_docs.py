"""Builds the site's documentation tab (site/docs/) from the repository's own Markdown.

The Markdown in docs/, docs/research/, CHANGELOG.md and a few top-level files stays the only source: this turns it into pages in the
site's look, with a sidebar, a search index and a Releases page, so nobody has to go to GitHub to read it. Standard library only; the
pages are generated at deploy time (see .github/workflows/pages.yml) and are not committed.

    python3 tools/build_docs.py [--out site/docs]
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/dea6cat/ClydeCLI"
SITE = "https://dea6cat.github.io/ClydeCLI/"

# (group, source, output name, title). The group order is the sidebar order.
PAGES = [
    ("Guide", "docs/install.md", "install", "Install"),
    ("Guide", "docs/usage.md", "usage", "Usage"),
    ("Guide", "docs/features.md", "features", "Features"),
    ("Guide", "docs/messaging.md", "messaging", "Messaging"),
    ("Guide", "docs/status.md", "status", "Status"),
    ("Guide", "docs/telemetry.md", "telemetry", "Telemetry"),
    ("Guide", "docs/project-structure.md", "project-structure", "Project structure"),
    ("Research", "docs/research/README.md", "research", "Research notes"),
    ("Research", "docs/research/small-models.md", "research-small-models", "Small models"),
    ("Research", "docs/research/local-models.md", "research-local-models", "Local models"),
    ("Research", "docs/research/omlx.md", "research-omlx", "oMLX"),
    ("Research", "docs/research/tune.md", "research-tune", "Tuning"),
    ("Research", "docs/research/fine-tuning-data.md", "research-fine-tuning-data", "Fine-tuning data"),
    ("Research", "docs/research/security-review-2026-10.md", "research-security-review", "Security review, October 2026"),
    ("Research", "docs/research/script-tool.md", "research-script-tool", "Script tool study"),
    ("Research", "docs/ccr-context-plan.md", "ccr-context-plan", "Context plan"),
    ("Project", "SECURITY.md", "security", "Security policy"),
    ("Project", "CONTRIBUTING.md", "contributing", "Contributing"),
    ("Project", "GOVERNANCE.md", "governance", "Governance"),
    ("Project", "EGRESS.md", "egress", "What leaves your machine"),
    ("Project", "THIRD_PARTY.md", "third-party", "Third-party notices"),
    ("Project", "docs/license.md", "license", "License"),
]
RELEASES = ("CHANGELOG.md", "releases", "Releases")
OUT_NAME = {src: name for _, src, name, _ in PAGES} | {RELEASES[0]: RELEASES[1]}

CODE = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)")


def slug(text: str) -> str:
    """A heading's anchor, as GitHub makes it, so links written for GitHub keep working."""
    return re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")


def resolve(target: str, source: str) -> str:
    """Where a link in `source` should go on the site: another built page, or the file on GitHub."""
    if re.match(r"^(https?:|mailto:|#)", target):
        return target
    path, _, anchor = target.partition("#")
    full = (ROOT / source).parent.joinpath(path).resolve()
    try:
        rel = full.relative_to(ROOT).as_posix()
    except ValueError:
        return target
    suffix = f"#{anchor}" if anchor else ""
    if rel in OUT_NAME:
        return f"{OUT_NAME[rel]}.html{suffix}"
    return f"{REPO}/{'tree' if full.is_dir() else 'blob'}/main/{rel}{suffix}"


def emphasis(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)


def inline(text: str, source: str) -> str:
    """Code, links, bold and italic. Everything else is escaped: the pages never carry raw HTML from the Markdown."""
    keep: list[str] = []

    def stash(markup: str) -> str:
        keep.append(markup)
        return f"\x00{len(keep) - 1}\x00"

    text = CODE.sub(lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = LINK.sub(lambda m: stash(f'<a href="{html.escape(resolve(m.group(2), source))}">{emphasis(m.group(1))}</a>'), text)
    text = emphasis(text)
    while "\x00" in text:   # a link's text can hold stashed code
        text = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)
    return text


def cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row.strip().removeprefix("|").removesuffix("|"))]   # `\|` is a pipe inside a cell


class Converter:
    """Block-level Markdown: headings, paragraphs, fenced code, tables, quotes and nested lists."""

    def __init__(self, source: str, heading=None):
        self.source, self.heading, self.seen = source, heading, {}
        self.headings: list[tuple[int, str, str]] = []

    def anchor(self, text: str) -> str:
        base = slug(text) or "section"
        n = self.seen.get(base, 0)
        self.seen[base] = n + 1
        return base if n == 0 else f"{base}-{n}"

    def convert(self, md: str) -> str:
        return "\n".join(self.blocks(md.split("\n")))

    def blocks(self, lines: list[str]) -> list[str]:
        out, i = [], 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
            elif line.startswith("```"):
                end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("```")), len(lines))
                out.append(f'<pre tabindex="0"><code>{html.escape(chr(10).join(lines[i + 1:end]))}</code></pre>')
                i = end + 1
            elif m := re.match(r"^(#{1,6})\s+(.*?)\s*#*$", line):
                level, text = len(m.group(1)), m.group(2)
                custom = self.heading(text) if self.heading else None
                ident, shown = custom or (self.anchor(text), text)
                self.headings.append((level, ident, re.sub(r"[`*]", "", shown)))
                out.append(f'<h{level} id="{ident}">{inline(shown, self.source)}</h{level}>')
                i += 1
            elif re.match(r"^(-{3,}|\*{3,})\s*$", line):
                out.append("<hr>")
                i += 1
            elif "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
                j = i + 2
                while j < len(lines) and "|" in lines[j]:
                    j += 1
                head = "".join(f"<th>{inline(c, self.source)}</th>" for c in cells(line))
                body = "".join("<tr>" + "".join(f"<td>{inline(c, self.source)}</td>" for c in cells(r)) + "</tr>" for r in lines[i + 2:j])
                out.append(f'<div class="tablewrap" tabindex="0"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
                i = j
            elif line.startswith(">"):
                j = i
                while j < len(lines) and lines[j].startswith(">"):
                    j += 1
                out.append("<blockquote>" + "\n".join(self.blocks([re.sub(r"^>\s?", "", q) for q in lines[i:j]])) + "</blockquote>")
                i = j
            elif ITEM.match(line):
                markup, i = self.list(lines, i)
                out.append(markup)
            else:
                j = i + 1
                while j < len(lines) and lines[j].strip() and not re.match(r"^(#{1,6}\s|```|>|\s*([-*]|\d+\.)\s)", lines[j]):
                    j += 1
                out.append(f"<p>{inline(' '.join(s.strip() for s in lines[i:j]), self.source)}</p>")
                i = j
        return out

    def list(self, lines: list[str], i: int) -> tuple[str, int]:
        first = ITEM.match(lines[i])
        base, tag = len(first.group(1)), "ol" if first.group(2)[0].isdigit() else "ul"
        items: list[str] = []
        while i < len(lines):
            m = ITEM.match(lines[i])
            if not m or len(m.group(1)) != base or m.group(2)[0].isdigit() != (tag == "ol"):
                break
            text, i, nested = m.group(3), i + 1, ""
            while i < len(lines) and lines[i].strip() and not ITEM.match(lines[i]) and lines[i].startswith(" "):
                text += " " + lines[i].strip()   # a continuation line
                i += 1
            deeper = ITEM.match(lines[i]) if i < len(lines) else None
            if deeper and len(deeper.group(1)) > base:
                nested, i = self.list(lines, i)
            items.append(f"<li>{inline(text, self.source)}{nested}</li>")
            nxt = ITEM.match(lines[i + 1]) if i + 1 < len(lines) else None
            if i < len(lines) and not lines[i].strip() and nxt and len(nxt.group(1)) == base and nxt.group(2)[0].isdigit() == (tag == "ol"):
                i += 1   # one blank line between items of the same list
        return f"<{tag}>{''.join(items)}</{tag}>", i


def release_heading(text: str):
    """`[0.8.0] - 2026-10-27` gets the anchor v0-8-0 and the title `0.8.0, 2026-10-27`; other headings keep the default."""
    m = re.match(r"^\[([^\]]+)\](?: - (.*))?$", text)
    if not m:
        return None
    ver = m.group(1)
    ident = "v" + slug(ver.replace(".", "-")) if ver[0].isdigit() else slug(ver)
    return ident, f"{ver}, {m.group(2)}" if m.group(2) else ver


def split_title(md: str, fallback: str) -> tuple[str, str]:
    """The page title from its first `# ` line (dropped from the body), and the body without the 'Back to the README' line."""
    lines = md.split("\n")
    title = fallback
    if lines and lines[0].startswith("# "):
        title, lines = lines[0][2:].strip(), lines[1:]
    return title, re.sub(r"^\s*\[Back to the README\]\([^)]*\)\s*$", "", "\n".join(lines), flags=re.M)


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · ClydeCLI docs</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta name="theme-color" content="#e8e5dd" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1a14" media="(prefers-color-scheme: dark)">
<link rel="icon" type="image/svg+xml" href="../brand/clyde-mark.svg">
<script>document.documentElement.className = "js";</script>
<link rel="stylesheet" href="../site.css">
<link rel="stylesheet" href="../engraving.css">
<link rel="stylesheet" href="../docs.css">
</head>
<body>
<div class="frame wide">
<header>
  <b><img src="../brand/clyde-mark.svg" alt="" width="24" height="24">ClydeCLI</b>
  <nav><a href="../">Home</a><a href="../features.html">Features</a><a href="./" aria-current="page">Docs</a><a href="../bonnie.html">Bonnie</a><a href="../keys.html">API keys</a><a href="{repo}">Source</a><a href="../report.html">Report an issue</a></nav>
</header>
<div class="docs">
<aside>
  <form class="search" role="search" onsubmit="return false"><label for="q" class="mono dim">Search the docs</label><input id="q" type="search" autocomplete="off" placeholder="oMLX, hooks, /rewind"></form>
  <ul id="hits" class="hits" hidden></ul>
  <details class="sidebar" open><summary class="mono">Pages</summary>
{sidebar}
  </details>
</aside>
<main>
{content}
<p class="mono dim edit">{edit}</p>
</main>
</div>
<footer><a href="{repo}/blob/main/LICENSE">PolyForm Noncommercial 1.0.0</a> · <a href="../privacy.html">Privacy</a> · <a href="../report.html">Found a mistake? Report it</a></footer>
</div>
<script src="../site.js" defer></script>
<script src="../docs.js" defer></script>
<script src="../analytics.js" defer></script>
</body>
</html>
"""


def sidebar(current: str, version: str) -> str:
    def link(name: str, text: str, extra: str = "") -> str:
        here = ' aria-current="page"' if name == current else ""
        return f'<li><a href="{"./" if name == "index" else name + ".html"}"{here}>{html.escape(text)}{extra}</a></li>'

    groups = {"Start": [link("index", "Overview"), link(RELEASES[1], "Releases", f' <span class="dim">v{version}</span>')]}
    for group, _, name, title in PAGES:
        groups.setdefault(group, []).append(link(name, title))
    return "\n".join(f'<p class="mono group">{g}</p><ul>{"".join(items)}</ul>' for g, items in groups.items())


def plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def latest_version(changelog: str) -> str:
    m = re.search(r"^## \[(\d[^\]]*)\]", changelog, flags=re.M)
    return m.group(1) if m else "?"


def build(out: Path) -> list[str]:
    """Write every page and `search.json` into `out`; returns the page file names."""
    out.mkdir(parents=True, exist_ok=True)
    changelog = (ROOT / RELEASES[0]).read_text(encoding="utf-8")
    version = latest_version(changelog)
    index: list[dict[str, str]] = []
    written: list[str] = []

    def emit(name: str, title: str, content: str, source: str, summary: str) -> None:
        edit = f'<a href="{REPO}/blob/main/{source}">Edit this page on GitHub</a>' if source else ""
        text = TEMPLATE.format(title=html.escape(title), description=html.escape(summary[:200]), canonical=SITE + "docs/" + (f"{name}.html" if name != "index" else ""), repo=REPO, sidebar=sidebar(name, version), content=content, edit=edit)
        (out / f"{name}.html").write_text(text, encoding="utf-8")
        written.append(f"{name}.html")
        index.append({"title": title, "url": f"{name}.html" if name != "index" else "./", "text": plain(re.sub(r"<h1[^>]*>.*?</h1>", "", content, count=1, flags=re.S))[:30000]})

    for _, source, name, fallback in PAGES:
        title, body = split_title((ROOT / source).read_text(encoding="utf-8"), fallback)
        content = f'<h1 class="docs-title">{html.escape(title)}</h1>\n{Converter(source).convert(body)}'
        first = re.search(r"<p>(.*?)</p>", content)
        emit(name, title, content, source, plain(first.group(1)) if first else title)

    _, body = split_title(changelog, "Changelog")
    conv = Converter(RELEASES[0], release_heading)
    converted = conv.convert(body)
    jump = " · ".join(f'<a href="#{i}">{html.escape(t.split(",")[0])}</a>' for lvl, i, t in conv.headings if lvl == 2 and i.startswith("v"))
    emit(RELEASES[1], RELEASES[2],
         f'<h1 class="docs-title">Releases</h1>\n<p>Every release, newest first. The same text is in <a href="{REPO}/blob/main/CHANGELOG.md">CHANGELOG.md</a>; '
         f'each release is also on <a href="{REPO}/releases">GitHub</a>, where the tags are.</p>\n<p class="mono dim jump">Jump to: {jump}</p>\n{converted}',
         RELEASES[0], f"Release notes for every ClydeCLI version, latest {version}.")

    cards = "".join(f'<li><a href="{n}.html">{html.escape(t)}</a></li>' for g, _, n, t in PAGES if g in ("Guide", "Research"))
    latest = f"releases.html#v{slug(version.replace('.', '-'))}"
    emit("index", "Documentation",
         f'<h1 class="docs-title">Documentation</h1>\n<p>Everything the repository documents about ClydeCLI, in one place: how to install and use it, what it does, '
         f'the research its claims rest on, and what changed in each release. Latest release: <a href="{latest}">v{version}</a>.</p>\n<ul class="cards">{cards}</ul>\n'
         '<p>Something wrong or missing? <a href="../report.html">Report an issue</a>; it opens GitHub with your text filled in.</p>',
         "", "How to install and use ClydeCLI, what it does, the research behind it, and every release.")

    (out / "search.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return written


def sitemap(site: Path, pages: list[str]) -> None:
    """`sitemap.xml` for the site root: the hand-written pages next to `docs/` plus every generated docs page."""
    urls = ["", *sorted(p.name for p in site.glob("*.html") if p.name not in ("index.html", "bonny.html"))]
    urls += ["docs/"] + [f"docs/{p}" for p in sorted(pages) if p != "index.html"]
    body = "".join(f"<url><loc>{SITE}{u}</loc></url>" for u in urls)
    (site / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n', encoding="utf-8")


if __name__ == "__main__":
    target = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "site" / "docs"
    written = build(target)
    print(f"wrote {len(written)} pages to {target}")
    if "--out" not in sys.argv:
        sitemap(ROOT / "site", written)
