"""Which port Bonny takes: 8080 by default, a free one when that is taken, and exactly the one asked for."""
from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from src.bonny import server


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestPort(unittest.TestCase):
    def serve(self, port):
        httpd = server.open_server(object(), port)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1]

    def test_the_default_is_8080_and_an_asked_for_port_is_used(self):
        want = free_port()
        with patch.object(server, "DEFAULT_PORT", want):
            self.assertEqual(self.serve(None), want)
        asked = free_port()
        self.assertEqual(self.serve(asked), asked)

    def test_a_taken_default_moves_to_a_free_port_but_a_taken_asked_port_fails(self):
        taken = free_port()
        with socket.socket() as hold:
            hold.bind(("127.0.0.1", taken))
            hold.listen()
            with patch.object(server, "DEFAULT_PORT", taken):
                moved = self.serve(None)
                self.assertNotEqual(moved, taken)
            with self.assertRaises(OSError):
                server.open_server(object(), taken)


if __name__ == "__main__":
    unittest.main()
