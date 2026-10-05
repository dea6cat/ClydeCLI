"""clyde --acp: a fake editor drives one Agent Client Protocol turn over pipes, with a scripted model."""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.acp import Server
from tests.fakes import FakeProvider, reply


class TestAcp(unittest.TestCase):
    def setUp(self):
        self.home, self.ws = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()).resolve()
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        self.provider = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo hi > hello.txt"}, "call_1")]),
                                     reply("Made hello.txt."), name="glm", models=("glm-4.5",))
        for p in (patch.object(Path, "home", return_value=self.home),
                  patch("src.repl.core.build_registry", return_value={"glm": self.provider}),
                  patch("src.repl.core.keys.load_into_env"),
                  patch.dict(os.environ, {"CLYDE_TRACE": "off"})):
            p.start()
            self.addCleanup(p.stop)
        r1, w1 = os.pipe()          # editor -> agent
        r2, w2 = os.pipe()          # agent -> editor
        self.to_agent = os.fdopen(w1, "w", buffering=1)
        self.from_agent = os.fdopen(r2, "r")
        server = Server(model="glm:glm-4.5", stdin=os.fdopen(r1, "r"), stdout=os.fdopen(w2, "w", buffering=1))
        self.thread = threading.Thread(target=server.serve, daemon=True)
        self.thread.start()
        self.updates: list[dict] = []

    def call(self, rid, method, params):
        """Send a request and read until its response, answering permission asks with allow-once."""
        self.to_agent.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
        while True:
            msg = json.loads(self.from_agent.readline())
            if msg.get("method") == "session/update":
                self.updates.append(msg["params"]["update"])
            elif msg.get("method") == "session/request_permission":
                self.asked = msg["params"]
                self.to_agent.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                                "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}}) + "\n")
            elif msg.get("id") == rid:
                return msg

    def test_a_turn_streams_asks_permission_and_runs_the_tool(self):
        init = self.call(1, "initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        self.assertEqual(init["result"]["protocolVersion"], 1)
        sid = self.call(2, "session/new", {"cwd": str(self.ws), "mcpServers": []})["result"]["sessionId"]
        done = self.call(3, "session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "create the file hello.txt"}]})
        self.assertEqual(done["result"], {"stopReason": "end_turn"})
        self.assertEqual(self.asked["options"][0]["kind"], "allow_once")
        kinds = [u["sessionUpdate"] for u in self.updates]
        self.assertIn("tool_call", kinds)
        self.assertEqual(self.updates[kinds.index("tool_call")]["kind"], "execute")
        self.assertEqual(self.updates[kinds.index("tool_call_update")]["status"], "completed")
        self.assertIn("Made hello.txt.", "".join(u["content"]["text"] for u in self.updates if u["sessionUpdate"] == "agent_message_chunk"))
        self.assertEqual((self.ws / "hello.txt").read_text(), "hi\n")
        unknown = self.call(4, "session/load", {})
        self.assertEqual(unknown["error"]["code"], -32601)
        self.to_agent.close()
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
