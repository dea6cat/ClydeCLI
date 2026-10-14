"""The licence acknowledgment: Clyde asks once, before its first command, that the user accepts the licence terms.

The record lives in Clyde's home folder, so every machine and every user asks once, including an already installed copy the
first time it runs after updating. Raising TERMS_VERSION asks everyone again. This is a click-through record, not copy
protection: the licence itself (LICENSE) is what binds, and anyone with the source can remove this check.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from src.config import clyde_home

LICENSE_NAME = "PolyForm-Noncommercial-1.0.0"
TERMS_VERSION = 1                       # raise it when the licence terms change
ACCEPT_PHRASE = "I accept"
ENV_ACCEPT = "CLYDE_ACCEPT_LICENSE"     # "1" accepts for that run only (CI, editors); nothing is recorded
EXIT_DECLINED = 3
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"

SUMMARY = f"""ClydeCLI is source-available under the PolyForm Noncommercial License 1.0.0.

  - You may use, study, change and share it for noncommercial purposes.
  - Commercial use needs written permission from the author.
  - The software is provided as is, with no warranty.

Full terms: the LICENSE file in the repository, and {LICENSE_URL}"""


def record_path() -> Path:
    return clyde_home() / "license.json"


def is_accepted() -> bool:
    """True when this machine's record is for the current licence and terms version."""
    try:
        data = json.loads(record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("license") == LICENSE_NAME and data.get("terms") == TERMS_VERSION


def record_acceptance() -> None:
    """Write the acceptance record. OSError when the folder cannot be written."""
    from src import __version__
    path = record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "license": LICENSE_NAME, "terms": TERMS_VERSION, "clyde_version": __version__,
        "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")


def ensure_accepted(console: Console) -> bool:
    """True when Clyde may go on: already accepted, accepted for this run through CLYDE_ACCEPT_LICENSE=1, or accepted now by
    typing the phrase. False (with a message saying what to do) otherwise; nothing is recorded then."""
    if is_accepted():
        return True
    if os.environ.get(ENV_ACCEPT) == "1":
        return True
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"ClydeCLI needs you to accept its licence ({LICENSE_NAME}) first. Run `clyde` or `clyde license accept` in a "
              f"terminal, or set {ENV_ACCEPT}=1 to accept for this run.", file=sys.stderr)
        return False
    return prompt_and_record(console)


def prompt_and_record(console: Console) -> bool:
    """Show the terms and take the typed phrase; anything else declines. Never accepts on Enter alone."""
    console.print(SUMMARY, markup=False, highlight=False)
    console.print()
    try:
        answer = input(f"Type '{ACCEPT_PHRASE}' to accept these terms and continue (anything else quits): ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() != ACCEPT_PHRASE.lower():
        console.print("[yellow]Licence not accepted. ClydeCLI will not run.[/yellow]")
        return False
    try:
        record_acceptance()
    except OSError as e:
        console.print(f"[red]Couldn't save your acceptance ({e}). ClydeCLI will not run until it can.[/red]")
        return False
    console.print("[green]Thank you. Accepted; you won't be asked again on this machine.[/green]")
    return True
