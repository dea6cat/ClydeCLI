from __future__ import annotations

import difflib
from typing import Any

from ...agent import trace
from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..diff_utils import unified_diff_hunks
from ..registry import ToolSpec


def _leading_ws(s: str) -> str:
    return s[: len(s) - len(s.lstrip())]


def _shift_indent(text: str, add: str, cut: str) -> str:
    """Re-indent each non-blank line: drop a leading `cut`, then prepend `add`."""
    out = []
    for ln in text.splitlines(keepends=True):
        body = ln.rstrip("\r\n")
        nl = ln[len(body):]
        if body.strip():
            if cut and body.startswith(cut):
                body = body[len(cut):]
            body = add + body
        out.append(body + nl)
    return "".join(out)


def _make_reindenter(file_line: str, old_line: str):
    """Shift new_string from old_string's indentation to the file's, when the two prefixes nest."""
    fw = _leading_ws(file_line.rstrip("\r\n"))
    ow = _leading_ws(old_line)
    if fw != ow and fw.startswith(ow):
        return lambda nt: _shift_indent(nt, fw[len(ow):], "")
    if fw != ow and ow.startswith(fw):
        return lambda nt: _shift_indent(nt, "", ow[len(fw):])
    return lambda nt: nt


def _resolve_edit(content: str, old: str):
    """Find the one region old_string refers to, tolerating the whitespace drift models produce.

    Tiers, in order: exact substring; trailing-whitespace-insensitive whole lines; indentation-
    insensitive whole lines (new_string is re-indented to the file). Returns (start, end, render, how)
    for a unique match, where `how` is None for an exact match and otherwise names what was ignored,
    ("ambiguous", n) when a tier matches more than once, or None.
    """
    count = content.count(old)
    if count == 1:
        start = content.index(old)
        return (start, start + len(old), lambda nt: nt, None)
    if count > 1:
        return ("ambiguous", count)

    content_lines = content.splitlines(keepends=True)
    old_lines = old.splitlines()
    # A stray trailing blank line in old_string has no counterpart in the file.
    while len(old_lines) > 1 and not old_lines[-1].strip():
        old_lines.pop()
    if not old_lines or not "".join(old_lines).strip():
        return None
    offsets, acc = [], 0
    for ln in content_lines:
        offsets.append(acc)
        acc += len(ln)
    owns_trailing_nl = old.endswith(("\n", "\r"))
    n = len(old_lines)
    for normalize, reindent, how in ((str.rstrip, False, "trailing whitespace"), (str.strip, True, "indentation")):
        norm_content = [normalize(ln) for ln in content_lines]
        norm_old = [normalize(ln) for ln in old_lines]
        hits = [i for i in range(len(norm_content) - n + 1) if norm_content[i:i + n] == norm_old]
        if len(hits) > 1:
            return ("ambiguous", len(hits))
        if hits:
            i = hits[0]
            matched = "".join(content_lines[i:i + n])
            start, end = offsets[i], offsets[i] + len(matched)
            if not owns_trailing_nl:  # keep the line break old_string didn't include
                end -= len(matched) - len(matched.rstrip("\r\n"))
            render = _make_reindenter(content_lines[i], old_lines[0]) if reindent else (lambda nt: nt)
            return (start, end, render, how)
    return None


def _nearest_hint(content: str, old: str) -> str:
    """Point at the closest real lines so the model re-copies them instead of retrying the same miss."""
    old_lines = [ln for ln in old.splitlines() if ln.strip()]
    file_lines = content.splitlines()
    if not old_lines or not file_lines:
        return ""
    stripped = [ln.strip() for ln in file_lines]
    match = difflib.get_close_matches(old_lines[0].strip(), stripped, n=1, cutoff=0.6)
    if not match:
        return ""
    i = stripped.index(match[0])
    lo, hi = max(0, i - 3), min(len(file_lines), i + 4)
    width = len(str(hi))
    snippet = "\n".join(f"{k + 1:>{width}} | {file_lines[k]}" for k in range(lo, hi))
    return (
        f". The closest match is around line {i + 1}:\n{snippet}\n"
        "Read the file again and copy old_string exactly from there, including indentation."
    )


MAX_EDITS = 50   # in one call


def _span(content: str, old: str, new: str) -> tuple[int, int, str, str | None]:
    """Where the unique region old_string refers to is, and what replaces it: (start, end, text, what the match ignored or None when exact).
    Raises ToolInputError when none or several match."""
    resolved = _resolve_edit(content, old)
    if resolved is None:
        raise ToolInputError("old_string not found in file" + _nearest_hint(content, old))
    if resolved[0] == "ambiguous":
        raise ToolInputError(
            f"old_string matches {resolved[1]} times; provide a larger old_string or set replace_all=true"
        )
    start, end, render, how = resolved
    rendered = render(new)
    # old_string replaced whole lines but new_string dropped the final newline: don't merge the next line.
    if old.endswith("\n") and rendered and not rendered.endswith("\n") and end < len(content) and content[end] != "\n":
        rendered += "\n"
    return start, end, rendered, how


def _apply_single_edit(content: str, old: str, new: str) -> tuple[str, str | None]:
    """Replace the unique region old_string refers to; (new content, what the match ignored or None when exact)."""
    start, end, rendered, how = _span(content, old, new)
    return content[:start] + rendered + content[end:], how


