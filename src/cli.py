"""CLI entry point for ClydeCLI."""

from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

_MODELS_SHOWN = 30   # longer live lists (e.g. OpenRouter) are truncated in the login prompt


def main():
    """CLI main entry point."""
    # Quick path for --version
    if len(sys.argv) == 2 and sys.argv[1] in ['--version', '-v', '-V']:
        from src import __version__
        print(f"clyde-cli version {__version__} (Python)")
        return 0

    parser = argparse.ArgumentParser(
        description="ClydeCLI - Python AI coding agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  clyde                               Start interactive REPL
  clyde --model openai:gpt-5.4        Start with a specific provider:model
  clyde --stream                      Start REPL with live response rendering
  clyde -c                            Continue the most recent session in this directory
  clyde --resume [SESSION_ID]         Pick a recent session to resume, or resume one by id
  clyde --list-models                 List models from every connected provider
  clyde login                         Connect a provider and pick a default model
  clyde logout openai                 Remove a saved API key
  clyde config                        Show current configuration
  clyde setup                         First-run onboarding: provider, other agents' hooks and skills, PATH
  clyde hooks import                  Bring over hooks set up for Claude Code, Gemini CLI, Cursor or Copilot CLI
  clyde mcp import                    Bring over MCP servers set up for Claude Code, Cursor, Gemini CLI, Codex or Copilot CLI
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
    parser.add_argument('--list-models', action='store_true', help='List models from every connected provider')

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
    mcp_parser.add_argument('action', choices=['import'], help="'import': copy other agents' MCP servers into ~/.clyde/settings.json")

    args = parser.parse_args()

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
        return handle_mcp_import(Console())

    return start_repl(model=args.model, stream=args.stream, resume=args.resume, continue_last=args.continue_last)


def prompt_secret(label: str) -> str:
    """Read a secret, echoing '*' per character so the user can see a paste landed."""
    try:
        from prompt_toolkit import prompt
    except ImportError:
        return Prompt.ask(label, password=True).strip()
    return prompt(f"{label}: ", is_password=True).strip()


def _login_choices(registry: dict) -> list[str]:
    """Provider names offered by login. Ollama Cloud is offered even before its key exists."""
    names = sorted(n for n in registry if n != "ollama-cloud")
    return names + ["ollama-cloud"]


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


def run_login_flow(console: Console, registry: dict, default_provider: str = "anthropic") -> str | None:
    """Connect a provider and choose its model. Saves the key and the default model, and returns
    the `provider:model` string, or None if the user bailed or the provider isn't usable."""
    from rich.prompt import Confirm
    from src.config import set_default_model
    from src.providers import build_registry, keys
    from src.providers.registry import SUGGESTED_MODELS

    choices = _login_choices(registry)
    provider_name = Prompt.ask(
        "Select provider",
        choices=choices,
        default=default_provider if default_provider in choices else "anthropic",
    )

    if provider_name != "ollama":
        key = prompt_secret(f"Enter {provider_name} API key")
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
            console.print(f"[red]{provider_name} isn't available.[/red]")
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

    if models:
        shown = models[:_MODELS_SHOWN]
        console.print(f"\n[dim]Models:[/dim] {', '.join(shown)}"
                      + (f" [dim](+{len(models) - len(shown)} more, see /models)[/dim]" if len(models) > len(shown) else ""))
        suggested = SUGGESTED_MODELS.get(provider_name)
        default_model = suggested if suggested in models else models[0]
    else:
        console.print(f"[yellow]Couldn't list {provider_name} models; check the key. You can still type a model id.[/yellow]")
        default_model = SUGGESTED_MODELS.get(provider_name, "")

    answer = Prompt.ask("Default model", default=default_model) if default_model else Prompt.ask("Default model")
    model = (answer or "").strip()
    if not model:
        console.print("\n[red]Error: a model is required[/red]")
        return None
    if models and model not in models and not Confirm.ask(
        f"'{model}' isn't in {provider_name}'s model list. Use it anyway?", default=False
    ):
        model = default_model

    ref = f"{provider_name}:{model}"
    set_default_model(ref)
    console.print(f"\n[green]✓ {provider_name} connected[/green]")
    console.print(f"[green]✓ Default model: {ref}[/green]\n")
    return ref


def handle_login():
    """Interactive provider configuration."""
    from src.providers import build_registry, keys

    console = Console()
    console.print("\n[bold blue]ClydeCLI - Connect a provider[/bold blue]\n")
    keys.load_into_env()
    registry = build_registry()
    _print_provider_table(console, registry)
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

    console.print("\n[bold blue]ClydeCLI setup[/bold blue]")

    # 1) provider and default model
    keys.load_into_env()
    registry = build_registry()
    connected = usable(registry)
    if connected and get_default_model():
        console.print(f"✓ Connected: {', '.join(connected)}; default model {get_default_model()}")
    elif assume_yes:
        console.print("• No default model yet: run [bold]clyde login[/bold] (or export a provider key).")
    else:
        _print_provider_table(console, registry)
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

    # 4) other agents' skills are read in place
    user_skills = [s for s in get_all_skills() if s.loaded_from == "user"]
    console.print(f"✓ {len(user_skills)} user skill(s) available, including ~/.claude, ~/.agents, ~/.codex, "
                  "~/.copilot and ~/.gemini skill folders.")

    # 5) graphify, which gives every model a code knowledge graph through the CodeGraph tool
    if shutil.which("graphify"):
        console.print("✓ graphify installed: the CodeGraph tool maps each repo when ClydeCLI starts in it.")
    elif shutil.which("uv") and (assume_yes or Confirm.ask(
            "Install graphify so any model can query a code knowledge graph of your repos (uv tool install graphifyy)?",
            default=True)):
        subprocess.run(["uv", "tool", "install", "graphifyy"], check=False)
    else:
        console.print("• Install graphify later for the CodeGraph tool: [bold]uv tool install graphifyy[/bold].")

    # 6) PATH
    if not _clyde_bin_on_path() and shutil.which("uv"):
        if not assume_yes and Confirm.ask("clyde isn't on your PATH yet. Add uv's tool folder to it (uv tool update-shell)?", default=True):
            subprocess.run(["uv", "tool", "update-shell"], check=False)
        else:
            console.print("• Add clyde to your PATH later with [bold]uv tool update-shell[/bold].")

    console.print("\nClydeCLI is ready. Start it from any project directory with [bold]clyde[/bold].")
    return 0


def handle_mcp_import(console: Console, quiet: bool = False) -> int:
    """Offer each other agent's stdio MCP servers for import; env values are never printed."""
    from rich.prompt import Confirm
    from src.tool_system.mcp_client import find_foreign_servers, import_servers

    found = find_foreign_servers()
    if not found:
        if not quiet:
            console.print("No MCP servers found for Claude Code, Cursor, Gemini CLI, Codex or Copilot CLI.")
        return 0
    added: list[str] = []
    for agent, path, servers in found:
        console.print(f"\n[bold]{agent}[/bold] MCP servers in {path}:")
        for name, cfg in servers.items():
            env = f"  (env: {', '.join(cfg['env'])})" if cfg.get("env") else ""
            console.print(f"  {name}: {' '.join([cfg['command'], *map(str, cfg.get('args', []))])}{env}", markup=False)
        if Confirm.ask("ClydeCLI will start these programs when it launches. Import them?", default=False):
            try:
                added += import_servers(servers)
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                return 1
    console.print(f"Imported MCP server(s): {', '.join(added)}." if added else "No MCP servers imported.")
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


def handle_logout(provider: str) -> int:
    from src.providers import keys

    console = Console()
    name = _key_name(provider)
    if name not in keys.PROVIDER_KEY_ENV:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        return 1
    if keys.disconnect(name):
        console.print(f"[green]✓ Removed the saved {provider} key.[/green]")
    else:
        console.print(f"[yellow]No saved key for {provider}.[/yellow]")
    if os.environ.get(keys.PROVIDER_KEY_ENV[name]):
        console.print(f"[dim]{keys.PROVIDER_KEY_ENV[name]} is still set in your shell.[/dim]")
    return 0


def _print_provider_table(console: Console, registry: dict) -> None:
    from src.providers import keys

    saved = keys.saved_providers()
    table = Table(title="Providers", show_header=True, header_style="bold")
    table.add_column("Provider", style="cyan")
    table.add_column("Key", style="magenta")
    table.add_column("Status", style="green")
    for name in _login_choices(registry):
        if name == "ollama":
            table.add_row(name, "none (local)", "")
            continue
        key_name = _key_name(name)
        env = keys.PROVIDER_KEY_ENV.get(key_name, "")
        value = os.environ.get(env, "")
        if value:
            status = f"{keys.mask(value)} ({'saved' if key_name in saved else 'env'})"
        else:
            status = "not connected"
        table.add_row(name, env, status)
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
        console.print(f"[cyan]Default model:[/cyan] {config.get('model') or 'Not set (picks a connected model at startup)'}\n")
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
        console.print(f"[bold cyan]{name}[/bold cyan]")
        if not models:
            console.print("  [dim](couldn't list models; check the key or connection)[/dim]")
        for m in models:
            console.print(f"  {name}:{m}")
    return 0


def start_repl(model: str | None = None, stream: bool = False, resume: str | None = None, continue_last: bool = False):
    """Start interactive REPL."""
    from src.repl import ClydeREPL

    repl = ClydeREPL(model=model, stream=stream, resume=resume, continue_last=continue_last)
    repl.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
