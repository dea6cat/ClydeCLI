"""Harness discovery: find installed agent CLIs, MCP servers, connected providers (with their real model lists), and Clyde skills.

Each discovered harness is a delivery target that Clyde can open in a role
(master, advisor, worker) with a specific model. The same harness can be
opened in multiple roles with different models.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field

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


ADAPTED_CLIS = frozenset({"claude", "aider"})   # CLIs Clyde can run as workers (agent/cli_workers.py)


def discover_cli_harnesses(provider_models: dict[str, list[str]] | None = None) -> list[Harness]:
    """Agent CLIs on PATH. One with an adapter lists the models it takes (Claude Code: its aliases; aider: the connected
    providers' models in litellm form); one without lists none, so it is shown but can't be picked."""
    from src.agent import cli_workers
    known_clis = {
        "claude": "Claude Code",
        "gemini": "Gemini CLI",
        "cursor": "Cursor",
        "copilot": "GitHub Copilot CLI",
        "codex": "Codex CLI",
        "aider": "Aider",
        "opencode": "OpenCode",
    }
    found: list[Harness] = []
    for binary, desc in known_clis.items():
        path = _which(binary)
        if not path:
            continue
        ids = {"claude": list(cli_workers.CLAUDE_MODELS),
               "aider": cli_workers.litellm_models(provider_models or {})}.get(binary, [])
        found.append(Harness(name=binary, kind="cli", binary=path, models=[HarnessModel(model_id=m) for m in ids], description=desc))
    return found


def discover_mcp_servers() -> list[Harness]:
    """Discover configured MCP servers from clyde config."""
    found: list[Harness] = []
    config_dir = clyde_home()
    mcp_config = config_dir / "mcp_servers.json"
    if mcp_config.exists():
        try:
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


LOCAL_PROVIDERS = frozenset({"ollama", "omlx"})
RUNNABLE_KINDS = frozenset({"provider"})   # can lead (master, advisor) and work


def can_work(harness: "Harness") -> bool:
    """A provider runs as Clyde's own agent loop; a CLI only when it has an adapter and models to pick from."""
    return harness.kind in RUNNABLE_KINDS or (harness.kind == "cli" and harness.name in ADAPTED_CLIS and bool(harness.models))
_MODELS_SHOWN = 40


def discover_providers() -> list[Harness]:
    """Connected providers with the models each one really offers (Ollama: what is installed)."""
    found: list[Harness] = []
    try:
        from src.providers import build_registry, keys, usable
        from src.providers.card_shuffle import CardShuffle
        keys.load_into_env()
        for name, provider in usable(build_registry()).items():
            if name == CardShuffle.name:   # a dealer over the others, not a model source
                continue
            try:
                ids = provider.list_models()[:_MODELS_SHOWN]
            except Exception:
                continue
            if not ids:
                continue
            found.append(Harness(
                name=f"provider:{name}",
                kind="provider",
                models=[HarnessModel(model_id=m, local=name in LOCAL_PROVIDERS) for m in ids],
                description=f"Provider: {name}",
            ))
    except Exception:
        pass
    return found


def discover_all() -> list[Harness]:
    """Every available harness: the agent CLIs, MCP servers, Clyde skills and the connected providers."""
    providers = discover_providers()
    by_provider = {h.name.removeprefix("provider:"): [m.model_id for m in h.models] for h in providers}
    return [*discover_cli_harnesses(by_provider), *discover_mcp_servers(), *discover_clyde_skills(), *providers]


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
