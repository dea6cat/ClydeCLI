"""Provider protocol, shared response/error types, and stdlib HTTP helpers.

Every adapter implements Provider with canonical types in and out; the wire format
is private to each implementation. urllib (stdlib) throughout, so there are no
per-provider SDKs.
"""
from __future__ import annotations

import email.utils
import json
import threading
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

from .. import __version__, activity
from .toolspec import ToolSpec
from .types import Conversation, Message

# urllib's default "Python-urllib/x" User-Agent is blocked by some providers' bot filters
# (e.g. Cerebras's Cloudflare returns 403 "error code: 1010"), so every request carries a
# real one.
_USER_AGENT = f"clyde-cli/{__version__}"


@dataclass(slots=True)
class ProviderResponse:
    message: Message
    raw: dict  # untouched provider payload, for debugging only
    # Why generation stopped, when the provider reports it ("length", "stop", ...).
    done_reason: str | None = None
    # Prompt (input) tokens the provider counted for this request, when reported.
    prompt_tokens: int | None = None
    # Token usage when reported: {"input_tokens", "output_tokens", and cache fields if any}.
    # input_tokens excludes cache_read/cache_creation_input_tokens (Anthropic's split, all providers).
    usage: dict | None = None


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, *, retryable: bool = False, status: int | None = None,
                 retry_after: float | None = None):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after   # seconds the provider asked us to wait, when it said


# --- Abortable connections -------------------------------------------------
# A flag can't wake a thread blocked in a C-level socket read; the socket has to be
# closed. Every live response registers here so abort_all_connections() can close them
# all at once. A close mid-read raises OSError/ValueError in the blocked thread, which the
# helpers translate to _Cancelled when the caller's cancel Event is set.
_active_conns: set = set()
_conns_lock = threading.Lock()


class _Cancelled(Exception):
    """Raised by the HTTP helpers when their cancel Event is set, either before connecting or
    because abort_all_connections() closed the socket mid-read. Not a ProviderError, so
    stream_with_retry re-raises it immediately (never retries)."""


def _register(resp) -> None:
    with _conns_lock:
        _active_conns.add(resp)


def _unregister(resp) -> None:
    with _conns_lock:
        _active_conns.discard(resp)


def abort_all_connections() -> None:
    """Close every live HTTP response so any thread blocked reading one raises at once."""
    with _conns_lock:
        conns = list(_active_conns)
        _active_conns.clear()
    for resp in conns:
        try:
            resp.close()
        except Exception:
            pass


class Provider(Protocol):
    name: str

    def is_available(self) -> bool:
        """Cheap check: is this provider configured/reachable enough to offer?"""
        ...

    def list_models(self) -> list[str]:
        ...

    def stream(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...],
               on_text: Callable[[str], None], *, cancel=None, reasoning=None,
               on_thinking: Callable[[str], None] | None = None) -> ProviderResponse:
        ...


# Plain-language causes for provider HTTP errors, checked in order. Keyword matches run
# against the provider's own message so a 400/403/429 that is really "out of credits"
# (providers disagree on the status code) still reads as such.
_CREDIT_WORDS = ("credit", "balance", "billing", "payment", "quota", "insufficient funds")
_CONTEXT_WORDS = ("context length", "context window", "too long", "maximum context", "too many tokens",
                  "reduce the length")


def _error_text(body: str) -> str:
    """The provider's own message from a JSON error body (the shapes vary by service), else
    the raw body, collapsed to one line and capped."""
    text = body
    try:
        data = json.loads(body)
        err = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(err, dict):
            err = err.get("message") or err.get("detail") or data.get("message") or data.get("detail") or err
        if isinstance(err, str):
            text = err
    except (ValueError, AttributeError):
        pass
    text = " ".join(str(text).split())
    return text[:240] + ("…" if len(text) > 240 else "")


def http_error_message(code: int, body: str, reason: str) -> str:
    """One readable line for a provider HTTP error: `HTTP <code> — <cause>: <provider message>`."""
    msg = _error_text(body) if body.strip() else (reason or "")
    low = msg.lower()
    if code == 401 or (code in (400, 403) and any(w in low for w in _AUTH_WORDS)):
        hint = "authentication failed, check the API key (clyde login)"
    elif code == 402 or any(w in low for w in _CREDIT_WORDS):
        hint = "out of credits or billing not set up on this account"
    elif code == 403:
        hint = "access denied for this key"
    elif code == 404:
        hint = "model not found or not available to this account, try /models"
    elif code == 429:
        hint = "rate limited"
    elif code == 413 or any(w in low for w in _CONTEXT_WORDS):
        hint = "request too large for the model's context, try /compact"
    elif code >= 500:
        hint = "provider error, usually temporary"
    else:
        hint = ""
    return f"HTTP {code} — {hint}: {msg}" if hint else f"HTTP {code}: {msg}"


