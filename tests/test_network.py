"""/proxy and the company certificate: what each setting writes into the environment Clyde and its children use."""

from __future__ import annotations

import os
import ssl
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from src import config, network


class TestNetwork(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        for p in (patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "HOME": home}), patch.object(Path, "home", return_value=Path(home))):
            p.start()
            self.addCleanup(p.stop)
        self.home = Path(home)

    def test_system_keeps_the_environment_proxy_but_never_sends_this_machines_servers_to_it(self):
        env = {"HTTPS_PROXY": "http://proxy.corp:8080", "NO_PROXY": "intranet.corp"}
        network.apply(env)
        self.assertEqual(env["HTTPS_PROXY"], "http://proxy.corp:8080")
        self.assertEqual(env["NO_PROXY"], "intranet.corp,localhost,127.0.0.1,::1")   # Ollama and oMLX stay direct
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(urllib.request.proxy_bypass("localhost:11434"))
            self.assertFalse(urllib.request.proxy_bypass("api.openai.com"))

    def test_without_any_proxy_nothing_is_written(self):
        env: dict[str, str] = {}
        network.apply(env)
        self.assertEqual(env, {})

    def test_a_saved_url_is_used_for_everything_and_off_goes_direct_whatever_the_environment_says(self):
        network.set_proxy("http://proxy.corp:8080")
        env: dict[str, str] = {}
        network.apply(env)
        self.assertEqual({env[v] for v in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")}, {"http://proxy.corp:8080"})
        network.set_proxy("off")
        env = {"HTTPS_PROXY": "http://proxy.corp:8080", "ALL_PROXY": "http://proxy.corp:8080"}
        network.apply(env)
        self.assertEqual(env, {"NO_PROXY": "*", "no_proxy": "*"})
        self.assertEqual(network.proxy_choices(), ("system", "off", "http://proxy.corp:8080"))   # /settings can go back to it

    def test_socks_and_passwords_are_refused_and_nothing_is_saved(self):
        for bad in ("socks5://127.0.0.1:1080", "http://me:secret@proxy:8080", "proxy.corp:8080"):
            with self.assertRaises(ValueError):
                network.set_proxy(bad)
        self.assertEqual(network.get_proxy(), "system")
        self.assertNotIn("secret", str(config.load_config()))

    def test_doctor_never_shows_a_proxy_password(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://me:secret@proxy.corp:8080"}, clear=True):
            proxy, _ = network.describe()
        self.assertNotIn("secret", proxy)
        self.assertIn("proxy.corp:8080", proxy)

    def test_a_company_certificate_is_added_to_the_default_roots_not_put_in_their_place(self):
        ca = self.home / "corp-root.pem"
        default = ssl.get_default_verify_paths().cafile
        if not default or not Path(default).is_file():
            self.skipTest("no default CA file on this machine")
        ca.write_text(Path(default).read_text().split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n")
        network.set_ca(str(ca))
        env: dict[str, str] = {}
        network.apply(env)
        bundle = Path(env["SSL_CERT_FILE"])
        self.assertEqual({env[v] for v in network.CA_VARS}, {str(bundle)})
        self.assertEqual(env["NODE_EXTRA_CA_CERTS"], str(ca.resolve()))
        self.assertGreater(bundle.read_text().count("BEGIN CERTIFICATE"), 1)   # the roots, then the company's
        self.assertEqual(network.ca_choices(), ("off", str(ca.resolve())))

    def test_a_file_that_isnt_a_certificate_is_refused(self):
        bad = self.home / "notes.txt"
        bad.write_text("not a certificate")
        with self.assertRaises(ValueError):
            network.set_ca(str(bad))
        self.assertIsNone(network.get_ca())

    def test_an_untrusted_certificate_says_how_to_fix_it_and_is_not_retried(self):
        import urllib.error
        from src.providers import base
        bad = ssl.SSLCertVerificationError(1, "certificate verify failed")
        bad.verify_message = "unable to get local issuer certificate"
        error = base._connection_failed(urllib.error.URLError(bad), "openai")
        self.assertIn("certificate not trusted (unable to get local issuer certificate)", str(error))
        self.assertIn("/proxy ca <file>", str(error))
        self.assertFalse(error.retryable)
        self.assertTrue(base._connection_failed(urllib.error.URLError(ConnectionRefusedError()), "openai").retryable)


if __name__ == "__main__":
    unittest.main()
