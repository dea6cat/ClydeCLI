import os

# The REPL refreshes the repo code map in the background; never from the test suite.
os.environ.setdefault("CLYDE_MAP", "off")

# Session traces go to ~/.clyde/traces; tests enable tracing explicitly under a patched home.
os.environ.setdefault("CLYDE_TRACE", "off")
# Post-edit ruff/mypy checks would run real tools; tests that want them turn them on.
os.environ.setdefault("CLYDE_CHECKS", "off")
