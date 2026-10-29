"""EGRESS.md lists every host the code can reach, so a new network destination cannot be added without telling users."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = re.compile(r"https?://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[a-z]{2,})")


def hosts_in_source() -> dict[str, str]:
    """Every host named in a string in src/, with one file that names it."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        for host in HOST.findall(path.read_text(encoding="utf-8")):
            found.setdefault(host.lower(), str(path.relative_to(ROOT)))
    return found


class TestEgressDoc(unittest.TestCase):
    def setUp(self):
        self.doc = (ROOT / "EGRESS.md").read_text(encoding="utf-8").lower()

    def test_every_host_the_code_names_is_in_the_doc(self):
        missing = {host: where for host, where in hosts_in_source().items() if host not in self.doc}
        self.assertEqual(missing, {}, "add each to EGRESS.md (what is sent, when, how to turn it off) or to its 'printed, not fetched' list")

    def test_the_scan_finds_the_destinations_that_matter(self):
        found = hosts_in_source()
        for host in ("api.anthropic.com", "html.duckduckgo.com", "api.github.com", "huggingface.co", "ollama.com"):
            self.assertIn(host, found, host)

    def test_the_off_switches_the_doc_promises_exist_in_the_code(self):
        source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))
        for switch in ("CLYDE_NO_UPDATE_CHECK", "CLYDE_CLOUD_REVIEW", "CLYDE_SKILL_SCAN", "HF_HUB_OFFLINE"):
            self.assertIn(switch, self.doc.upper(), f"{switch} is not in EGRESS.md")
            self.assertIn(switch, source, f"EGRESS.md promises {switch} but the code never reads it")


if __name__ == "__main__":
    unittest.main()
