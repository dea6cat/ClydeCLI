"""HTML to readable text with stdlib only.

`extract_text` replaces WebFetch's regex tag-strip: an HTMLParser that drops script/style/noscript content and renders the rest as
markdown-ish text (headings, links with their targets, lists, code blocks), which a model reads better than tag soup. `select`
runs a small CSS selector (tag, .class, #id, tag.class, descendant combinator) over the parsed tree and returns the same text
for the matches.

Every walk over the tree uses an explicit stack, never recursion: a fetched page can nest as deep as it likes, and a page
must neither overflow the stack nor make a walk quadratic.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
_HEADING_LEVELS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_INLINE_TAGS = {"b", "i", "em", "strong", "span", "code", "small", "sub", "sup", "u", "s", "abbr", "cite", "q", "time"}
_BLOCK_TAGS = {"p", "blockquote", "tr", "td", "th", "dt", "dd"}
_VERBATIM_TAGS = {"pre", "textarea"}   # whitespace is content here: a code block keeps its lines and indentation
# Containers a browser lays out as blocks: their content starts and ends a line. Any other tag flows inline.
_BLOCK_CONTAINERS = {"div", "section", "article", "header", "footer", "nav", "main", "aside", "ul", "ol", "dl", "table",
                     "thead", "tbody", "tfoot", "form", "fieldset", "figure", "figcaption", "address", "details", "summary"}
_WS_RE = re.compile(r"\s+")


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

    # these tags auto-close each other: a new one pops any of them open at the top, so "<p>a<li>b" repeated can't nest unboundedly
    _AUTO_CLOSE = {"p", "li", "td", "th", "option"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        # a new <p>/<li>/<td>/<th>/<option> closes the open one instead of nesting inside it
        if tag in self._AUTO_CLOSE:
            while len(self._stack) > 1 and self._stack[-1].tag in self._AUTO_CLOSE:
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


def _parse(raw_html: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(raw_html)
    builder.close()
    return builder.root


def _text_of(node: _Node) -> str:
    """All the text under `node` (script and style left out), as it is in the source."""
    parts: list[str] = []
    stack: list[_Node | str] = list(reversed(node.children))
    while stack:
        child = stack.pop()
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _SKIP_TAGS:
            stack.extend(reversed(child.children))
    return "".join(parts)


# _render emits text (inline, joined exactly as the source spaced it) and these markers, which _join turns into lines.
_OPEN = "open"         # ("open", prefix): end the current line and start one beginning with `prefix` ("## ", "  - ", "")
_CLOSE = "close"       # ("close",): end the current line, so following text can't fuse onto a heading or paragraph
_VERBATIM = "verbatim" # ("verbatim", text): a <pre> block, its lines kept as written


def _render(root: _Node, out: list) -> None:
    """Markdown-ish rendering of `root`'s subtree into text pieces and line markers, walking with an explicit stack."""
    stack: list = [("node", child, 0) for child in reversed(root.children)]
    while stack:
        item = stack.pop()
        if item[0] == "emit":
            out.append(item[1])
            continue
        _, child, depth = item
        if isinstance(child, str):
            out.append(_WS_RE.sub(" ", child))   # one space for any run: newlines in the source are not line breaks
            continue
        tag = child.tag
        kids = [("node", c, depth) for c in reversed(child.children)]
        if tag in _SKIP_TAGS:
            continue
        if tag in _VERBATIM_TAGS:
            out.append((_VERBATIM, _text_of(child)))
        elif tag == "br":
            out.append((_OPEN, ""))
        elif tag == "hr":
            out.append((_CLOSE,))
        elif tag in _HEADING_LEVELS:
            out.append((_OPEN, "#" * int(tag[1]) + " "))
            stack.append(("emit", (_CLOSE,)))
            stack.extend(kids)   # children render, so a link inside a heading keeps its target
        elif tag == "a":
            text = _WS_RE.sub(" ", _text_of(child)).strip()
            href = child.attrs.get("href", "")
            if text:
                out.append(f"[{text}]({href})" if href else text)
        elif tag == "li":
            out.append((_OPEN, "  " * max(depth - 1, 0) + "- "))   # depth counts the enclosing lists: a top-level item has none
            stack.extend(kids)
        elif tag in _INLINE_TAGS:
            stack.extend(kids)   # flows into the current line; a link inside keeps its target
        elif tag in _BLOCK_TAGS:
            out.append((_OPEN, ""))
            stack.append(("emit", (_CLOSE,)))
            stack.extend(kids)
        else:   # container (div, section, ul, body, ...): its children carry on, one list level deeper under ul/ol
            if tag in _BLOCK_CONTAINERS:   # <div>outer<div>inner</div></div> is two lines, not "outerinner"
                out.append((_OPEN, ""))
                stack.append(("emit", (_CLOSE,)))
            stack.extend(("node", c, depth + (1 if tag in {"ul", "ol"} else 0)) for c in reversed(child.children))


