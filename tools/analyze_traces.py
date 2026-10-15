"""DIAGNOSTIC ONLY, throwaway. Not imported by Clyde, not part of the test suite, standard library only.

Reads Clyde trace files (~/.clyde/traces/*.jsonl) and prints one block per file about prefill against decode, to
decide whether persistent KV caching is worth building. Run: python3 tools/analyze_traces.py [trace.jsonl ...]
With no arguments it reads the newest trace file.

It only counts model requests that carry prefill_ms and decode_ms (Ollama, since the usage change that records them).
Older traces and other providers are skipped, not an error.

Read the millisecond fields, not the token counts, to judge reuse: Ollama's input_tokens is the whole prompt including
tokens it reused, so in a 3-turn CPU-only test input_tokens grew 79 -> 129 while prefill_ms fell 155 -> 122.
"""
import json
import statistics
import sys
from pathlib import Path

COLD_LOAD_MS = 2000      # a load longer than this makes the turn a cold start
GROWTH = 1.5             # "more than ~50%" for the reuse check
DROP = 0.8               # input_tokens under this share of the previous turn: compaction or a shorter prompt
JUMP = 2.0               # input_tokens over this multiple of the previous turn: a new prefix
MIN_TOKENS = 500         # below this, growth is just a short conversation, not a prefix change


def events(path):
    for line in path.read_text(errors="replace").splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def num(d, key):
    v = (d or {}).get(key)
    return v if isinstance(v, (int, float)) else None


def turns(path):
    """Model requests with timings, each with the number of `compact` events seen since the previous request."""
    out, compacts, skipped = [], 0, 0
    for e in events(path):
        if e.get("event") == "compact":
            compacts += 1
        elif e.get("event") == "model_request":
            u = e.get("usage") or {}
            if num(u, "prefill_ms") is None or num(u, "decode_ms") is None:
                skipped += 1
                continue
            out.append({"in": num(u, "input_tokens") or 0, "out": num(u, "output_tokens") or 0,
                        "pre": u["prefill_ms"], "dec": u["decode_ms"], "load": num(u, "load_ms") or 0,
                        "compacted": compacts, "model": e.get("model")})
            compacts = 0
    return out, skipped


def share(t):
    total = t["pre"] + t["dec"]
    return t["pre"] / total if total else 0.0


def p95(xs):
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def report(path):
    ts, skipped = turns(path)
    print(f"=== {path.name}  ({len(ts)} timed requests, {skipped} without timings skipped)")
    if not ts:
        print("    nothing to analyse\n")
        return
    print("  turn   in_tok  out_tok  prefill_ms  decode_ms  load_ms  share  ttft_ms  note")
    for i, t in enumerate(ts, 1):
        ttft = t["load"] + t["pre"]
        notes = []
        if t["load"] > COLD_LOAD_MS:
            notes.append("COLD START")
        if t["compacted"]:
            notes.append(f"after {t['compacted']} compact")
        print(f"  {i:4d} {t['in']:8d} {t['out']:8d} {t['pre']:11.0f} {t['dec']:10.0f} {t['load']:8.0f} "
              f"{share(t):5.0%} {ttft:8.0f}  {', '.join(notes)}")

    steady = [t for t in ts if t["load"] <= COLD_LOAD_MS]
    for label, group in (("all turns", ts), ("steady state (no cold load)", steady)):
        if group:
            sh = [share(t) for t in group]
            print(f"  {label}: n={len(group)} median share={statistics.median(sh):.0%} p95 share={p95(sh):.0%}")
    print(f"  session totals: prefill {sum(t['pre'] for t in ts) / 1000:.1f}s, decode {sum(t['dec'] for t in ts) / 1000:.1f}s, "
          f"load {sum(t['load'] for t in ts) / 1000:.1f}s")

    flagged = [(i, a, b) for i, (a, b) in enumerate(zip(ts, ts[1:]), 2)
               if a["in"] and a["pre"] and b["in"] > a["in"] * GROWTH and b["pre"] > a["pre"] * GROWTH]
    print("  reuse check (input and prefill_ms both grew >50%, a candidate full re-prefill):",
          ", ".join(f"turn {i} ({a['in']}->{b['in']} tok, {a['pre']:.0f}->{b['pre']:.0f} ms)" for i, a, b in flagged) or "none")

    marks = []
    for i, (a, b) in enumerate(zip(ts, ts[1:]), 2):
        kind = ("compaction or shorter prompt" if a["in"] and b["in"] < a["in"] * DROP else
                "new prefix" if a["in"] and b["in"] > MIN_TOKENS and b["in"] > a["in"] * JUMP else
                "compaction event" if b["compacted"] else "")
        if kind:
            after = ts[i] if i < len(ts) else None
            tail = f"; next turn prefill {after['pre']:.0f} ms ({share(after):.0%})" if after else ""
            marks.append(f"turn {i}: {kind}, in {a['in']}->{b['in']} tok, prefill {b['pre']:.0f} ms ({share(b):.0%}){tail}")
    print("  event markers:", "none" if not marks else "")
    for m in marks:
        print("    " + m)
    print()


def main(argv):
    paths = [Path(a) for a in argv]
    if not paths:
        files = sorted((Path.home() / ".clyde" / "traces").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        paths = files[-1:]
    if not paths:
        print("no trace files found")
        return 1
    for p in paths:
        if p.is_file():
            report(p)
        else:
            print(f"=== {p}: not a file, skipped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
