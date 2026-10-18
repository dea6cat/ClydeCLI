# Security review, October 2026 — found and fixed

*Research note, 2026-10-08. Manual review with real exploit attempts; an automated scanner could not run that day (see Gotchas in the log). Each item below was reproduced, then fixed, then re-tested.*

SECURITY.md lists what *remains* open. This note lists what was found and closed, because a fixed hole is also knowledge.

## 1. Pre-prompt execution via the project's own tooling

- **Found:** the post-edit check ran **before** the permission dispatch. A planted `.venv/bin/ruff` (or any tool `checks.detect` picked up: `uv run` tools, mypy) executed as the user, **even when the edit itself was denied**.
- **Fix:** unprompted checks use only the user's own ruff on PATH unless the folder is in `trustedFolders` (user settings, never project-controlled). `/check` is unchanged — it runs what you asked for, after a yes.

## 2. Redirect to the private network (SSRF-shaped)

- **Found:** the private-network check ran on the first URL only. A public URL that redirected to `localhost` reached the local server — demonstrated with two real servers.
- **Fix:** redirects re-checked (`_CheckedRedirects`); the connection resolves once, refuses any private answer in the chain, and connects to the checked address — which also closes DNS rebinding (tested by faking `getaddrinfo`). The permission prompt now shows the whole URL, not just the host, because a key can ride in a query string.

## 3. Unprompted secret reads

- **Found:** `cat ~/.clyde/keys.json`, `cat ~/.ssh/id_rsa`, `echo $OPENAI_API_KEY`, `grep -r sk- ~` all ran with no permission prompt, due to a bug in `permission_rules.check_rules`.
- **Fix:** rule evaluation now treats secret paths and secret-shaped output as prompting conditions. Current behavior is visible in SECURITY.md's "What counts" list; `tests/test_egress_doc.py` and the permission tests keep the floor.