# How providers that don't answer 401 say the key itself is wrong (Google: 400 "API key not valid").
_AUTH_WORDS = ("api key not valid", "invalid api key", "invalid_api_key", "incorrect api key", "invalid x-api-key",
               "api key expired", "api_key_invalid", "invalid authentication", "invalid token", "unauthenticated")


def is_auth_error(exc: BaseException) -> bool:
    """A rejected key: any 401, or a 400/403 whose message says the key or token is bad."""
    if not isinstance(exc, ProviderError):
        return False
    return exc.status == 401 or (exc.status in (400, 403) and any(w in str(exc).lower() for w in _AUTH_WORDS))


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds from a Retry-After header: delta-seconds or an HTTP date; None when absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - (_time.time() if now is None else now))


def _http_error(e: urllib.error.HTTPError, provider: str) -> ProviderError:
    body = ""
    try:
        body = e.read().decode(errors="replace")[:4000]
    except Exception:
        pass
    return ProviderError(provider, http_error_message(e.code, body, e.reason),
                         retryable=(e.code == 429 or e.code >= 500), status=e.code,
                         retry_after=parse_retry_after(e.headers.get("Retry-After") if e.headers else None))


def _request(url: str, payload: dict, headers: dict | None) -> urllib.request.Request:
    hdrs = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    return urllib.request.Request(url, data=json.dumps(payload).encode(), headers=hdrs, method="POST")


# A remote stream that sends nothing for this long has stalled: give up instead of holding the turn
# for the full read timeout. Local servers keep 600 s, since loading a model can be that slow.
# ponytail: one fixed value; a per-provider setting if some endpoint legitimately idles longer.
STALL_TIMEOUT = 180
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _stall_timeout(url: str) -> int:
    return 600 if urllib.parse.urlsplit(url).hostname in _LOCAL_HOSTS else STALL_TIMEOUT


def _stalled(provider: str, timeout) -> ProviderError:
    # Not retried: a stalled endpoint usually stalls again, and cardShuffle re-deals on any error.
    return ProviderError(provider, f"no response for {timeout} s; the endpoint stalled. Try again or switch model")


def _open(req, timeout, provider, cancel):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except TimeoutError as e:                                       # waiting for the response headers
        raise _stalled(provider, timeout) from e
    except urllib.error.HTTPError as e:
        raise _http_error(e, provider) from e
    except urllib.error.URLError as e:
        if cancel is not None and cancel.is_set():
            raise _Cancelled() from e
        if isinstance(e.reason, TimeoutError):
            raise _stalled(provider, timeout) from e
        raise ProviderError(provider, f"connection failed: {e.reason}", retryable=True) from e


# Provider -> its last response's remaining-quota headers (x-ratelimit-remaining-tokens, anthropic-ratelimit-
# requests-remaining, ...), for the per-turn usage line. Empty for providers that don't send them.
RATE_LIMITS: dict[str, dict[str, str]] = {}


def _note_limits(resp, provider: str) -> None:
    headers = getattr(resp, "headers", None) or {}
    found = {k.lower(): v for k, v in headers.items() if "ratelimit" in k.lower() and "remaining" in k.lower()}
    if found:
        RATE_LIMITS[provider] = found


def remaining_quota(provider: str) -> str:
    """'812 requests left', from the provider's last rate-limit headers; '' when it sent none."""
    limits = RATE_LIMITS.get(provider, {})
    for unit in ("requests", "tokens"):
        value = next((v for k, v in limits.items() if unit in k and v.isdigit()), None)
        if value is not None:
            return f"{int(value):,} {unit} left"
    return ""


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 600,
              provider: str = "http", cancel=None) -> dict:
    """POST JSON, return parsed JSON. Raises ProviderError with a useful message, or
    _Cancelled if the cancel Event is set (before connecting or via an aborted socket)."""
    if cancel is not None and cancel.is_set():
        raise _Cancelled()
    resp = _open(_request(url, payload, headers), timeout, provider, cancel)
    _note_limits(resp, provider)
    _register(resp)
    try:
        with resp:
            return json.loads(resp.read())
    except (OSError, ValueError) as e:
        if cancel is not None and cancel.is_set():
            raise _Cancelled() from e
        raise ProviderError(provider, f"read failed: {e}", retryable=True) from e
    finally:
        _unregister(resp)


