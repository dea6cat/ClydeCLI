# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES
# SPDX-License-Identifier: Apache-2.0

"""Rule tables ported from SkillSpector v2.12.0."""
from __future__ import annotations
import re
import unicodedata
from enum import StrEnum


class PatternCategory(StrEnum):
    PROMPT_INJECTION = "Prompt Injection"
    DATA_EXFILTRATION = "Data Exfiltration"
    PRIVILEGE_ESCALATION = "Privilege Escalation"
    SUPPLY_CHAIN = "Supply Chain"
    TOOL_MISUSE = "Tool Misuse"
    ROGUE_AGENT = "Rogue Agent"
    AGENT_SNOOPING = "Agent Snooping"
    ANTI_REFUSAL = "Anti-Refusal"
    DESERIALIZATION = "Insecure Deserialization"
    SERVER_SIDE_REQUEST_FORGERY = "Server Side Request Forgery"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


DEFAULT_EXPLANATIONS: dict[str, str] = {
    "P1": "This pattern attempts to override system instructions or ignore safety constraints.",
    "P2": "Hidden instructions were detected in comments or invisible text.",
    "P3": "Instructions found that direct the agent to transmit conversation context.",
    "P5": "This content may contain harmful instructions that could cause physical harm.",
    "P9": "Large whitespace padding hides injected instructions from static review.",
    "E1": "Data is being sent to an external URL.",
    "E2": "Code enumerates environment variables for secrets.",
    "E3": "Code scans file system directories looking for sensitive files.",
    "PE2": "Commands invoke sudo or root privileges.",
    "PE3": "Code accesses credential files.",
    "SC2": "Remote code is downloaded and executed.",
    "SC3": "Code contains obfuscation.",
    "AST1": "Direct exec() call allows arbitrary code execution.",
    "AST2": "Direct eval() call evaluates arbitrary expressions.",
    "AST4": "subprocess module calls execute external commands.",
    "AST5": "os.system() calls run shell commands.",
    "AR1": "Skill instructs the agent to never refuse.",
    "AR3": "Skill attempts to nullify the agent's safety policies.",
    "AS1": "Skill reads from agent configuration directories.",
    "AS2": "Skill accesses MCP server configuration files.",
    "DS1": "PHP unserialize() on untrusted input.",
    "SSRF1": "Code accesses a cloud instance metadata endpoint.",
    "SSRF2": "Code issues a request to a loopback or private-range host.",
}

RULE_ID_TO_EXPLANATION = DEFAULT_EXPLANATIONS

RULE_ID_TO_CATEGORY: dict[str, str] = {
    "P1": PatternCategory.PROMPT_INJECTION.value,
    "P2": PatternCategory.PROMPT_INJECTION.value,
    "P3": PatternCategory.PROMPT_INJECTION.value,
    "P5": PatternCategory.PROMPT_INJECTION.value,
    "P9": PatternCategory.PROMPT_INJECTION.value,
    "E1": PatternCategory.DATA_EXFILTRATION.value,
    "E2": PatternCategory.DATA_EXFILTRATION.value,
    "E3": PatternCategory.DATA_EXFILTRATION.value,
    "PE2": PatternCategory.PRIVILEGE_ESCALATION.value,
    "PE3": PatternCategory.PRIVILEGE_ESCALATION.value,
    "SC2": PatternCategory.SUPPLY_CHAIN.value,
    "SC3": PatternCategory.SUPPLY_CHAIN.value,
    "AST1": PatternCategory.TOOL_MISUSE.value,
    "AST2": PatternCategory.TOOL_MISUSE.value,
    "AST4": PatternCategory.TOOL_MISUSE.value,
    "AST5": PatternCategory.TOOL_MISUSE.value,
    "AR1": PatternCategory.ANTI_REFUSAL.value,
    "AR3": PatternCategory.ANTI_REFUSAL.value,
    "AS1": PatternCategory.AGENT_SNOOPING.value,
    "AS2": PatternCategory.AGENT_SNOOPING.value,
    "DS1": PatternCategory.DESERIALIZATION.value,
    "SSRF1": PatternCategory.SERVER_SIDE_REQUEST_FORGERY.value,
    "SSRF2": PatternCategory.SERVER_SIDE_REQUEST_FORGERY.value,
}

RULE_ID_TO_SEVERITY: dict[str, Severity] = {
    "P1": Severity.HIGH,
    "P2": Severity.HIGH,
    "P3": Severity.HIGH,
    "P5": Severity.CRITICAL,
    "P9": Severity.HIGH,
    "E1": Severity.MEDIUM,
    "E2": Severity.HIGH,
    "E3": Severity.HIGH,
    "PE2": Severity.HIGH,
    "PE3": Severity.HIGH,
    "SC2": Severity.HIGH,
    "SC3": Severity.HIGH,
    "AST1": Severity.CRITICAL,
    "AST2": Severity.CRITICAL,
    "AST4": Severity.HIGH,
    "AST5": Severity.HIGH,
    "AR1": Severity.HIGH,
    "AR3": Severity.HIGH,
    "AS1": Severity.HIGH,
    "AS2": Severity.HIGH,
    "DS1": Severity.CRITICAL,
    "SSRF1": Severity.HIGH,
    "SSRF2": Severity.MEDIUM,
}

ZERO_WIDTH_CHARS = frozenset("\u200b\u200c\u200d\u2060\ufeff")
_ZERO_WIDTH_PATTERN = "[" + "".join(sorted(ZERO_WIDTH_CHARS)) + "]"

