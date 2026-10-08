"""Bonny's "Notify me" toggle: the page's own notification code, run under Node against a stand-in for the browser's
Notification API, permission and storage. Skipped without Node."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from src.bonny.page import PAGE

_PREAMBLE = r"""
const opts = %s;
const shown = [], notes = [], announces = [], store = Object.assign({}, opts.stored || {});
let requests = 0, pressed = null, clickHandler = null, focused = false;
class N {
  constructor(title, o) { this.title = title; this.o = o; this.closed = false; shown.push(this); }
  close() { this.closed = true; }
  static get permission() { return opts.permission; }
  static async requestPermission() { requests++; opts.permission = opts.grant ? "granted" : "denied"; return opts.permission; }
}
if (!opts.noApi) globalThis.Notification = N;
globalThis.window = opts.noApi ? {} : { Notification: N, focus() { focused = true; } };
globalThis.localStorage = opts.storageThrows
  ? { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } }
  : { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
globalThis.document = { hidden: !!opts.hidden, hasFocus: () => !!opts.focused };
const el = { setAttribute(k, v) { if (k === "aria-pressed") pressed = v; }, addEventListener(t, f) { clickHandler = f; }, title: "" };
globalThis.$ = () => el;
globalThis.note = (m) => notes.push(m);
globalThis.announce = (m) => announces.push(m);
"""


def _block() -> str:
    return PAGE[PAGE.index("/* notify:start"):PAGE.index("notify:end */") + len("notify:end */")]


def run(opts: dict, actions: str = "") -> dict:
    script = (_PREAMBLE % json.dumps(opts)) + _block() + \
        "\n(async () => {" + actions + "\nconsole.log(JSON.stringify({ shown: shown.map((n) => ({ title: n.title, body: n.o.body, tag: n.o.tag, closed: n.closed })), " \
        "notes, announces, store, pressed, requests, focused }));})();"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


ON = {"permission": "granted", "stored": {"bonny.notify": "1"}, "hidden": True}


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestNotify(unittest.TestCase):
    def test_off_until_the_user_turns_it_on(self):
        out = run({"permission": "granted", "hidden": True}, 'notifyAnswer({ ok: true }, "hello");')
        self.assertEqual((out["shown"], out["pressed"]), ([], "false"))

    def test_an_answer_in_a_background_tab_notifies_with_the_question_not_the_answer(self):
        out = run(ON, 'notifyAnswer({ ok: true, answer: "the secret answer" }, "what is\\n  my   plan?");')
        self.assertEqual(len(out["shown"]), 1)
        self.assertEqual(out["shown"][0]["title"], "Bonny answered")
        self.assertEqual(out["shown"][0]["body"], "what is my plan?")        # whitespace collapsed, and no answer text
        self.assertNotIn("secret", json.dumps(out["shown"]))
        self.assertEqual(out["pressed"], "true")

    def test_a_tab_you_are_looking_at_is_left_alone_but_an_unfocused_one_is_not(self):
        self.assertEqual(run({**ON, "hidden": False, "focused": True}, 'notifyAnswer({ ok: true }, "q");')["shown"], [])
        self.assertEqual(len(run({**ON, "hidden": False, "focused": False}, 'notifyAnswer({ ok: true }, "q");')["shown"]), 1)

    def test_a_stopped_turn_is_silent_and_a_failed_one_says_so(self):
        self.assertEqual(run(ON, 'notifyAnswer({ stopped: true }, "q");')["shown"], [])
        out = run(ON, 'notifyAnswer({ ok: false }, "q");')
        self.assertEqual(out["shown"][0]["title"], "Bonny hit a problem")

    def test_a_long_question_is_cut_short(self):
        out = run(ON, 'notifyAnswer({ ok: true }, "x".repeat(300));')
        self.assertEqual(len(out["shown"][0]["body"]), 80)
        self.assertTrue(out["shown"][0]["body"].endswith("…"))

    def test_permission_taken_back_in_the_browser_turns_it_off_even_if_the_choice_was_saved(self):
        out = run({**ON, "permission": "denied"}, 'notifyAnswer({ ok: true }, "q");')
        self.assertEqual((out["shown"], out["pressed"]), ([], "false"))

    def test_turning_it_on_asks_the_browser_once_and_confirms(self):
        out = run({"permission": "default", "grant": True, "hidden": True}, "await clickHandler();")
        self.assertEqual(out["requests"], 1)
        self.assertEqual(out["store"]["bonny.notify"], "1")
        self.assertEqual((out["pressed"], out["announces"]), ("true", ["Notifications on."]))
        self.assertEqual(out["shown"][0]["title"], "Bonny")                # the confirmation proves it works

    def test_a_refusal_leaves_it_off_and_says_how_to_allow_it(self):
        out = run({"permission": "default", "grant": False}, "await clickHandler();")
        self.assertEqual((out["pressed"], out["store"]), ("false", {}))
        self.assertIn("blocked", out["notes"][0])
        self.assertEqual(out["shown"], [])

    def test_already_blocked_is_not_asked_again(self):
        out = run({"permission": "denied"}, "await clickHandler();")
        self.assertEqual(out["requests"], 0)
        self.assertIn("site settings", out["notes"][0])

    def test_clicking_it_when_on_turns_it_off(self):
        out = run(ON, "await clickHandler();")
        self.assertEqual((out["store"]["bonny.notify"], out["pressed"], out["announces"]), ("0", "false", ["Notifications off."]))

    def test_a_browser_without_notifications_says_so_and_nothing_throws(self):
        out = run({"noApi": True}, 'await clickHandler(); notifyAnswer({ ok: true }, "q");')
        self.assertIn("can't show notifications", out["notes"][0])
        self.assertEqual(out["shown"], [])

    def test_blocked_storage_does_not_break_the_page(self):
        out = run({"permission": "granted", "storageThrows": True, "hidden": True}, 'notifyAnswer({ ok: true }, "q");')
        self.assertEqual((out["shown"], out["pressed"]), ([], "false"))

    def test_clicking_the_notification_brings_the_tab_back(self):
        out = run(ON, 'notifyAnswer({ ok: true }, "q"); shown[0].onclick();')
        self.assertTrue(out["focused"])
        self.assertTrue(out["shown"][0]["closed"])


if __name__ == "__main__":
    unittest.main()
