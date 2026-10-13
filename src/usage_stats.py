"""Usage numbers for /settings Stats: tokens per day and per model, streaks, and the charts that draw them.

The tokens come from the model_request events in ~/.clyde/traces, the sessions from ~/.clyde/sessions, so
the figures cover this machine only and stop where tracing was off. Everything here is plain data in,
prompt_toolkit fragments out, so tests need no screen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.config import clyde_home

Fragments = list[tuple[str, str]]

RANGES = (("all", "All time"), ("30", "Last 30 days"), ("7", "Last 7 days"))
_DIM = "#8a8a8a"
_SERIES = ("#a8a8ff", "#4eba65", "#e0b341", "#56c2e6", "#d0202f", "#c678dd")
_SHADES = ("#3a3a3a", "#6b3b2c", "#9b4f36", "#c9633f", "#e8794a")   # no tokens .. most tokens in a day


@dataclass(frozen=True)
class Totals:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    def __add__(self, other: Totals) -> Totals:
        return Totals(self.input + other.input, self.output + other.output,
                      self.cache_read + other.cache_read, self.cache_write + other.cache_write)


@dataclass(frozen=True)
class Request:
    day: date
    ref: str
    usage: Totals


@dataclass(frozen=True)
class Session:
    start: datetime
    end: datetime


def compact(n: float) -> str:
    """12, 1.2k, 13.4m, 8.7b."""
    for limit, suffix in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if n >= limit:
            return f"{n / limit:.1f}{suffix}"
    return str(int(n))


def _count(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def load_requests(traces: Path | None = None) -> list[Request]:
    """Every traced model request that reported usage."""
    found = []
    for path in (traces or clyde_home() / "traces").glob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
                usage = event["usage"] if event.get("event") == "model_request" else None
                if not isinstance(usage, dict):
                    continue
                found.append(Request(date.fromisoformat(event["ts"][:10]), f"{event['provider']}:{event['model']}", Totals(
                    _count(usage.get("input_tokens")), _count(usage.get("output_tokens")),
                    _count(usage.get("cache_read_input_tokens")), _count(usage.get("cache_creation_input_tokens")))))
            except (ValueError, KeyError, TypeError):
                continue
    return found


def load_sessions(folder: Path | None = None) -> list[Session]:
    found = []
    for path in (folder or clyde_home() / "sessions").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            start = datetime.fromisoformat(data["created_at"])
            found.append(Session(start, max(start, datetime.fromisoformat(data.get("updated_at") or data["created_at"]))))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return found


def first_day(range_key: str, today: date, requests: list[Request]) -> date:
    """The first day a range covers (the earliest request for all time)."""
    if range_key == "all":
        return min((r.day for r in requests), default=today)
    return today - timedelta(days=int(range_key) - 1)


def by_model(requests: list[Request], since: date) -> list[tuple[str, Totals]]:
    """Totals per model since `since`, the busiest first."""
    sums: dict[str, Totals] = {}
    for r in requests:
        if r.day >= since:
            sums[r.ref] = sums.get(r.ref, Totals()) + r.usage
    return sorted(sums.items(), key=lambda kv: kv[1].total, reverse=True)


def daily(requests: list[Request], ref: str | None, since: date, today: date) -> list[int]:
    """Tokens per day from `since` to `today`, for one model or (None) all of them."""
    days = [0] * ((today - since).days + 1)
    for r in requests:
        if since <= r.day <= today and (ref is None or r.ref == ref):
            days[(r.day - since).days] += r.usage.total
    return days


def _streaks(active: set[date], today: date) -> tuple[int, int]:
    """(longest, current) run of consecutive active days; the current one may end yesterday."""
    longest = run = 0
    for day in sorted(active):
        run = run + 1 if day - timedelta(days=1) in active else 1
        longest = max(longest, run)
    day = today if today in active else today - timedelta(days=1)
    current = 0
    while day in active:
        current, day = current + 1, day - timedelta(days=1)
    return longest, current


@dataclass(frozen=True)
class Overview:
    favorite: str
    sessions: int
    active_days: int
    span_days: int
    longest_session: timedelta
    longest_streak: int
    current_streak: int
    totals: Totals


def overview(requests: list[Request], sessions: list[Session], since: date, today: date) -> Overview:
    chosen = [r for r in requests if r.day >= since]
    in_range = [s for s in sessions if s.start.date() >= since]
    models = by_model(requests, since)
    active = {r.day for r in chosen} | {s.start.date() for s in in_range}
    longest, current = _streaks(active, today)
    return Overview(models[0][0] if models else "none yet", len(in_range), len(active), (today - since).days + 1,
                    max((s.end - s.start for s in in_range), default=timedelta()), longest, current,
                    sum((r.usage for r in chosen), Totals()))


def duration(delta: timedelta) -> str:
    """9d 13h 19m, 2h 5m, 4m."""
    days, rest = divmod(int(delta.total_seconds() // 60), 1440)
    hours, minutes = divmod(rest, 60)
    return " ".join(f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n) or "0m"


def heatmap(requests: list[Request], today: date, weeks: int = 26) -> Fragments:
    """Weeks across, Monday to Sunday down: how many tokens each day used, in five shades."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    per_day = daily(requests, None, start, today)
    top = max(per_day)

    def shade(day: date) -> str:
        used = per_day[(day - start).days]
        return _SHADES[1 + min(3, 4 * (used - 1) // top) if used else 0]

    months, last = [" "] * (2 * weeks + 4), 0
    for w in range(weeks):
        month = (start + timedelta(weeks=w)).month
        if month != last and w * 2 + 3 <= len(months):
            months[w * 2:w * 2 + 3] = date(2000, month, 1).strftime("%b")
        last = month
    out: Fragments = [(f"fg:{_DIM}", "      " + "".join(months).rstrip() + "\n")]
    for row, label in enumerate(("Mon", "", "Wed", "", "Fri", "", "")):
        out.append((f"fg:{_DIM}", f"{label:<6}"))
        for w in range(weeks):
            day = start + timedelta(weeks=w, days=row)
            out.append((f"fg:{shade(day)}", "■ ") if day <= today else ("", "  "))
        out.append(("", "\n"))
    out.append((f"fg:{_DIM}", "      Less "))
    out += [(f"fg:{c}", "■ ") for c in _SHADES[1:]]
    out.append((f"fg:{_DIM}", "More\n"))
    return out


def chart(series: list[tuple[str, list[int]]], since: date, today: date, *, height: int = 8, width: int = 52) -> Fragments:
    """Tokens per day, one coloured line of dots per model: a day takes several columns when there are few, one column groups several days when there are many."""
    days = (today - since).days + 1
    cols = width
    peak = max((max(values) for _, values in series), default=0) or 1
    grid: list[list[tuple[str, str]]] = [[("", " ")] * cols for _ in range(height)]
    for index, (_, values) in enumerate(series):
        for c in range(cols):
            chunk = values[c * days // cols:max(c * days // cols + 1, (c + 1) * days // cols)]
            level = round((height - 1) * max(chunk) / peak)
            grid[height - 1 - level][c] = (f"fg:{_SERIES[index % len(_SERIES)]}", "•")
    out: Fragments = [("bold", "Tokens per Day\n")]
    for r in range(height):
        out.append((f"fg:{_DIM}", f"{compact(peak * (height - 1 - r) / (height - 1)):>6} │"))
        out += grid[r]
        out.append(("", "\n"))
    left, right = since.strftime("%b %d"), today.strftime("%b %d")
    out.append((f"fg:{_DIM}", "       └" + "─" * cols + "\n"))
    out.append((f"fg:{_DIM}", "        " + left + " " * max(1, cols - len(left) - len(right)) + right + "\n"))
    for index, (ref, _) in enumerate(series):
        out += [(f"fg:{_SERIES[index % len(_SERIES)]}", "● "), ("", ref + "  ")]
    out.append(("", "\n"))
    return out
