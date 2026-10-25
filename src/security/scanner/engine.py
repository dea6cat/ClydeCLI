# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES
# SPDX-License-Identifier: Apache-2.0

"""In-house security scan engine replacing SkillSpector.

Pure-Python, stdlib-only static scanner for skills, plugins, and MCP servers.
"""
from __future__ import annotations

import ast
import json
import re
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
    VERTICAL_BLANK_LINES,
    get_compiled_patterns,
    is_padding_char,
)


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
    ".py", ".js", ".ts", ".sh", ".bash", ".zsh", ".ps1", ".rb",
    ".go", ".java", ".c", ".cpp", ".php", ".yaml", ".yml", ".json",
    ".toml", ".md", ".txt", "",  # "" for files without extension
}

# Files to skip
SKIP_FILES = {
    "__pycache__", ".pyc", ".pyo", ".git", ".svn", ".hg",
    "node_modules", "vendor", "venv", ".venv", "dist", "build",
}


def should_scan_file(path: Path) -> bool:
    """Check if a file should be scanned based on its extension."""
    if any(skip in str(path) for skip in SKIP_FILES):
        return False
    return path.suffix.lower() in CODE_EXTENSIONS or path.suffix == ""


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
        # AST1: exec()
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name):
                if node.value.func.id in DANGEROUS_BUILTINS:
                    findings.append(Finding(
                        rule_id="AST1" if node.value.func.id == "exec" else "AST2",
                        severity="CRITICAL",
                        category="Tool Misuse",
                        message=f"Found dangerous call to {node.value.func.id}()",
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
        if file_path.is_file() and should_scan_file(file_path):
            all_findings.extend(scan_file(file_path))

    # Calculate score and recommendation
    score = calculate_score(all_findings)
    recommendation, severity = calculate_recommendation(all_findings, score)

    return ScanResult(
        name=skill_name,
        findings=all_findings,
        score=score,
        recommendation=recommendation,
        severity=severity,
    )


def scan_mcp_tools(tools: list[dict[str, Any]], server_name: str) -> ScanResult:
    """Scan MCP server tool definitions."""
    all_findings = []

    # Convert tools to pseudo-SKILL.md content
    tool_content = json.dumps(tools, indent=2)

    # Check text patterns in tool definitions
    all_findings.extend(check_text_patterns_all(tool_content, f"{server_name}.mcp.json"))

    # Calculate score and recommendation
    score = calculate_score(all_findings)
    recommendation, severity = calculate_recommendation(all_findings, score)

    return ScanResult(
        name=server_name,
        findings=all_findings,
        score=score,
        recommendation=recommendation,
        severity=severity,
    )


def calculate_score(findings: list[Finding]) -> int:
    """Calculate a score from 0-100 based on findings."""
    if not findings:
        return 0

    # Score based on severity
    severity_scores = {
        "CRITICAL": 100,
        "HIGH": 70,
        "MEDIUM": 40,
        "LOW": 20,
    }

    # Use the highest severity finding
    max_severity = max(
        (severity_scores.get(f.severity, 0) for f in findings),
        default=0,
    )

    # Count findings to adjust score
    num_findings = len(findings)
    if num_findings > 1:
        # Cap at 100
        max_severity = min(max_severity + (num_findings - 1) * 10, 100)

    return max_severity


def calculate_recommendation(findings: list[Finding], score: int) -> tuple[str, str]:
    """Calculate recommendation and severity from findings and score."""
    if not findings:
        return "SAFE", ""

    # Check for any CRITICAL or HIGH findings
    has_critical = any(f.severity == "CRITICAL" for f in findings)
    has_high = any(f.severity == "HIGH" for f in findings)
    has_medium = any(f.severity == "MEDIUM" for f in findings)

    if has_critical:
        return "DO_NOT_INSTALL", "CRITICAL"
    elif has_high:
        return "DO_NOT_INSTALL", "HIGH"
    elif has_medium:
        return "CAUTION", "MEDIUM"
    else:
        return "CAUTION", "LOW"


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


__all__ = ["scan", "scan_skill_folder", "scan_mcp_tools", "ScanResult", "Finding"]
