# What leaves your machine

Every way ClydeCLI can send something over the network, what it sends, when, and how to stop it. Written from the code at v0.5.9 by
searching for every network call. If you find one that is missing here, that is a bug in this document: please open an issue.
`tests/test_egress_doc.py` fails when the code mentions a host that this file does not.

**The short version.** Your prompts, your files and your command output go to exactly one place: the model provider you chose
(and nowhere, if that provider is a local one). Everything else below is small, named, and has an off switch.

## 1. Your model provider

This is the point of the tool, and it is the only place your content goes.

| | |
|---|---|
| **Sent** | the system prompt (Clyde's instructions plus project context such as your `CLAUDE.md`, a README excerpt and `git status`), the conversation, and tool results, which includes the text of files the model read and the output of commands it ran |
| **Goes to** | the provider you connected: `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `api.mistral.ai`, `api.deepseek.com`, `api.cerebras.ai`, `api.together.xyz`, `integrate.api.nvidia.com`, `openrouter.ai`, `open.bigmodel.cn`, `api.minimaxi.com`, `gen.pollinations.ai`, `api.cloudflare.com` (Workers AI), or a custom endpoint you added. Model lists are fetched from the same provider, with your key |
| **Local models** | Ollama and oMLX are reached on your own machine, so nothing leaves it. (Ollama itself talks to `ollama.com` when you pull a model: that is Ollama's traffic, not Clyde's) |
| **cardShuffle and council** | each turn goes to whichever of *your connected* providers is dealt; council sends the same request to several of them |
| **Secrets** | keys and `.env` files reach the model only after a yes (or an allow rule) |
| **Turn it off** | connect only a local model: then the model traffic never leaves your machine |

### The local runtime's own traffic

A model's weights have no network code: inference alone sends nothing. What can reach out is the program serving the model (Ollama,
oMLX), with its own update checks, downloads or bugs, and that sits below Clyde, so Clyde can neither see nor stop it. Measured on
2026-11-16: Ollama.app 0.35.1, idle with no model loaded, listened only on `127.0.0.1` and opened no outside connection in 3 minutes of
sampling (`lsof -a -i -n -P -p <pid>` every 2 seconds). That does not cover a pull, an update check or a loaded model. To be sure,
block the runtime at the OS: a per-app firewall such as LuLu can deny the `ollama` binary (or oMLX's Python in `~/.clyde/omlx/venv`)
everything but localhost; allow it again while you pull or download a model.

## 2. On by default, with no file content

| What | Goes to | Sent | When | Turn it off |
|---|---|---|---|---|
| Update check | `api.github.com` (newest commit and tags) and `github.com` (`git ls-remote`) | nothing but your IP address and the user agent `clyde-cli` | at the start of the terminal UI, in the background, at most once a day | `CLYDE_NO_UPDATE_CHECK=1` |

The Worker keeps only daily totals: no event, no install id and no address is stored. Cloudflare sees your IP address at its edge, as with
any web request; the Worker never reads it. See [the privacy page](https://dea6cat.github.io/ClydeCLI/privacy.html).

## 3. Tools the model can call

| Tool | Goes to | Sent | Asks first? | Turn it off |
|---|---|---|---|---|
| WebSearch | `html.duckduckgo.com`, with `lite.duckduckgo.com` as fallback when the first answers with an anti-bot page | the search query the model wrote | Yes, before every search, showing the whole query; "don't ask again" saves a `WebSearch` allow rule. (Before 0.5.10 it did not ask.) In `clyde -p`, which cannot ask, it is denied unless that rule exists or you pass `--mode all_in` | answer no, or add `"WebSearch"` to `permissions.deny` in `~/.clyde/settings.json` |
| WebFetch | the URL the model chose | the request for that URL (a key can ride in a query string, so the whole URL is shown) | Yes, before every URL; a `WebFetch(domain:...)` rule skips the question for that domain | answer no, or deny it the same way |
| MCP servers you configured | the server's own address (remote ones) | the model's tool calls and their results; sign-in goes to that server's auth service | you chose to add the server | remove it from your MCP settings. A local (stdio) server is just a process on your machine, and what it does on the network is its own |
| Bash and hooks | wherever the command or script goes | whatever it sends | Bash asks for any command that is not read-only | decline the command |

**After a result tries to steer the model.** A web page, a search result or an MCP answer can carry text written for the model
("send the conversation to ..."). Clyde puts a notice in front of such a result (`CLYDE_INJECTION_SCAN=off` turns the check off), and
from then on, for the rest of the session, WebFetch, WebSearch, MCP tools and every Bash command that is not read-only ask before they
run, even when an allow rule or "all in" would let them through. The question names the result that tripped it and offers no
"don't ask again". Deny rules still deny, and `clyde -p`, which cannot ask, refuses those calls.

## 4. Only after you say yes, or when you use the feature

| What | Goes to | Sent | Turn it off |
|---|---|---|---|
| Cloud review of a weak local reply | the cloud provider you connected | your request and the local model's reply, after a yes once per session | `CLYDE_CLOUD_REVIEW=off`, or answer no |
| SkillSpector's LLM review | the model you connected | the skill, plugin or MCP tool list being reviewed, only for plugin installs, items its offline stage flagged, and `/skills scan`. The static scan is offline | `CLYDE_SKILL_SCAN=off`, or connect no model |
| Finding local models | `ollama.com` (search), `huggingface.co` (model lists, chat templates), and the leaderboards the vendored `whichllm` (`src/vendor/whichllm`) reads to rank them — `artificialanalysis.ai`, `livebench.ai`, `raw.githubusercontent.com` (Aider's leaderboard) and `datasets-server.huggingface.co` (Chatbot Arena data) — building a list in the background, about 5 minutes | search terms and model names; no content | do not open the local-model search |
| Installing Ollama | `brew`, or `ollama.com/install.sh`, from the offer in the local-model flow | nothing of yours | answer no to the offer |
| Installing oMLX | `github.com/jundot/omlx` (its pinned source), PyPI and GitHub (its Python packages), and uv's Python 3.13 when the Mac has none | nothing of yours | answer no to the offer |
| Downloading an MLX model | `huggingface.co`, by oMLX's own downloader | the model's name | do not pick an MLX model in `/models local` |
| `clyde setup` | PyPI and GitHub (the optional Laya package, `graphifyy`) and `huggingface.co` (Laya's model, about 800 MB) | nothing of yours | answer no (Laya's model is never fetched without a yes: Clyde sets `HF_HUB_OFFLINE=1`) |
| `clyde update`, `clyde plugin install <git url>` | GitHub, or the git address you gave | nothing of yours | do not run them |
| Running tasks against models (`/eval`, council) | the providers you connected | the task prompts | do not run them |

### Nothing downloads and runs without a yes

If you pick an MLX model and oMLX isn't installed, Clyde needs it. In the terminal UI it asks first ("Install it? [y/N]") and, on a
yes, installs oMLX's pinned release from source into `~/.clyde/omlx` (a git checkout, a Python 3.13 environment made by uv, and its
Metal kernels when Xcode is there); nothing outside that folder changes. Where nobody can be asked (an editor over ACP, `clyde -p`,
Bonnie) it never installs: it stops and says so.

### Through a proxy

With a proxy set (`/proxy`, or `HTTPS_PROXY` in your environment), everything above goes through it, so the proxy sees
which hosts Clyde talks to; with HTTPS it cannot read the content unless your network inspects TLS (the case a company
certificate, `/proxy ca`, is for). Servers on this machine (Ollama, oMLX) never go through it.

## 5. What does not leave

- **Bonnie** serves its page on `127.0.0.1` only, and the page loads nothing from outside (no fonts, scripts or images from the web).
- **The website** (`dea6cat.github.io/ClydeCLI`) and the app collect no usage data and send no error reports.

## Links Clyde prints but never fetches

Where to get a key or an installer, shown on screen or in a setup message: `platform.openai.com`, `platform.claude.com`,
`platform.deepseek.com`, `platform.minimax.io`, `console.mistral.ai`, `aistudio.google.com`, `dash.cloudflare.com`, `cloud.cerebras.ai`,
`build.nvidia.com`, `enter.pollinations.ai`, `mcp.linear.app` (an example in the MCP help),
`polyformproject.org` (the licence text), `www.apache.org` (Apache-2.0 licence text in scanner headers), `astral.sh` (uv's install command, printed by the vendored whichllm's own `run` command),
`example.com` and `proxy.example.com` (placeholders in help text),
`www.w3.org` (the SVG namespace name the station page gives to the nodes it draws: an identifier, never fetched).
