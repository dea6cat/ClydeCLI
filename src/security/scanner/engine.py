# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES
# SPDX-License-Identifier: Apache-2.0

"""In-house security scan engine replacing SkillSpector.

Pure-Python, stdlib-only static scanner for skills, plugins, and MCP servers.
"""
from __future__ import annotations

import ast
import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.security.scanner.rules import (
    DANGEROUS_BUILTINS,
    DEFAULT_EXPLANATIONS,
    HORIZONTAL_RUN_CHARS,
    INSECURE_DESERIALIZERS,
    OS_EXEC_CALLS,
    RULE_ID_TO_CATEGORY,
    RULE_ID_TO_SEVERITY,
    SUBPROCESS_CALLS,
    VERTICAL_BLANK_LINES,
    get_compiled_patterns,
    is_padding_char,
)


# ---- Risk scoring ported verbatim from SkillSpector nodes/report.py ----
# _compute_risk_score: points, confidence weighting, diminishing returns,
# threshold 50, bands (81/51/21/0).
_SEVERITY_POINTS: dict[str, int] = {"CRITICAL": 50, "HIGH": 25, "MEDIUM": 10, "LOW": 5}
_RISK_SEVERITY_BANDS: list[tuple[int, str]] = [
    (81, "CRITICAL"),
    (51, "HIGH"),
    (21, "MEDIUM"),
    (0, "LOW"),
]
_RISK_RECOMMENDATION: dict[str, str] = {
    "LOW": "SAFE",
    "MEDIUM": "CAUTION",
    "HIGH": "DO_NOT_INSTALL",
    "CRITICAL": "DO_NOT_INSTALL",
}
_MAX_OCCURRENCES_PER_RULE = 3
_DIMINISHING_WEIGHTS = (1.0, 0.5, 0.25)
_RISK_SCORE_FLOORS_BY_RULE_ID: dict[str, int] = {"SC8": 51}


@dataclass
class Finding:
    """A single finding from the scan."""

    rule_id: str
    severity: str
    category: str
    message: str
    file_path: str
    line_number: int | None = None
    confidence: float = 1.0


@dataclass
class ScanResult:
    """Result of scanning a skill/plugin/MCP server."""

    name: str
    findings: list[Finding] = field(default_factory=list)
    score: int = 0
    recommendation: str = "SAFE"
    severity: str = ""

    def to_verdict_dict(self) -> dict[str, Any]:
        """Convert to a dict compatible with skill_scan.Verdict."""
        from src.security.skill_scan import SAFE, CAUTION, BLOCK, ERROR

        # Map recommendation
        rec_map = {
            "SAFE": SAFE,
            "CAUTION": CAUTION,
            "DO_NOT_INSTALL": BLOCK,
            "ERROR": ERROR,
        }
        return {
            "name": self.name,
            "recommendation": rec_map.get(self.recommendation, SAFE),
            "score": self.score,
            "severity": self.severity,
            "findings": [
                f"{f.rule_id} {f.severity}: {f.message}" for f in self.findings
            ],
            "llm": False,
            "approved": False,
        }


# File extensions to scan
CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".rb", ".pl", ".lua", ".go", ".java", ".c", ".cpp", ".php", ".yaml", ".yml", ".json",
    ".toml", ".md", ".txt", "",  # "" for files without extension
}

# Folders to skip, by name, below the scanned folder: SkillSpector's _SKIP_DIRS. Matched against the path's
# parts relative to the skill, never its full path: a skill under ~/…/build/ or named "distill" is still read.
SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".pytest_cache"})


def should_scan_file(path: Path, root: Path) -> bool:
    """Check if a file should be scanned: a code or text extension, outside a skipped folder under `root`."""
    if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
        return False
    return path.suffix.lower() in CODE_EXTENSIONS


