"""Connecting providers from the page: a key is tested before it is saved, never echoed back, and refused when it doesn't work."""
from __future__ import annotations

import json
import os
from unittest.mock import patch

from src.bonnie import providers
from src.providers import keys
from tests.bonnie import test_server as ts

KEY = "sk-test-0123456789abcdef"


class Fake:
    def __init__(self, name, models, available=True):
        self.name, self._models, self._available = name, models, available

    def is_available(self):
        return self._available

    def list_models(self):
        return list(self._models)


def registry_of(models_by_name):
    return lambda: {n: Fake(n, m) for n, m in models_by_name.items()}


class TestProviders(ts.BonnieCase):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in list(keys.PROVIDER_KEY_ENV.values()) + ["CLOUDFLARE_ACCOUNT_ID"]:
            os.environ.pop(name, None)
        keys.keys_file().unlink(missing_ok=True)
        self.addCleanup(keys.keys_file().unlink, missing_ok=True)

    def connect(self, provider="openai", key=KEY, **more):
        return self.call("POST", "/api/providers/connect", {"provider": provider, "key": key, **more})

    def saved(self):
        return json.loads(keys.keys_file().read_text()) if keys.keys_file().exists() else {}

    def test_the_list_has_every_provider_with_its_guide_and_nothing_connected(self):
        status, body = self.call("GET", "/api/providers")
        rows = {r["id"]: r for r in body["providers"]}
        self.assertEqual(status, 200)
        self.assertTrue({"anthropic", "openai", "google", "ollama-cloud", "cloudflare", "ollama", "lmstudio"} <= set(rows))
        self.assertTrue(all(r["url"].startswith("https://") for r in rows.values()))
        self.assertFalse(any(r["connected"] for r in rows.values() if r["kind"] == "key"))
        self.assertEqual(rows["cloudflare"]["extra"]["set"], False)

    def test_a_working_key_is_saved_connected_and_never_sent_back(self):
        with patch("src.bonnie.providers.build_registry", registry_of({"openai": ["gpt-a", "gpt-b"]})):
            status, body = self.connect()
            self.assertEqual((status, body["verified"], body["models"]), (200, True, ["gpt-a", "gpt-b"]))
            self.assertEqual(self.saved(), {"openai": KEY})
            self.assertEqual(os.environ["OPENAI_API_KEY"], KEY)
            listing = self.call("GET", "/api/providers")[1]
        row = next(r for r in listing["providers"] if r["id"] == "openai")
        self.assertEqual((row["connected"], row["source"]), (True, "saved"))
        self.assertNotIn(KEY, json.dumps(listing) + json.dumps(body))
        self.assertEqual(oct(keys.keys_file().stat().st_mode & 0o777), "0o600")

    def test_a_refused_key_is_not_saved_and_the_environment_is_put_back(self):
        os.environ["OPENAI_API_KEY"] = "old-key-in-the-shell"
        with patch("src.bonnie.providers.build_registry", registry_of({"openai": []})):
            status, body = self.connect()
        self.assertEqual(status, 400)
        self.assertNotIn(KEY, body["error"])
        self.assertEqual((self.saved(), os.environ["OPENAI_API_KEY"]), ({}, "old-key-in-the-shell"))

    def test_a_service_that_cannot_check_a_key_is_saved_as_unverified(self):
        with patch("src.bonnie.providers.build_registry", registry_of({"glm": ["glm-5"]})):
            status, body = self.connect("glm")
        self.assertEqual((status, body["verified"], self.saved()), (200, False, {"glm": KEY}))

    def test_malformed_keys_and_unknown_providers_are_refused_before_any_request(self):
        with patch("src.bonnie.providers.build_registry", side_effect=AssertionError("no request expected")):
            for bad in ("short", "has space inside-the-key", "naïve-key-0123456789", "x" * 513, "", None, 12345678):
                self.assertEqual(self.connect(key=bad)[0], 400, bad)
            self.assertEqual(self.connect("nope")[0], 400)
            self.assertEqual(self.call("POST", "/api/providers/connect", {"key": KEY})[0], 400)
        self.assertEqual(self.saved(), {})

    def test_cloudflare_needs_its_account_id_and_keeps_it(self):
        with patch("src.bonnie.providers.build_registry", registry_of({"cloudflare": ["@cf/model"]})):
            self.assertEqual(self.connect("cloudflare")[0], 400)
            self.assertEqual(self.connect("cloudflare", extra="abc123")[0], 200)
        self.assertEqual(os.environ["CLOUDFLARE_ACCOUNT_ID"], "abc123")

    def test_disconnect_forgets_a_saved_key_and_refuses_when_there_is_none(self):
        with patch("src.bonnie.providers.build_registry", registry_of({"openai": ["gpt-a"]})):
            self.connect()
            status, body = self.call("POST", "/api/providers/disconnect", {"provider": "openai"})
            self.assertEqual((status, body["from_shell"], self.saved()), (200, False, {}))
            self.assertEqual(self.call("POST", "/api/providers/disconnect", {"provider": "openai"})[0], 400)

    def test_nothing_changes_while_a_turn_runs(self):
        self.bonnie.control.busy = True
        self.assertEqual(self.connect()[0], 409)
        self.assertEqual(self.call("POST", "/api/providers/disconnect", {"provider": "openai"})[0], 409)
        self.bonnie.control.busy = False

    def test_a_custom_service_is_added_with_its_key_and_removed_again_when_the_key_fails(self):
        body = {"name": "together", "protocol": "openai", "base_url": "https://api.together.test/v1", "key": KEY}
        with patch("src.bonnie.providers.build_registry", registry_of({"together": []})):
            self.assertEqual(self.call("POST", "/api/providers/custom", body)[0], 400)
            self.assertNotIn("together", keys.custom_providers())
        with patch("src.bonnie.providers.build_registry", registry_of({"together": ["m1"]})):
            self.assertEqual(self.call("POST", "/api/providers/custom", body)[0], 200)
            self.addCleanup(keys.remove_custom, "together")
            self.assertEqual(self.call("GET", "/api/providers")[1]["custom"][0]["id"], "together")
        self.assertEqual(self.call("POST", "/api/providers/custom", {**body, "name": "openai"})[0], 400)


if __name__ == "__main__":
    import unittest
    unittest.main()
