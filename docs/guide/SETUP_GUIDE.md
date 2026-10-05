# Setup Guide

## 1. Install

```bash
git clone https://github.com/dea6cat/ClydeCLI.git
cd ClydeCLI

uv venv --python 3.14
source .venv/bin/activate
uv pip install -e .

clyde --version
```

Or install it as a tool that's on your PATH everywhere: `uv tool install --editable . --python 3.14`.

## 2. Connect a provider

No login is required: if any provider key below is exported, just run `clyde` and it picks a
connected model (change it with `/model`). `clyde login` is for saving a key and choosing a
default.

### Option 1: `clyde login`

```bash
clyde login
```

Pick a provider, paste its API key (each character shows as `*`), then choose a default model
from the provider's live model list. The key is saved to `~/.clyde/keys.json` (mode 600) and the
model to `~/.clyde/config.json` as `provider:model`.

### Option 2: environment variables

| Provider | Variable |
|----------|----------|
| anthropic | `ANTHROPIC_API_KEY` |
| openai | `OPENAI_API_KEY` |
| google | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |
| openrouter | `OPENROUTER_API_KEY` |
| deepseek | `DEEPSEEK_API_KEY` |
| mistral | `MISTRAL_API_KEY` |
| nvidia | `NVIDIA_API_KEY` |
| cerebras | `CEREBRAS_API_KEY` |
| cloudflare | `CLOUDFLARE_API_TOKEN` (plus `CLOUDFLARE_ACCOUNT_ID`) |
| pollinations | `POLLINATIONS_API_KEY` |
| glm | `GLM_API_KEY` |
| minimax | `MINIMAX_API_KEY` |
| ollama-cloud | `OLLAMA_API_KEY` |

```bash
export OPENAI_API_KEY="sk-..."
clyde --model openai:gpt-5.4
```

A key exported in your shell always wins over a saved one.

### Option 3: local models with Ollama

No key needed. Start Ollama (`ollama serve`), pull a tool-capable model, and ClydeCLI picks up
the first installed model when nothing else is configured:

```bash
ollama pull qwen3:8b
clyde --model ollama:qwen3:8b
```

`clyde login` → `ollama` suggests models that fit your machine's RAM. Set `OLLAMA_HOST` if the
server isn't on `localhost:11434`. The context window is sized to your RAM automatically;
override it with `CLYDE_CONTEXT_TOKENS` (all models) or `CLYDE_MODEL_CONTEXT_<MODEL>`.

## 3. Verify

```bash
clyde config          # default model + which providers have keys
clyde --list-models   # every model you can use right now
```

## 4. Switching models

- `clyde --model provider:model` for one session
- `/model provider:model` inside the REPL (saved as the new default)
- `/models` lists everything available; `/think high` turns up reasoning where supported

The conversation carries over when you switch: history is re-expressed for whichever provider is
active.

## FAQ

**401 / "authentication failed"**: the key is wrong or revoked. Run `clyde login` again, or
`clyde logout <provider>` to remove a saved key.

**"model not found"**: the provider doesn't offer that id to your account. Check `/models`.

**Upgrading from an older config**: keys stored in the old `config.json` are moved to
`keys.json` on first run, and your previous default provider's model becomes `model`.
