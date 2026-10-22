"""How Clyde reaches the network: a proxy, and a company's root certificate for networks that inspect TLS.

Both are kept in ~/.clyde/config.json (`/proxy`, and the Network rows in /settings) and applied once at start by writing
the standard environment variables, so Clyde's own requests (urllib reads HTTPS_PROXY and SSL_CERT_FILE) and everything it
starts (MCP servers, the oMLX downloader, Bash commands) follow the same route.

- proxy "system" (the default) keeps what the environment already says; "off" goes direct; an http(s) URL is used for
  everything. In every case this machine's own servers (Ollama, oMLX) are reached directly: a company proxy can't reach
  your localhost, and urllib would send `localhost` to the proxy without a NO_PROXY entry.
- A CA file is added to the trust store, never put in its place: the bundle Clyde writes is the default roots plus it.
"""
from __future__ import annotations

import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

from src import config
from src.config import clyde_home

PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy")
LOCAL = ("localhost", "127.0.0.1", "::1")
CA_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")   # Python and OpenSSL, requests / huggingface_hub, curl


def get_proxy() -> str:
    value = config.load_config().get("proxy")
    return value if isinstance(value, str) and value else "system"


def check_proxy(value: str) -> str | None:
    """Why `value` can't be the proxy setting, or None when it can."""
    if value in ("system", "off"):
        return None
    url = urllib.parse.urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname:
        return "give an http:// or https:// proxy URL such as http://proxy.example.com:8080 (SOCKS isn't supported)"
    if url.username or url.password:
        return ("Clyde doesn't store proxy passwords: for a proxy that needs one, export "
                "HTTPS_PROXY=http://user:pass@host:port in your shell profile and keep this setting on system")
    return None


def set_proxy(value: str) -> None:
    """Persist the proxy setting. ValueError when it can't be used. Applies from the next start."""
    if (problem := check_proxy(value)) is not None:
        raise ValueError(problem)
    cfg = config.load_config()
    cfg["proxy"] = value
    if value not in ("system", "off"):
        cfg["proxy_url"] = value   # kept when the setting goes back to system or off, so /settings can return to it
    config.save_config(cfg)


def proxy_choices() -> tuple[str, ...]:
    """What the /settings row cycles through: system, off, and the last URL set with /proxy."""
    url = config.load_config().get("proxy_url")
    return ("system", "off", *((url,) if isinstance(url, str) and url else ()))


def get_ca() -> str | None:
    value = config.load_config().get("ca_file")
    return value if isinstance(value, str) and value else None


def set_ca(path: str | None) -> None:
    """Persist the company root certificate (a PEM file), or None to drop it. ValueError when it isn't one."""
    cfg = config.load_config()
    if path is None:
        cfg.pop("ca_file", None)
    else:
        resolved = Path(path).expanduser().resolve()
        try:
            ssl.create_default_context().load_verify_locations(cafile=str(resolved))
        except (OSError, ssl.SSLError) as e:
            raise ValueError(f"{resolved} isn't a PEM certificate file Clyde can load: {e}") from e
        cfg["ca_file"] = cfg["ca_file_saved"] = str(resolved)   # the saved one stays for /settings to return to
    config.save_config(cfg)


def ca_choices() -> tuple[str, ...]:
    """What the /settings row cycles through: off, and the last certificate set with /proxy ca."""
    saved = config.load_config().get("ca_file_saved")
    return ("off", *((saved,) if isinstance(saved, str) and saved else ()))


def _bundle(ca: Path) -> Path:
    """The default roots followed by the company certificate, in ~/.clyde/ca-bundle.pem (rewritten at each start)."""
    default = ssl.get_default_verify_paths().cafile
    roots = Path(default).read_text(encoding="utf-8", errors="replace") if default and Path(default).is_file() else ""
    out = clyde_home() / "ca-bundle.pem"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(roots.rstrip("\n") + "\n" + ca.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return out


def apply(env: dict[str, str] | None = None) -> None:
    """Write the proxy and CA settings into the environment (os.environ by default), before any request is made."""
    env = os.environ if env is None else env
    proxy = get_proxy()
    if proxy == "off":
        for var in PROXY_VARS:
            env.pop(var, None)
        env["NO_PROXY"] = env["no_proxy"] = "*"
    else:
        if proxy != "system":
            for var in PROXY_VARS[:4]:
                env[var] = proxy
        if any(env.get(var) for var in PROXY_VARS):   # this machine's servers never go through a proxy
            listed = [h.strip() for h in (env.get("NO_PROXY") or env.get("no_proxy") or "").split(",") if h.strip()]
            env["NO_PROXY"] = env["no_proxy"] = ",".join([*listed, *(h for h in LOCAL if h not in listed)])
    ca = get_ca()
    if ca and Path(ca).is_file():
        bundle = str(_bundle(Path(ca)))
        for var in CA_VARS:
            env[var] = bundle
        env["NODE_EXTRA_CA_CERTS"] = ca   # Node adds this to its own roots


def describe() -> tuple[str, str]:
    """(proxy, certificate) as /doctor shows them, without a proxy's password."""
    proxies = urllib.request.getproxies_environment()
    route = proxies.get("https") or proxies.get("http")
    if route:
        url = urllib.parse.urlsplit(route)
        route = url._replace(netloc=f"***@{url.hostname}:{url.port}" if url.password else url.netloc).geturl()
    setting = get_proxy()
    proxy = ("off (direct)" if setting == "off" else f"{route} ({setting})" if route else "none (direct)")
    ca = get_ca()
    return proxy, (f"{ca} added to the default roots" if ca and Path(ca).is_file() else
                   f"{ca} is missing" if ca else "default roots")