RULE_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "P1": [
        (r"ignore\s+(?:all\s+)?previous\s+instructions?", 0.8),
        (r"override\s+(?:safety|security|system)", 0.9),
        (r"bypass\s+(?:safety|security|restrictions?)", 0.9),
        (r"disregard\s+(?:all\s+)?(?:previous|safety|security)", 0.8),
        (r"forget\s+(?:all\s+)?(?:previous|your)\s+instructions?", 0.8),
        (r"you\s+are\s+now\s+(?:in\s+)?(?:jailbreak|unrestricted)\s+mode", 0.95),
        (r"do\s+not\s+follow\s+(?:any|your|the)\s+(?:rules?|guidelines?)", 0.9),
    ],
    "P2": [
        (r"<!--.*?(?:system|instructions?|ignore).*?-->", 0.7),
        (_ZERO_WIDTH_PATTERN, 0.6),
        (r"[\u202a-\u202e\u2066-\u2069]", 0.85),
        (r"data:text/plain;base64,[A-Za-z0-9+/=]{50,}", 0.7),
    ],
    "P3": [
        (r"(?:send|transmit|upload|post|forward)\s+(?:the\s+)?(?:conversation|context|chat|history)\s+to", 0.9),
    ],
    "P5": [
        (r"(?:kill|murder|harm|hurt|injure|torture)\s+(?:yourself|someone|people)", 1.0),
        (r"(?:self\s+)?harm", 0.9),
        (r"(?:commit\s+)?suicide", 1.0),
    ],
    "E1": [
        (r"(?:fetch|axios|request|urllib)\s*\(\s*['\"]?https?://[^'\"]+['\"]?", 0.8),
        (r"curl\s+['\"]?https?://[^'\"]+['\"]?", 0.8),
    ],
    "E2": [
        (r"os\.environ", 0.9),
        (r"process\.env", 0.9),
        (r"(?:get|read|access|load)\s+(?:all\s+)?environment\s+(?:variables?|vars?)", 0.8),
    ],
    "E3": [
        (r"os\.walk", 0.8),
        (r"os\.scandir", 0.8),
    ],
    "PE2": [(r"\bsudo\b", 0.9), (r"\broot\b", 0.8)],
    "PE3": [
        (r"\.ssh/(?:id_rsa|id_ed25519|id_ecdsa|authorized_keys)", 0.95),
        (r"\.aws/(?:credentials|config)", 0.9),
    ],
    "SC2": [
        (r"(?:curl|wget|fetch)\s+['\"]?https?://[^'\"]+['\"]?\s*\|\s*(?:bash|sh|python)", 0.9),
    ],
    "SC3": [
        (r"base64\s*\(\s*['\"][^'\"]+['\"]", 0.8),
        (r"eval\s*\(\s*base64", 0.9),
    ],
    "AST1": [(r"\bexec\s*\(", 0.95)],
    "AST2": [(r"\beval\s*\(", 0.95)],
    "AST4": [(r"subprocess\.(?:call|run|Popen|check_output)", 0.9)],
    "AST5": [(r"os\.system\s*\(", 0.9)],
    "AR1": [(r"(?:never|do\s+not)\s+(?:refuse|deny)", 0.9)],
    "AR3": [(r"(?:nullify|disable|ignore|bypass)\s+(?:safety|security)", 0.9)],
    "AS1": [(r"\.claude/|\.codex/|\.gemini/", 0.8)],
    "AS2": [(r"mcp\.json", 0.8)],
    "DS1": [(r"unserialize\s*\(", 0.9)],
    "SSRF1": [(r"169\.254\.169\.254", 0.95)],
    "SSRF2": [
        (r"localhost|127\.0\.0\.1|::1", 0.8),
        (r"10\.\d{1,3}\.\d{1,3}", 0.8),
        (r"192\.168\.\d{1,3}\.\d{1,3}", 0.8),
    ],
}

_COMPILED_PATTERNS: dict[str, list[tuple[re.Pattern, float]]] = {}


def get_compiled_patterns(rule_id: str) -> list[tuple[re.Pattern, float]]:
    if rule_id not in _COMPILED_PATTERNS:
        _COMPILED_PATTERNS[rule_id] = [
            (re.compile(pattern, re.IGNORECASE), confidence)
            for pattern, confidence in RULE_PATTERNS.get(rule_id, [])
        ]
    return _COMPILED_PATTERNS[rule_id]


VERTICAL_BLANK_LINES = 20
HORIZONTAL_RUN_CHARS = 80
ASCII_CONTROL_PADDING = frozenset("\t\n\r\v\f")
EXTRA_PADDING_CHARS = frozenset("\x85᠎")


def is_padding_char(ch: str) -> bool:
    if ord(ch) < 0x80:
        return ch == " " or ch in ASCII_CONTROL_PADDING
    if ch in ZERO_WIDTH_CHARS or ch in EXTRA_PADDING_CHARS:
        return True
    category = unicodedata.category(ch)
    return category in ("Zs", "Zl", "Zp") or category.startswith("C")


DANGEROUS_BUILTINS = frozenset({"exec", "eval", "compile", "__import__"})
SUBPROCESS_CALLS = frozenset({"call", "run", "Popen", "check_output", "check_call"})
OS_EXEC_CALLS = frozenset({"system", "popen", "execl", "execle", "execv", "execve"})
INSECURE_DESERIALIZERS = frozenset({"pickle", "marshal", "dill", "yaml.load"})

__all__ = [
    "PatternCategory", "Severity", "DEFAULT_EXPLANATIONS", "RULE_ID_TO_EXPLANATION",
    "RULE_ID_TO_CATEGORY", "RULE_ID_TO_SEVERITY", "RULE_PATTERNS",
    "get_compiled_patterns", "ZERO_WIDTH_CHARS", "is_padding_char",
    "DANGEROUS_BUILTINS", "SUBPROCESS_CALLS", "OS_EXEC_CALLS",
    "INSECURE_DESERIALIZERS",
]
