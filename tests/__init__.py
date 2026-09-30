import os

# The REPL refreshes the repo code map in the background; never from the test suite.
os.environ.setdefault("CLYDE_MAP", "off")

# Post-edit ruff/mypy checks would run real tools; tests that want them turn them on.
os.environ.setdefault("CLYDE_CHECKS", "off")
