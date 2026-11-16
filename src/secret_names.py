"""Which names hold secrets: environment variables and fields named like a key, token, password or cookie. Traces
redact their values, and a CLI worker starts without them (it is handed only the one key it needs)."""
from __future__ import annotations

import re

_SECRET_NAME = re.compile(r"api[_-]?key|(api|access|auth|refresh|bearer|session)[_-]?token|^token$|secret|password|passwd|"
                          r"authorization|credential|cookie", re.I)


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))
