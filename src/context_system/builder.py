from __future__ import annotations

from datetime import date
from pathlib import Path

from .claude_md import load_claude_md_context
from .git_context import collect_git_context
from .project_summary import build_project_summary
from .workspace_snapshot import build_workspace_snapshot


def build_context_prompt(
    workspace_root: str | Path,
    *,
    cwd: str | Path | None = None,
) -> str:
    root = Path(workspace_root).expanduser().resolve()
    current = Path(cwd).expanduser().resolve() if cwd is not None else root

    workspace = build_workspace_snapshot(root, cwd=current)
    git = collect_git_context(root)
    claude_md = load_claude_md_context(root, cwd=current)
    summary = build_project_summary(root)

    sections: list[str] = []

    sections.append("\n".join(_render_workspace_section(workspace)))

    git_lines = _render_git_section(git, root)
    if git_lines:
        sections.append("\n".join(git_lines))

    summary_lines = _render_project_summary_section(summary, root)
    if summary_lines:
        sections.append("\n".join(summary_lines))

    map_lines = _render_code_map_section(root)
    if map_lines:
        sections.append("\n".join(map_lines))

    md_lines = _render_claude_md_section(claude_md, root)
    if md_lines:
        sections.append("\n".join(md_lines))

    return "\n\n".join(section for section in sections if section.strip())


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
        lines.extend([
            f"### {label}",
            "```md",
            item.content,
            "```",
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
        lines.extend([
            f"### ./{summary.readme_path.relative_to(workspace_root)} (excerpt)",
            # Four backticks so fenced code inside the README cannot close the block.
            "````text",
            summary.readme_excerpt,
            "````",
        ])
    return lines
