import os

# The REPL refreshes the repo code map in the background; never from the test suite.
os.environ.setdefault("CLYDE_MAP", "off")
