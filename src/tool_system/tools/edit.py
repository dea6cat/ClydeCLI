from __future__ import annotations

import difflib
from typing import Any

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
    insensitive whole lines (new_string is re-indented to the file). Returns (start, end, render)
    for a unique match, ("ambiguous", n) when a tier matches more than once, or None.
    """
    count = content.count(old)
    if count == 1:
        start = content.index(old)
        return (start, start + len(old), lambda nt: nt)
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
    for normalize, reindent in ((str.rstrip, False), (str.strip, True)):
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
            return (start, end, render)
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


def _apply_single_edit(content: str, old: str, new: str) -> str:
    """Replace the unique region old_string refers to; raise ToolInputError when none or several match."""
    resolved = _resolve_edit(content, old)
    if resolved is None:
        raise ToolInputError("old_string not found in file" + _nearest_hint(content, old))
    if resolved[0] == "ambiguous":
        raise ToolInputError(
            f"old_string matches {resolved[1]} times; provide a larger old_string or set replace_all=true"
        )
    start, end, render = resolved
    rendered = render(new)
    # old_string replaced whole lines but new_string dropped the final newline: don't merge the next line.
    if old.endswith("\n") and rendered and not rendered.endswith("\n") and end < len(content) and content[end] != "\n":
        rendered += "\n"
    return content[:start] + rendered + content[end:]


class FileEditTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Edit",
            description=(
                "Performs string replacements in files. old_string should match the file exactly; "
                "a unique match that differs only in trailing whitespace or indentation is also accepted."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["file_path", "old_string", "new_string"],
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
        old = tool_input["old_string"]
        new = tool_input["new_string"]
        replace_all = bool(tool_input.get("replace_all", False))

        if not isinstance(file_path, str):
            raise ToolInputError("file_path must be a string")
        if not isinstance(old, str) or not isinstance(new, str):
            raise ToolInputError("old_string/new_string must be strings")

        path = context.ensure_allowed_path(file_path)

        if not path.exists():
            raise ToolInputError(f"file does not exist: {path}")
        if not context.was_file_read_and_unchanged(path):
            raise ToolInputError("refusing to edit: file must be read first and unchanged since last read")

        original_file = path.read_text(encoding="utf-8", errors="replace")
        if replace_all:
            if old not in original_file:
                raise ToolInputError("old_string not found in file" + _nearest_hint(original_file, old))
            updated = original_file.replace(old, new)
        else:
            updated = _apply_single_edit(original_file, old, new)

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
        return ToolResult(
            name="Edit",
            output={
                "filePath": str(path),
                "oldString": old,
                "newString": new,
                "originalFile": original_file,
                "structuredPatch": hunks,
                "userModified": False,
                "replaceAll": bool(replace_all),
            },
        )
