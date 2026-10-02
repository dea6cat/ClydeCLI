"""OAuth sign-in for remote MCP servers, as the MCP authorization spec lays it out. Stdlib only.

1. Discovery: the server's 401 names its Protected Resource Metadata (RFC 9728) in WWW-Authenticate,
   else it is looked up at /.well-known/oauth-protected-resource; that names the authorization
   server, whose metadata (RFC 8414, or OpenID discovery) gives its endpoints. A server without
   either (the 2025-03-26 spec) is its own authorization server, with the spec's default paths.
2. Dynamic Client Registration (RFC 7591) registers ClydeCLI as a public client, so nobody has to
   create an app by hand. The registration is kept and reused while its redirect port is free.
3. Authorization code with PKCE (S256), bound to the server by the `resource` parameter (RFC 8707):
   the browser opens on the sign-in page and a one-shot listener on 127.0.0.1 catches the redirect.
4. Tokens live in ~/.clyde/mcp_oauth.json (mode 600), keyed by server URL, and refresh themselves.

Sign-in only ever starts from `/mcp login <server>` or `clyde mcp login <server>`, never on its own.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

CLIENT_NAME = "ClydeCLI"
LOGIN_TIMEOUT = 300   # seconds to finish signing in in the browser
_lock = threading.Lock()


class OAuthError(Exception):
    pass


# --- token store -------------------------------------------------------------

def store_path() -> Path:
    return Path.home() / ".clyde" / "mcp_oauth.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    path.chmod(0o600)   # access and refresh tokens


def resource(url: str) -> str:
    """The server's canonical URI (RFC 8707): no fragment, no trailing slash, lowercase scheme and host."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def signed_in(url: str) -> bool:
    return bool((_load().get(resource(url)) or {}).get("tokens"))


def logout(url: str) -> bool:
    """Forget a server's tokens and registration; False when there were none."""
    with _lock:
        data = _load()
        if data.pop(resource(url), None) is None:
            return False
        _save(data)
        return True


def bearer(url: str) -> str | None:
    """A usable access token for the server, refreshed when it is about to expire; None when not signed in."""
    entry = _load().get(resource(url)) or {}
    tokens = entry.get("tokens") or {}
    if not tokens.get("access_token"):
        return None
    if tokens.get("expires_at") and tokens["expires_at"] - 60 < time.time():
        return refresh(url)
    return tokens["access_token"]


def refresh(url: str) -> str | None:
    """Trade the refresh token for a new access token; None (and the tokens dropped) when that fails."""
    with _lock:
        data = _load()
        entry = data.get(resource(url)) or {}
        tokens, client, meta = entry.get("tokens") or {}, entry.get("client") or {}, entry.get("server") or {}
        if not tokens.get("refresh_token") or not meta.get("token_endpoint"):
            return None
        form = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                "client_id": client.get("client_id", ""), "resource": resource(url)}
        if client.get("client_secret"):
            form["client_secret"] = client["client_secret"]
        try:
            fresh = _post_form(meta["token_endpoint"], form)
            entry["tokens"] = _token_record(fresh, keep_refresh=tokens["refresh_token"])
        except OAuthError:
            entry.pop("tokens", None)   # the grant is gone: the next connect asks for a sign-in
            _save(data)
            return None
        _save(data)
        return entry["tokens"]["access_token"]


# --- HTTP helpers ------------------------------------------------------------

def _get_json(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=15) as r:
            data = json.loads(r.read() or b"null")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _post(url: str, body: bytes, content_type: str) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": content_type, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
        raise OAuthError(f"{url} answered HTTP {e.code}: {detail}".rstrip(": ")) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise OAuthError(f"{url}: {getattr(e, 'reason', e)}") from e
    if not isinstance(data, dict):
        raise OAuthError(f"{url} returned no JSON object")
    return data


def _post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    return _post(url, urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded")


def _token_record(answer: dict[str, Any], keep_refresh: str | None = None) -> dict[str, Any]:
    if not answer.get("access_token"):
        raise OAuthError(f"the token endpoint returned no access token: {answer.get('error_description') or answer.get('error') or answer}")
    expires = answer.get("expires_in")
    return {"access_token": answer["access_token"], "refresh_token": answer.get("refresh_token") or keep_refresh,
            "expires_at": time.time() + float(expires) if expires else None}


# --- discovery ---------------------------------------------------------------

def _challenge_metadata_url(url: str) -> str | None:
    """resource_metadata from the server's 401 WWW-Authenticate header ("" when the 401 names none),
    probing with an unauthenticated request; None when the server answers without credentials."""
    probes = [urllib.request.Request(url, method="POST", data=json.dumps({"jsonrpc": "2.0", "id": 0, "method": "ping"}).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}),
              urllib.request.Request(url, headers={"Accept": "text/event-stream"})]
    for req in probes:
        try:
            urllib.request.urlopen(req, timeout=15).close()
            return None
        except urllib.error.HTTPError as e:
            if e.code == 401:
                for part in (e.headers.get("WWW-Authenticate") or "").split(","):
                    key, _, value = part.strip().partition("=")
                    if key.lower().endswith("resource_metadata"):
                        return value.strip().strip('"')
                return ""
        except (urllib.error.URLError, OSError):
            raise OAuthError(f"{url} is unreachable") from None
    return None


