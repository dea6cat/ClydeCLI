"""Bonny's theme: what is kept, what is refused, and what reaches the page."""
from __future__ import annotations

import unittest

from src.bonny import theme

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32


class TestClean(unittest.TestCase):
    def test_anything_invalid_falls_back_to_the_default(self):
        self.assertEqual(theme.clean(None), theme.clean({}))
        self.assertEqual(theme.clean("red"), theme.clean({}))
        bad = theme.clean({"preset": "neon", "fit": "stretch", "shape": "blob", "font": "comic", "dim": "lots", "blur": True,
                           "colors": {"bg": "red", "link": "#12345", "nope": "#ffffff"}, "greeting": 5, "css": 7})
        self.assertEqual(bad, theme.clean({}))
        self.assertEqual(bad["colors"], {})

    def test_numbers_are_clamped_and_colours_are_lowercased(self):
        t = theme.clean({"dim": 5, "blur": 999, "glass": -1, "colors": {"bg": "#ABCDEF", "text": "#000000"}})
        self.assertEqual((t["dim"], t["blur"], t["glass"]), (0.9, 24, 0.0))
        self.assertEqual(t["colors"], {"bg": "#abcdef", "text": "#000000"})

    def test_greeting_is_one_short_line_and_css_is_capped(self):
        t = theme.clean({"greeting": "  hello\n\n   there  " + "x" * 200, "css": "a{}" * 20_000})
        self.assertNotIn("\n", t["greeting"])
        self.assertLessEqual(len(t["greeting"]), theme.MAX_GREETING)
        self.assertEqual(len(t["css"]), theme.MAX_CSS)


class TestImage(unittest.TestCase):
    def tearDown(self):
        theme.remove_image()

    def test_images_are_recognised_by_their_first_bytes(self):
        self.assertEqual([theme.sniff_image(d) for d in (PNG, JPG, GIF, WEBP)], ["png", "jpg", "gif", "webp"])
        for refused in (b"<svg xmlns='x'><script>alert(1)</script></svg>", b"<html>", b"", b"RIFF\x00\x00\x00\x00WAVEfmt "):
            self.assertIsNone(theme.sniff_image(refused))

    def test_saving_replaces_the_old_image_and_refuses_bad_or_big_ones(self):
        self.assertEqual(theme.save_image(PNG), "png")
        self.assertEqual(theme.image_path().name, "background.png")
        self.assertEqual(theme.save_image(JPG), "jpg")
        self.assertEqual(theme.image_path().name, "background.jpg")   # the PNG is gone
        self.assertFalse((theme.folder() / "background.png").exists())
        with self.assertRaises(ValueError):
            theme.save_image(b"<svg></svg>")
        with self.assertRaises(ValueError):
            theme.save_image(PNG + b"\x00" * theme.MAX_IMAGE)
        self.assertEqual(theme.image_path().name, "background.jpg")   # a refused upload leaves the old one
        theme.remove_image()
        self.assertIsNone(theme.image_path())


class TestSaveAndVars(unittest.TestCase):
    def test_a_saved_theme_comes_back_cleaned(self):
        theme.save({"preset": "felt", "colors": {"link": "#FFAA00", "bad": "#fff"}, "shape": "round", "dim": 0.55})
        t = theme.load()
        self.assertEqual((t["preset"], t["shape"], t["dim"], t["colors"]), ("felt", "round", 0.55, {"link": "#ffaa00"}))

    def test_auto_sets_no_colours_so_the_page_follows_light_and_dark(self):
        v = theme.css_vars(theme.clean({}), None)
        self.assertNotIn("--bg", v)
        self.assertEqual((v["--bg-image"], v["--panel-alpha"]), ("none", "1"))

    def test_a_preset_sets_its_colours_and_an_override_wins(self):
        v = theme.css_vars(theme.clean({"preset": "night", "colors": {"link": "#ff0000"}}), None)
        self.assertEqual((v["--bg"], v["--link"], v["--spade"]), ("#0f1a14", "#ff0000", "#d0202f"))

    def test_glass_only_applies_when_there_is_an_image(self):
        t = theme.clean({"glass": 0.4, "fit": "tile", "blur": 6})
        self.assertEqual(theme.css_vars(t, None)["--panel-alpha"], "1")
        v = theme.css_vars(t, "/theme/background?v=1")
        self.assertEqual((v["--panel-alpha"], v["--img-repeat"], v["--img-blur"]), ("0.6", "repeat", "6px"))
        self.assertIn("/theme/background?v=1", v["--bg-image"])

    def test_custom_css_cannot_close_the_style_element(self):
        css = theme.safe_css("a{color:red}</style><script>alert(1)</script></STYLE>")
        self.assertNotIn("</style", css.lower())
        self.assertIn("a{color:red}", css)

    def test_the_root_block_lists_every_variable(self):
        self.assertEqual(theme.root_block({"--bg": "#000000", "--img-dim": "0.4"}), ":root{--bg:#000000;--img-dim:0.4}")


if __name__ == "__main__":
    unittest.main()
