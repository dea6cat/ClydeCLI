from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Callable

from .claude_md import load_claude_md_context
from .git_context import collect_git_context
from .project_summary import build_project_summary
from .workspace_snapshot import build_workspace_snapshot


def build_context_prompt(
    workspace_root: str | Path,
    *,
    cwd: str | Path | None = None,
    compact: bool = False,
    filter_user_file: Callable[[str], str] | None = None,
) -> str:
    """The workspace, git, project and instruction sections. `compact` leaves out the README excerpt, for a small local
    model whose every prompt token costs prefill time and which can read the README itself."""
    root = Path(workspace_root).expanduser().resolve()
    current = Path(cwd).expanduser().resolve() if cwd is not None else root

    workspace = build_workspace_snapshot(root, cwd=current)
    git = collect_git_context(root)
    claude_md = load_claude_md_context(root, cwd=current, filter_user_file=filter_user_file)
    summary = build_project_summary(root)
    if compact:
        summary = replace(summary, readme_path=None, readme_excerpt="")

    sections = [
        ("Runtime Context", _render_workspace_section(workspace)),
        ("Git Context", _render_git_section(git, root)),
        ("Project Summary", _render_project_summary_section(summary, root)),
        ("Code Map", _render_code_map_section(root)),
        ("Project Instructions", _render_claude_md_section(claude_md, root)),
    ]
    kept = [(name, "\n".join(lines)) for name, lines in sections if "\n".join(lines).strip()]
    previous = _BUILDS.get(str(root), ((), ()))[1]
    _BUILDS[str(root)] = (previous, tuple((name, hashlib.sha256(text.encode()).hexdigest(), text) for name, text in kept))
    return "\n\n".join(text for _, text in kept)


# The sections of the last two prompts built per workspace, (name, sha256, text) each: what /context compares.
_BUILDS: dict[str, tuple[tuple, tuple]] = {}


def section_report(workspace_root: str | Path) -> list[dict]:
    """Each section of the last context prompt built for this workspace: its tokens, whether it was cut (and where the
    rest is), and whether it is byte-identical to the build before. A provider caches the prompt up to the first change,
    so a section is cache-aligned when it and every section before it are unchanged; [] before the first build."""
    from .token_estimation import count_tokens
    previous, current = _BUILDS.get(str(Path(workspace_root).expanduser().resolve()), ((), ()))
    before = {name: sha for name, sha, _ in previous}
    rows, aligned = [], bool(previous)
    for name, sha, text in current:
        stable = before.get(name) == sha if previous else None
        aligned = aligned and bool(stable)
        rows.append({"name": name, "tokens": count_tokens(text), "stable": stable, "aligned": aligned,
                     "refs": re.findall(r'reference="(ctx:[0-9a-f]{16})"', text)})
    return rows


def _render_code_map_section(root: Path, hubs: int = 8) -> list[str]:
    """Point the model at the Map tool once the repo has a code map."""
    out = root / ".clyde" / "code-map"
    if not (out / "map.json").is_file():
        return []
    lines = [
        "## Code Map",
        "This repository has a code map (.clyde/code-map/map.json: symbols, calls, imports).",
        "Use the Map tool first for structural questions - `query` for what relates to a topic,",
        "`explain` for a symbol, `path` for how two symbols connect, `affected` before changing a symbol -",
        "then read the cited files. Fall back to Grep/Glob for exact text.",
    ]
    try:
        report = (out / "GRAPH_REPORT.md").read_text(encoding="utf-8")
    except OSError:
        return lines
    section = report.split("## God Nodes", 1)[-1].split("\n## ", 1)[0] if "## God Nodes" in report else ""
    top = [line.strip() for line in section.splitlines() if line.strip()[:1].isdigit()][:hubs]
    if top:
        lines += ["", "Most connected symbols (architectural hubs):", *(f"- {line.split('. ', 1)[-1]}" for line in top)]
    return lines


def _render_workspace_section(workspace) -> list[str]:
    lines = [
        "## Runtime Context",
        f"- Today's date: {date.today().isoformat()}",
        f"- Workspace root: {workspace.workspace_root}",
        f"- Current directory: {workspace.current_directory}",
        f"- Python files: {workspace.python_file_count}",
        f"- Test files: {workspace.test_file_count}",
    ]
    if workspace.key_files:
        lines.append(f"- Key files: {', '.join(workspace.key_files)}")
    if workspace.top_level_entries:
        lines.append(f"- Top-level entries: {', '.join(workspace.top_level_entries)}")
    return lines


def _render_git_section(git, workspace_root: Path) -> list[str]:
    if not git.available:
        return []
    lines = ["## Git Context"]
    if git.repo_root is not None:
        lines.append(f"- Repository root: {git.repo_root}")
    if git.branch:
        lines.append(f"- Current branch: {git.branch}")
    if git.recent_commit:
        lines.append(f"- Latest commit: {git.recent_commit}")
    if git.status:
        lines.extend([
            "- Git status snapshot:",
            "```text",
            git.status,
            "```",
        ])
    return lines


def _fence(text: str, lang: str = "") -> tuple[str, str]:
    """Opening and closing code fence for `text`: one backtick longer than the longest run inside it, so the text can't close it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return ticks + lang, ticks


def _render_claude_md_section(claude_md, workspace_root: Path) -> list[str]:
    if not claude_md.files:
        return []
    lines = ["## Project Instructions"]
    for item in claude_md.files:
        try:
            rel = item.path.relative_to(workspace_root)
            label = f"./{rel}"
        except ValueError:
            label = str(item.path)
        opening, closing = _fence(item.content, "md")
        lines.extend([
            f"### {label}",
            opening,
            item.content,
            closing,
        ])
    if claude_md.truncated:
        lines.append("- Additional instruction files were truncated to stay within prompt budget.")
    return lines


def _render_project_summary_section(summary, workspace_root: Path) -> list[str]:
    if not summary.readme_excerpt and not summary.entry_points:
        return []
    lines = ["## Project Summary"]
    if summary.entry_points:
        lines.append(f"- Entry points: {', '.join(summary.entry_points)}")
    if summary.readme_path is not None:
        opening, closing = _fence(summary.readme_excerpt, "text")
        lines.extend([
            f"### ./{summary.readme_path.relative_to(workspace_root)} (excerpt)",
            opening,
            summary.readme_excerpt,
            closing,
        ])
    return lines