def _origin(url: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")


def discover(url: str) -> dict[str, Any]:
    """The authorization server's endpoints and the scopes to ask for."""
    challenge = _challenge_metadata_url(url)
    if challenge is None:
        raise OAuthError("this server answers without signing in; nothing to do")
    origin, path = _origin(url)
    prm = None
    for candidate in ([challenge] if challenge else []) + [f"{origin}/.well-known/oauth-protected-resource{path}",
                                                           f"{origin}/.well-known/oauth-protected-resource"]:
        prm = _get_json(candidate)
        if prm and prm.get("authorization_servers"):
            break
        prm = None
    issuer = str(prm["authorization_servers"][0]).rstrip("/") if prm else origin
    as_origin, as_path = _origin(issuer)
    meta = None
    for candidate in [f"{as_origin}/.well-known/oauth-authorization-server{as_path}", f"{as_origin}/.well-known/openid-configuration{as_path}"] \
            + ([f"{issuer}/.well-known/openid-configuration"] if as_path else []):
        meta = _get_json(candidate)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            break
        meta = None
    if meta is None:
        if prm:   # a named authorization server must publish its metadata
            raise OAuthError(f"the authorization server {issuer} publishes no metadata")
        meta = {"authorization_endpoint": f"{origin}/authorize", "token_endpoint": f"{origin}/token",
                "registration_endpoint": f"{origin}/register"}   # the 2025-03-26 spec's defaults
    methods = meta.get("code_challenge_methods_supported")
    if methods and "S256" not in methods:
        raise OAuthError("the authorization server doesn't support PKCE S256, which MCP requires")
    scopes = (prm or {}).get("scopes_supported") or []
    return {"issuer": issuer, "authorization_endpoint": meta["authorization_endpoint"], "token_endpoint": meta["token_endpoint"],
            "registration_endpoint": meta.get("registration_endpoint"), "scope": " ".join(scopes)}


# --- sign-in -----------------------------------------------------------------

def _listen(port: int) -> HTTPServer | None:
    """A one-shot redirect listener on 127.0.0.1:port (0 = any free port); None when the port is taken."""
    result: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if "code" not in query and "error" not in query:
                self.send_response(404)
                self.end_headers()
                return
            result.update(query)
            ok = "code" in query
            body = (f"<html><body style='font-family:system-ui;padding:3em'><h2>{'Signed in' if ok else 'Sign-in failed'}</h2>"
                    f"<p>{'You can close this tab and go back to ClydeCLI.' if ok else query.get('error_description') or query.get('error')}</p>"
                    "</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        server = HTTPServer(("127.0.0.1", port), Callback)
    except OSError:
        return None
    server.result = result   # type: ignore[attr-defined]
    return server


def _register(endpoint: str, redirect_uri: str) -> dict[str, Any]:
    answer = _post(endpoint, json.dumps({
        "client_name": CLIENT_NAME, "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none",
    }).encode(), "application/json")
    if not answer.get("client_id"):
        raise OAuthError("dynamic client registration returned no client_id")
    return {"client_id": answer["client_id"], "client_secret": answer.get("client_secret"), "redirect_uri": redirect_uri}


def login(url: str, *, open_browser: Callable[[str], Any] = webbrowser.open, timeout: float = LOGIN_TIMEOUT,
          on_url: Callable[[str], Any] | None = None) -> str:
    """Run the whole sign-in for one server and store its tokens; returns the access token."""
    key = resource(url)
    meta = discover(url)
    entry = _load().get(key) or {}
    client = entry.get("client") if (entry.get("server") or {}).get("issuer") == meta["issuer"] else None
    listener = _listen(urllib.parse.urlsplit(client["redirect_uri"]).port or 0) if client else None
    if listener is None:   # no registration yet, or its redirect port is taken: register afresh
        listener = _listen(0)
        if listener is None:
            raise OAuthError("couldn't open a local port for the sign-in redirect")
        if not meta.get("registration_endpoint"):
            listener.server_close()
            raise OAuthError("the authorization server has no dynamic client registration, so ClydeCLI can't sign in by itself")
        try:
            client = _register(meta["registration_endpoint"], f"http://127.0.0.1:{listener.server_address[1]}/callback")
        except OAuthError:
            listener.server_close()
            raise
    try:
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        params = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": client["redirect_uri"],
                  "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": key}
        if meta.get("scope"):
            params["scope"] = meta["scope"]
        sep = "&" if "?" in meta["authorization_endpoint"] else "?"
        auth_url = meta["authorization_endpoint"] + sep + urllib.parse.urlencode(params)
        if on_url:
            on_url(auth_url)
        open_browser(auth_url)
        listener.timeout = 1
        deadline = time.time() + timeout
        while not listener.result and time.time() < deadline:   # type: ignore[attr-defined]
            listener.handle_request()
        result = listener.result   # type: ignore[attr-defined]
    finally:
        listener.server_close()
    if not result:
        raise OAuthError("sign-in timed out")
    if result.get("state") != state:
        raise OAuthError("the redirect's state didn't match; sign-in abandoned")
    if "code" not in result:
        raise OAuthError(f"sign-in refused: {result.get('error_description') or result.get('error')}")
    form = {"grant_type": "authorization_code", "code": result["code"], "redirect_uri": client["redirect_uri"],
            "client_id": client["client_id"], "code_verifier": verifier, "resource": key}
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    tokens = _token_record(_post_form(meta["token_endpoint"], form))
    with _lock:
        data = _load()
        data[key] = {"server": meta, "client": client, "tokens": tokens}
        _save(data)
    return tokens["access_token"]
