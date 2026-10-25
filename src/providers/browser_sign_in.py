"""Browser sign-in for providers that run a Mistral-Vibe-style sign-in endpoint.

PKCE-based browser sign-in, not generic OAuth:

1. Generate a PKCE code verifier + challenge (SHA-256, base64url).
2. POST the challenge to the provider's sign-in endpoint
   (``{api_base}/vibe/sign-in``), which returns a ``process_id``, a
   ``sign_in_url`` and a ``poll_url``.
3. Open the browser on ``sign_in_url``; the user signs in to the provider's
   console there.
4. Poll ``poll_url`` until status is ``completed`` (returns an
   ``exchange_token``), ``expired``/``denied``/``error``.
5. POST ``{exchange_token, code_verifier}`` to
   ``{api_base}/vibe/sign-in/{process_id}/exchange`` to receive an API key.
6. Save the key via :func:`src.providers.keys.connect`.

Only works for providers that run this specific server-side sign-in endpoint
(Mistral's console). It is not generic OAuth -- each provider needs its own
sign-in / exchange endpoints. Stdlib only (urllib), matching ClydeCLI's HTTP
style.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .base import _USER_AGENT

LOGIN_TIMEOUT = 300   # seconds to finish signing in the browser
POLL_INTERVAL = 3.0   # seconds between poll attempts


class BrowserSignInError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class BrowserSignInProcess:
    process_id: str
    sign_in_url: str
    poll_url: str
    expires_at: float  # unix timestamp deadline


@dataclass(slots=True)
class BrowserSignInPollResult:
    status: Literal["pending", "completed", "expired", "denied", "error"]
    exchange_token: str | None = None
    message: str | None = None


class BrowserSignInGateway:
    """HTTP client for a provider's browser sign-in endpoints (stdlib urllib)."""

    def __init__(
        self,
        browser_base_url: str,
        api_base_url: str,
        timeout: float = 30.0,
    ) -> None:
        self._browser_base_url = browser_base_url.rstrip("/")
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout

    def _agent(self) -> dict[str, str]:
        return {"User-Agent": _USER_AGENT}

    def _post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                **self._agent(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                raw = r.read() or b"null"
        except urllib.error.HTTPError as e:
            raise BrowserSignInError("request failed", code="http_error") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise BrowserSignInError(f"unreachable: {e}", code="unreachable") from e
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise BrowserSignInError("invalid json", code="invalid_json") from e
        if not isinstance(data, dict):
            raise BrowserSignInError("expected json object", code="invalid_json")
        return data

    def _get_json(self, url: str) -> dict[str, object] | None:
        req = urllib.request.Request(
            url, headers={**self._agent(), "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                raw = r.read() or b"null"
        except urllib.error.HTTPError as e:
            if e.code == 410:
                return None
            raise BrowserSignInError("poll failed", code="poll_failed") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise BrowserSignInError(f"poll unreachable: {e}", code="poll_failed") from e
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise BrowserSignInError("invalid json", code="invalid_json") from e
        if not isinstance(data, dict):
            return None
        return data

    def create_process(self, code_challenge: str) -> BrowserSignInProcess:
        data = self._post_json(
            f"{self._api_base_url}/vibe/sign-in",
            {"code_challenge": code_challenge, "code_challenge_method": "S256"},
        )
        try:
            expires_at = _parse_expires_at(str(data["expires_at"]))
        except (KeyError, ValueError, TypeError) as e:
            raise BrowserSignInError("missing expires_at", code="bad_payload") from e
        return BrowserSignInProcess(
            process_id=str(data["process_id"]),
            sign_in_url=str(data["sign_in_url"]),
            poll_url=str(data["poll_url"]),
            expires_at=expires_at,
        )

    def poll(self, poll_url: str) -> BrowserSignInPollResult:
        data = self._get_json(poll_url)
        if data is None:
            return BrowserSignInPollResult(status="expired")
        status = data.get("status")
        if status not in ("pending", "completed", "expired", "denied", "error"):
            raise BrowserSignInError("unknown sign-in state", code="unknown_state")
        return BrowserSignInPollResult(
            status=status,
            exchange_token=data.get("exchange_token"),
            message=data.get("message"),
        )

    def exchange(
        self, process_id: str, exchange_token: str, code_verifier: str
    ) -> str:
        data = self._post_json(
            f"{self._api_base_url}/vibe/sign-in/{process_id}/exchange",
            {"exchange_token": exchange_token, "code_verifier": code_verifier},
        )
        api_key = data.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise BrowserSignInError(
                "exchange returned no api key", code="missing_api_key"
            )
        return api_key


class BrowserSignInService:
    _max_consecutive_poll_failures = 3

    def __init__(
        self,
        gateway: BrowserSignInGateway,
        *,
        open_browser: Callable[[str], bool] | None = None,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self._gateway = gateway
        self._open_browser = open_browser or webbrowser.open
        self._poll_interval = poll_interval

    def authenticate(self) -> str:
        verifier = _generate_code_verifier()
        challenge = _generate_code_challenge(verifier)
        process = self._gateway.create_process(challenge)
        self._open_browser_or_raise(process.sign_in_url)
        return self._complete(process, verifier)

    def _complete(self, process: BrowserSignInProcess, verifier: str) -> str:
        consecutive_poll_failures = 0
        while time.time() < process.expires_at:
            try:
                result = self._gateway.poll(process.poll_url)
            except BrowserSignInError as err:
                # A transient poll failure (network blip, 5xx) is recoverable;
                # mirror Mistral Vibe's tolerance of 3 in a row before giving up.
                if err.code != "poll_failed":
                    raise
                consecutive_poll_failures += 1
                if consecutive_poll_failures >= self._max_consecutive_poll_failures:
                    raise
                self._sleep_until_next_poll_or_timeout(process.expires_at)
                continue

            consecutive_poll_failures = 0
            if result.status == "completed":
                if not result.exchange_token:
                    raise BrowserSignInError(
                        "sign-in completed but no exchange token",
                        code="missing_exchange_token",
                    )
                return self._gateway.exchange(process.process_id, result.exchange_token, verifier)
            if result.status in ("expired", "denied", "error"):
                raise BrowserSignInError(
                    result.message or f"sign-in {result.status}", code=result.status
                )
            self._sleep_until_next_poll_or_timeout(process.expires_at)
        raise BrowserSignInError("sign-in timed out", code="timed_out")

    def _sleep_until_next_poll_or_timeout(self, expires_at: float) -> None:
        remaining = expires_at - time.time()
        if remaining <= 0:
            raise BrowserSignInError("sign-in timed out", code="timed_out")
        time.sleep(min(self._poll_interval, remaining))

    def _open_browser_or_raise(self, sign_in_url: str) -> None:
        try:
            opened = self._open_browser(sign_in_url)
        except OSError as err:
            raise BrowserSignInError(
                "failed to open browser for sign-in", code="open_browser_failed"
            ) from err
        if not opened:
            raise BrowserSignInError(
                "failed to open browser for sign-in", code="open_browser_failed"
            )


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _parse_expires_at(value: str) -> float:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    return dt.timestamp()


def login(
    browser_base_url: str,
    api_base_url: str,
    *,
    open_browser: Callable[[str], bool] | None = None,
    timeout: float = LOGIN_TIMEOUT,
) -> str:
    """Run the full browser sign-in and return the API key."""
    gateway = BrowserSignInGateway(browser_base_url, api_base_url)
    service = BrowserSignInService(gateway, open_browser=open_browser)

    def run() -> str:
        return service.authenticate()

    # The CLI is synchronous; run the blocking sign-in loop directly.
    return run()


# Provider -> (browser base url, api base url) for browser sign-in. Only
# providers that run the Mistral-Vibe sign-in endpoint belong here.
PROVIDER_BROWSER_AUTH: dict[str, tuple[str, str]] = {
    "mistral": ("https://console.mistral.ai", "https://console.mistral.ai/api"),
}
