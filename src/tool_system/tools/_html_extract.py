"""HTML to readable text with stdlib only.

`extract_text` replaces WebFetch's regex tag-strip: an HTMLParser that drops script/style/noscript content and renders the rest as
markdown-ish text (headings, links with their targets, lists), which a model reads better than tag soup. `select` runs a small
CSS selector (tag, .class, #id, tag.class, descendant combinator) over the parsed tree and returns the same text for the matches.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
_HEADING_LEVELS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WS_RE = re.compile(r"\s+")   # all whitespace collapses in text nodes, so only the markers _render adds can break a line


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

    _IMPLIED_END = {"p": {"p"}, "li": {"li"}, "td": {"td", "th"}, "th": {"td", "th"}, "option": {"option"}}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        # a new <p>/<li>/<td>/<th>/<option> closes the open one instead of nesting (2,000 unclosed <p> must not overflow the stack)
        while len(self._stack) > 1 and self._stack[-1].tag in self._IMPLIED_END.get(tag, ()):
            self._stack.pop()
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
_BLOCK_TAGS = {"p", "blockquote", "tr", "td", "th", "pre", "dt", "dd"}


def _render(node: _Node, out: list[str], depth: int = 0) -> None:
    """Markdown-ish rendering of one node's subtree. Block tags open a line ("\n"), recurse so links and nested
    lists survive, then close it ("\n"); inline tags flow into the current line."""
    for child in node.children:
        if isinstance(child, str):
            text = _WS_RE.sub(" ", child)
            if text.strip():
                out.append(text)
            continue
        tag = child.tag
        if tag in _SKIP_TAGS:
            continue
        if tag in _HEADING_LEVELS:
            out.append("\n" + "#" * int(tag[1]) + " ")
            _render(child, out, depth)   # render children so a link inside a heading keeps its target
            out.append("\n")
        elif tag == "a":
            text = _text_of(child)
            href = child.attrs.get("href", "")
            if text:
                out.append(f"[{text}]({href})" if href else text)
        elif tag == "li":
            out.append("\n" + "  " * depth + "- ")
            _render(child, out, depth)   # a nested <ul> raises depth through the container branch
        elif tag in _INLINE_TAGS:
            _render(child, out, depth)   # render children so a link inside <strong>/<em>/<span> keeps its target
        elif tag in _BLOCK_TAGS:
            out.append("\n")
            _render(child, out, depth)
            out.append("\n")
        else:   # container (div, section, ul, body, ...): recurse, don't emit its text (that would duplicate the children's)
            _render(child, out, depth + (1 if tag in {"ul", "ol"} else 0))


def _join(out: list[str]) -> str:
    """One line per rendered block. A piece that starts with "\n" opens a new line, a bare "\n" piece closes it, so a
    heading or paragraph can't fuse with the text after it. Leading spaces of a block piece (list indent) are kept."""
    lines: list[str] = []
    close = False
    for piece in out:
        if piece == "\n":
            close = True
            continue
        opens_block = piece.startswith("\n")
        body = piece.lstrip("\n")
        indent = body[: len(body) - len(body.lstrip(" "))] if opens_block else ""
        text = indent + _WS_RE.sub(" ", body).strip()
        if not text:
            continue
        if opens_block or close or not lines:
            lines.append(text)
        else:
            lines[-1] = lines[-1] + " " + text.strip()   # keep a merged line's leading indent
        close = False
    return "\n".join(lines)


def _plain_text(raw_html: str) -> str:
    """Fallback for pages too deep to structure: script/style bodies dropped, tags stripped, entities unescaped, whitespace collapsed."""
    no_script = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", raw_html)
    no_script = re.sub(r"(?is)<(script|style)\b[^>]*>.*$", " ", no_script)   # unclosed script swallows the rest
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", no_script))).strip()


def extract_text(raw_html: str) -> str:
    """Readable text of an HTML page: scripts/styles dropped, structure kept."""
    builder = _TreeBuilder()
    builder.feed(raw_html)
    builder.close()
    out: list[str] = []
    try:
        _render(builder.root, out)
    except RecursionError:
        return _plain_text(raw_html)   # a hostile page must not break the fetch
    return _join(out)


# --- mini CSS selector: tag, .class, #id, tag.class, descendant combinator ---

_SIMPLE_RE = re.compile(r"^(?P<tag>[a-zA-Z][\w-]*)?(?:\.(?P<cls>[\w-]+))?(?:#(?P<id>[\w-]+))?$")


def _matches_simple(node: _Node, simple: str) -> bool:
    m = _SIMPLE_RE.match(simple)
    if m.group("tag") and node.tag != m.group("tag").lower():
        return False
    if m.group("cls") and m.group("cls") not in node.attrs.get("class", "").split():
        return False
    if m.group("id") and node.attrs.get("id") != m.group("id"):
        return False
    return True


def _descendants(node: _Node):
    """Iterative pre-order walk: a hostile page nests deep enough to overflow a recursive walk."""
    stack = [c for c in reversed(node.children) if isinstance(c, _Node)]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in reversed(n.children) if isinstance(c, _Node))


def select(raw_html: str, selector: str) -> str:
    """Text of every element matching `selector` (descendant combinator), rendered like extract_text."""
    parts = [p for p in selector.split() if p.strip()]
    if not parts:
        raise ValueError("empty selector")
    for part in parts:   # validate every part before parsing, so "a > b" fails even on an empty page
        m = _SIMPLE_RE.match(part)
        if not m or not (m.group("tag") or m.group("cls") or m.group("id")):
            raise ValueError(f"unsupported selector part: {part!r} (supported: tag, .class, #id, tag.class, descendant)")
    builder = _TreeBuilder()
    builder.feed(raw_html)
    builder.close()
    current: list[_Node] = [builder.root]
    for part in parts:
        current = [d for node in current for d in _descendants(node) if _matches_simple(d, part)]
    # drop duplicate nodes, then any node whose ancestor also matched (its text is already in the ancestor's)
    seen: set[int] = set()
    unique = [n for n in current if not (id(n) in seen or seen.add(id(n)))]
    matched = {id(n) for n in unique}

    def _under_match(n: _Node) -> bool:
        p = n.parent
        while p is not None:
            if id(p) in matched:
                return True
            p = p.parent
        return False

    current = [n for n in unique if not _under_match(n)]
    if not current:
        return ""
    out: list[str] = []
    try:
        for node in current:
            _render(node, out)
    except RecursionError:
        return _plain_text(raw_html)   # a hostile page must not break the fetch
    return _join(out)
