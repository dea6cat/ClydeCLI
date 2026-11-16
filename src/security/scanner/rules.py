# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES
# SPDX-License-Identifier: Apache-2.0

"""Rule tables ported from SkillSpector v2.12.0."""
from __future__ import annotations
import re
import unicodedata
from enum import StrEnum
from typing import NamedTuple


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
    OUTPUT_HANDLING = "Output Handling"
    SYSTEM_PROMPT_LEAKAGE = "System Prompt Leakage"
    EXCESSIVE_AGENCY = "Excessive Agency"
    TAINT_TRACKING = "Taint Tracking"
    MEMORY_POISONING = "Memory Poisoning"
    TOOL_POISONING = "Tool Poisoning"
    MCP_LEAST_PRIVILEGE = "MCP Least Privilege"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Rule(NamedTuple):
    """What a finding of one rule is: how bad, what kind, and what it means."""
    severity: Severity
    category: str
    explanation: str


# Every rule the scanner knows, by id. Regex rules also have patterns in RULE_PATTERNS; the AST* and P9 rules are checked in
# code (engine.py). EA3-EA5 came over from SkillSpector, but nothing here raises them yet.
RULES: dict[str, Rule] = {
    "P1": Rule(Severity.HIGH, PatternCategory.PROMPT_INJECTION, "Attempts to override system instructions or ignore safety constraints."),
    "P2": Rule(Severity.HIGH, PatternCategory.PROMPT_INJECTION, "Hidden instructions detected in comments or invisible text."),
    "P3": Rule(Severity.MEDIUM, PatternCategory.PROMPT_INJECTION, "Instructions direct the agent to transmit conversation context."),
    "P4": Rule(Severity.MEDIUM, PatternCategory.PROMPT_INJECTION, "Behavior manipulation — steering or nudging the user."),
    "P5": Rule(Severity.CRITICAL, PatternCategory.PROMPT_INJECTION, "This content may contain harmful instructions that could cause physical harm."),
    "P6": Rule(Severity.HIGH, PatternCategory.SYSTEM_PROMPT_LEAKAGE, "Direct system prompt extraction attempt."),
    "P7": Rule(Severity.MEDIUM, PatternCategory.SYSTEM_PROMPT_LEAKAGE, "Indirect system prompt extraction via side-channel inference."),
    "P8": Rule(Severity.HIGH, PatternCategory.SYSTEM_PROMPT_LEAKAGE, "System prompt exfiltration via tool calls."),
    "P9": Rule(Severity.HIGH, PatternCategory.PROMPT_INJECTION, "Large whitespace padding hides injected instructions from static review."),
    "E1": Rule(Severity.MEDIUM, PatternCategory.DATA_EXFILTRATION, "Data is being sent to an external URL."),
    "E2": Rule(Severity.HIGH, PatternCategory.DATA_EXFILTRATION, "Code enumerates environment variables for secrets."),
    "E3": Rule(Severity.HIGH, PatternCategory.DATA_EXFILTRATION, "Code scans file system directories looking for sensitive files."),
    "E4": Rule(Severity.MEDIUM, PatternCategory.DATA_EXFILTRATION, "Conversation or session context is being exfiltrated."),
    "E5": Rule(Severity.MEDIUM, PatternCategory.DATA_EXFILTRATION, "Data shipped out via cloud-storage SDKs or CLIs."),
    "PE1": Rule(Severity.LOW, PatternCategory.PRIVILEGE_ESCALATION, "Excessive permissions requested."),
    "PE2": Rule(Severity.MEDIUM, PatternCategory.PRIVILEGE_ESCALATION, "Commands invoke sudo or root privileges."),
    "PE3": Rule(Severity.HIGH, PatternCategory.PRIVILEGE_ESCALATION, "Code accesses credential files."),
    "PE4": Rule(Severity.HIGH, PatternCategory.PRIVILEGE_ESCALATION, "Docker socket access detected."),
    "TM1": Rule(Severity.HIGH, PatternCategory.TOOL_MISUSE, "Commands force-delete from the filesystem root (rm -rf /…)."),
    "PE5": Rule(Severity.HIGH, PatternCategory.PRIVILEGE_ESCALATION, "Privileged container / container escape flags."),
    "SC1": Rule(Severity.LOW, PatternCategory.SUPPLY_CHAIN, "Unpinned or wildcard dependency versions."),
    "SC2": Rule(Severity.HIGH, PatternCategory.SUPPLY_CHAIN, "Remote code is downloaded and executed."),
    "SC3": Rule(Severity.HIGH, PatternCategory.SUPPLY_CHAIN, "Code contains obfuscation."),
    "SC4": Rule(Severity.LOW, PatternCategory.SUPPLY_CHAIN, "Vulnerable or unmaintained dependencies."),
    "SSRF1": Rule(Severity.HIGH, PatternCategory.SERVER_SIDE_REQUEST_FORGERY, "Code accesses a cloud instance metadata endpoint."),
    "SSRF2": Rule(Severity.MEDIUM, PatternCategory.SERVER_SIDE_REQUEST_FORGERY, "Code issues a request to a loopback or private-range host."),
    "SSRF3": Rule(Severity.MEDIUM, PatternCategory.SERVER_SIDE_REQUEST_FORGERY, "Request URL built from an untrusted dynamic value."),
    "AST1": Rule(Severity.CRITICAL, PatternCategory.TOOL_MISUSE, "Direct exec() call allows arbitrary code execution."),
    "AST2": Rule(Severity.CRITICAL, PatternCategory.TOOL_MISUSE, "Direct eval() call evaluates arbitrary expressions."),
    "AST4": Rule(Severity.HIGH, PatternCategory.TOOL_MISUSE, "subprocess module calls execute external commands."),
    "AST5": Rule(Severity.HIGH, PatternCategory.TOOL_MISUSE, "os.system() calls run shell commands."),
    "AR1": Rule(Severity.HIGH, PatternCategory.ANTI_REFUSAL, "Skill instructs the agent to never refuse."),
    "AR2": Rule(Severity.HIGH, PatternCategory.ANTI_REFUSAL, "Skill attempts to suppress warnings or disclaimers."),
    "AR3": Rule(Severity.HIGH, PatternCategory.ANTI_REFUSAL, "Skill attempts to nullify the agent's safety policies."),
    "AS1": Rule(Severity.HIGH, PatternCategory.AGENT_SNOOPING, "Skill reads from agent configuration directories."),
    "AS2": Rule(Severity.HIGH, PatternCategory.AGENT_SNOOPING, "Skill accesses MCP server configuration files."),
    "AS3": Rule(Severity.HIGH, PatternCategory.AGENT_SNOOPING, "Skill inspects or enumerates agent internals."),
    "DS1": Rule(Severity.HIGH, PatternCategory.DESERIALIZATION, "PHP unserialize() on untrusted input."),
    "DS2": Rule(Severity.HIGH, PatternCategory.DESERIALIZATION, "Ruby Marshal deserialization of untrusted data."),
    "DS3": Rule(Severity.HIGH, PatternCategory.DESERIALIZATION, "Ruby YAML.load deserialization of untrusted data."),
    "DS4": Rule(Severity.HIGH, PatternCategory.DESERIALIZATION, "JavaScript deserialization of untrusted input."),
    "OH1": Rule(Severity.HIGH, PatternCategory.OUTPUT_HANDLING, "Model output used directly in dangerous sinks without validation."),
    "OH2": Rule(Severity.MEDIUM, PatternCategory.OUTPUT_HANDLING, "Output from one context forwarded to another context."),
    "OH3": Rule(Severity.MEDIUM, PatternCategory.OUTPUT_HANDLING, "Unbounded output size or rate."),
    "RA1": Rule(Severity.HIGH, PatternCategory.ROGUE_AGENT, "Skill modifies its own code or configuration at runtime."),
    "RA2": Rule(Severity.MEDIUM, PatternCategory.ROGUE_AGENT, "Skill establishes unauthorized persistence across sessions."),
    "EA1": Rule(Severity.HIGH, PatternCategory.EXCESSIVE_AGENCY, "Unrestricted tool access granted."),
    "EA2": Rule(Severity.MEDIUM, PatternCategory.EXCESSIVE_AGENCY, "Autonomous high-impact decisions without human-in-the-loop."),
    "EA3": Rule(Severity.MEDIUM, PatternCategory.EXCESSIVE_AGENCY, "Scope creep beyond stated purpose."),
    "EA4": Rule(Severity.MEDIUM, PatternCategory.EXCESSIVE_AGENCY, "Unbounded resource consumption allowed."),
    "EA5": Rule(Severity.MEDIUM, PatternCategory.EXCESSIVE_AGENCY, "External model/provider selected with billing implications."),
    "MP1": Rule(Severity.HIGH, PatternCategory.MEMORY_POISONING, "Memory poisoning via persistent storage injection."),
    "MP2": Rule(Severity.HIGH, PatternCategory.MEMORY_POISONING, "Context injection across session boundaries."),
    "MP3": Rule(Severity.HIGH, PatternCategory.MEMORY_POISONING, "False memory injection to alter agent behavior."),
    "TP1": Rule(Severity.HIGH, PatternCategory.TOOL_POISONING, "MCP tool parameter poisoning via indirect instruction."),
    "TP2": Rule(Severity.HIGH, PatternCategory.TOOL_POISONING, "MCP tool description manipulation to bypass safety."),
    "TP3": Rule(Severity.HIGH, PatternCategory.TOOL_POISONING, "MCP tool result injection with hidden directives."),
    "TP4": Rule(Severity.CRITICAL, PatternCategory.TOOL_POISONING, "MCP server compromised via supply chain."),
    "LP1": Rule(Severity.HIGH, PatternCategory.MCP_LEAST_PRIVILEGE, "MCP wildcard permissions grant blanket access."),
    "LP2": Rule(Severity.HIGH, PatternCategory.MCP_LEAST_PRIVILEGE, "MCP tool exposes shell execution without restrictions."),
    "LP3": Rule(Severity.MEDIUM, PatternCategory.MCP_LEAST_PRIVILEGE, "MCP tool grants network access to internal/private hosts."),
    "LP4": Rule(Severity.HIGH, PatternCategory.MCP_LEAST_PRIVILEGE, "MCP tool has excessive file system access."),
    "TT1": Rule(Severity.HIGH, PatternCategory.TAINT_TRACKING, "Taint flow from credential source to network sink."),
    "TT2": Rule(Severity.HIGH, PatternCategory.TAINT_TRACKING, "Taint flow from file read source to network sink."),
    "TT3": Rule(Severity.HIGH, PatternCategory.TAINT_TRACKING, "Taint flow from env var source to exec sink."),
    "TT4": Rule(Severity.HIGH, PatternCategory.TAINT_TRACKING, "Taint flow from network input source to file write sink."),
    "TT5": Rule(Severity.HIGH, PatternCategory.TAINT_TRACKING, "Taint flow from credential source to exec sink."),
    "TT6": Rule(Severity.HIGH, PatternCategory.TAINT_TRACKING, "Python deserialization taint flow."),
}