def _apply_edits(content: str, edits: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Every edit matched against the ORIGINAL content (not one after another), all or nothing: (the new content, what loose matches ignored).
    Raises ToolInputError naming the edit that cannot be made, or two that touch the same text."""
    spans: list[tuple[int, int, str, int]] = []
    ignored: list[str] = []
    for i, e in enumerate(edits):
        old, new = e["old_string"], e["new_string"]
        try:
            if e.get("replace_all"):
                if old not in content:
                    raise ToolInputError("old_string not found in file" + _nearest_hint(content, old))
                found, at = [], content.find(old)
                while old and at != -1:
                    found.append((at, at + len(old), new, i))
                    at = content.find(old, at + len(old))
                spans += found
            else:
                start, end, text, how = _span(content, old, new)
                spans.append((start, end, text, i))
                if how and how not in ignored:
                    ignored.append(how)
        except ToolInputError as err:
            raise ToolInputError(f"edits[{i}]: {err}") from err
    spans.sort()
    for before, after in zip(spans, spans[1:]):
        if after[0] < before[1]:
            raise ToolInputError(f"edits[{before[3]}] and edits[{after[3]}] touch the same text: merge them into one edit")
    for start, end, text, _ in reversed(spans):
        content = content[:start] + text + content[end:]
    return content, ignored


def _edits_of(tool_input: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The `edits` list of a call that has one, checked; None for the single old_string/new_string form."""
    edits = tool_input.get("edits")
    if edits is None:
        return None
    if "old_string" in tool_input or "new_string" in tool_input:
        raise ToolInputError("give either old_string and new_string or edits, not both")
    if not isinstance(edits, list) or not edits:
        raise ToolInputError("edits must be a list of one or more {old_string, new_string}")
    if len(edits) > MAX_EDITS:
        raise ToolInputError(f"at most {MAX_EDITS} edits in one call")
    for i, e in enumerate(edits):
        if not isinstance(e, dict) or not isinstance(e.get("old_string"), str) or not isinstance(e.get("new_string"), str) or not e["old_string"]:
            raise ToolInputError(f"edits[{i}] needs a non-empty old_string and a new_string, both text")
    return edits


class FileEditTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Edit",
            description=(
                "Performs string replacements in files. old_string should match the file exactly; "
                "a unique match that differs only in trailing whitespace or indentation is also accepted. "
                "To change several places in one file, give edits (a list of old_string/new_string) in one call instead of several calls: "
                "each is matched against the file as it is now, none may touch the same text, and all are made or none."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                    "edits": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                          "properties": {"old_string": {"type": "string"}, "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
                                                          "required": ["old_string", "new_string"]}},
                },
                "required": ["file_path"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def check_permissions(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionResult:
        """Check if edit permission is allowed for this file."""
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str):
            return PermissionResult.allow()  # Input validation happens in run()

        try:
            path = context.ensure_allowed_path(file_path)
        except ToolPermissionError:
            return PermissionResult.allow()  # Path validation happens in run()

        if path.suffix.lower() in {".md", ".markdown"} and not context.permission_context.allow_docs:
            return PermissionResult.ask(
                message="Editing documentation files is blocked unless allow_docs is enabled",
                suggestion="Enable allow_docs to edit .md files",
            )
        return PermissionResult.allow()

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = tool_input["file_path"]
        edits = _edits_of(tool_input)
        old, new = tool_input.get("old_string"), tool_input.get("new_string")
        replace_all = bool(tool_input.get("replace_all", False))

        if not isinstance(file_path, str):
            raise ToolInputError("file_path must be a string")
        if edits is None and (not isinstance(old, str) or not isinstance(new, str)):
            raise ToolInputError("give old_string and new_string (both text), or edits")

        path = context.ensure_allowed_path(file_path)

        if not path.exists():
            raise ToolInputError(f"file does not exist: {path}")
        if not context.was_file_read_and_unchanged(path):
            raise ToolInputError("refusing to edit: file must be read first and unchanged since last read")

        original_file = path.read_text(encoding="utf-8", errors="replace")
        how = None
        if edits is not None:
            updated, ignored = _apply_edits(original_file, edits)
            how = " and ".join(ignored) or None
        elif replace_all:
            if old not in original_file:
                raise ToolInputError("old_string not found in file" + _nearest_hint(original_file, old))
            updated = original_file.replace(old, new)
        else:
            updated, how = _apply_single_edit(original_file, old, new)

        path.write_text(updated, encoding="utf-8")
        context.mark_file_read(path)
        before_lines = original_file.splitlines(keepends=True)
        after_lines = updated.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=str(path),
                tofile=str(path),
                n=3,
                lineterm="",
            )
        )
        hunks = unified_diff_hunks(diff_lines)
        output = {
            "filePath": str(path),
            "oldString": old if edits is None else f"({len(edits)} edits)",
            "newString": new if edits is None else f"({len(edits)} edits)",
            "originalFile": original_file,
            "structuredPatch": hunks,
            "userModified": False,
            "replaceAll": bool(replace_all) or bool(edits and any(e.get("replace_all") for e in edits)),
            **({"edits": len(edits)} if edits is not None else {}),
        }
        if how:
            # The match was not exact: say so to the model (it may have misread the file) and to the user and the trace.
            output["matchedLoosely"] = how
            output["note"] = (f"old_string did not match exactly; it matched after ignoring {how}, and the edit was made at those lines. "
                              "Check structuredPatch, and Read the file again before the next edit.")
            trace.record("edit_loose_match", file=str(path), ignored=how)
        return ToolResult(name="Edit", output=output)
