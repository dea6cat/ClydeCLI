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

# 3) oMLX for Apple Silicon (first-use ready)
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  log "Installing oMLX for Apple Silicon…"
  CLYDE_HOME="${CLYDE_HOME:-$HOME/.clyde}"
  OMLX_DIR="$CLYDE_HOME/omlx"
  if [ ! -d "$OMLX_DIR/src" ]; then
    git clone --quiet --depth 1 --branch v0.7.2 https://github.com/jundot/omlx.git "$OMLX_DIR/src" || echo "Could not clone oMLX; will install on first use." >&2
    if [ -d "$OMLX_DIR/src" ]; then
      uv venv --quiet --seed --python 3.13 "$OMLX_DIR/venv" || echo "Could not create oMLX venv; will install on first use." >&2
      if [ -d "$OMLX_DIR/venv" ]; then
        uv pip install --quiet --python "$OMLX_DIR/venv/bin/python" -e "$OMLX_DIR/src" || echo "Could not install oMLX; will install on first use." >&2
        if [ -f "$OMLX_DIR/venv/bin/omlx" ]; then
          if command -v xcrun >/dev/null 2>&1 && xcrun -f metal >/dev/null 2>&1; then
            log "Building oMLX Metal kernels…"
            make -C "$OMLX_DIR/src" kernels PYTHON="$OMLX_DIR/venv/bin/python" >/dev/null 2>&1 || echo "Metal kernels failed; oMLX runs without them." >&2
          else
            echo "No Metal toolchain; oMLX runs without native kernels." >&2
          fi
        fi
      fi
    fi
  fi
fi

# 3) onboarding. Read answers from the terminal even when piped from `curl | sh`.
log "Running clyde setup…"
if [ -r /dev/tty ]; then
  clyde setup "$@" < /dev/tty
else
  clyde setup --yes "$@"
fi
