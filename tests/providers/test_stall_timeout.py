"""A remote stream that goes quiet fails fast with a clear error instead of holding the turn for 600 s."""

from __future__ import annotations

import http.server
import threading
import time
import unittest

from src.providers.base import STALL_TIMEOUT, ProviderError, _stall_timeout, post_stream


class _Stalling(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/after-first-line":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: one\n")
            self.wfile.flush()
        time.sleep(3)                                   # then nothing: the stall

    def log_message(self, *args):
        pass


class TestStallTimeout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stalling)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _stall(self, path):
        lines, started = [], time.monotonic()
        with self.assertRaises(ProviderError) as caught:
            lines.extend(post_stream(self.base + path, {}, timeout=1, provider="nvidia"))
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertIn("no response for 1 s", str(caught.exception))
        self.assertFalse(caught.exception.retryable)    # not retried 3 more times
        return lines

    def test_a_stall_before_any_response(self):
        self.assertEqual(self._stall("/before-headers"), [])

    def test_a_stall_mid_stream(self):
        self.assertEqual(self._stall("/after-first-line"), ["data: one\n"])

    def test_remote_hosts_get_the_short_wait_local_ones_keep_600(self):
        self.assertEqual(_stall_timeout("https://integrate.api.nvidia.com/v1/chat/completions"), STALL_TIMEOUT)
        self.assertEqual(_stall_timeout("http://localhost:11434/api/chat"), 600)
        self.assertEqual(_stall_timeout("http://127.0.0.1:1234/v1/chat/completions"), 600)


if __name__ == "__main__":
    unittest.main()
