#!/usr/bin/env python
"""Record SkillSpector's verdicts for the scan corpus into tests/fixtures/scan_baseline.json.

Parity reference for the in-house scanner (docs: plan 'Replace SkillSpector', phase 1).
Run with the skillspector dependency still installed:
    .venv/bin/python scripts/record_scan_baseline.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "scan_corpus"
OUT = ROOT / "tests" / "fixtures" / "scan_baseline.json"
EXE = [str(ROOT / ".venv" / "bin" / "skillspector")]


def scan(folder: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        done = subprocess.run([*EXE, "scan", str(folder.resolve()), "--format", "json",
                               "--output", str(report), "--no-llm"],
                              capture_output=True, text=True, check=False, timeout=300)
        if not report.is_file():
            return {"recommendation": "ERROR", "score": 0, "severity": "",
                    "findings": [f"exited {done.returncode}: {' '.join((done.stderr or done.stdout).split())[:200]}"]}
        data = json.loads(report.read_text(encoding="utf-8"))
        risk = data.get("risk_assessment") or {}
        findings = [f"{i.get('id')} {i.get('severity')}: {str(i.get('finding') or i.get('explanation') or '')[:120]}"
                    for i in data.get("issues") or []]
        return {"recommendation": str(risk.get("recommendation") or "ERROR"),
                "score": int(risk.get("score") or 0),
                "severity": str(risk.get("severity") or ""),
                "findings": findings}


def main() -> int:
    if not (ROOT / ".venv" / "bin" / "skillspector").is_file():
        print("skillspector is not installed in .venv — install it before recording the baseline", file=sys.stderr)
        return 1
    baseline = {}
    for folder in sorted(p for p in CORPUS.iterdir() if p.is_dir()):
        baseline[folder.name] = scan(folder)
        v = baseline[folder.name]
        print(f"{folder.name:22s} {v['recommendation']:14s} {v['score']:3d}  {len(v['findings'])} findings")
    OUT.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {len(baseline)} verdicts to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
