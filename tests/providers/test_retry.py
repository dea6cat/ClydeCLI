import os, sys, unittest
from src.providers import base
from src.providers.base import ProviderError, ProviderResponse
from src.providers.types import Conversation, Message
class Retry(unittest.TestCase):
    def setUp(self):
        self._orig_sleep = base._time.sleep
        base._time.sleep = lambda *_: None   # no real backoff in tests

    def tearDown(self):
        base._time.sleep = self._orig_sleep   # base._time IS the stdlib time module;
        # leaving it patched would break other tests' real-timing assertions.
    def test_retries_then_succeeds(self):
        calls = {"n": 0}
        class P:
            name="x"
            def stream(self, c, m, t, on_text, *, cancel=None, **_kwargs):
                calls["n"] += 1
                if calls["n"] < 3: raise ProviderError("x", "HTTP 429: slow down", retryable=True)
                return ProviderResponse(message=Message.assistant(text="ok"), raw={})
        r = base.stream_with_retry(P(), Conversation(system_prompt="s"), "m", (), lambda _c: None, retries=3)
        self.assertEqual(r.message.text, "ok"); self.assertEqual(calls["n"], 3)
    def test_non_retryable_raises_immediately(self):
        class P:
            name="x"
            def stream(self, c,m,t,on_text, *, cancel=None, **_kwargs): raise ProviderError("x","HTTP 400: bad", retryable=False)
        with self.assertRaises(ProviderError):
            base.stream_with_retry(P(), Conversation(system_prompt="s"), "m", (), lambda _c: None, retries=3)

    def test_exhausted_retries_annotates_message(self):
        class P:
            name="nvidia"
            def stream(self, c,m,t,on_text, *, cancel=None, **_kwargs): raise ProviderError("nvidia","HTTP 504: Gateway Timeout", retryable=True)
        with self.assertRaises(ProviderError) as ctx:
            base.stream_with_retry(P(), Conversation(system_prompt="s"), "m", (), lambda _c: None, retries=3)
        # Provider prefix isn't duplicated, and the retry count is surfaced.
        self.assertEqual(str(ctx.exception), "[nvidia] HTTP 504: Gateway Timeout — retried 3×, still failing")

    def test_retry_after_header_parses_seconds_and_dates(self):
        self.assertEqual(base.parse_retry_after("12"), 12.0)
        self.assertEqual(base.parse_retry_after("Wed, 21 Oct 2015 07:28:30 GMT", now=1445412510 - 30), 30.0)
        self.assertIsNone(base.parse_retry_after("soon"))
        self.assertIsNone(base.parse_retry_after(None))

    def test_http_429_carries_the_retry_after_the_provider_sent(self):
        import io, urllib.error
        from email.message import Message as Headers
        headers = Headers()
        headers["Retry-After"] = "20"
        err = urllib.error.HTTPError("http://x", 429, "Too Many", headers, io.BytesIO(b"{}"))
        self.assertEqual(base._http_error(err, "x").retry_after, 20.0)

    def test_a_retry_after_longer_than_the_cap_is_not_retried(self):
        calls = []
        class P:
            name = "x"
            def stream(self, c, m, t, on_text, *, cancel=None, **_kwargs):
                calls.append(1)
                raise ProviderError("x", "HTTP 429: limit", retryable=True, status=429, retry_after=600)
        with self.assertRaises(ProviderError) as ctx:
            base.stream_with_retry(P(), Conversation(system_prompt="s"), "m", (), lambda _c: None, retries=3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(ctx.exception.retry_after, 600)

    def test_no_retries_left_is_not_annotated(self):
        # retries=0 means we never actually retried, so no "retried N×" suffix.
        class P:
            name="x"
            def stream(self, c,m,t,on_text, *, cancel=None, **_kwargs): raise ProviderError("x","HTTP 503: down", retryable=True)
        with self.assertRaises(ProviderError) as ctx:
            base.stream_with_retry(P(), Conversation(system_prompt="s"), "m", (), lambda _c: None, retries=0)
        self.assertEqual(str(ctx.exception), "[x] HTTP 503: down")
