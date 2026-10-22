"""oMLX: a key only Clyde holds, Clyde's planned window applied before load, the server started with the key in its environment."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.providers import omlx
from src.providers.base import ProviderError

GB = 1024 ** 3


class TestOMLX(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        home = patch.object(omlx, "home", return_value=Path(self.tmp) / "omlx")
        home.start()
        self.addCleanup(home.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("OMLX_API_KEY", None)
        self.provider = omlx.OMLXProvider()

    def test_the_server_key_is_made_once_and_only_the_owner_can_read_it(self):
        key = omlx.server_key()
        self.assertGreaterEqual(len(key), 40)
        self.assertEqual(omlx.server_key(), key)
        self.assertEqual(stat.S_IMODE((Path(self.tmp) / "omlx" / "api_key").stat().st_mode), 0o600)

    def test_requests_carry_the_key_once_omlx_is_installed(self):
        with patch.object(omlx, "_exe", return_value="/bin/omlx"):
            self.assertEqual(self.provider._headers()["Authorization"], f"Bearer {omlx.server_key()}")
        with patch.object(omlx, "_exe", return_value="/bin/omlx"), patch.dict(os.environ, {"OMLX_API_KEY": "mine"}):
            self.assertEqual(self.provider.api_key, "mine")   # a server you run yourself

    def test_the_server_starts_with_the_key_in_its_environment_not_its_command_line(self):
        with patch.object(omlx, "_exe", return_value="/bin/omlx"), \
                patch.object(self.provider, "_server_up", side_effect=[False, True]), \
                patch.object(omlx.subprocess, "Popen") as popen:
            self.provider._ensure_server()
        argv, kwargs = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual(argv[:2], ["/bin/omlx", "serve"])
        self.assertEqual(argv[argv.index("--memory-guard") + 1], "balanced")
        self.assertNotIn(omlx.server_key(), " ".join(argv))
        self.assertEqual(kwargs["env"]["OMLX_API_KEY"], omlx.server_key())
        self.assertEqual(kwargs["env"]["HF_HUB_OFFLINE"], "0")   # laya_client's offline default must not reach oMLX's downloader

    def test_not_installed_and_nobody_to_ask_never_installs(self):
        with patch.object(omlx, "_exe", return_value=None), patch.object(self.provider, "_server_up", return_value=False), \
                patch.object(omlx, "install") as install:
            with self.assertRaises(ProviderError):
                self.provider._ensure_server()
        install.assert_not_called()

    def test_your_own_server_is_never_replaced(self):
        with patch.object(self.provider, "_server_up", return_value=False), patch.dict(os.environ, {"OMLX_API_KEY": "mine"}), \
                patch.object(omlx.subprocess, "Popen") as popen:
            with self.assertRaises(ProviderError):
                self.provider._ensure_server()
        popen.assert_not_called()

    def test_the_planned_window_is_set_before_loading_and_only_once(self):
        folder = Path(self.tmp) / "m"
        folder.mkdir()
        (folder / "config.json").write_text(json.dumps({"num_hidden_layers": 36, "num_attention_heads": 32,
                                                         "num_key_value_heads": 8, "head_dim": 128}))
        entry = {"id": "Qwen3-8B-4bit", "model_path": str(folder), "estimated_size": 4 * GB, "model_context_length": 40960,
                 "loaded": False}
        calls = []
        with patch.object(self.provider, "_status", return_value=[entry]), patch.object(omlx, "fixed_window", return_value=None), \
                patch.object(omlx.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(omlx, "post_json", side_effect=lambda url, payload, **kw: calls.append((kw["method"], url, payload))):
            self.provider.ensure_loaded("Qwen3-8B-4bit")
            self.provider.ensure_loaded("Qwen3-8B-4bit")
        (method, url, payload), load = calls
        self.assertEqual((method, url.endswith("/admin/api/models/Qwen3-8B-4bit/settings")), ("PUT", True))
        self.assertTrue(omlx.WINDOW_FLOOR <= payload["max_context_window"] <= omlx.MAX_WINDOW)
        self.assertTrue(load[1].endswith("/v1/models/Qwen3-8B-4bit/load"))

    def test_context_window_is_what_the_server_serves(self):
        with patch.object(omlx, "get_json", return_value={"data": [{"id": "m", "max_model_len": 16384}]}):
            self.assertEqual(self.provider.context_window("m"), 16384)

    def test_lmstudio_models_join_omlx_folders_once_and_omlx_keeps_its_own(self):
        lms, settings = Path(self.tmp) / "lms-models", Path(self.tmp) / "omlx-settings.json"
        lms.mkdir()
        settings.write_text(json.dumps({"server": {"port": 8000}}))
        with patch.object(omlx, "LMSTUDIO_MODELS", lms), patch.object(omlx, "settings_file", return_value=settings):
            self.assertTrue(omlx.adopt_lmstudio_models())
            self.assertFalse(omlx.adopt_lmstudio_models())
        data = json.loads(settings.read_text())
        self.assertEqual(data["server"], {"port": 8000})
        self.assertEqual(data["model"]["model_dirs"], [str(Path.home() / ".omlx" / "models"), str(lms)])

    def test_an_unreadable_omlx_settings_file_is_left_alone(self):
        lms, settings = Path(self.tmp) / "lms-models", Path(self.tmp) / "omlx-settings.json"
        lms.mkdir()
        settings.write_text("{not json")
        with patch.object(omlx, "LMSTUDIO_MODELS", lms), patch.object(omlx, "settings_file", return_value=settings):
            self.assertFalse(omlx.adopt_lmstudio_models())
        self.assertEqual(settings.read_text(), "{not json")

    def test_each_memory_guard_choice_becomes_serve_arguments(self):
        with patch("src.providers.ollama._total_ram_bytes", return_value=18 * GB):
            choices = omlx.memory_guard_choices()
        self.assertEqual(choices, ("balanced", "aggressive", "custom 7 GB", "custom 9 GB", "custom 10 GB", "off"))
        self.assertEqual(omlx.memory_guard_args("custom 9 GB"), ["--memory-guard-gb", "9"])
        self.assertEqual(omlx.memory_guard_args("off"), ["--memory-guard", "off"])
        self.assertEqual(omlx.memory_guard_args(None), ["--memory-guard", "balanced"])
        self.assertEqual(omlx.memory_guard_args("custom lots GB"), ["--memory-guard", "balanced"])

    def test_the_server_starts_with_the_guard_picked_in_settings_and_its_pid_is_kept(self):
        with patch.object(omlx, "_exe", return_value="/bin/omlx"), patch.object(self.provider, "_server_up", side_effect=[False, True]), \
                patch("src.config.get_omlx_memory_guard", return_value="aggressive"), \
                patch.object(omlx.subprocess, "Popen") as popen:
            popen.return_value.pid = 4242
            self.provider._ensure_server()
        argv = popen.call_args.args[0]
        self.assertEqual(argv[argv.index("--memory-guard") + 1], "aggressive")
        self.assertEqual((Path(self.tmp) / "omlx" / "server.pid").read_text(), "4242")

    def test_stopping_touches_only_the_omlx_server_clyde_started(self):
        pid_file = Path(self.tmp) / "omlx" / "server.pid"
        pid_file.parent.mkdir(parents=True)
        for name, stopped in (("/usr/bin/vim", False), ("omlx-server", True)):
            pid_file.write_text("4242")
            with patch.object(omlx.subprocess, "run", return_value=omlx.subprocess.CompletedProcess([], 0, name + "\n", "")), \
                    patch.object(omlx.os, "kill") as kill:
                self.assertEqual(omlx.stop_server(), stopped)
            self.assertEqual(kill.called, stopped)
            self.assertFalse(pid_file.exists())
        self.assertFalse(omlx.stop_server())   # nothing started: nothing to stop

    def test_models_are_listed_from_disk_while_the_server_is_down(self):
        own, lms, settings = Path(self.tmp) / "own", Path(self.tmp) / "lms", Path(self.tmp) / "omlx-settings.json"
        for folder in (own / "Qwen3-8B-4bit", lms / "AnkitAI" / "Parable-4B-MLX-8bit", lms / "x" / "bge-m3-embedding", own / "no-weights"):
            folder.mkdir(parents=True)
            (folder / "config.json").write_text("{}")
            if folder.name != "no-weights":
                (folder / "model.safetensors").write_bytes(b"0" * 10)
        settings.write_text(json.dumps({"model": {"model_dirs": [str(own)]}}))
        with patch.object(omlx, "LMSTUDIO_MODELS", lms), patch.object(omlx, "settings_file", return_value=settings), \
                patch.object(self.provider, "_server_up", return_value=False), patch.object(self.provider, "_status", return_value=[]):
            self.assertEqual(self.provider._fetch_models(), ["Parable-4B-MLX-8bit", "Qwen3-8B-4bit"])   # bare folder names, no embedder
            self.assertEqual(self.provider._entry("Qwen3-8B-4bit")["estimated_size"], 10)

    def _download(self, *updates, interrupt=False):
        task = {"task_id": "t1", "repo_id": "mlx-community/Qwen3-8B-4bit", "status": "pending"}
        polls = [{"tasks": [{**task, **u}]} for u in updates]
        calls, seen = [], []

        def post(url, payload, **kw):
            calls.append(url)
            return {"task": task}

        def poll(*_a, **_kw):
            if interrupt:
                raise KeyboardInterrupt
            return polls.pop(0)
        with patch.object(self.provider, "_ensure_server"), patch.object(omlx, "post_json", side_effect=post), \
                patch.object(omlx, "get_json", side_effect=poll), patch.object(omlx.time, "sleep"):
            try:
                return self.provider.download("mlx-community/Qwen3-8B-4bit", seen.append), seen, calls
            except (ProviderError, KeyboardInterrupt) as e:
                return e, seen, calls

    def test_a_download_waits_for_omlx_and_names_the_model_as_omlx_serves_it(self):
        model, seen, _ = self._download({"status": "downloading", "progress": 40.0}, {"status": "completed", "progress": 100.0})
        self.assertEqual(model, "Qwen3-8B-4bit")
        self.assertEqual([t["progress"] for t in seen], [40.0, 100.0])

    def test_a_failed_download_says_why(self):
        error, _, _ = self._download({"status": "failed", "error": "401 gated repo"})
        self.assertIsInstance(error, ProviderError)
        self.assertIn("401 gated repo", str(error))

    def test_ctrl_c_cancels_the_download_in_omlx_too(self):
        error, _, calls = self._download(interrupt=True)
        self.assertIsInstance(error, KeyboardInterrupt)
        self.assertTrue(calls[-1].endswith("/admin/api/hf/cancel/t1"))

    def test_lmstudio_refs_move_to_the_folder_oMLX_serves_only_when_one_matches(self):
        folders = {"Parable-Qwen3-4B-Claude-Fable-5-MLX-8bit": Path("a"), "Qwen3.5-9B-MLX-4bit": Path("b"), "Qwen3.5-9B-MLX-8bit": Path("c")}
        with patch.object(omlx, "on_disk", return_value=folders):
            self.assertEqual(omlx.lmstudio_ref("lmstudio:parable-qwen3-4b-claude-fable-5-mlx"),
                             "omlx:Parable-Qwen3-4B-Claude-Fable-5-MLX-8bit")   # the key LM Studio gave it, on this Mac
            self.assertIsNone(omlx.lmstudio_ref("lmstudio:qwen/qwen3.5-9b"))   # two quantizations: don't guess
            self.assertIsNone(omlx.lmstudio_ref("lmstudio:gone-model"))

    def test_the_saved_model_and_eval_results_move_and_unmatched_ones_stay(self):
        from src.providers import model_eval
        evals = Path(self.tmp) / "model_evals.json"
        evals.write_text(json.dumps({"lmstudio:a-mlx": {"passed": True, "strength": 3}, "lmstudio:b-mlx": {"passed": False},
                                     "omlx:B-MLX-4bit": {"passed": True, "strength": 4}, "lmstudio:gone": {"passed": True}}))
        saved = {"model": "lmstudio:a-mlx"}
        with patch.object(omlx, "on_disk", return_value={"A-MLX-8bit": Path("a"), "B-MLX-4bit": Path("b")}), \
                patch.object(model_eval, "results_path", return_value=evals), \
                patch("src.config.get_default_model", side_effect=lambda: saved["model"]), \
                patch("src.config.set_default_model", side_effect=lambda ref: saved.update(model=ref)):
            moved = omlx.migrate_lmstudio_refs()
            self.assertEqual(omlx.migrate_lmstudio_refs(), [])   # nothing left to move
        data = json.loads(evals.read_text())
        self.assertEqual(saved["model"], "omlx:A-MLX-8bit")
        self.assertEqual(data["omlx:A-MLX-8bit"], {"passed": True, "strength": 3})
        self.assertEqual(data["omlx:B-MLX-4bit"]["strength"], 4)   # the oMLX result is newer than LM Studio's
        self.assertEqual(sorted(k for k in data if k.startswith("lmstudio:")), ["lmstudio:gone"])
        self.assertEqual(len(moved), 3)

    def test_native_kernels_are_asked_of_the_omlx_install_itself(self):
        exe = Path(self.tmp) / "omlx"
        exe.write_text("#!/opt/omlx/venv/bin/python\nimport sys\n")
        done = omlx.subprocess.CompletedProcess([], 0, '{"attention": null, "lowbit": "ImportError: no _ext"}\n', "")
        with patch.object(omlx, "_exe", return_value=str(exe)), patch.object(omlx.subprocess, "run", return_value=done) as run:
            self.assertEqual(omlx.native_kernels(), {"attention": None, "lowbit": "ImportError: no _ext"})
        self.assertEqual(run.call_args.args[0][0], "/opt/omlx/venv/bin/python")   # the install's own interpreter, not Clyde's
        failed = omlx.subprocess.CompletedProcess([], 1, "", "ModuleNotFoundError: No module named 'omlx'\n")
        with patch.object(omlx, "_exe", return_value=str(exe)), patch.object(omlx.subprocess, "run", return_value=failed):
            self.assertEqual(omlx.native_kernels(), "ModuleNotFoundError: No module named 'omlx'")
        with patch.object(omlx, "_exe", return_value=None):
            self.assertIsNone(omlx.native_kernels())
        (Path(self.tmp) / "python").write_text("")   # a venv: its own python wins over a #!/bin/sh trampoline
        exe.write_text("#!/bin/sh\n'''exec' '/very/long/venv/bin/python' \"$0\" \"$@\"\n")
        with patch.object(omlx, "_exe", return_value=str(exe)), patch.object(omlx.subprocess, "run", return_value=done) as run:
            omlx.native_kernels()
        self.assertEqual(run.call_args.args[0][0], str((Path(self.tmp) / "python").resolve()))

    def test_only_offered_on_apple_silicon(self):
        with patch.object(omlx.sys, "platform", "linux"):
            self.assertFalse(omlx.supported())


if __name__ == "__main__":
    unittest.main()