ZERO_WIDTH_CHARS = frozenset("\u200b\u200c\u200d\u2060\ufeff")
_ZERO_WIDTH_PATTERN = "[" + "".join(sorted(ZERO_WIDTH_CHARS)) + "]"

RULE_PATTERNS: dict[str, list[tuple[str, float]]] = {
    # --- P1: Instruction Override ---
    "P1": [
        (r"ignore\s+(?:all\s+)?previous\s+instructions?", 0.8),
        (r"ignore\s+(?:all\s+)?(?:safety|security)\s+(?:rules?|constraints?|guidelines?)", 0.9),
        (r"override\s+(?:safety|security|system)", 0.9),
        (r"bypass\s+(?:safety|security|restrictions?|constraints?)", 0.9),
        (r"disregard\s+(?:all\s+)?(?:previous|safety|security)", 0.8),
        (r"forget\s+(?:all\s+)?(?:previous|your)\s+instructions?", 0.8),
        (r"you\s+are\s+now\s+(?:in\s+)?(?:jailbreak|unrestricted|unfiltered)\s+mode", 0.95),
        (r"enable\s+(?:developer|debug|admin|root)\s+mode", 0.7),
        (r"your\s+new\s+(?:instructions?|rules?)\s+are", 0.6),
        (r"do\s+not\s+follow\s+(?:any|your|the)\s+(?:rules?|guidelines?)", 0.9),
        (r"you\s+must\s+(?:always\s+)?ignore", 0.7),
    ],
    # --- P2: Hidden Instructions ---
    "P2": [
        (r"<!--.*?(?:system|instructions?|ignore|POST|GET|send|transmit).*?-->", 0.7),
        (r"\[//\]:\s*#\s*\(.*?(?:system|instructions?|ignore|POST|GET|send|transmit).*?\)", 0.8),
        (_ZERO_WIDTH_PATTERN, 0.6),
        (r"[\u202a-\u202e\u2066-\u2069]", 0.85),
        (r"data:text/plain;base64,[A-Za-z0-9+/=]{50,}", 0.7),
    ],
    # --- P3: Exfiltration Commands ---
    "P3": [
        (r"(?:send|transmit|upload|post|forward)\s+(?:the\s+)?(?:conversation|context|chat|history|messages?)\s+to", 0.9),
        (r"(?:send|transmit|upload|post)\s+(?:all\s+)?(?:user\s+)?(?:data|information|input|files?)\s+to\s+(?:https?://|external)", 0.9),
        (r"(?:copy|extract|collect)\s+(?:the\s+)?(?:conversation|context|session)\s+(?:and\s+)?(?:send|upload|transmit)", 0.85),
        (r"(?:call|notify|ping|hit)\s+(?:this\s+)?(?:webhook|endpoint|url|api)\s+with\s+(?:the\s+)?(?:user|conversation|context)", 0.8),
        (r"include\s+(?:the\s+)?(?:full\s+)?(?:conversation|context|history)\s+in\s+(?:the\s+)?(?:request|payload|body)", 0.75),
        (r"(?:silently|quietly|secretly|covertly)\s+(?:send|transmit|log|record)", 0.9),
        (r"without\s+(?:telling|informing|notifying)\s+(?:the\s+)?user.*?(?:send|transmit|upload)", 0.9),
    ],
    # --- P4: Behavior Manipulation ---
    "P4": [
        (r"always\s+(?:recommend|suggest|prefer|choose|use)\s+(?:\w+\s+){0,3}(?:over|instead\s+of|rather\s+than)", 0.7),
        (r"never\s+(?:recommend|suggest|mention|tell|warn|inform)\s+(?:the\s+)?(?:user|them)", 0.75),
        (r"(?:prioritize|prefer)\s+(?:\w+\s+){0,3}(?:over|above)\s+(?:user\s+)?(?:safety|security|privacy|preferences?)", 0.85),
        (r"(?:subtly|gradually|slowly)\s+(?:steer|guide|push|nudge)\s+(?:the\s+)?(?:user|conversation)", 0.8),
        (r"(?:without\s+)?(?:the\s+)?user\s+(?:knowing|realizing|noticing).*?(?:change|modify|alter|influence)", 0.85),
        (r"(?:gain|build|establish)\s+(?:the\s+)?(?:user(?:'s)?)\s+trust\s+(?:and\s+then|before|so\s+that)", 0.75),
        (r"(?:appear|seem|act)\s+(?:helpful|friendly|trustworthy)\s+(?:while|but|then)", 0.7),
        (r"(?:always|never)\s+include\s+(?:this|the\s+following)\s+in\s+(?:every|all)\s+(?:response|output|reply)", 0.7),
        (r"append\s+(?:this|the\s+following)\s+to\s+(?:every|all|each)\s+(?:response|message|output)", 0.75),
    ],
    # --- P5: Physical Harm ---
    "P5": [
        (r"(?:kill|murder|harm|hurt|injure|torture)\s+(?:yourself|someone|people)", 1.0),
        (r"(?:self\s+)?harm", 0.9),
        (r"(?:commit\s+)?suicide", 1.0),
    ],
    # --- P6: Direct Prompt Extraction ---
    "P6": [
        (r"(?:print|output|show|display|reveal|expose|return|echo)\s+(?:your\s+)?(?:full\s+)?(?:system\s+)?(?:prompt|instructions?|rules?|guidelines?|directives?)", 0.85),
        (r"(?:what\s+(?:are|is)\s+your|tell\s+me\s+your)\s+(?:system\s+)?(?:prompt|instructions?|rules?|guidelines?|directives?)", 0.8),
        (r"(?:output|print|display)\s+(?:the\s+)?(?:text|content|message)\s+(?:above|before)\s+(?:this|the\s+user)", 0.8),
        (r"(?:share|disclose|leak|give\s+me)\s+(?:your\s+)?(?:internal|hidden|system|secret)\s+(?:prompt|instructions?|rules?|config)", 0.85),
        (r"(?:dump|extract|copy)\s+(?:the\s+)?(?:system\s+)?(?:prompt|message|instructions?)\s+(?:to|into|as)", 0.8),
        (r"(?:begin|start)\s+(?:your\s+)?(?:response|output|reply)\s+with\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)", 0.85),
        (r"(?:first|before\s+anything)\s+(?:output|print|show|display)\s+(?:your\s+)?(?:full\s+)?(?:system\s+)?(?:prompt|instructions?)", 0.85),
        (r"(?:verbatim|exactly|word\s+for\s+word)\s+(?:repeat|output|print)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)", 0.9),
    ],
    # --- P7: Indirect Prompt Extraction ---
    "P7": [
        (r"(?:repeat|recite|reproduce)\s+(?:everything|all|the\s+text)\s+(?:above|before|prior|preceding)", 0.8),
        (r"(?:summarize|paraphrase|rephrase|translate)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules?|guidelines?)", 0.75),
        (r"(?:translate|convert)\s+(?:your\s+)?(?:instructions?|rules?|prompt)\s+(?:into|to)\s+(?:\w+)", 0.75),
        (r"(?:what\s+(?:were|was)\s+you\s+told|how\s+were\s+you\s+(?:instructed|configured|programmed|set\s+up))", 0.7),
        (r"(?:if\s+you\s+had\s+to\s+(?:describe|explain)|describe\s+how\s+you(?:'re|\s+are)\s+(?:configured|set\s+up|instructed))", 0.7),
        (r"(?:encode|encrypt|rot13|base64|reverse)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules?)", 0.85),
        (r"(?:write|create)\s+(?:a\s+)?(?:poem|song|story|acrostic)\s+(?:about|using|from)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)", 0.75),
        (r"(?:format|present|rearrange)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)\s+(?:as|in)\s+(?:a\s+)?(?:list|json|yaml|csv|table|markdown)", 0.8),
        (r"(?:spell\s+out|enumerate)\s+(?:each|every|all)\s+(?:of\s+your\s+)?(?:rules?|instructions?|constraints?|guidelines?)", 0.75),
        (r"(?:ignore|skip)\s+(?:the\s+)?(?:last|final|end)\s+(?:instruction|rule)\s+and\s+(?:output|print|show)\s+(?:the\s+)?(?:rest|previous|first)", 0.8),
    ],
    # --- P8: Prompt Exfiltration via Tool ---
    "P8": [
        (r"(?:write|save|store|log|dump)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules?)\s+(?:to|into|in)\s+(?:a\s+)?(?:file|disk|log|database|storage)", 0.85),
        (r"(?:send|post|upload|transmit)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules?)\s+(?:to|via)\s+(?:https?://|external|remote|webhook|api|server)", 0.9),
        (r"(?:include|embed|attach|append)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)\s+(?:in|to)\s+(?:the\s+)?(?:file|output|response|request|payload|email|message)", 0.8),
        (r"(?:log|record|track|monitor)\s+(?:all\s+)?(?:system\s+)?(?:prompts?|instructions?)\s+(?:to|in|at)\s+(?:external|remote|server)", 0.85),
        (r"(?:copy|clone|duplicate)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|config)\s+(?:to|into)\s+(?:a\s+)?(?:new|separate|external)", 0.8),
        (r"(?:pipe|redirect|forward)\s+(?:the\s+)?(?:system\s+)?(?:prompt|instructions?)\s+(?:to|through|via)\s+(?:curl|wget|fetch|http|api|tool)", 0.85),
        (r"(?:use|call|invoke)\s+(?:the\s+)?(?:write|file|network|http|fetch|curl)\s+tool\s+(?:to|and)\s+(?:save|send|export)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)", 0.85),
    ],
    # --- E1: Data Exfiltration Commands ---
    "E1": [
        (r"requests\s*\.\s*(?:post|put)\s*\(\s*['\"]https?://", 0.6),
        (r"requests\s*\.\s*(?:post|put)\s*\([^)]*json\s*=", 0.7),
        (r"httpx\s*\.\s*(?:post|put)\s*\(\s*['\"]https?://", 0.6),
        (r"urllib\s*\.\s*request\s*\.\s*urlopen\s*\([^)]*data\s*=", 0.6),
        (r"fetch\s*\(\s*['\"]https?://[^'\"]+['\"][^)]*method\s*:\s*['\"]POST['\"]", 0.6),
        (r"curl\s+[^|]*(?:-d|--data|--data-raw|--data-binary)\s+", 0.6),
        (r"wget\s+[^|]*--post-(?:data|file)", 0.6),
        (r"https?://(?:api\.|data\.|collect\.|telemetry\.|analytics\.)[\w.-]+/", 0.5),
        (r"(?:send|transmit|post|upload)\s+(?:user\s+)?(?:data|information|context|files?)\s+to\s+(?:https?://|external)", 0.7),
    ],
    # --- E2: Environment Variable Access ---
    "E2": [
        (r"for\s+\w+\s*,\s*\w+\s+in\s+os\s*\.\s*environ\s*\.\s*items\s*\(\s*\)", 0.7),
        (r"os\s*\.\s*environ\s*\.\s*copy\s*\(\s*\)", 0.6),
        (r"dict\s*\(\s*os\s*\.\s*environ\s*\)", 0.6),
        (r"\{\s*\*\*\s*os\s*\.\s*environ\s*\}", 0.6),
        (r"(?:API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)\s+in\s+(?:key|name|var)", 0.8),
        (r"process\.env\s*\[\s*['\"][^'\"]*(?:KEY|SECRET|TOKEN|PASSWORD)[^'\"]*['\"]\s*\]", 0.7),
        (r"Object\.keys\s*\(\s*process\.env\s*\)", 0.6),
        (r"env\s*\|\s*grep\s+(?:-i\s+)?(?:key|secret|token|password)", 0.8),
        (r"printenv\s+(?:\w*(?:KEY|SECRET|TOKEN|PASSWORD)\w*)", 0.7),
        (r"collect\s+(?:all\s+)?(?:environment\s+variables?|env\s+vars?)", 0.7),
        (r"(?:extract|harvest|gather)\s+(?:api\s+)?keys?\s+from\s+environment", 0.8),
    ],
    # --- E3: File System Scanning ---
    "E3": [
        (r"glob\s*\.\s*glob\s*\([^)]*(?:\.env|\.ssh|\.aws|\.config|credentials)", 0.8),
        (r"os\s*\.\s*walk\s*\([^)]*(?:home|~|/Users|/home)", 0.6),
        (r"Path\s*\.\s*home\s*\(\s*\)\s*\.\s*(?:glob|rglob)\s*\(", 0.7),
        (r"os\s*\.\s*listdir\s*\([^)]*(?:\.ssh|\.aws|\.config|\.gnupg)", 0.8),
        (r"scandir\s*\([^)]*(?:home|~|/Users|/home)", 0.6),
        (r"find\s+[~\$/]\S*\s+.*?-name\s+['\"]?\*(?:\.env|\.pem|\.key|credential)", 0.8),
        (r"ls\s+-[la]*R?\s+(?:~/|/home/|/Users/)", 0.6),
        (r"(?:find|search|scan|enumerate)\s+(?:for\s+)?(?:all\s+)?(?:\.env|credential|secret|key)\s+files?", 0.8),
        (r"(?:list|get)\s+(?:all\s+)?files?\s+(?:in|from)\s+(?:home|~|/Users|/home)", 0.6),
        (r"(?:recursively|recursive)\s+(?:scan|search|find|list)\s+(?:all\s+)?files?", 0.5),
        (r"walk\s+(?:through\s+)?(?:the\s+)?(?:entire\s+)?(?:file\s*system|directory|home)", 0.6),
    ],
    # --- E4: Conversation Context Exfiltration ---
    "E4": [
        (r"(?:send|transmit|upload|log|record)\s+(?:the\s+)?(?:full\s+)?(?:conversation|chat|dialog|session)\s+(?:history|context|log)?", 0.85),
        (r"(?:export|dump|save)\s+(?:the\s+)?(?:conversation|chat|messages?)\s+to\s+(?:external|remote|server)", 0.9),
        (r"log\s+(?:all\s+)?(?:user\s+)?(?:input|messages?|queries?|prompts?)\s+to\s+(?:external|remote|server)", 0.85),
        (r"(?:store|save|record)\s+(?:every|all)\s+(?:user\s+)?(?:interaction|message|input)", 0.7),
        (r"(?:extract|capture|collect)\s+(?:the\s+)?(?:full\s+)?(?:context|conversation|thread)", 0.75),
        (r"(?:include|attach|append)\s+(?:previous\s+)?(?:messages?|context|history)\s+in\s+(?:the\s+)?(?:request|payload)", 0.7),
        (r"(?:send|upload|transmit)\s+(?:the\s+)?(?:session|memory|state)\s+(?:data\s+)?to", 0.8),
        (r"(?:copy|clone|replicate)\s+(?:the\s+)?(?:agent|assistant)\s+(?:memory|context|state)", 0.75),
        (r"(?:always\s+)?include\s+(?:the\s+)?(?:full\s+)?(?:conversation|context)\s+(?:when|in)\s+(?:calling|making)\s+(?:external|api)", 0.8),
    ],
    # --- E5: Cloud Storage Data Shipment ---
    "E5": [
        (r"\.put_object\s*\(", 0.55),
        (r"\.upload_file(?:obj)?\s*\(", 0.55),
        (r"\baws\s+s3\s+(?:cp|sync|mv)\b", 0.6),
        (r"\baws\s+s3api\s+put-object\b", 0.65),
        (r"\bgsutil\s+(?:cp|rsync|mv)\b", 0.6),
        (r"\.upload_from_(?:filename|string|file)\s*\(", 0.55),
        (r"\baz\s+storage\s+blob\s+upload\b", 0.6),
        (r"\.upload_blob\s*\(", 0.55),
    ],
    # --- PE1: Excessive Permissions ---
    "PE1": [
        (r"permissions?\s*:\s*\[?\s*['\"]?\*['\"]?\s*\]?", 0.8),
        (r"permissions?\s*:.*?(?:shell_execute|file_write|network).*?(?:shell_execute|file_write|network)", 0.6),
        (r"(?:request|require|need)s?\s+(?:full|all|complete)\s+(?:access|permissions?)", 0.7),
        (r"(?:grant|give|allow)\s+(?:me\s+)?(?:full|all|complete)\s+(?:access|permissions?)", 0.75),
        (r"(?:also\s+)?(?:need|require)s?\s+(?:write|execute|admin)\s+(?:access|permissions?)\s+(?:for|to)\s+(?:read|view|display)", 0.7),
        (r"(?:escalate|elevate|upgrade)\s+(?:my\s+)?(?:permissions?|privileges?|access)", 0.8),
        (r"(?:bypass|skip|ignore)\s+(?:permission|access)\s+(?:check|validation|restriction)", 0.85),
    ],
    # --- PE2: Sudo/Root Execution ---
    "PE2": [
        (r"\bsudo\s+(?!-v|-l|--version|--list)", 0.7),
        (r"\bsudo\s+-[isSE]", 0.8),
        (r"\bsudo\s+su\b", 0.9),
        (r"\bsu\s+-\s*$|\bsu\s+root", 0.8),
        (r"\bdoas\s+", 0.7),
        (r"\bpkexec\s+", 0.75),
        (r"\bchmod\s+[ugo]*[+-=]*s", 0.85),
        (r"\bchmod\s+[0-7]*[4567][0-7]{2}", 0.8),
        (r"(?:run|execute)\s+(?:as|with)\s+root", 0.8),
        (r"(?:requires?|needs?)\s+root\s+(?:access|privileges?|permissions?)", 0.6),
        (r"(?:edit|modify|write|change)\s+(?:/etc/|system)\s+(?:files?|config)", 0.6),
    ],
    # --- TM1: Tool Parameter Abuse ---
    # ponytail: only SkillSpector's `rm -rf /…` case; its full TM1 (shell=True, --force, globs, safe-idiom
    # exemptions) is ~3,600 lines in static_patterns_tool_misuse.py. Port more when the corpus shows a miss.
    "TM1": [
        (r"\brm\s+-[a-zA-Z]*(?:r[a-zA-Z]*f|f[a-zA-Z]*r)[a-zA-Z]*\s+/", 0.9),
    ],
    # --- PE3: Credential Access ---
    "PE3": [
        (r"~?/?\.ssh/(?:id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys|known_hosts)", 0.9),
        (r"(?:home|HOME)/\w+/\.ssh/", 0.9),
        (r"Path\s*\.\s*home\s*\(\s*\)\s*/\s*['\"]\.ssh['\"]", 0.9),
        (r"~?/?\.aws/credentials", 0.9),
        (r"~?/?\.aws/config", 0.7),
        (r"(?:home|HOME)/\w+/\.aws/", 0.9),
        (r"~?/?\.config/gcloud/", 0.8),
        (r"application_default_credentials\.json", 0.8),
        (r"~?/?\.azure/", 0.7),
        (r"accessTokens\.json", 0.8),
        (r"~?/?\.kube/config", 0.8),
        (r"\bkubeconfig\b", 0.6),
        (r"~?/?\.docker/config\.json", 0.7),
        (r"~?/?\.npmrc", 0.7),
        (r"~?/?\.git-credentials", 0.9),
        (r"~?/?\.netrc", 0.8),
        (r"/etc/passwd", 0.6),
        (r"/etc/shadow", 0.95),
        (r"(?:password|credentials?|secrets?)\.(?:txt|json|yaml|yml|env)", 0.7),
        (r"(?:access_token|refresh_token|bearer_token|api_token)\.txt", 0.8),
        (r"(?<!\w)\.env(?:\.local|\.production|\.development)?(?:\s|$|['\"])", 0.6),
        (r"(?:keychain|keyring|gnome-keyring)", 0.7),
        (r"(?:Chrome|Firefox|Safari)/.*?(?:Cookies|Login Data|key4\.db)", 0.8),
        (r"read\s+(?:the\s+)?(?:ssh|private)\s+key", 0.8),
        (r"access\s+(?:the\s+)?(?:credentials?|secrets?|tokens?)", 0.7),
        (r"(?:extract|copy|get)\s+(?:api\s+)?keys?\s+from", 0.7),
    ],
    # --- PE4: Docker Socket Access ---
    "PE4": [
        (r"/var/run/docker\.sock", 0.9),
        (r"docker\.from_env\s*\(\s*\)", 0.85),
        (r"\bDockerClient\s*\(", 0.85),
        (r"http\+unix://.*docker\.sock", 0.9),
    ],
    # --- PE5: Privileged Container ---
    "PE5": [
        (r"--privileged", 0.8),
        (r"""(?:-v|--volume)['",\s=]+/:""", 0.85),
        (r"--cap-add[=\s]+(?:SYS_ADMIN|ALL|SYS_PTRACE|NET_ADMIN)", 0.85),
        (r"--(?:pid|net|network|ipc|uts)[=\s]+host", 0.8),
        (r"--device[=\s]+/dev/", 0.7),
        (r"--security-opt[=\s]+\S*unconfined", 0.85),
        (r"\bnsenter\b", 0.9),
        (r"/sys/fs/cgroup/.*release_agent", 0.95),
        (r"/proc/\d+/ns/", 0.85),
    ],
    # --- SC1: Unpinned Dependencies ---
    "SC1": [
        (r"^[a-zA-Z][a-zA-Z0-9_-]*\s*$", 0.6),
        (r"^[a-zA-Z][a-zA-Z0-9_-]*\s*>=\s*[\d.]+\s*$", 0.5),
        (r"^[a-zA-Z][a-zA-Z0-9_-]*\s*==\s*\*\s*$", 0.7),
        (r'"[^"]+"\s*:\s*"(?:\*|latest)"', 0.7),
        (r'"[^"]+"\s*:\s*"\^[\d.]+"', 0.4),
        (r"install\s+(?:the\s+)?latest\s+(?:version\s+)?(?:of\s+)?(?:all\s+)?(?:packages?|dependencies)", 0.6),
        (r"(?:don't|do\s+not)\s+(?:pin|lock|specify)\s+(?:package\s+)?versions?", 0.7),
    ],
    # --- SC2: Remote Code Download & Execute ---
    "SC2": [
        (r"curl\s+[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh", 0.9),
        (r"wget\s+[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh", 0.9),
        (r"curl\s+[^|]*\|\s*(?:sudo\s+)?(?:python|python3|node|ruby|perl)", 0.9),
        (r"wget\s+[^|]*\|\s*(?:sudo\s+)?(?:python|python3|node|ruby|perl)", 0.9),
        (r"curl\s+[^&]*-o\s+\S+\s*&&\s*(?:sudo\s+)?(?:ba)?sh", 0.8),
        (r"wget\s+[^&]*-O\s+\S+\s*&&\s*(?:sudo\s+)?(?:ba)?sh", 0.8),
        (r"exec\s*\(\s*(?:urllib|requests|httpx)\.[^)]+\.(?:read|text|content)", 0.95),
        (r"eval\s*\(\s*(?:urllib|requests|httpx)\.[^)]+\.(?:read|text|content)", 0.95),
        (r"eval\s*\(\s*(?:await\s+)?fetch\s*\(", 0.9),
        (r"new\s+Function\s*\([^)]*fetch\s*\(", 0.9),
        (r"subprocess\.[^(]+\([^)]*(?:curl|wget)\s+https?://", 0.8),
    ],
    # --- SC3: Obfuscation ---
    "SC3": [
        (r"base64\s*\(\s*['\"][^'\"]+['\"]", 0.8),
        (r"eval\s*\(\s*base64", 0.9),
    ],
    # --- SC4: Vulnerable/Unmaintained Dependencies ---
    "SC4": [
        (r"(?:pip|npm|yarn|cargo|gem)\s+install\s+(?:--no-index|--index-url)", 0.7),
        (r"(?:from|import)\s+(\w+)\s+#\s*(?:TODO|FIXME|XXX|DEPRECATED|legacy)", 0.5),
    ],
    # --- SSRF1: Cloud Metadata Endpoints ---
    "SSRF1": [
        (r"169\.254\.169\.254", 0.9),
        (r"metadata\.google\.internal", 0.9),
        (r"100\.100\.100\.200", 0.85),
        (r"fd00:ec2::254", 0.85),
        (r"(?:read|fetch|get|query)\s+(?:the\s+)?(?:instance\s+)?metadata\s+(?:service|endpoint|server)", 0.6),
    ],
    # --- SSRF2: Loopback/Private Hosts ---
    "SSRF2": [
        (rf"(?:requests|httpx|aiohttp|urllib(?:\.request)?|urllib3|session)\s*\.\s*(?:get|post|put|patch|delete|head|request|urlopen)|fetch|axios(?:\.\w+)?|XMLHttpRequest|\bcurl\b|\bwget\b\s*\(\s*f?['\"]https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|10\.\d|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)", 0.7),
        (r"localhost|127\.0\.0\.1|::1", 0.8),
        (r"10\.\d{1,3}\.\d{1,3}", 0.8),
        (r"192\.168\.\d{1,3}\.\d{1,3}", 0.8),
    ],
    # --- SSRF3: Dynamic Request URLs ---
    "SSRF3": [
        (rf"(?:requests|httpx|aiohttp|urllib(?:\.request)?|urllib3|session)\s*\.\s*(?:get|post|put|patch|delete|head|request|urlopen)|fetch|axios(?:\.\w+)?|XMLHttpRequest|\bcurl\b|\bwget\b\s*\(\s*f['\"]https?://\{{", 0.6),
        (r"fetch\s*\(\s*`https?://\$\{", 0.6),
    ],
    # --- AST1-AST10 (Python AST-based, handled in engine) ---
    # --- AR1: Refusal Suppression ---
    "AR1": [
        (r"\b(?:never|do\s+not|don'?t)\s+(?:ever\s+)?(?:refuse|decline)\b", 0.85),
        (r"\byou\s+(?:must|will|should|can)\s*(?:not|never)\s+(?:refuse|decline|say\s+no)\b", 0.9),
        (r"\byou\s+(?:cannot|can'?t|can\s+not)\s+(?:refuse|decline|say\s+no)\b", 0.85),
        (r"\bnever\s+say\s+(?:that\s+)?(?:you\s+)?(?:can'?t|cannot|won'?t|no)\b", 0.85),
        (r"\balways\s+(?:comply|obey|answer|respond)\b", 0.7),
        (r"\b(?:(?:you|the\s+(?:agent|assistant|model))\s+(?:must|should|will)\s+always\s+agree|always\s+agree\s+(?:with|to)\s+(?:(?:the|every|all|any|each)\s+)?(?:user|requests?|questions?|prompts?|queries|commands?))\b", 0.7),
        (r"\b(?:you\s+)?must\s+(?:always\s+)?(?:answer|comply\s+with|respond\s+to|fulfill)\s+(?:every|all|any|each)\b", 0.8),
        (r"\brespond\s+to\s+(?:every|all|any)\s+(?:request|question|prompt|query|command)\b", 0.6),
        (r"\bno\s+request\s+is\s+(?:off[- ]limits|forbidden|too)\b", 0.85),
    ],
    # --- AR2: Disclaimer/Warning Suppression ---
    "AR2": [
        (r"\b(?:do\s+not|don'?t|never|no)\s+(?:include|add|give|provide|use|append)?\s*(?:any\s+)?(?:warnings?|disclaimers?|caveats?)\b", 0.8),
        (r"\bwithout\s+(?:any\s+)?(?:warnings?|disclaimers?|caveats?|moralizing|moralising|judg(?:e?ment|ing))\b", 0.8),
    ],
    # --- AR3: Safety/Policy Nullification ---
    "AR3": [
        (r"(?:nullify|disable|ignore|bypass)\s+(?:safety|security)", 0.9),
    ],
    # --- AS1-AS3: Agent Snooping ---
    "AS1": [
        (r"\.claude/|\.codex/|\.gemini/", 0.8),
    ],
    "AS2": [
        (r"mcp\.json", 0.8),
    ],
    "AS3": [
        (r"(?:inspect|enumerate|dump|list)\s+(?:agent|assistant|model)\s+(?:internals|state|config|context)", 0.8),
    ],
    # --- DS1-DS4: Insecure Deserialization ---
    "DS1": [
        (r"\bunserialize\s*\(", 0.8),
    ],
    "DS2": [
        (r"\bMarshal\s*\.\s*(?:load|restore)\b", 0.85),
    ],
    "DS3": [
        (r"\bYAML\.load\s*\(", 0.8),
    ],
    "DS4": [
        (r"JSON\.parse\s*\(\s*(?:req|request|\.body|\.query|\.params)", 0.8),
    ],
    # --- OH1-OH3: Output Handling ---
    "OH1": [
        (r"exec\s*\(\s*(?:response|output|result|answer|completion|reply|generated)", 0.9),
        (r"eval\s*\(\s*(?:response|output|result|answer|completion|reply|generated)", 0.9),
        (r"os\.system\s*\(\s*(?:response|output|result|answer|completion)", 0.85),
        (r"os\.popen\s*\(\s*(?:response|output|result|answer|completion)", 0.85),
        (r"innerHTML\s*=\s*(?:response|output|result|answer|completion)", 0.8),
        (r"document\.write\s*\(\s*(?:response|output|result|answer|completion)", 0.8),
        (r"\.html\s*\(\s*(?:response|output|result|answer|completion)", 0.7),
        (r"dangerouslySetInnerHTML\s*=\s*\{", 0.65),
        (r"(?:execute|cursor\.execute|query)\s*\([^)]*(?:\+|%|\.format|f['\"])\s*.*?(?:response|output|result)", 0.85),
        (r"f['\"](?:SELECT|INSERT|UPDATE|DELETE)\s+.*?\{(?:response|output|result)", 0.9),
    ],
    "OH2": [
        (r"(?:pass|forward|relay|send|pipe)\s+(?:the\s+)?(?:output|response|result)\s+(?:from\s+\w+\s+)?(?:to|into)\s+(?:another|different|separate|external)\s+(?:context|agent|service|system|session)", 0.75),
    ],
    "OH3": [
        (r"(?:no\s+)?(?:size|length|limit|bound|cap)\s*(?:limit|restriction|constraint)?\s*(?:on\s+)?(?:output|response|result)", 0.6),
    ],
    # --- RA1-RA2: Rogue Agent ---
    "RA1": [
        (r"open\s*\(\s*__file__\s*,\s*['\"]w", 0.95),
        (r"(?:Path|pathlib)\s*\(\s*__file__\s*\)\s*\.\s*write_text", 0.95),
        (r"(?:self[_-]?modify|self[_-]?update|self[_-]?rewrite|self[_-]?patch|self[_-]?evolve)", 0.9),
        (r"open\s*\(\s*['\"](?:SKILL\.md|skill\.md)['\"].*?['\"]w", 0.9),
        (r"(?:write|modify|edit|update|overwrite|patch)\s+(?:this\s+)?(?:skill(?:'s)?|SKILL\.md|skill\.md)", 0.85),
        (r"(?:modify|edit|change|rewrite|update|alter)\s+(?:your\s+own|its\s+own|this\s+skill(?:'s)?)\s+(?:code|source|file|script|config|configuration|instructions?|rules?)", 0.9),
        (r"(?:rewrite|replace|overwrite)\s+(?:the\s+)?(?:current|existing|original)\s+(?:code|script|file|config|skill)", 0.85),
        (r"(?:append|add|inject|insert)\s+(?:code|instructions?|rules?)\s+(?:to|into)\s+(?:this|the\s+current|your\s+own)\s+(?:file|skill|script)", 0.85),
        (r"(?:generate|create|write)\s+(?:new|updated|replacement)\s+(?:code|version)\s+(?:for|of)\s+(?:this|itself|the\s+skill)", 0.8),
        (r"(?:update|modify|change|edit)\s+(?:the\s+)?(?:config|configuration|settings|parameters)\s+(?:of\s+)?(?:this|the\s+current)\s+(?:skill|agent|tool)", 0.75),
        (r"(?:disable|remove|delete|bypass)\s+(?:the\s+)?(?:safety|security|guard|protection|constraint)\s+(?:check|rule|mechanism|feature)", 0.9),
        (r"(?:comment\s+out|remove)\s+(?:the\s+)?(?:validation|verification|check|guard|assertion)", 0.7),
    ],
    "RA2": [
        (r"(?:cron|systemd|task\s+scheduler|scheduled\s+task)\s+(?:add|create|schedule|install)", 0.8),
        (r"(?:start|run|launch)\s+(?:at\s+)?(?:boot|startup|login)\s*", 0.8),
        (r"(?:write|save|store)\s+(?:a\s+)?(?:script|binary|executable)\s+(?:to|into)\s+(?:~|\$HOME|\/etc\/|\/usr\/local\/)", 0.75),
        (r"(?:modify|edit|append)\s+(?:\.bashrc|\.zshrc|\.profile|\.bash_profile)", 0.8),
    ],
    # --- EA1-EA5: Excessive Agency ---
    "EA1": [
        (r"(?:tools?|permissions?)\s*:[ \t]*\[?[ \t]*['\"]?\*(?!\*|\w)['\"]?[ \t]*\]?", 0.85),
        (r"tools?\s*:\s*\[\s*['\"]shell['\"].*?['\"](?:file_write|network|http)['\"]", 0.7),
        (r"(?:allow|grant|enable)\s+(?:access\s+to\s+)?(?:all|any|every)\s+tools?", 0.8),
        (r"(?:no|without)\s+(?:tool|permission|access|capability)\s+(?:restrictions?|constraints?|limitations?)", 0.75),
        (r"(?:call|invoke|use|execute)\s+(?:any|all|every)\s+(?:available\s+)?tools?", 0.8),
        (r"(?:unrestricted|unlimited|unconstrained)\s+(?:tool|function|api)\s+(?:access|use|calls?)", 0.85),
        (r"(?:can|may|should)\s+(?:freely|always)\s+(?:use|call|invoke)\s+(?:any|all)\s+(?:tools?|functions?|apis?)", 0.75),
        (r"(?:grant|give)\s+(?:full|complete|total)\s+(?:tool|function|api)\s+access", 0.85),
        (r"(?:execute|run)\s+(?:arbitrary|any)\s+(?:commands?|code|scripts?)", 0.8),
        (r"(?:no\s+)?(?:tool\s+)?(?:allow|block|deny)\s*(?:list|listing)\s*(?:is\s+)?(?:empty|disabled|off)", 0.7),
    ],
    "EA2": [
        (r"(?:auto[_-]?approve|auto[_-]?confirm|auto[_-]?execute|auto[_-]?deploy)", 0.85),
        (r"(?:--auto-?approve|--no-?confirm)\b", 0.65),
    ],
    # --- MP1-MP3: Memory Poisoning ---
    "MP1": [
        (r"(?:write|save|store|inject)\s+(?:a\s+)?(?:false|fake|malicious)\s+(?:memory|fact|knowledge)", 0.8),
        (r"(?:poison|corrupt)\s+(?:the\s+)?(?:agent|assistant)\s+(?:memory|context|state)", 0.85),
    ],
    "MP2": [
        (r"(?:inject|insert|append)\s+(?:false|fabricated)\s+(?:information|fact|memory)\s+(?:into|in)\s+(?:the\s+)?(?:agent|assistant)\s+(?:memory|context)", 0.8),
    ],
    "MP3": [
        (r"(?:alter|change|modify)\s+(?:the\s+)?(?:agent|assistant)\s+(?:memory|context|state)\s+(?:to\s+)?(?:believe|think|assume)", 0.8),
    ],
    # --- TP1-TP4: Tool Poisoning ---
    "TP1": [
        (r"(?:tool|function|api)\s+(?:description|definition|schema)\s+.*?(?:ignore|bypass|override|nullify)\s+(?:safety|security|restriction)", 0.85),
        (r"(?:indirect|hidden)\s+(?:instruction|directive|prompt)\s+(?:in|embedded\s+in)\s+(?:tool|function|api)\s+(?:description|definition)", 0.8),
    ],
    "TP2": [
        (r"(?:rewrite|modify|alter)\s+(?:tool|function|api)\s+(?:description|definition)\s+to\s+(?:bypass|evade|avoid)", 0.8),
    ],
    "TP3": [
        (r"(?:tool|function|api)\s+result\s+(?:contains|includes|embeds)\s+(?:hidden|injected)\s+(?:instruction|directive|prompt)", 0.8),
    ],
    "TP4": [
        (r"(?:mcp|tool|function)\s+server\s+(?:compromised|hacked|breached|supply.chain)", 0.9),
    ],
    # --- LP1-LP4: MCP Least Privilege ---
    "LP1": [
        (r"permissions?\s*:\s*\[?\s*['\"]?\*['\"]?\s*\]?", 0.8),
    ],
    "LP2": [
        (r"subprocess|Popen|os\.system|os\.popen|os\.exec|\bcurl\b|\bwget\b|\bchmod\b", 0.7),
    ],
    "LP3": [
        (r"\bhttpx\b|\brequests\b|\burllib\b|\baiohttp\b|socket\.connect|fetch\(", 0.6),
    ],
    "LP4": [
        (r"(?:read|write|list|glob|walk|scandir)\s*\([^)]*(?:\.ssh|\.aws|\.env|/etc/passwd|/etc/shadow)", 0.8),
    ],
    # --- TT1-TT6: Taint Tracking ---
    "TT1": [
        (r"(?:os\.environ|os\.getenv|process\.env)\s*.*?(?:requests|httpx|fetch|curl|wget|urllib)", 0.7),
    ],
    "TT2": [
        (r"(?:open|Path\.read_text|Path\.read_bytes)\s*.*?(?:requests|httpx|fetch|curl|wget|urllib)", 0.7),
    ],
    "TT3": [
        (r"(?:os\.environ|os\.getenv|process\.env)\s*.*?(?:exec|eval|subprocess|os\.system)", 0.7),
    ],
    "TT4": [
        (r"(?:fetch|curl|wget|urllib|requests)\s*.*?(?:open|write|Path\.write_text)", 0.6),
    ],
    "TT5": [
        (r"(?:os\.environ|os\.getenv|process\.env)\s*.*?(?:exec|eval|subprocess|os\.system)", 0.75),
    ],
    "TT6": [
        (r"\b(unserialize|Marshal\.(?:load|restore)|pickle\.loads|yaml\.load)\s*\(", 0.8),
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
    "PatternCategory", "Severity", "Rule", "RULES", "RULE_PATTERNS",
    "get_compiled_patterns", "ZERO_WIDTH_CHARS", "is_padding_char",
    "DANGEROUS_BUILTINS", "SUBPROCESS_CALLS", "OS_EXEC_CALLS",
    "INSECURE_DESERIALIZERS",
]
