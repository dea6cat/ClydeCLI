"""Connecting and disconnecting providers: the login picker, saving a key or a custom provider, logout, and the
provider status table. Shared by `clyde login`/`logout`/`config` and the REPL's /login and /logout."""
from __future__ import annotations

import os

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from src.providers.base import LOCAL_PROVIDERS
from src.providers.card_shuffle import CardShuffle
from src.ui.picker import Choice, pick


def pick_or_prompt(console: Console, title: str, choices: list[Choice], *, current: str | None = None,
                   description: str | None = None, allow_custom: bool = False) -> str | None:
    """pick(), degrading to a numbered prompt when the interactive picker can't run.

    prompt_toolkit fails to attach to the terminal in some setups (for example `curl ... | sh` on macOS,
    where kqueue rejects the tty with OSError 22). It re-raises that as a bare EOFError, so both are caught.
    """
    try:
        return pick(console, title, choices, current=current, description=description, allow_custom=allow_custom)
    except (OSError, EOFError):
        pass

    console.print(f"\n[bold]{title}[/bold]" + (f" [dim]{description}[/dim]" if description else ""))
    for i, c in enumerate(choices, 1):
        mark = "*" if getattr(c, "value", None) == current else " "
        console.print(f" {mark}{i:>2}. {getattr(c, 'label', c)}", markup=False)
    hint = "number" + (" or custom id" if allow_custom else "")
    try:
        answer = Prompt.ask(f"Choose ({hint}, empty to cancel)" if current is None else f"Choose ({hint})",
                            default=current or "", show_default=bool(current)).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not answer:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(choices):
        return choices[int(answer) - 1].value
    values = [c.value for c in choices]
    if answer in values or allow_custom:
        return answer
    console.print(f"[red]'{answer}' is not one of the options.[/red]")
    return None


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


def _suggest_local_models(console: Console) -> None:
    from src.providers import discover
    from src.system import machine

    ram_gb = machine.total_ram_bytes() // machine.GB
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
    protocol = pick_or_prompt(console, "Protocol", [Choice(p, p) for p in keys.PROTOCOLS], current="openai")
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
    provider_name = provider if provider in choices else pick_or_prompt(
        console, "Connect a provider", _provider_choices(registry), current=default_provider if default_provider in choices else None,
        description="Pick one, then enter its key. Type to filter.")
    if provider_name is None:
        return None

    custom = provider_name == "custom" or provider_name in keys.custom_providers()
    if provider_name == "custom":
        provider_name = _add_custom_provider(console)
        if provider_name is None:
            return None

    if provider_name not in (*LOCAL_PROVIDERS, CardShuffle.name):  # local servers and cardShuffle need no key
        from src.providers import browser_sign_in

        browser = browser_sign_in.PROVIDER_BROWSER_AUTH.get(provider_name)
        key = None
        if browser:
            choice = pick_or_prompt(
                console,
                f"Sign in to {provider_name}",
                [
                    Choice("browser", "Open browser to sign in (browser sign-in)"),
                    Choice("key", "Paste an API key"),
                ],
                current="browser",
                description="Browser sign-in opens the provider's sign-in page and saves the key for you.",
            )
            if choice is None:
                return None
            if choice == "browser":
                base, api = browser
                console.print(
                    f"[dim]Opening your browser to sign in to {provider_name}…[/dim]"
                )
                try:
                    key = browser_sign_in.login(base, api)
                except browser_sign_in.BrowserSignInError as e:
                    console.print(f"[red]Sign-in failed:[/red] {e}")
                    return None
                except KeyboardInterrupt:
                    console.print("Sign-in cancelled.")
                    return None
                console.print(f"[green]✓ {provider_name} connected[/green]")
        if key is None:
            key = prompt_secret(f"Enter {provider_name} API key" + (" (empty if it needs none)" if custom else ""))
            key = key or ("none" if custom else "")   # a keyless server (vLLM, a local proxy) still gets a Bearer header
            if not key:
                console.print("\n[red]Error: API key cannot be empty[/red]")
                return None
        keys.connect(keys.key_name(provider_name), key)
        extra = keys.PROVIDER_EXTRA_ENV.get(provider_name)   # e.g. Cloudflare's account id, which its URL contains
        if extra:
            env, label = extra
            current = os.environ.get(env, "")
            value = (Prompt.ask(label, default=current, show_default=bool(current)) or "").strip()
            if not value:
                console.print("\n[red]Error: that setting cannot be empty[/red]")
                return None
            problem = keys.connect_setting(provider_name, value)
            if problem:
                console.print(f"[red]Couldn't save it: {problem}[/red]")
                return None
        registry = build_registry()   # Ollama Cloud only registers once its key is set

    provider = registry.get(provider_name)
    if provider_name == "ollama" and provider is not None and not provider.is_available():
        from src.tuning import tune
        tune.start_saved_server(console)
    if provider is None or not provider.is_available():
        if provider_name == "ollama":
            console.print(f"[red]Ollama isn't reachable at {getattr(provider, 'host', 'localhost:11434')}.[/red] "
                          "Start it with `ollama serve`.")
        else:
            console.print(f"[red]{provider_name} isn't available.[/red]"
                          + (" oMLX installs itself on first use, on Apple Silicon." if provider_name == "omlx" else "")
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
        model = pick_or_prompt(console, f"Select {provider_name} model", [Choice(m, m) for m in models], current=default_model,
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


def handle_logout(provider: str, console: Console | None = None) -> int:
    from src.providers import keys

    console = console or Console()
    name = keys.key_name(provider)
    custom = name in keys.custom_providers()   # also registers custom providers' key names
    if name not in keys.PROVIDER_KEY_ENV:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        return 1
    env = keys.PROVIDER_KEY_ENV[name]
    try:
        removed = keys.disconnect(name)
    except keys.KeysFileError as e:
        console.print(f"[red]{e}[/red]")
        return 1
    if removed:
        console.print(f"[green]✓ Removed the saved {name} key.[/green]")
    else:
        console.print(f"[yellow]No saved key for {name}.[/yellow]")
    if custom:
        problem = keys.remove_custom(name)
        if problem:
            console.print(f"[red]Couldn't remove {provider} from settings.json: {problem}[/red]")
            return 1
        console.print(f"[green]✓ Removed the {provider} provider from ~/.clyde/settings.json.[/green]")
    if os.environ.get(env):
        console.print(f"[dim]{env} is still set in your shell. Remove its export line from your shell profile.[/dim]")
    return 0


def _provider_status(name: str, saved: set[str]) -> tuple[str, str]:
    """(key env var, status text) for a login choice."""
    from src.providers import keys

    if name == "ollama":
        return "none (local)", ""
    if name == "custom":
        return "", "an OpenAI- or Anthropic-compatible service that isn't built in"
    key_name = keys.key_name(name)
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
