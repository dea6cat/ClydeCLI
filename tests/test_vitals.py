from __future__ import annotations

import unittest
from unittest.mock import patch

from src import vitals
from src.providers.fit import GB


class TestVitals(unittest.TestCase):
    def setUp(self):
        vitals._cache = None

    def test_line_names_what_it_read_and_skips_the_rest(self):
        self.assertEqual(vitals.line(vitals.Vitals(3.2 * GB, 1.4 * GB, 0.41, 0.12)), "3.2G free · swap 1.4G · cpu 41% · gpu 12%")
        self.assertEqual(vitals.line(vitals.Vitals(None, 0, None)), "")

    def test_low_memory_swap_or_load_marks_the_machine_strained(self):
        self.assertFalse(vitals.Vitals(8 * GB, 0, 0.2).strained)
        self.assertTrue(vitals.Vitals(1 * GB, 0, 0.2).strained)
        self.assertTrue(vitals.Vitals(8 * GB, 2 * GB, 0.2).strained)
        self.assertTrue(vitals.Vitals(8 * GB, 0, 1.5).strained)
        self.assertTrue(vitals.Vitals(8 * GB, 0, 0.2, 0.95).strained)

    def test_a_reading_is_reused_inside_the_ttl(self):
        with patch.object(vitals.fit, "free_now_bytes", return_value=5 * GB) as free, \
                patch.object(vitals, "_swap_used", return_value=0), patch.object(vitals, "_load", return_value=0.1):
            vitals.sample()
            vitals.sample()
        free.assert_called_once()

    def test_mac_swap_usage_is_parsed(self):
        out = "total = 2048.00M  used = 1536.00M  free = 512.00M  (encrypted)"
        done = type("D", (), {"stdout": out})()
        with patch.object(vitals.platform, "system", return_value="Darwin"), patch.object(vitals.subprocess, "run", return_value=done):
            self.assertEqual(vitals._swap_used(), 1536 * 1024 ** 2)

    def test_mac_gpu_utilization_is_read_from_ioreg(self):
        done = type("D", (), {"stdout": '"Renderer Utilization %"=93,"Device Utilization %"=94'})()
        with patch.object(vitals.platform, "system", return_value="Darwin"), patch.object(vitals.subprocess, "run", return_value=done):
            self.assertEqual(vitals._gpu(), 0.94)

    def test_nvidia_gpu_utilization_is_read_from_nvidia_smi(self):
        done = type("D", (), {"stdout": "37\n"})()
        with patch.object(vitals.platform, "system", return_value="Linux"), patch.object(vitals.subprocess, "run", return_value=done):
            self.assertEqual(vitals._gpu(), 0.37)

    def test_no_gpu_tool_gives_none(self):
        with patch.object(vitals.platform, "system", return_value="Linux"), patch.object(vitals.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(vitals._gpu())


if __name__ == "__main__":
    unittest.main()
