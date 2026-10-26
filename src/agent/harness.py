"""Harness discovery: find installed agent CLIs, MCP servers, local models, and Clyde skills.

Each discovered harness is a delivery target that Clyde can open in a role
(master, advisor, worker) with a specific model. The same harness can be
opened in multiple roles with different models.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import clyde_home


@dataclass(frozen=True)
class HarnessModel:
    """A model that a harness can run."""
    model_id: str
    context_window: int | None = None
    local: bool = False


@dataclass(frozen=True)
class Harness:
    """An installed agent harness or model provider."""
    name: str
    kind: str  # "cli", "mcp", "local_model", "clyde_skill", "provider"
    binary: str | None = None          # executable path for CLI harnesses
    config_path: str | None = None     # config file path
    models: list[HarnessModel] = field(default_factory=list)
    description: str = ""


def _which(name: str) -> str | None:
    return shutil.which(name)


def discover_cli_harnesses() -> list[Harness]:
    """Discover installed agent CLIs on PATH."""
    known_clis = {
        "claude": ("Claude Code", "cli"),
        "gemini": ("Gemini CLI", "cli"),
        "cursor": ("Cursor", "cli"),
        "copilot": ("GitHub Copilot CLI", "cli"),
        "codex": ("Codex CLI", "cli"),
        "aider": ("Aider", "cli"),
        "opencode": ("OpenCode", "cli"),
    }
    found: list[Harness] = []
    for binary, (desc, kind) in known_clis.items():
        path = _which(binary)
        if path:
            found.append(Harness(
                name=binary,
                kind=kind,
                binary=path,
                models=[HarnessModel(model_id="default", local=False)],
                description=desc,
            ))
    return found


def discover_local_models() -> list[Harness]:
    """Discover locally runnable models (Ollama, MLX, oMLX)."""
    found: list[Harness] = []

    # Ollama
    if _which("ollama"):
        found.append(Harness(
            name="ollama",
            kind="local_model",
            binary=_which("ollama"),
            models=[
                HarnessModel(model_id="ollama:qwen2.5-coder:32b", local=True),
                HarnessModel(model_id="ollama:codestral:22b", local=True),
                HarnessModel(model_id="ollama:deepseek-coder-v2:236b", local=True),
            ],
            description="Ollama local models",
        ))

    # MLX
    if _which("mlx"):
        found.append(Harness(
            name="mlx",
            kind="local_model",
            binary=_which("mlx"),
            models=[HarnessModel(model_id="mlx:default", local=True)],
            description="MLX local models (Apple Silicon)",
        ))

    # oMLX
    if _which("omlx"):
        found.append(Harness(
            name="omlx",
            kind="local_model",
            binary=_which("omlx"),
            models=[HarnessModel(model_id="omlx:default", local=True)],
            description="oMLX local models",
        ))

    return found


def discover_mcp_servers() -> list[Harness]:
    """Discover configured MCP servers from clyde config."""
    found: list[Harness] = []
    config_dir = clyde_home()
    mcp_config = config_dir / "mcp_servers.json"
    if mcp_config.exists():
        try:
            import json
            data = json.loads(mcp_config.read_text(encoding="utf-8"))
            servers = data.get("servers", {}) if isinstance(data, dict) else {}
            for name, cfg in servers.items():
                cmd = cfg.get("command", "")
                found.append(Harness(
                    name=f"mcp:{name}",
                    kind="mcp",
                    binary=cmd if isinstance(cmd, str) else None,
                    config_path=str(mcp_config),
                    models=[HarnessModel(model_id="default", local=False)],
                    description=f"MCP server: {name}",
                ))
        except Exception:
            pass
    return found


def discover_clyde_skills() -> list[Harness]:
    """Discover Clyde skills as delivery targets."""
    found: list[Harness] = []
    skills_dir = clyde_home() / "skills"
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").exists():
                found.append(Harness(
                    name=f"skill:{entry.name}",
                    kind="clyde_skill",
                    config_path=str(entry / "SKILL.md"),
                    models=[HarnessModel(model_id="default", local=False)],
                    description=f"Clyde skill: {entry.name}",
                ))
    return found


def discover_providers() -> list[Harness]:
    """Discover configured providers from Clyde's provider registry."""
    found: list[Harness] = []
    try:
        from src.providers import build_registry
        registry = build_registry()
        for spec in registry.list_specs():
            found.append(Harness(
                name=f"provider:{spec.name}",
                kind="provider",
                models=[HarnessModel(model_id=spec.name, local=False)],
                description=f"Provider: {spec.name}",
            ))
    except Exception:
        pass
    return found


def discover_all() -> list[Harness]:
    """Discover all available harnesses."""
    harnesses: list[Harness] = []
    harnesses.extend(discover_cli_harnesses())
    harnesses.extend(discover_local_models())
    harnesses.extend(discover_mcp_servers())
    harnesses.extend(discover_clyde_skills())
    harnesses.extend(discover_providers())
    return harnesses


def format_harness_table(harnesses: list[Harness]) -> str:
    """Format harnesses as a table for display."""
    if not harnesses:
        return "No harnesses discovered."
    lines = ["# Discovered Harnesses", ""]
    for h in harnesses:
        models_str = ", ".join(m.model_id for m in h.models) or "none"
        lines.append(f"- **{h.name}** ({h.kind}) — {h.description}")
        lines.append(f"  Models: {models_str}")
        if h.binary:
            lines.append(f"  Binary: {h.binary}")
        if h.config_path:
            lines.append(f"  Config: {h.config_path}")
        lines.append("")
    return "\n".join(lines)


def harness_by_name(harnesses: list[Harness], name: str) -> Harness | None:
    for h in harnesses:
        if h.name == name:
            return h
    return None