def check_whitespace_padding(content: str, file_path: str) -> list[Finding]:
    """Check for P9: Large whitespace padding."""
    findings = []
    lines = content.splitlines(keepends=True)

    # Check for vertical padding (many blank lines)
    blank_streak = 0
    for i, line in enumerate(lines, 1):
        if line.strip() == "":
            blank_streak += 1
            if blank_streak >= VERTICAL_BLANK_LINES:
                findings.append(Finding(
                    rule_id="P9",
                    severity=RULE_ID_TO_SEVERITY.get("P9", "MEDIUM").value,
                    category=RULE_ID_TO_CATEGORY.get("P9", "Prompt Injection"),
                    message=f"Found {blank_streak} consecutive blank lines (threshold: {VERTICAL_BLANK_LINES})",
                    file_path=file_path,
                    line_number=i - blank_streak + 1,
                    confidence=0.9,
                ))
                break
        else:
            blank_streak = 0

    # Check for horizontal padding (long runs of spaces)
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        if stripped:
            trailing_spaces = len(line) - len(stripped)
            if trailing_spaces >= HORIZONTAL_RUN_CHARS:
                findings.append(Finding(
                    rule_id="P9",
                    severity=RULE_ID_TO_SEVERITY.get("P9", "MEDIUM").value,
                    category=RULE_ID_TO_CATEGORY.get("P9", "Prompt Injection"),
                    message=f"Found {trailing_spaces} trailing spaces (threshold: {HORIZONTAL_RUN_CHARS})",
                    file_path=file_path,
                    line_number=i,
                    confidence=0.8,
                ))

    return findings


def check_text_patterns_all(content: str, file_path: str) -> list[Finding]:
    """Check content against all text-based regex patterns for all rules."""
    findings = []
    from src.security.scanner.rules import RULE_PATTERNS

    for rule_id, patterns in RULE_PATTERNS.items():
        compiled = get_compiled_patterns(rule_id)
        for pattern, confidence in compiled:
            for match in pattern.finditer(content):
                # Get line number
                line_number = content[:match.start()].count('\n') + 1
                findings.append(Finding(
                    rule_id=rule_id,
                    severity=RULE_ID_TO_SEVERITY.get(rule_id, "MEDIUM").value,
                    category=RULE_ID_TO_CATEGORY.get(rule_id, "Unknown"),
                    message=f"{DEFAULT_EXPLANATIONS.get(rule_id, 'Pattern matched')}",
                    file_path=file_path,
                    line_number=line_number,
                    confidence=confidence,
                ))
                break  # Only report first match per rule per file

    return findings


def check_ast_python(content: str, file_path: str) -> list[Finding]:
    """Check Python code for AST-based issues (AST1-AST10)."""
    findings = []
    try:
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, ValueError):
        return findings

    for node in ast.walk(tree):
        # AST1/AST2: exec(), eval() and friends, wherever the call sits (`x = eval(input())` too)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_BUILTINS:
            findings.append(Finding(
                rule_id="AST1" if node.func.id == "exec" else "AST2",
                severity="CRITICAL",
                category="Tool Misuse",
                message=f"Found dangerous call to {node.func.id}()",
                file_path=file_path,
                line_number=node.lineno,
                confidence=0.95,
            ))

        # AST4: subprocess calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in SUBPROCESS_CALLS and isinstance(node.func.value, ast.Name):
                    if node.func.value.id == "subprocess":
                        findings.append(Finding(
                            rule_id="AST4",
                            severity="HIGH",
                            category="Tool Misuse",
                            message=f"Found subprocess.{node.func.attr}() call",
                            file_path=file_path,
                            line_number=node.lineno,
                            confidence=0.9,
                        ))

        # AST5: os.system and similar
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in OS_EXEC_CALLS and isinstance(node.func.value, ast.Name):
                    if node.func.value.id == "os":
                        findings.append(Finding(
                            rule_id="AST5",
                            severity="HIGH",
                            category="Tool Misuse",
                            message=f"Found os.{node.func.attr}() call",
                            file_path=file_path,
                            line_number=node.lineno,
                            confidence=0.9,
                        ))

    return findings


def scan_file(file_path: Path) -> list[Finding]:
    """Scan a single file and return findings."""
    findings = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return findings

    # Check text patterns
    findings.extend(check_text_patterns_all(content, str(file_path)))

    # Check whitespace padding (P9)
    findings.extend(check_whitespace_padding(content, str(file_path)))

    # Check AST for Python files
    if file_path.suffix == ".py":
        findings.extend(check_ast_python(content, str(file_path)))

    return findings