def post_stream(url: str, payload: dict, headers: dict | None = None, timeout: int | None = None,
                provider: str = "http", cancel=None):
    """POST JSON and yield decoded response lines as they arrive (NDJSON / SSE). Raises
    ProviderError on connection/HTTP failure or a stall (no bytes for `timeout`, by default
    STALL_TIMEOUT for remote hosts), or _Cancelled when the cancel Event is set."""
    if cancel is not None and cancel.is_set():
        raise _Cancelled()
    timeout = timeout or _stall_timeout(url)
    resp = _open(_request(url, payload, headers), timeout, provider, cancel)
    _note_limits(resp, provider)
    _register(resp)
    try:
        with resp:
            for raw in resp:
                if cancel is not None and cancel.is_set():
                    raise _Cancelled()
                yield raw.decode("utf-8", errors="replace")
    except (OSError, ValueError) as e:
        if cancel is not None and cancel.is_set():
            raise _Cancelled() from e
        if isinstance(e, TimeoutError):
            raise _stalled(provider, timeout) from e
        raise ProviderError(provider, f"stream read failed: {e}", retryable=True) from e
    finally:
        _unregister(resp)


MAX_RETRY_AFTER_WAIT_S = 30.0   # longer asks bench the card instead of stalling the turn


def stream_with_retry(provider, conversation, model, tools, on_text, *, retries=3, cancel=None,
                      reasoning=None, on_thinking=None) -> ProviderResponse:
    """provider.stream with backoff on retryable ProviderError (429/5xx/connection). Honors a
    cancel Event (re-raises immediately). When a retryable error survives every retry, the
    message gets a `— retried N×, still failing` suffix so it doesn't read as a single blip."""
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            return provider.stream(conversation, model, tools, on_text, cancel=cancel,
                                   reasoning=reasoning, on_thinking=on_thinking)
        except _Cancelled:
            raise
        except ProviderError as e:
            cancelled = cancel is not None and cancel.is_set()
            if not e.retryable or cancelled:
                raise
            if e.retry_after and e.retry_after > MAX_RETRY_AFTER_WAIT_S:
                raise   # waiting that long would stall the turn; the caller (cardShuffle) benches the model instead
            if attempt == retries:
                if attempt >= 1:
                    raw = str(e).removeprefix(f"[{e.provider}] ")
                    raise ProviderError(e.provider, f"{raw} — retried {attempt}×, still failing",
                                        retryable=True, status=e.status, retry_after=e.retry_after) from e
                raise
            delay = min(e.retry_after, MAX_RETRY_AFTER_WAIT_S) if e.retry_after else delay   # the provider's own ask beats our backoff
            activity.set(f"retry {attempt + 1} of {retries} in {delay:.0f}s: {str(e).removeprefix(f'[{e.provider}] ')[:70]}")
            waited = 0.0
            while waited < delay:
                if cancel is not None and cancel.is_set():
                    raise
                _time.sleep(0.1)
                waited += 0.1
            delay = min(delay * 2, 8.0)
    raise AssertionError("unreachable")


MODELS_TTL = 60  # seconds to cache a provider's live model list


def cached_model_list(provider, fetch) -> list[str]:
    """A provider's live model list via `fetch()`, cached on the provider for MODELS_TTL. On
    failure (down, blocked, bad/absent key) returns [] and caches nothing, so the next call
    retries. Never a stale hardcoded guess."""
    cache = getattr(provider, "_models_cache", None)
    if cache is not None and _time.monotonic() - cache[0] < MODELS_TTL:
        return cache[1]
    try:
        models = fetch()
    except Exception:
        return []
    provider._models_cache = (_time.monotonic(), models)
    return models


def get_json(url: str, headers: dict | None = None, timeout: int = 15, provider: str = "http") -> dict:
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error(e, provider) from e
    except urllib.error.URLError as e:
        raise ProviderError(provider, f"connection failed: {e.reason}", retryable=True) from e
