"""HTML to readable text with stdlib only.

`extract_text` replaces WebFetch's regex tag-strip: an HTMLParser that drops script/style/noscript content and renders the rest as
markdown-ish text (headings, links with their targets, lists), which a model reads better than tag soup. `select` runs a small
CSS selector (tag, .class, #id, tag.class, descendant combinator) over the parsed tree and returns the same text for the matches.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
_HEADING_LEVELS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WS_RE = re.compile(r"[^\S\n]+")   # horizontal whitespace only: newlines are block separators in the output


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: _Node | None):
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node | str] = []
        self.parent = parent


class _TreeBuilder(HTMLParser):
    """Builds a light DOM tree. Void elements never get children; unclosed tags close at their parent's end (HTMLParser handles that)."""

    _VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: (v or "") for k, v in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in self._VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(_Node(tag, {k: (v or "") for k, v in attrs}, self._stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(data)


def _text_of(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _SKIP_TAGS:
            parts.append(_text_of(child))
    return _WS_RE.sub(" ", "".join(parts)).strip()


_INLINE_TAGS = {"b", "i", "em", "strong", "span", "code", "small", "sub", "sup", "u", "s", "abbr", "cite", "q", "time"}


def _render(node: _Node, out: list[str], depth: int = 0) -> None:
    """Markdown-ish rendering of one node's subtree. Block tags start a new line; inline tags flow into it."""
    for child in node.children:
        if isinstance(child, str):
            text = _WS_RE.sub(" ", child)
            if text.strip():
                out.append(text)
            continue
        tag = child.tag
        if tag in _SKIP_TAGS:
            continue
        text = _text_of(child)
        if not text:
            continue
        if tag in _HEADING_LEVELS:
            out.append("\n" + "#" * int(tag[1]) + " " + text)
        elif tag == "a":
            href = child.attrs.get("href", "")
            out.append(f"[{text}]({href})" if href else text)
        elif tag == "li":
            out.append("\n" + "  " * depth + "- " + text)
        elif tag in _INLINE_TAGS:
            out.append(text)
        elif tag in {"p", "blockquote", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "dt", "dd"} or tag in _HEADING_LEVELS:
            out.append("\n" + text)
        else:   # container (div, section, ul, body, ...): recurse, don't emit its text (that would duplicate the children's)
            _render(child, out, depth + (1 if tag in {"ul", "ol"} else 0))


def _join(out: list[str]) -> str:
    """One line per rendered block: a piece that starts with "\n" opens a new line and a piece that ends with one
    closes it, so nested children can't fuse into the parent's line. Whitespace runs collapse to one space."""
    lines: list[str] = []
    for piece in out:
        opens_block = piece.startswith("\n")
        text = _WS_RE.sub(" ", piece).strip()
        if not text:
            continue
        if opens_block or not lines:
            lines.append(text)
        else:
            lines[-1] = (lines[-1] + " " + text).strip()
    return "\n".join(lines)


def extract_text(raw_html: str) -> str:
    """Readable text of an HTML page: scripts/styles dropped, structure kept."""
    builder = _TreeBuilder()
    builder.feed(raw_html)
    builder.close()
    out: list[str] = []
    _render(builder.root, out)
    return _join(out)


# --- mini CSS selector: tag, .class, #id, tag.class, descendant combinator ---

_SIMPLE_RE = re.compile(r"^(?P<tag>[a-zA-Z][\w-]*)?(?:\.(?P<cls>[\w-]+))?(?:#(?P<id>[\w-]+))?$")


def _matches_simple(node: _Node, simple: str) -> bool:
    m = _SIMPLE_RE.match(simple.strip())
    if not m or not (m.group("tag") or m.group("cls") or m.group("id")):
        raise ValueError(f"unsupported selector part: {simple!r} (supported: tag, .class, #id, tag.class, descendant)")
    if m.group("tag") and node.tag != m.group("tag").lower():
        return False
    if m.group("cls") and m.group("cls") not in node.attrs.get("class", "").split():
        return False
    if m.group("id") and node.attrs.get("id") != m.group("id"):
        return False
    return True


def _descendants(node: _Node):
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _descendants(child)


def select(raw_html: str, selector: str) -> str:
    """Text of every element matching `selector` (descendant combinator), rendered like extract_text."""
    parts = [p for p in selector.split() if p.strip()]
    if not parts:
        raise ValueError("empty selector")
    builder = _TreeBuilder()
    builder.feed(raw_html)
    builder.close()
    current: list[_Node] = [builder.root]
    for part in parts:
        current = [d for node in current for d in _descendants(node) if _matches_simple(d, part)]
    if not current:
        return ""
    out: list[str] = []
    for node in current:
        _render(node, out)
    return _join(out)
