from __future__ import annotations

import json
import os
import platform
import re
import uuid
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..protocol import ToolResult
from ..registry import ToolSpec


class SendMessageTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SendMessage",
            description="Send a message to another recipient (best-effort, local only).",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "to": {"type": "string"},
                    "summary": {"type": "string"},
                    "message": {},
                },
                "required": ["to", "message"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        to = tool_input.get("to")
        message = tool_input.get("message")
        summary = tool_input.get("summary")
        if not isinstance(to, str) or not to.strip():
            raise ToolInputError("to must be a non-empty string")
        if summary is not None and not isinstance(summary, str):
            raise ToolInputError("summary must be a string when provided")
        context.outbox.append({"tool": "SendMessage", "to": to, "summary": summary, "message": message})
        return ToolResult(name="SendMessage", output={"success": True, "message": f"Message queued for {to}"})


class RemoteTriggerTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="RemoteTrigger",
            description="Trigger a remote action (not implemented).",
            input_schema={"type": "object", "additionalProperties": True},
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(name="RemoteTrigger", output={"error": "RemoteTrigger is not implemented"}, is_error=True)


class PowerShellTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="PowerShell",
            description="Run a PowerShell command (Windows only).",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            is_destructive=True,
            max_result_size_chars=200_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if platform.system().lower() != "windows":
            return ToolResult(name="PowerShell", output={"error": "PowerShell is only supported on Windows"}, is_error=True)
        raise ToolPermissionError("PowerShell execution is not enabled in this build")


class NotebookEditTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="NotebookEdit",
            description="Replace, insert, or delete a cell in a Jupyter notebook (.ipynb).",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "notebook_path": {"type": "string"},
                    "cell_id": {"type": "string"},
                    "new_source": {"type": "string"},
                    "cell_type": {"type": "string", "enum": ["code", "markdown"]},
                    "edit_mode": {"type": "string", "enum": ["replace", "insert", "delete"]},
                },
                "required": ["notebook_path", "new_source"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        notebook_path = tool_input.get("notebook_path")
        new_source = tool_input.get("new_source")
        cell_id = tool_input.get("cell_id")
        cell_type = tool_input.get("cell_type")
        edit_mode = tool_input.get("edit_mode") or "replace"

        if not isinstance(notebook_path, str) or not os.path.isabs(notebook_path):
            raise ToolInputError("notebook_path must be an absolute path")
        if not isinstance(new_source, str):
            raise ToolInputError("new_source must be a string")
        if cell_id is not None and not isinstance(cell_id, str):
            raise ToolInputError("cell_id must be a string when provided")
        if edit_mode not in ("replace", "insert", "delete"):
            raise ToolInputError("edit_mode must be replace, insert, or delete")
        if cell_type is not None and cell_type not in ("code", "markdown"):
            raise ToolInputError("cell_type must be code or markdown")
        if edit_mode == "insert" and cell_type is None:
            raise ToolInputError("cell_type is required when edit_mode=insert")
        if edit_mode != "insert" and cell_id is None:
            raise ToolInputError(f"cell_id is required when edit_mode={edit_mode}")

        path = context.ensure_allowed_path(notebook_path)
        if path.suffix.lower() != ".ipynb":
            raise ToolInputError("notebook_path must be a .ipynb file")
        if not path.exists():
            raise ToolInputError(f"file does not exist: {path}")
        if not context.was_file_read_and_unchanged(path):
            raise ToolInputError("refusing to edit: file must be read first and unchanged since last read")

        original_file = path.read_text(encoding="utf-8")
        try:
            notebook = json.loads(original_file)
        except json.JSONDecodeError as e:
            raise ToolInputError(f"notebook is not valid JSON: {e}") from e
        cells = notebook.get("cells") if isinstance(notebook, dict) else None
        if not isinstance(cells, list):
            raise ToolInputError("notebook has no cells list")

        # Without a cell_id an insert lands at the start (index -1 + 1).
        index = -1 if cell_id is None else _find_cell_index(cells, cell_id)

        if edit_mode == "delete":
            del cells[index]
        elif edit_mode == "insert":
            cell: dict[str, Any] = {"cell_type": cell_type, "metadata": {}, "source": new_source}
            if cell_type == "code":
                cell.update(execution_count=None, outputs=[])
            if (notebook.get("nbformat", 0), notebook.get("nbformat_minor", 0)) >= (4, 5):
                cell["id"] = uuid.uuid4().hex[:8]
            cells.insert(index + 1, cell)
            cell_id = cell.get("id", f"cell-{index + 1}")
        else:
            cell = cells[index]
            cell["source"] = new_source
            if cell_type is not None:
                cell["cell_type"] = cell_type
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
            else:
                cell.pop("outputs", None)
                cell.pop("execution_count", None)
            cell_type = cell.get("cell_type")

        updated_file = json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"
        path.write_text(updated_file, encoding="utf-8")
        context.mark_file_read(path)
        return ToolResult(
            name="NotebookEdit",
            output={
                "notebook_path": str(path),
                "cell_id": cell_id,
                "cell_type": cell_type,
                "edit_mode": edit_mode,
                "new_source": new_source,
                "original_file": original_file,
                "updated_file": updated_file,
            },
        )


def _find_cell_index(cells: list[Any], cell_id: str) -> int:
    """Resolve a cell by its ``id``, falling back to the ``cell-N`` index form."""
    for i, cell in enumerate(cells):
        if isinstance(cell, dict) and cell.get("id") == cell_id:
            return i
    match = re.fullmatch(r"cell-(\d+)", cell_id)
    if match and int(match.group(1)) < len(cells):
        return int(match.group(1))
    raise ToolInputError(f"cell not found: {cell_id}")


class REPLTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="REPL",
            description="Interact with the REPL UI (not implemented).",
            input_schema={"type": "object", "additionalProperties": True},
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(name="REPL", output={"error": "REPL tool is not implemented"}, is_error=True)
