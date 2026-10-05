"""CLI entry point for ClydeCLI."""

from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from src.picker import Choice, pick



def main():
    """CLI main entry point."""
    # Quick path for --version
    if len(sys.argv) == 2 and sys.argv[1] in ['--version', '-v', '-V']:
        from src import __version__
        print(f"clyde-cli version {__version__} (Python)")
        return 0

    parser = argparse.ArgumentParser(
        description="ClydeCLI - a coding-agent harness for any LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  clyde                               Start interactive REPL
  clyde --model openai:gpt-5.4        Start with a specific provider:model
  clyde --stream                      Start REPL with live response rendering
  clyde -c                            Continue the most recent session in this directory
  clyde --resume [SESSION_ID]         Pick a recent session to resume, or resume one by id
  clyde --list-models                 List models from every connected provider
  clyde --debug                       Start REPL and print trace events (model/tool calls) to stderr
  clyde login                         Connect a provider and pick a default model
  clyde logout openai                 Remove a saved API key
  clyde config                        Show current configuration
  clyde setup                         First-run onboarding: provider, other agents' hooks and skills, PATH
  clyde hooks import                  Bring over hooks set up for Claude Code, Gemini CLI, Cursor or Copilot CLI
  clyde mcp import                    Bring over MCP servers set up for Claude Code, Cursor, Gemini CLI, Codex or Copilot CLI
  clyde plugin install <path|git-url> Install a plugin (skills, hooks, MCP servers, tools); asks before enabling it
  clyde plugin import                 Bring over plugins installed for Claude Code, Codex or Cursor
  clyde plugin list                   List installed plugins; also: plugin remove|enable|disable <name>
  clyde -p "<prompt>"                 One turn without the prompt, answer on stdout (scripts, CI); also --mode,
                                      --output-format json, --max-turns. Piped input is added: git diff | clyde -p "review"
  clyde --acp                         Run as an Agent Client Protocol agent on stdio, for editors (Zed, JetBrains)
"""
    )

    parser.add_argument('--version', action='store_true', help='Show version information')
    parser.add_argument('--config', action='store_true', help='Show current configuration')
    parser.add_argument('--stream', action='store_true', help='Enable live response rendering in the REPL')
    parser.add_argument('--model', metavar='PROVIDER:MODEL', help='Model to use for this session')
    parser.add_argument('-c', '--continue', dest='continue_last', action='store_true',
                        help='Continue the most recent session in this directory')
    parser.add_argument('-r', '--resume', nargs='?', const='', metavar='SESSION_ID',
                        help='Resume a session by id, or pick one of the recent sessions')
    parser.add_argument('-d', '--debug', action='store_true', help='Print trace events (model and tool calls) live to stderr')
    parser.add_argument('--list-models', action='store_true', help='List models from every connected provider')
    parser.add_argument('-p', '--print', dest='print_prompt', nargs='?', const='', metavar='PROMPT',
                        help='Run one turn without the interactive prompt and print the answer (piped stdin is added '
                             'to the prompt); for scripts and CI')
    parser.add_argument('--mode', choices=['hold', 'plan', 'all_in'], default='hold',
                        help="-p: permission mode. hold (default) and plan deny anything that would ask; all_in still "
                             "denies major moves (rm -r, git push, ...)")
    parser.add_argument('--output-format', choices=['text', 'json'], default='text',
                        help='-p: plain answer, or JSON with the answer, model, usage, turns and session id')
    parser.add_argument('--max-turns', type=int, default=20, metavar='N', help='-p: tool rounds before giving up (default 20)')
    parser.add_argument('--acp', action='store_true',
                        help='Speak the Agent Client Protocol on stdio so an editor (Zed, JetBrains) can run Clyde')

    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    subparsers.add_parser('login', help='Connect a provider and pick a default model')
    logout_parser = subparsers.add_parser('logout', help='Remove a saved API key')
    logout_parser.add_argument('provider', help='Provider name, e.g. openai')
    subparsers.add_parser('config', help='Show current configuration')
    setup_parser = subparsers.add_parser('setup', help='First-run onboarding (run by install.sh)')
    setup_parser.add_argument('-y', '--yes', action='store_true', help='No prompts: skip anything that needs an answer')
    hooks_parser = subparsers.add_parser('hooks', help='Manage tool hooks')
    hooks_parser.add_argument('action', choices=['import'], help="'import': copy other agents' hooks into ~/.clyde/settings.json")
    mcp_parser = subparsers.add_parser('mcp', help='Manage MCP servers')
    mcp_parser.add_argument('action', choices=['import', 'login', 'logout'],
                            help="'import': copy other agents' MCP servers into ~/.clyde/settings.json; "
                                 "'login'/'logout': OAuth sign-in for a remote server")
    mcp_parser.add_argument('server', nargs='?', help='login/logout: the server name from mcpServers')
    plugin_parser = subparsers.add_parser('plugin', help='Manage plugins in ~/.clyde/plugins')
    plugin_parser.add_argument('action', choices=['install', 'import', 'list', 'remove', 'enable', 'disable'])
    plugin_parser.add_argument('target', nargs='?', help='install: a folder or git URL; remove/enable/disable: a plugin name')
    plugin_parser.add_argument('-y', '--yes', action='store_true', help='install without prompting; the plugin stays disabled')

    args = parser.parse_args()

    if args.acp:
        from src import acp
        return acp.main(model=args.model)

    if args.print_prompt is not None:
        from src.repl import headless
        return headless.run(args.print_prompt, model=args.model, mode=args.mode,
                            output_format=args.output_format, max_turns=args.max_turns)

    if args.version:
        from src import __version__
        print(f"clyde-cli version {__version__} (Python)")
        return 0
    if args.config or args.command == 'config':
        return show_config()
    if args.list_models:
        return list_models()
    if args.command == 'login':
        return handle_login()
    if args.command == 'logout':
        return handle_logout(args.provider)
    if args.command == 'setup':
        return handle_setup(Console(), assume_yes=args.yes)
    if args.command == 'hooks':
        return handle_hooks_import(Console())
    if args.command == 'mcp':
        if args.action == 'import':
            return handle_mcp_import(Console())
        return handle_mcp_auth(Console(), args.action, args.server or "")
    if args.command == 'plugin':
        if args.action != 'list' and not args.target:
            parser.error(f"plugin {args.action} needs a {'folder or git URL' if args.action == 'install' else 'plugin name'}")
        return handle_plugin(Console(), args.action, args.target, assume_yes=args.yes)

    return start_repl(model=args.model, stream=args.stream, resume=args.resume, continue_last=args.continue_last,
                      debug=args.debug)


def prompt_secret(label: str) -> str:
    """Read a secret, echoing '*' per character so the user can see a paste landed."""
    try:
        from prompt_toolkit import prompt
    except ImportError:
        return Prompt.ask(label, password=True).strip()
    return prompt(f"{label}: ", is_password=True).strip()


def _login_choices(registry: dict) -> list[str]:
    """Provider names offered by login. Ollama Cloud is offered even before its key exists;
    `custom` adds an OpenAI-compatible service that isn't built in."""
    names = sorted(n for n in registry if n != "ollama-cloud")
    return names + ["ollama-cloud", "custom"]


def _key_name(provider: str) -> str:
    """keys.json / env-var name for a login choice (Ollama Cloud uses the ollama key)."""
    return "ollama" if provider == "ollama-cloud" else provider


def _suggest_local_models(console: Console) -> None:
    from src.providers import discover
    from src.providers.ollama import _total_ram_bytes

    ram_gb = _total_ram_bytes() // 1024 ** 3
    with console.status("[dim]Looking up models that fit this machine...[/dim]", spinner="dots"):
        rows = discover.discover(ram_gb) if ram_gb else []
    if not rows:
        console.print("[dim]Pull a tool-capable model with `ollama pull <model>`, then run clyde login again.[/dim]")
        return
    console.print(f"[bold]Tool-capable models that fit {ram_gb}GB RAM:[/bold]")
    for tag, _pulls, est in rows[:8]:
        console.print(f"  ollama pull {tag}  [dim](~{est}GB)[/dim]")


def _add_custom_provider(console: Console) -> str | None:
    """Ask for a service's name, protocol and base URL and save it; its name, or None."""
    from src.providers import keys

    console.print("[dim]Any OpenAI-compatible API (Together, Fireworks, Groq, vLLM, LiteLLM...) or Anthropic-compatible "
                  "one (a second Anthropic account, MiniMax, a proxy). The base URL is the part before "
                  "/chat/completions (OpenAI) or /v1/messages (Anthropic).[/dim]")
    name = Prompt.ask("Name (e.g. together)").strip().lower()
    protocol = pick(console, "Protocol", [Choice(p, p) for p in keys.PROTOCOLS], current="openai")
    if protocol is None:
        return None
    base_url = Prompt.ask("Base URL (e.g. https://api.together.xyz/v1)").strip()
    problem = keys.add_custom(name, base_url, protocol)
    if problem:
        console.print(f"[red]Can't add {name or 'it'}: {problem}.[/red]")
        return None
    console.print(f"[green]✓ Added {name}[/green] [dim](saved in ~/.clyde/settings.json)[/dim]")
    return name


def run_login_flow(console: Console, registry: dict, default_provider: str = "anthropic",
                   provider: str | None = None) -> str | None:
    """Connect a provider and choose its model. Saves the key and the default model, and returns
    the `provider:model` string, or None if the user bailed or the provider isn't usable.
    `provider` (a login choice) skips the provider question."""
    from rich.prompt import Confirm
    from src.config import set_default_model
    from src.providers import build_registry, keys
    from src.providers.registry import SUGGESTED_MODELS

    choices = _login_choices(registry)
    provider_name = provider if provider in choices else pick(
        console, "Connect a provider", _provider_choices(registry), current=default_provider if default_provider in choices else None,
        description="Pick one, then enter its key. Type to filter.")
    if provider_name is None:
        return None

    custom = provider_name == "custom" or provider_name in keys.custom_providers()
    if provider_name == "custom":
        provider_name = _add_custom_provider(console)
        if provider_name is None:
            return None

    if provider_name not in ("ollama", "lmstudio", "cardShuffle"):  # local servers and cardShuffle need no key
        key = prompt_secret(f"Enter {provider_name} API key" + (" (empty if it needs none)" if custom else ""))
        key = key or ("none" if custom else "")   # a keyless server (vLLM, a local proxy) still gets a Bearer header
        if not key:
            console.print("\n[red]Error: API key cannot be empty[/red]")
            return None
        keys.connect(_key_name(provider_name), key)
        registry = build_registry()   # Ollama Cloud only registers once its key is set

    provider = registry.get(provider_name)
    if provider is None or not provider.is_available():
        if provider_name == "ollama":
            console.print(f"[red]Ollama isn't reachable at {getattr(provider, 'host', 'localhost:11434')}.[/red] "
                          "Start it with `ollama serve`.")
        else:
            console.print(f"[red]{provider_name} isn't available.[/red]"
                          + (" Install LM Studio, or start its server." if provider_name == "lmstudio" else "")
                          + (" It deals only models that passed /eval: run /eval first." if provider_name == "cardShuffle" else ""))
        return None

    with console.status(f"[dim]Fetching {provider_name} models...[/dim]", spinner="dots"):
        try:
            models = provider.list_models()
        except Exception:
            models = []

    if provider_name == "ollama" and not models:
        console.print("[yellow]Ollama is running but has no models installed.[/yellow]")
        _suggest_local_models(console)
        return None

    suggested = SUGGESTED_MODELS.get(provider_name)
    if models:
        default_model = suggested if suggested in models else models[0]
        model = pick(console, f"Select {provider_name} model", [Choice(m, m) for m in models], current=default_model,
                     allow_custom=True, description="Your pick becomes the default. Type to filter, or type any model id.")
        if model is None:
            return None
        if model not in models and not Confirm.ask(
            f"'{model}' isn't in {provider_name}'s model list. Use it anyway?", default=False
        ):
            model = default_model
    else:
        console.print(f"[yellow]Couldn't list {provider_name} models; check the key. You can still type a model id.[/yellow]")
        default_model = suggested or ""
        answer = Prompt.ask("Default model", default=default_model) if default_model else Prompt.ask("Default model")
        model = (answer or "").strip()
        if not model:
            console.print("\n[red]Error: a model is required[/red]")
            return None

    ref = f"{provider_name}:{model}"
    set_default_model(ref)
    console.print(f"\n[green]✓ {provider_name} connected[/green]")
    console.print(f"[green]✓ Default model: {ref}[/green]\n")
    return ref


def handle_login():
    """Interactive provider configuration."""
    from src.providers import build_registry, keys

    console = Console()
    console.print("\n[bold #4eba65]ClydeCLI - Connect a provider[/bold #4eba65]\n")
    keys.load_into_env()
    registry = build_registry()
    return 0 if run_login_flow(console, registry) else 1


def _clyde_bin_on_path() -> bool:
    """Whether `clyde` resolves on the PATH future terminals get (install.sh passes the original)."""
    import shutil
    return shutil.which("clyde", path=os.environ.get("_CLYDE_ORIG_PATH") or os.environ.get("PATH")) is not None


def handle_setup(console: Console, assume_yes: bool = False) -> int:
    """First-run onboarding, as 2B's `2b setup`: provider, other agents' hooks and skills, PATH."""
    import shutil
    import subprocess
    from rich.prompt import Confirm
    from src.config import get_default_model
    from src.providers import build_registry, keys, usable
    from src.skills.loader import get_all_skills

    console.print("\n[bold #4eba65]ClydeCLI setup[/bold #4eba65]")

    # 1) provider and default model
    keys.load_into_env()
    registry = build_registry()
    connected = usable(registry)
    if connected and get_default_model():
        console.print(f"✓ Connected: {', '.join(connected)}; default model {get_default_model()}")
    elif assume_yes:
        console.print("• No default model yet: run [bold]clyde login[/bold] (or export a provider key).")
    else:
        if not run_login_flow(console, registry):
            console.print("[yellow]Skipped connecting a provider; run clyde login later.[/yellow]")

    # 2) other agents' hooks: they run commands, so never imported without an explicit yes
    if assume_yes:
        console.print("• Hooks from other agents are not imported with --yes: run [bold]clyde hooks import[/bold].")
    else:
        handle_hooks_import(console, quiet=True)

    # 3) other agents' MCP servers: they start programs, so also only after a yes
    if assume_yes:
        console.print("• MCP servers from other agents are not imported with --yes: run [bold]clyde mcp import[/bold].")
    else:
        handle_mcp_import(console, quiet=True)

    # 4) other agents' plugins: they run code, so each one needs its own yes (never with --yes)
    handle_plugin_import(console, assume_yes=assume_yes, quiet=True)

    # 5) other agents' skills are read in place
    user_skills = [s for s in get_all_skills() if s.loaded_from == "user"]
    console.print(f"✓ {len(user_skills)} user skill(s) available, including ~/.claude, ~/.agents, ~/.codex, "
                  "~/.copilot and ~/.gemini skill folders.")

    # 6) the code map (built by graphify), which every model queries through the Map tool
    if shutil.which("graphify"):
        console.print("✓ Code map ready: the Map tool maps each repo when ClydeCLI starts in it.")
    elif shutil.which("uv") and (assume_yes or Confirm.ask(
            "Install the code map builder so any model can map your repos (uv tool install graphifyy)?",
            default=True)):
        subprocess.run(["uv", "tool", "install", "graphifyy"], check=False)
    else:
        console.print("• Install the code map builder later for the Map tool: [bold]uv tool install graphifyy[/bold].")

    # 7) Laya's weights: a large download, so only after a yes (never with --yes)
    from src.providers import laya_client
    if laya_client.cached():
        console.print("✓ Laya (the bundled decision model) is downloaded.")
    elif not assume_yes and Confirm.ask(
            f"Download Laya's model ({laya_client.DOWNLOAD_SIZE}) so cardShuffle can spot a stuck model?", default=True):
        env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
        script = "from src.providers.laya_client import _WARMUP; import laya; laya.Router().predict(*_WARMUP)"
        done = subprocess.run([sys.executable, "-c", script], env=env, check=False)
        console.print("✓ Laya downloaded." if done.returncode == 0 and laya_client.cached()
                      else "[yellow]Laya's download didn't finish; run clyde setup again to retry.[/yellow]")
    else:
        console.print(f"• Laya's model isn't downloaded ({laya_client.DOWNLOAD_SIZE}); run [bold]clyde setup[/bold] to get it.")

    # 8) PATH
    if not _clyde_bin_on_path() and shutil.which("uv"):
        if not assume_yes and Confirm.ask("clyde isn't on your PATH yet. Add uv's tool folder to it (uv tool update-shell)?", default=True):
            subprocess.run(["uv", "tool", "update-shell"], check=False)
        else:
            console.print("• Add clyde to your PATH later with [bold]uv tool update-shell[/bold].")

    console.print("\nClydeCLI is ready. Start it from any project directory with [bold]clyde[/bold].")
    return 0


def handle_mcp_import(console: Console, quiet: bool = False) -> int:
    """Offer each other agent's MCP servers (stdio and remote) for import; env and header values are never printed."""
    from rich.prompt import Confirm
    from src.tool_system.mcp_client import describe_server, find_foreign_servers, import_servers

    found = find_foreign_servers()
    if not found:
        if not quiet:
            console.print("No MCP servers found for Claude Code, Cursor, Gemini CLI, Codex or Copilot CLI.")
        return 0
    added: list[str] = []
    for agent, path, servers in found:
        console.print(f"\n[bold]{agent}[/bold] MCP servers in {path}:")
        for name, cfg in servers.items():
            console.print(f"  {name}: {describe_server(cfg)}", markup=False)
        if Confirm.ask("ClydeCLI will start these programs or connect to these servers when it launches. Import them?",
                       default=False):
            try:
                added += import_servers(servers)
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                return 1
    console.print(f"Imported MCP server(s): {', '.join(added)}." if added else "No MCP servers imported.")
    return 0


def handle_mcp_auth(console: Console, action: str, name: str) -> int:
    """`clyde mcp login|logout <server>`: OAuth sign-in (browser) for a remote server, or forget its tokens."""
    from src.tool_system import mcp_oauth
    from src.tool_system.mcp_client import load_servers, remote_spec

    servers = load_servers()
    spec = remote_spec(servers[name]) if name in servers else None
    if spec is None:
        remote = [n for n, c in servers.items() if remote_spec(c)]
        console.print(f"Usage: clyde mcp {action} <server>. Remote servers: {', '.join(remote) or 'none configured'}.")
        return 1
    if action == "logout":
        console.print(f"Signed out of {name}." if mcp_oauth.logout(spec[1]) else f"{name} had no saved sign-in.")
        return 0
    console.print(f"Opening your browser to sign in to {name}…")
    try:
        mcp_oauth.login(spec[1], on_url=lambda u: console.print(f"[dim]If it didn't open: {u}[/dim]", soft_wrap=True))
    except mcp_oauth.OAuthError as e:
        console.print(f"[red]Sign-in failed:[/red] {e}")
        return 1
    except KeyboardInterrupt:
        console.print("Sign-in cancelled.")
        return 1
    console.print(f"[green]✓ Signed in to {name}.[/green] ClydeCLI connects to it the next time it starts.")
    return 0


def handle_hooks_import(console: Console, quiet: bool = False) -> int:
    """Offer each other agent's hooks for import; nothing is copied without a yes."""
    from rich.prompt import Confirm
    from src.tool_system.hooks import find_foreign_hooks, import_hooks, settings_paths

    found = find_foreign_hooks()
    if not found:
        if not quiet:
            console.print("No hooks found for Claude Code, Gemini CLI, Cursor or Copilot CLI.")
        return 0
    total = 0
    for agent, path, hooks in found:
        console.print(f"\n[bold]{agent}[/bold] hooks in {path}:")
        for event, groups in hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    console.print(f"  {event} [{group['matcher'] or '*'}]  {hook['command']}", markup=False)
        if Confirm.ask("ClydeCLI will run these commands around its tool calls. Import them?", default=False):
            try:
                total += import_hooks(hooks)
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                return 1
    console.print(f"Imported {total} hook(s) into {settings_paths()[0]}." if total else "No hooks imported.")
    return 0


def _scan_plugin(console: Console, plugin):  # type: ignore[no-untyped-def]
    """SkillSpector's verdict on a plugin before the user decides to enable it: the static scan, plus
    the LLM review with the default model when SkillSpector can use it (Ctrl+C skips the review)."""
    from src import skill_scan

    env = skill_scan.default_llm_env()
    try:
        verdict = skill_scan.check("plugin", plugin.name, plugin.root, env=env)
    except KeyboardInterrupt:
        console.print("[dim]LLM review skipped; static scan only.[/dim]")
        verdict = skill_scan.check("plugin", plugin.name, plugin.root)
    color = {"SAFE": "green", "CAUTION": "yellow", "DO_NOT_INSTALL": "red"}.get(verdict.recommendation, "dim")
    console.print(f"  SkillSpector: [{color}]{verdict.recommendation}[/{color}] (risk {verdict.score}"
                  f"{', LLM-reviewed' if verdict.llm else ', static scan'})")
    for finding in verdict.findings[:5]:
        console.print(f"    • {finding}", markup=False)
    if verdict.blocked:
        console.print("  [red]SkillSpector recommends not installing it.[/red] Enabling it anyway records your approval.")
    return verdict


def handle_plugin(console: Console, action: str, target: str | None, assume_yes: bool = False) -> int:
    """`clyde plugin install|list|remove|enable|disable`. Plugins run code, so enabling needs an explicit yes."""
    from rich.prompt import Confirm
    from src import plugins

    try:
        if action == 'import':
            return handle_plugin_import(console, assume_yes=assume_yes)
        if action == 'list':
            found, errors = plugins.installed()
            if not found and not errors:
                console.print(f"No plugins installed in {plugins.plugins_dir()}.")
            for p in found:
                state = "[green]enabled[/green]" if plugins.is_enabled(p.name) else "[dim]disabled[/dim]"
                console.print(f"{p.name} {p.version}  {state}")
                for line in ([p.description] if p.description else []) + plugins.describe(p):
                    console.print(f"    {line}", markup=False)
            for error in errors:
                console.print(f"✗ {error}", style="red", markup=False)
            return 0
        if action == 'install':
            plugin = plugins.install(target or "")
            console.print(f"Installed [bold]{plugin.name}[/bold] {plugin.version} into {plugin.root}")
            for line in plugins.describe(plugin) or ["(nothing ClydeCLI can load)"]:
                console.print(f"  {line}", markup=False)
            verdict = _scan_plugin(console, plugin)
            if not assume_yes and Confirm.ask(
                    "Plugins run code: their tools, hooks and MCP servers run on this machine. Enable it?", default=False):
                plugins.set_enabled(plugin.name, True)
                if verdict.blocked:
                    from src import skill_scan
                    skill_scan.approve("plugin", plugin.name)
                console.print(f"[green]✓ Enabled {plugin.name}[/green]; it loads the next time ClydeCLI starts.")
            else:
                console.print(f"Left disabled. Enable it with [bold]clyde plugin enable {plugin.name}[/bold].")
            return 0
        if action == 'remove':
            plugins.remove(target or "")
            console.print(f"Removed {target}.")
            return 0
        if target not in {p.name for p in plugins.installed()[0]}:
            raise ValueError(f"no plugin named '{target}' is installed")
        plugins.set_enabled(target, action == 'enable')
        console.print(f"{'Enabled' if action == 'enable' else 'Disabled'} {target}; this applies the next time ClydeCLI starts.")
        return 0
    except (OSError, ValueError) as e:
        console.print(str(e), style="red", markup=False)
        return 1


def handle_plugin_import(console: Console, assume_yes: bool = False, quiet: bool = False) -> int:
    """Offer every plugin other agents have installed; each is copied and enabled only after its own yes."""
    from rich.prompt import Confirm
    from src import plugins

    found = plugins.find_foreign()
    if not found:
        if not quiet:
            console.print("No plugins found for Claude Code, Codex or Cursor that ClydeCLI doesn't already have.")
        return 0
    importable = [f for f in found if not f.reason]
    for f in found:
        if f.reason:
            console.print(f"[dim]• {f.agent}: {f.plugin.name if f.plugin else f.source.name} skipped: {f.reason}[/dim]")
    if assume_yes:
        if importable:
            console.print(f"• {len(importable)} plugin(s) from other agents can be imported: run [bold]clyde plugin import[/bold].")
        return 0
    imported = []
    for f in importable:
        state = "" if f.enabled_there else f"  [dim](disabled in {f.agent})[/dim]"
        console.print(f"\n[bold]{f.plugin.name}[/bold] {f.plugin.version} from {f.agent}{state}")
        if f.plugin.description:
            console.print(f"  {f.plugin.description}", markup=False)
        for line in plugins.describe(f.plugin):
            console.print(f"  {line}", markup=False)
        verdict = _scan_plugin(console, f.plugin)
        if Confirm.ask("It will run on this machine (tools, hooks, MCP servers). Import and enable it?",
                       default=f.enabled_there and not verdict.blocked and verdict.recommendation != "CAUTION"):
            try:
                plugins.set_enabled(plugins.install(str(f.source)).name, True)
            except (OSError, ValueError) as e:
                console.print(f"  [red]{e}[/red]")
                continue
            imported.append(f.plugin.name)
    console.print(f"Imported plugin(s): {', '.join(imported)}; they load the next time ClydeCLI starts." if imported else "No plugins imported.")
    return 0


def handle_logout(provider: str) -> int:
    from src.providers import keys

    console = Console()
    name = _key_name(provider)
    custom = name in keys.custom_providers()   # also registers custom providers' key names
    if name not in keys.PROVIDER_KEY_ENV:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        return 1
    env = keys.PROVIDER_KEY_ENV[name]
    if keys.disconnect(name):
        console.print(f"[green]✓ Removed the saved {provider} key.[/green]")
    else:
        console.print(f"[yellow]No saved key for {provider}.[/yellow]")
    if custom:
        problem = keys.remove_custom(name)
        if problem:
            console.print(f"[red]Couldn't remove {provider} from settings.json: {problem}[/red]")
            return 1
        console.print(f"[green]✓ Removed the {provider} provider from ~/.clyde/settings.json.[/green]")
    if os.environ.get(env):
        console.print(f"[dim]{env} is still set in your shell.[/dim]")
    return 0


def _provider_status(name: str, saved: set[str]) -> tuple[str, str]:
    """(key env var, status text) for a login choice."""
    from src.providers import keys

    if name == "ollama":
        return "none (local)", ""
    if name == "custom":
        return "", "an OpenAI- or Anthropic-compatible service that isn't built in"
    key_name = _key_name(name)
    env = keys.PROVIDER_KEY_ENV.get(key_name, "")
    value = os.environ.get(env, "")
    if not value:
        return env, "not connected"
    return env, f"{keys.mask(value)} ({'saved' if key_name in saved else 'env'})"


def _provider_choices(registry: dict) -> list[Choice]:
    """The login picker's rows: each provider with its key status."""
    from src.providers import keys

    saved = keys.saved_providers()
    return [Choice(name, name, _provider_status(name, saved)[1]) for name in _login_choices(registry)]


def _print_provider_table(console: Console, registry: dict) -> None:
    from src.providers import keys

    saved = keys.saved_providers()
    table = Table(title="Providers", show_header=True, header_style="bold")
    table.add_column("Provider", style="#4eba65")
    table.add_column("Key", style="#e8e4dc")
    table.add_column("Status", style="green")
    for name in _login_choices(registry):
        if name != "custom":
            table.add_row(name, *_provider_status(name, saved))
    console.print(table)
    console.print()


def show_config():
    """Show current configuration."""
    console = Console()
    try:
        from src.config import get_config_path, load_config
        from src.providers import build_registry, keys

        keys.load_into_env()
        config = load_config()
        console.print(f"\n[bold]Configuration file:[/bold] {get_config_path()}")
        console.print(f"[bold]Saved keys:[/bold] {keys.keys_file()}\n")
        console.print(f"[#4eba65]Default model:[/#4eba65] {config.get('model') or 'Not set (picks a connected model at startup)'}\n")
        _print_provider_table(console, build_registry())
    except Exception as e:
        console.print(f"\n[red]Error loading configuration: {e}[/red]\n")
        return 1
    return 0


def list_models() -> int:
    from src.providers import build_registry, keys, usable

    console = Console()
    keys.load_into_env()
    live = usable(build_registry())
    if not live:
        console.print("[yellow]No providers connected.[/yellow] Run [bold]clyde login[/bold], or start Ollama.")
        return 1
    for name, provider in live.items():
        models = provider.list_models()
        console.print(f"[bold #e8e4dc]{name}[/bold #e8e4dc]")
        if not models:
            console.print("  [dim](couldn't list models; check the key or connection)[/dim]")
        for m in models:
            console.print(f"  {name}:{m}")
    return 0


def start_repl(model: str | None = None, stream: bool = False, resume: str | None = None, continue_last: bool = False,
               debug: bool = False):
    """Start interactive REPL."""
    from src.repl import ClydeREPL

    repl = ClydeREPL(model=model, stream=stream, resume=resume, continue_last=continue_last, debug=debug)
    repl.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
