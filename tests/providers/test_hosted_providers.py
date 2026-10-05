"""Cloudflare Workers AI and Pollinations: model listing, availability, the per-account base URL, and the
account-id setting that login saves (no network)."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src.cli import run_login_flow
from src.providers import cloudflare, keys, pollinations
from src.providers.cloudflare import CloudflareProvider
from src.providers.pollinations import PollinationsProvider
from src.providers.types import Conversation, Message
from tests.fakes import FakeProvider

ACCOUNT, TOKEN = "a" * 32, "cf-token"


def _model(name, tools=None):
    props = [] if tools is None else [{"property_id": "function_calling", "value": tools}]
    return {"name": name, "task": {"name": "Text Generation"}, "properties": props}


class TestCloudflare(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": TOKEN, "CLOUDFLARE_ACCOUNT_ID": ACCOUNT})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = CloudflareProvider()

    def test_the_base_url_carries_the_account_id_and_cannot_be_overwritten(self):
        self.assertEqual(self.provider.base_url, f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/v1")
        self.provider.base_url = "https://elsewhere"
        self.assertTrue(self.provider.base_url.endswith(f"{ACCOUNT}/ai/v1"))

    def test_it_needs_both_the_token_and_the_account_id(self):
        self.assertTrue(self.provider.is_available())
        for missing in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
            with patch.dict(os.environ, {missing: ""}):
                self.assertFalse(CloudflareProvider().is_available(), missing)

    def test_only_models_with_function_calling_are_listed(self):
        rows = [_model("@cf/b/with-tools", "true"), _model("@cf/a/no-tools", "false"), _model("@cf/c/also-tools", "True")]
        with patch.object(cloudflare, "get_json", return_value={"result": rows}) as get:
            self.assertEqual(self.provider.list_models(), ["@cf/b/with-tools", "@cf/c/also-tools"])
        url = get.call_args.args[0]
        self.assertIn(f"/accounts/{ACCOUNT}/ai/models/search?", url)
        self.assertIn("task=Text+Generation", url)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], f"Bearer {TOKEN}")

    def test_nothing_is_dropped_when_the_catalog_has_no_function_calling_field(self):
        with patch.object(cloudflare, "get_json", return_value={"result": [_model("@cf/b/x"), _model("@cf/a/y")]}):
            self.assertEqual(self.provider.list_models(), ["@cf/a/y", "@cf/b/x"])

    def test_it_reads_every_page_until_one_comes_up_short(self):
        full = [_model(f"@cf/m/{i:03d}", "true") for i in range(cloudflare._PER_PAGE)]
        pages = iter([{"result": full}, {"result": [_model("@cf/z/last", "true")]}])
        with patch.object(cloudflare, "get_json", side_effect=lambda *a, **k: next(pages)) as get:
            models = self.provider.list_models()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(models), cloudflare._PER_PAGE + 1)

    def test_chat_goes_to_the_openai_compatible_route_of_the_account(self):
        with patch("src.providers.openai_compat.post_stream", return_value=iter([])) as stream:
            try:
                self.provider.stream(Conversation("sys", [Message.user("hi")]), "@cf/moonshotai/kimi-k2.6", (), lambda _t: None)
            except Exception:
                pass   # an empty stream is not a reply; only where it was sent matters here
        self.assertEqual(stream.call_args.args[0], f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/v1/chat/completions")


class TestPollinations(unittest.TestCase):
    def test_it_lists_only_official_tool_capable_text_models(self):
        rows = [{"id": "openai/gpt-5.4-nano", "category": "text"}, {"id": "black-forest-labs/flux.2-pro", "category": "image"},
                {"id": "qwen/qwen3guard-gen-8b", "category": "text"}, {"id": "anthropic/claude-sonnet-5", "category": "text"}]
        with patch.dict(os.environ, {"POLLINATIONS_API_KEY": "sk_x"}), \
                patch.object(pollinations, "get_json", return_value={"data": rows}) as get:
            models = PollinationsProvider().list_models()
        self.assertEqual(models, ["anthropic/claude-sonnet-5", "openai/gpt-5.4-nano"])
        url = get.call_args.args[0]
        self.assertTrue(url.startswith("https://gen.pollinations.ai/v1/models?"))
        for part in ("capabilities=tool_calling", "source=official"):
            self.assertIn(part, url)

    def test_it_is_available_with_a_key_only(self):
        with patch.dict(os.environ, {"POLLINATIONS_API_KEY": ""}):
            self.assertFalse(PollinationsProvider().is_available())
        with patch.dict(os.environ, {"POLLINATIONS_API_KEY": "sk_x"}):
            self.assertTrue(PollinationsProvider().is_available())


class _Home(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = {v: "" for v in [*keys.PROVIDER_KEY_ENV.values(), "CLOUDFLARE_ACCOUNT_ID"]}
        for p in (patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, env)):
            p.start()
            self.addCleanup(p.stop)


class TestAccountSetting(_Home):
    def test_it_is_saved_in_settings_and_loaded_without_beating_the_shell(self):
        self.assertIsNone(keys.connect_setting("cloudflare", "acct-1"))
        saved = json.loads((self.home / ".clyde" / "settings.json").read_text())
        self.assertEqual(saved["providerSettings"], {"cloudflare": {"CLOUDFLARE_ACCOUNT_ID": "acct-1"}})
        os.environ.pop("CLOUDFLARE_ACCOUNT_ID")
        keys.load_into_env()
        self.assertEqual(os.environ["CLOUDFLARE_ACCOUNT_ID"], "acct-1")
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "from-the-shell"
        keys.load_into_env()
        self.assertEqual(os.environ["CLOUDFLARE_ACCOUNT_ID"], "from-the-shell")

    def test_other_settings_and_providers_are_kept(self):
        keys.add_custom("together", "https://api.together.xyz/v1")
        keys.connect_setting("cloudflare", "acct-1")
        self.assertEqual(keys.custom_providers(), {"together": "https://api.together.xyz/v1"})

    def test_the_account_id_is_not_listed_as_a_saved_key(self):
        keys.connect_setting("cloudflare", "acct-1")
        self.assertNotIn("cloudflare", keys.saved_providers())


class TestLogin(_Home):
    def test_cloudflare_login_asks_for_the_account_id_after_the_token(self):
        provider = FakeProvider(name="cloudflare", models=("@cf/moonshotai/kimi-k2.6",))
        answers = iter(["acct-9"])
        with patch("src.cli.pick", side_effect=["cloudflare", "@cf/moonshotai/kimi-k2.6"]), \
                patch("src.cli.prompt_secret", return_value=TOKEN), \
                patch("src.cli.Prompt.ask", side_effect=lambda *a, **k: next(answers)), \
                patch("src.providers.build_registry", return_value={"cloudflare": provider}):
            ref = run_login_flow(Console(file=io.StringIO()), {"cloudflare": provider})
        self.assertEqual(ref, "cloudflare:@cf/moonshotai/kimi-k2.6")
        self.assertEqual((os.environ["CLOUDFLARE_API_TOKEN"], os.environ["CLOUDFLARE_ACCOUNT_ID"]), (TOKEN, "acct-9"))
        self.assertIn("cloudflare", keys.saved_providers())

    def test_an_empty_account_id_stops_the_login(self):
        with patch("src.cli.pick", return_value="cloudflare"), patch("src.cli.prompt_secret", return_value=TOKEN), \
                patch("src.cli.Prompt.ask", return_value="  "):
            self.assertIsNone(run_login_flow(Console(file=io.StringIO()), {"cloudflare": FakeProvider(name="cloudflare")}))

    def test_pollinations_login_needs_only_the_key(self):
        provider = FakeProvider(name="pollinations", models=("openai/gpt-5.4-nano",))
        with patch("src.cli.pick", side_effect=["pollinations", "openai/gpt-5.4-nano"]), \
                patch("src.cli.prompt_secret", return_value="sk_abc"), \
                patch("src.cli.Prompt.ask") as ask, \
                patch("src.providers.build_registry", return_value={"pollinations": provider}):
            ref = run_login_flow(Console(file=io.StringIO()), {"pollinations": provider})
        self.assertEqual(ref, "pollinations:openai/gpt-5.4-nano")
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
