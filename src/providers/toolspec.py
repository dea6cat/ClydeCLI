"""Canonical tool schema, serialized to each provider's format.

Tools are defined once (name, description, JSON Schema for the input) and every
adapter serializes from here, so the schema never drifts between providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


def from_specs(specs: Iterable[Any]) -> tuple[ToolSpec, ...]:
    """ToolSpecs from anything with name/description/input_schema (the tool registry's specs)."""
    return tuple(ToolSpec(s.name, s.description, s.input_schema) for s in specs)


def _object_schema(schema) -> dict:  # type: ignore[no-untyped-def]
    """Strict servers (LM Studio, OpenAI strict mode) require parameters with type object and a
    properties map, even for a tool that takes nothing."""
    out = dict(schema or {})
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out


def to_openai(specs: tuple[ToolSpec, ...]) -> list[dict]:
    """OpenAI / OpenRouter / Mistral / NVIDIA / DeepSeek / Cerebras / GLM / Ollama / LM Studio shape."""
    return [
        {"type": "function", "function": {
            "name": s.name, "description": s.description, "parameters": _object_schema(s.input_schema),
        }}
        for s in specs
    ]


def to_anthropic(specs: tuple[ToolSpec, ...]) -> list[dict]:
    return [{"name": s.name, "description": s.description, "input_schema": s.input_schema} for s in specs]


def to_gemini(specs: tuple[ToolSpec, ...]) -> list[dict]:
    """One tools entry holding functionDeclarations. Uses parametersJsonSchema, which takes
    full JSON Schema; the older `parameters` field is an OpenAPI subset that rejects
    additionalProperties / oneOf, which ClydeCLI's tool schemas use."""
    if not specs:
        return []
    return [{"functionDeclarations": [
        {"name": s.name, "description": s.description, "parametersJsonSchema": s.input_schema}
        for s in specs
    ]}]
