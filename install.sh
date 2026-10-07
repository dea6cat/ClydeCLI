#!/bin/sh
# ClydeCLI installer — https://github.com/dea6cat/ClydeCLI
#
#   curl -fsSL https://raw.githubusercontent.com/dea6cat/ClydeCLI/main/install.sh | sh
#   curl -fsSL .../install.sh | CLYDE_REF=v0.2.0 sh      # a specific release tag or commit
#
# Installs uv (if needed) and the `clyde` command, then hands off to `clyde setup`, which
# connects a provider, offers to bring over other agents' hooks, and fixes PATH. Flags are
# passed through to `clyde setup` (e.g. --yes for no prompts).
set -u

# CLYDE_REF pins what gets installed: a release tag (v0.2.0) or a full commit sha. Unset installs the newest main.
CLYDE_REF="${CLYDE_REF:-}"
case "$CLYDE_REF" in
  *[!A-Za-z0-9._-]*) echo "CLYDE_REF may only contain letters, digits, dots, dashes and underscores." >&2; exit 1 ;;
esac
REPO="git+https://github.com/dea6cat/ClydeCLI${CLYDE_REF:+@$CLYDE_REF}"

have() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# 1) uv
if ! have uv; then
  log "Installing uv…"
  if   have curl; then curl -LsSf https://astral.sh/uv/install.sh | sh
  elif have wget; then wget -qO- https://astral.sh/uv/install.sh | sh
  else echo "Need curl or wget to install uv. Install one and re-run." >&2; exit 1; fi
fi
# `clyde setup` checks PATH against what future terminals get, not the shims added below.
_CLYDE_ORIG_PATH="$PATH"; export _CLYDE_ORIG_PATH
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; export PATH

# 2) the clyde tool (uv fetches Python 3.14 if needed)
log "Installing ClydeCLI…"
uv tool install --force --python 3.14 "$REPO" || { echo "uv tool install failed." >&2; exit 1; }
PATH="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin"):$PATH"; export PATH

# 3) onboarding. Read answers from the terminal even when piped from `curl | sh`.
log "Running clyde setup…"
if [ -r /dev/tty ]; then
  clyde setup "$@" < /dev/tty
else
  clyde setup --yes "$@"
fi
