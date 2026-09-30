import os

# The REPL refreshes the repo code graph in the background; never from the test suite.
os.environ.setdefault("CLYDE_CODE_GRAPH", "off")
