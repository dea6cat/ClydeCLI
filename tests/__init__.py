import atexit
import os
import shutil
import tempfile

# Every test runs against an empty home, never the developer's real ~/.clyde, ~/.claude settings,
# keys, plugins, skills or sessions. Tests that need a specific home still patch Path.home.
_TEST_HOME = tempfile.mkdtemp(prefix="clyde-test-home-")
os.environ["HOME"] = _TEST_HOME
atexit.register(shutil.rmtree, _TEST_HOME, ignore_errors=True)

# The REPL refreshes the repo code map in the background; never from the test suite.
os.environ.setdefault("CLYDE_MAP", "off")

# Session traces go to ~/.clyde/traces; tests enable tracing explicitly under a patched home.
os.environ.setdefault("CLYDE_TRACE", "off")
# Post-edit ruff/mypy checks would run real tools; tests that want them turn them on.
os.environ.setdefault("CLYDE_CHECKS", "off")
# SkillSpector scans would run the real scanner on every skill a test loads; its tests turn it on.
os.environ.setdefault("CLYDE_SKILL_SCAN", "off")