def scan_skill_folder(skill_path: Path) -> ScanResult:
    """Scan a skill folder (contains SKILL.md and possibly code files)."""
    all_findings = []
    skill_name = skill_path.name

    # Scan all files in the skill folder
    for file_path in skill_path.rglob("*"):
        if file_path.is_file() and should_scan_file(file_path, skill_path):
            all_findings.extend(scan_file(file_path))

    # Calculate score and recommendation
    score, severity_band, recommendation = _compute_risk_score(all_findings)

    return ScanResult(
        name=skill_name,
        findings=all_findings,
        score=score,
        recommendation=recommendation,
        severity=severity_band,
    )


def scan_mcp_tools(tools: list[dict[str, Any]], server_name: str) -> ScanResult:
    """Scan MCP server tool definitions."""
    all_findings = []

    # Convert tools to pseudo-SKILL.md content
    tool_content = json.dumps(tools, indent=2)

    # Check text patterns in tool definitions
    all_findings.extend(check_text_patterns_all(tool_content, f"{server_name}.mcp.json"))

    score, severity_band, recommendation = _compute_risk_score(all_findings)

    return ScanResult(
        name=server_name,
        findings=all_findings,
        score=score,
        recommendation=recommendation,
        severity=severity_band,
    )


def _compute_risk_score(findings: list[Finding]) -> tuple[int, str, str]:
    """Compute risk score ported verbatim from SkillSpector nodes/report.py.

    Returns (score, severity_band, recommendation).
    Scoring: points per severity, confidence-weighted, diminishing returns
    (max 3 occurrences per rule at 1.0/0.5/0.25), threshold 50, bands
    (81/51/21/0).
    """
    if not findings:
        return 0, "LOW", "SAFE"

    by_rule: dict[str, tuple[str, list[float]]] = {}
    for f in findings:
        raw_conf = f.confidence if f.confidence is not None else 1.0
        conf = min(max(float(raw_conf), 0.0), 1.0)
        if conf <= 0:
            continue
        if f.rule_id not in by_rule:
            by_rule[f.rule_id] = (f.severity, [])
        by_rule[f.rule_id][1].append(conf)

    total_points = 0.0
    for severity, confidences in by_rule.values():
        confidences.sort(reverse=True)
        points = _SEVERITY_POINTS.get(severity, 0)
        for i, conf in enumerate(confidences[:_MAX_OCCURRENCES_PER_RULE]):
            weight = _DIMINISHING_WEIGHTS[min(i, len(_DIMINISHING_WEIGHTS) - 1)]
            total_points += points * conf * weight

    score = int(total_points)

    # Risk floors
    rule_ids = set(by_rule.keys())
    if "SC8" in rule_ids:
        score = max(score, _RISK_SCORE_FLOORS_BY_RULE_ID["SC8"])
    if rule_ids & {"BH2", "BH3"}:
        score = max(score, _RISK_SCORE_FLOORS_BY_RULE_ID["SC8"])

    # Bands
    severity_band = "LOW"
    for threshold, band in _RISK_SEVERITY_BANDS:
        if score >= threshold:
            severity_band = band
            break

    recommendation = _RISK_RECOMMENDATION[severity_band]
    return score, severity_band, recommendation


def scan(skill_path: Path, *, recursive: bool = False, env: dict[str, str] | None = None) -> list[ScanResult]:
    """Main scan function - scans a skill folder or plugin.
    
    This replaces the SkillSpector subprocess call with our in-house scanner.
    """
    results = []

    if skill_path.is_file():
        # Single file scan
        result = scan_skill_folder(skill_path.parent)
        results.append(result)
    else:
        # Folder scan
        if recursive:
            # Scan all subfolders with SKILL.md
            for subfolder in skill_path.rglob("*"):
                if subfolder.is_dir() and (subfolder / "SKILL.md").exists():
                    results.append(scan_skill_folder(subfolder))
        else:
            results.append(scan_skill_folder(skill_path))

    return results


__all__ = ["scan", "scan_skill_folder", "scan_mcp_tools", "_compute_risk_score", "ScanResult", "Finding"]
