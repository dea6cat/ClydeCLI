from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# Keys whose `a, b, c` shorthand means a list; everywhere else a comma is just text.
LIST_KEYS = {"allowed-tools", "allowed_tools", "disallowed-tools", "tools", "arguments", "paths"}


@dataclass(frozen=True)
class FrontmatterParseResult:
    frontmatter: Dict[str, Any]
    body: str


def parse_frontmatter(markdown: str) -> FrontmatterParseResult:
    """
    Minimal frontmatter parser supporting a safe subset of YAML-like syntax:
    - Top-level key: value pairs
    - Booleans: true/false (case-insensitive)
    - Numbers: integers
    - Lists via inline bracket form:
        key: [item1, item2]
    - Lists via hyphen form:
        key:
          - item1
          - item2
    - Lists via comma-separated shorthand, only for list keys such as allowed-tools:
        allowed-tools: Read, Grep
    - Block scalars: `key: >` folds the indented lines below into one line, `key: |` keeps them as lines
    Quoted values are plain strings; prose such as a description keeps its commas.
    Any unsupported structure falls back to a string.
    """
    lines = markdown.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return FrontmatterParseResult(frontmatter={}, body=markdown)
    # Find closing ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return FrontmatterParseResult(frontmatter={}, body=markdown)

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])
    fm: Dict[str, Any] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip():
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, value = _split_key_value(line)
        if _BLOCK_SCALAR.fullmatch(value):
            block: List[str] = []
            i += 1
            while i < len(fm_lines) and (not fm_lines[i].strip() or fm_lines[i][0] in " \t"):
                block.append(fm_lines[i])
                i += 1
            fm[key] = _block_text(block, folded=value[0] == ">")
            continue
        # List (hyphen form)
        if value == "" and i + 1 < len(fm_lines) and fm_lines[i + 1].lstrip().startswith("- "):
            items: List[str] = []
            i += 1
            while i < len(fm_lines):
                item_line = fm_lines[i]
                if item_line.lstrip().startswith("- "):
                    items.append(item_line.lstrip()[2:].strip())
                    i += 1
                else:
                    break
            fm[key] = [_coerce_scalar(x) for x in items]
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            fm[key] = value[1:-1]
            i += 1
            continue
        inline_list = _parse_inline_list(value)
        if inline_list is not None:
            fm[key] = inline_list
            i += 1
            continue
        # Comma-separated list
        if "," in value and key in LIST_KEYS:
            fm[key] = [_coerce_scalar(v.strip()) for v in value.split(",") if v.strip()]
        else:
            fm[key] = _coerce_scalar(value.strip())
        i += 1
    return FrontmatterParseResult(frontmatter=fm, body=body)


_BLOCK_SCALAR = re.compile(r"[>|][+-]?")


def _block_text(lines: List[str], *, folded: bool) -> str:
    """The text of a YAML block scalar: `>` joins its lines with spaces (a blank line starts a new
    paragraph), `|` keeps them as written. Surrounding blank lines are dropped."""
    text = textwrap.dedent("\n".join(lines)).strip("\n")
    if not folded:
        return text
    return "\n".join(" ".join(paragraph.split()) for paragraph in re.split(r"\n\s*\n", text)).strip()


def _split_key_value(line: str) -> Tuple[str, str]:
    idx = line.find(":")
    key = line[:idx].strip()
    value = line[idx + 1 :].strip()
    return key, value


def _coerce_scalar(value: str) -> Any:
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    if value.isdigit():
        try:
            return int(value)
        except Exception:
            pass
    return value


def _parse_inline_list(value: str) -> List[Any] | None:
    stripped = value.strip()
    if len(stripped) < 2 or not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    inner = stripped[1:-1].strip()
    if not inner:
        return []
    return [_coerce_scalar(part.strip()) for part in inner.split(",") if part.strip()]
