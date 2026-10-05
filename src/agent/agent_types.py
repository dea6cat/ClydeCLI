"""Custom sub-agent types: Markdown files with a header, in Claude Code's format.

    ---
    name: test-runner
    description: Runs the test suite and reports failures with their likely cause
    tools: Bash, Read, Grep          # optional allow-list; omit for every tool
    model: inherit                   # optional: provider:model, or inherit
    ---
    You run tests. Report each failure with the file, the assertion and the likely cause.

Looked up in the project's .clyde/agents and .claude/agents, then ~/.clyde/agents and ~/.claude/agents
(the first definition of a name wins). `general-purpose` is built in. Agents written for other tools
pass the same SkillSpector gate as skills before the model can use them.
"""
from __future__ import annotations

from src.config import clyde_home

from dataclasses import dataclass
from pathlib import Path

from ..skills.frontmatter import parse_frontmatter

GENERAL = "general-purpose"


@dataclass(frozen=True)
class AgentType:
    name: str
    description: str
    prompt: str = ""                       # the agent's system prompt (the file's body)
    tools: tuple[str, ...] | None = None   # None: every tool
    model: str | None = None               # provider:model, or None to use the caller's model
    path: Path | None = None


_BUILT_IN = AgentType(GENERAL, "General-purpose agent for research and multi-step tasks; has every tool.")


def agent_dirs(project_root: Path) -> list[Path]:
    root, home = Path(project_root), Path.home()
    return [root / ".clyde" / "agents", root / ".claude" / "agents", clyde_home() / "agents", home / ".claude" / "agents"]


def _parse(path: Path) -> AgentType | None:
    try:
        parsed = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    meta = parsed.frontmatter
    name = str(meta.get("name") or path.stem).strip()
    if not name:
        return None
    tools = meta.get("tools")
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    model = str(meta.get("model") or "").strip()
    return AgentType(
        name=name,
        description=str(meta.get("description") or "").strip() or f"Custom agent from {path.name}",
        prompt=parsed.body.strip(),
        tools=tuple(str(t) for t in tools) if isinstance(tools, list) and tools else None,
        # Claude Code's sonnet/opus/haiku aliases name its own models: the caller's model is used instead.
        model=model if ":" in model else None,
        path=path,
    )


def load(project_root: Path) -> dict[str, AgentType]:
    """Every agent type available here, by name; held-back ones (SkillSpector) are left out."""
    from .. import skill_scan

    found: dict[str, AgentType] = {GENERAL: _BUILT_IN}
    for folder in agent_dirs(project_root):
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            agent = _parse(path)
            if agent is None or agent.name in found:
                continue
            if skill_scan.check("agent", agent.name, path).blocked:
                continue
            found[agent.name] = agent
    return found