def _join(out: list) -> str:
    """Lines from _render's pieces. Inline text is concatenated as the source spaced it (so `$<span>5</span>.99` stays
    `$5.99`), whitespace runs collapse to one space, and a line holding only its prefix (an empty heading or item) is
    dropped. Verbatim blocks keep their own lines."""
    lines: list[str] = []
    prefix, text = "", ""

    def flush() -> None:
        body = _WS_RE.sub(" ", text).strip()
        if body:
            lines.append(prefix + body)

    for piece in out:
        if isinstance(piece, str):
            text += piece
            continue
        pending = bool(text.strip())
        flush()
        if piece[0] == _OPEN:   # a bare line break before any text keeps the prefix waiting: <li><p>x</p></li> is "- x"
            prefix = piece[1] if (piece[1] or pending) else prefix
        else:
            prefix = ""
        text = ""
        if piece[0] == _VERBATIM:
            block = piece[1].strip("\n")
            if block.strip():
                lines.extend(line.rstrip() for line in block.split("\n"))
    flush()
    return "\n".join(lines)


def extract_text(raw_html: str) -> str:
    """Readable text of an HTML page: scripts/styles dropped, structure kept."""
    out: list = []
    _render(_parse(raw_html), out)
    return _join(out)


# --- mini CSS selector: tag, .class, #id, tag.class, descendant combinator ---

_SIMPLE_RE = re.compile(r"^(?P<tag>[a-zA-Z][\w-]*)?(?:\.(?P<cls>[\w-]+))?(?:#(?P<id>[\w-]+))?$")


def validate_selector(selector: str) -> list[str]:
    """The selector's parts; ValueError for an empty one or any part this mini selector doesn't support. WebFetch calls it
    before fetching, so a bad selector costs no request."""
    parts = selector.split()
    if not parts:
        raise ValueError("empty selector")
    for part in parts:
        m = _SIMPLE_RE.match(part)
        if not m or not (m.group("tag") or m.group("cls") or m.group("id")):
            raise ValueError(f"unsupported selector part: {part!r} (supported: tag, .class, #id, tag.class, descendant)")
    return parts


def _matches_simple(node: _Node, simple: str) -> bool:
    m = _SIMPLE_RE.match(simple)
    if m.group("tag") and node.tag != m.group("tag").lower():
        return False
    if m.group("cls") and m.group("cls") not in node.attrs.get("class", "").split():
        return False
    if m.group("id") and node.attrs.get("id") != m.group("id"):
        return False
    return True


def select(raw_html: str, selector: str) -> str:
    """Text of every element matching `selector` (descendant combinator), rendered like extract_text. A match inside another
    match is not repeated: its text is already in the outer one's."""
    parts = validate_selector(selector)
    last = len(parts) - 1
    matches: list[_Node] = []
    # One walk. `done` is how many of the parts before the last the ancestors have matched, greedily from the left, which
    # is enough for a chain of descendant combinators; `inside` is whether an ancestor is already a match.
    stack: list[tuple[_Node, int, bool]] = [(c, 0, False) for c in reversed(_parse(raw_html).children) if isinstance(c, _Node)]
    while stack:
        node, done, inside = stack.pop()
        is_match = not inside and done == last and _matches_simple(node, parts[last])
        if is_match:
            matches.append(node)
        if done < last and _matches_simple(node, parts[done]):
            done += 1
        stack.extend((c, done, inside or is_match) for c in reversed(node.children) if isinstance(c, _Node))
    out: list = []
    for node in matches:
        out.append((_CLOSE,))   # each match starts on its own line
        _render(node, out)
    return _join(out)
