# Install, configure, run

[Back to the README](../README.md)

*Three steps. I'll wait. Might light one while you do it.*

## Install

One line (installs uv if needed, then `clyde`, then runs `clyde setup`):

```bash
curl -fsSL https://raw.githubusercontent.com/dea6cat/ClydeCLI/main/install.sh | sh
# or pin a release tag or an exact commit:
curl -fsSL https://raw.githubusercontent.com/dea6cat/ClydeCLI/main/install.sh | CLYDE_REF=v0.2.5 sh
```

Or with pipx (needs Python 3.12 to 3.14, so name one if your default is older or newer; add `--backend pip` if pipx complains about an older `uv`).
Python 3.11 is not supported: the bundled skill scanner, SkillSpector, needs 3.12.

```bash
pipx install --python python3.13 git+https://github.com/dea6cat/ClydeCLI
# pin a release: ...ClydeCLI@v0.2.5
```

Both give you `clyde` and `bonnie`, and `clyde update` and `clyde uninstall` use the tool that installed Clyde.

It includes SkillSpector, the bundled skill scanner, and the install is about 180 MB. Laya, the local
decision model, is an optional extra (about 640 MB of packages, mostly PyTorch, plus its 800 MB model); an update keeps it
if you already have it.
`clyde setup` connects a provider and picks a default model, asks before adding Laya and downloading its model, lists the hooks, MCP servers and plugins you
already set up for other agents (Claude Code, Cursor, Gemini CLI, Codex, Copilot CLI) and imports
them only if you say yes, and offers to
put `clyde` on your PATH. Pass `--yes` for no prompts (hooks, MCP servers and plugins are never imported that way). Run it
again any time.

Or from source:

```bash
git clone https://github.com/dea6cat/ClydeCLI.git
cd ClydeCLI

# Create venv (uv recommended)
uv venv --python 3.14
source .venv/bin/activate

# Install
uv pip install -r requirements.txt
```

## Configure

> **Where to get an API key** for each provider, and a one-minute tutorial for adding it: [dea6cat.github.io/ClydeCLI/keys.html](https://dea6cat.github.io/ClydeCLI/keys.html?ref=github-readme).
>
> **Every feature** with recordings, including **tuning a local model** (`clyde tune`: what it tries, the checks a setting must pass, real results): [dea6cat.github.io/ClydeCLI/features.html](https://dea6cat.github.io/ClydeCLI/features.html?ref=github-readme)

### Option 1: Just export a key (no login needed)

If a provider key is already in your environment (see the table above), run `clyde`. With no
default model saved, it picks one from whatever is connected (local Ollama first), tells you
which, and `/model` switches it.

### Option 2: Interactive login

```bash
python -m src.cli login
```

This flow will:

1. ask you to choose a provider
2. ask for that provider's API key (shown as `*` while you type or paste)
3. fetch the provider's live model list and ask for a default model
4. save the key to `~/.clyde/keys.json` and the model to `~/.clyde/config.json`

For Ollama there's no key: it checks the server is up, and if you have no models yet it
suggests tool-capable ones that fit your RAM.

Inside the REPL, `/login` runs the same flow and switches to the model you pick (`/login nvidia`
skips the provider question, handy for replacing a key).

**A provider that isn't built in:** pick `custom` and give it a name, the base URL of any
OpenAI-compatible API (the part before `/chat/completions`, e.g. `https://api.together.xyz/v1`)
and its key (leave it empty for a keyless local server such as vLLM). It's saved under
`"providers"` in `~/.clyde/settings.json`, its key in `keys.json` (or export
`CLYDE_<NAME>_API_KEY`), and from then on it works like a built-in one: `/models`, `/eval`,
`<name>:<model>` and cardShuffle. `clyde logout <name>` removes both its key and its entry in
`settings.json`.

### Option 3: Pick the model per session

`clyde --model openai:gpt-5.4` overrides the default for one session. A key exported in your
shell always wins over a saved one.

The config file only holds the default model and session settings:

```json
{
  "model": "anthropic:claude-sonnet-4-6",
  "session": {"auto_save": true, "max_history": 100}
}
```

Upgrading from an older config with per-provider `api_key` entries? The first run moves the
keys to `keys.json` and keeps your default provider's model.

## Run

```bash
python -m src.cli          # Start REPL
python -m src.cli --help   # Show help
```

That's all it takes: clone, configure, run.
