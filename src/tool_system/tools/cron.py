from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec

# (low, high) for minute, hour, day-of-month, month, day-of-week (0 and 7 are Sunday).
_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        rng, _, step_text = part.partition("/")
        if rng == "*":
            start, end = lo, hi
        elif "-" in rng:
            start_text, end_text = rng.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = int(rng)
            end = hi if step_text else start
        step = int(step_text) if step_text else 1
        if not lo <= start <= end <= hi or step < 1:
            raise ValueError(f"cron field out of range: {part!r}")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> tuple[list[set[int]], bool]:
    """Parse a 5-field cron expression into value sets, plus whether day-of-month and
    day-of-week are both restricted (cron then matches either, not both)."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("cron must have 5 fields: minute hour day-of-month month day-of-week")
    sets = [_parse_field(spec, lo, hi) for spec, (lo, hi) in zip(fields, _FIELD_BOUNDS)]
    if 7 in sets[4]:
        sets[4].add(0)
    return sets, not fields[2].startswith("*") and not fields[4].startswith("*")


def cron_matches(expr: str, when: datetime) -> bool:
    (minute, hour, dom, month, dow), either_day = parse_cron(expr)
    day_hits = (when.day in dom, (when.weekday() + 1) % 7 in dow)
    day_ok = any(day_hits) if either_day else all(day_hits)
    return when.minute in minute and when.hour in hour and when.month in month and day_ok


def pop_due_jobs(crons: dict[str, dict[str, Any]], since: datetime, now: datetime) -> list[dict[str, Any]]:
    """Return jobs matching any minute in (since, now], removing the one-shot ones from `crons`.

    A recurring job fires at most once per call even if several of its minutes passed.
    """
    # ponytail: minute-by-minute scan capped at one day of catch-up; compute next-fire times if gaps grow.
    start = max(since, now - timedelta(days=1)).replace(second=0, microsecond=0)
    minutes = [start + timedelta(minutes=i) for i in range(1, int((now - start).total_seconds() // 60) + 1)]
    due = [job for job in crons.values() if any(cron_matches(job["cron"], m) for m in minutes)]
    for job in due:
        if not job.get("recurring", True):
            crons.pop(job["id"], None)
    return due


class CronCreateTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronCreate",
            description="Schedule a recurring or one-shot prompt (in-memory, session-scoped). It runs while the REPL is idle at the prompt.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "cron": {"type": "string"},
                    "prompt": {"type": "string"},
                    "recurring": {"type": "boolean"},
                    "durable": {"type": "boolean"},
                },
                "required": ["cron", "prompt"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        cron = tool_input.get("cron")
        prompt = tool_input.get("prompt")
        if not isinstance(cron, str) or not cron.strip():
            raise ToolInputError("cron must be a non-empty string")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ToolInputError("prompt must be a non-empty string")
        try:
            parse_cron(cron)
        except ValueError as exc:
            raise ToolInputError(f"invalid cron expression: {exc}") from exc
        recurring = bool(tool_input.get("recurring", True))
        durable = bool(tool_input.get("durable", False))

        cid = uuid.uuid4().hex[:12]
        context.crons[cid] = {"id": cid, "cron": cron, "prompt": prompt, "recurring": recurring, "durable": durable}
        return ToolResult(
            name="CronCreate",
            output={
                "id": cid,
                "humanSchedule": cron,
                "recurring": recurring,
                "durable": durable,
            },
        )


class CronListTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronList",
            description="List scheduled cron jobs.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {}},
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        jobs = list(context.crons.values())
        jobs.sort(key=lambda x: x["id"])
        return ToolResult(name="CronList", output={"jobs": jobs})


class CronDeleteTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronDelete",
            description="Delete a scheduled cron job.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        cid = tool_input.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise ToolInputError("id must be a non-empty string")
        existed = cid in context.crons
        context.crons.pop(cid, None)
        return ToolResult(name="CronDelete", output={"success": existed, "id": cid})

