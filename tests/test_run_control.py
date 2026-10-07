"""RunControl: queue order, steering collection, and stop only interrupting a running turn."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.run_control import RunControl


class TestRunControl(unittest.TestCase):
    def test_queued_prompts_come_out_in_order(self):
        control = RunControl()
        control.queue("a")
        control.queue("b")
        self.assertEqual([control.prompts.get_nowait(), control.prompts.get_nowait()], ["a", "b"])

    def test_steering_is_collected_once_and_in_order(self):
        control = RunControl()
        self.assertIsNone(control.take_steer())
        control.steer("first")
        control.steer("second")
        self.assertEqual(control.take_steer(), "first\n\nsecond")
        self.assertIsNone(control.take_steer())

    def test_stop_interrupts_only_a_running_turn_and_drops_its_steering(self):
        control = RunControl()
        control.steer("old")
        with patch("src.run_control.interrupt_turn") as interrupt:
            control.stop()
            interrupt.assert_not_called()
            control.busy = True
            control.steer("old again")
            control.queue("later")
            control.stop()
            interrupt.assert_called_once()
        self.assertIsNone(control.take_steer())
        self.assertEqual(control.prompts.get_nowait(), "later")   # queued prompts survive a stop


if __name__ == "__main__":
    unittest.main()
