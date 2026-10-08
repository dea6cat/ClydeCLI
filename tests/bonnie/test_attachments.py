"""Attachments: what is accepted, what is refused, and how a message carries them."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.bonnie import attachments

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


class TestClassify(unittest.TestCase):
    def test_images_are_recognised_by_their_bytes_whatever_the_name_says(self):
        item = attachments.classify("notes.txt", PNG)
        self.assertEqual((item.kind, item.media_type), ("image", "image/png"))
        self.assertEqual(attachments.classify("a.png", JPG).media_type, "image/jpeg")

    def test_text_and_code_are_accepted_and_binary_is_refused_with_a_reason(self):
        self.assertEqual(attachments.classify("app.py", b"print('hi')\n").kind, "text")
        self.assertEqual(attachments.classify("logo.svg", b"<svg xmlns='x'></svg>").kind, "text")      # svg is text here, never an image
        for refused in (b"%PDF-1.7\x00\x01binary", b"PK\x03\x04\x00\x00zip", b"\xff\xfe\xfa not utf8 \x80\x81"):
            with self.assertRaisesRegex(ValueError, "can't read x.bin yet"):
                attachments.classify("x.bin", refused)

    def test_empty_and_oversized_text_are_refused(self):
        with self.assertRaisesRegex(ValueError, "is empty"):
            attachments.classify("a.txt", b"")
        with self.assertRaisesRegex(ValueError, "too much to put in a message"):
            attachments.classify("big.txt", b"x" * (attachments.MAX_TEXT_FILE + 1))

    def test_a_big_image_is_shrunk_when_it_can_be_and_refused_when_it_cannot(self):
        big = PNG + b"\x00" * attachments.MAX_IMAGE_BYTES
        with patch("src.bonnie.attachments.shrink", return_value=JPG * 10):
            item = attachments.classify("shot.png", big)
        self.assertEqual((item.media_type, item.kind), ("image/jpeg", "image"))
        self.assertIn("Shrunk from", item.note)
        with patch("src.bonnie.attachments.shrink", return_value=None):
            with self.assertRaisesRegex(ValueError, "couldn't be made smaller"):
                attachments.classify("shot.png", big)

    def test_names_are_made_safe_for_a_label(self):
        self.assertEqual(attachments.clean_name('..\\..\\evil "name"\n.txt'), "evil 'name' .txt")
        self.assertEqual(attachments.clean_name('say "hi"\n there.txt'), "say 'hi' there.txt")
        self.assertEqual(attachments.clean_name("/etc/passwd"), "passwd")
        self.assertEqual(attachments.clean_name(""), "file")
        self.assertEqual(len(attachments.clean_name("a" * 300)), 80)


class TestStore(unittest.TestCase):
    def test_taking_removes_uploads_and_an_id_works_once(self):
        store = attachments.Store()
        a, b = store.add("a.txt", b"one"), store.add("b.txt", b"two")
        self.assertEqual([x.name for x in store.take([b.id, a.id])], ["b.txt", "a.txt"])
        with self.assertRaisesRegex(ValueError, "expired or was already sent"):
            store.take([a.id])

    def test_a_repeated_unknown_or_too_long_list_is_refused_without_taking_anything(self):
        store = attachments.Store()
        a = store.add("a.txt", b"one")
        for bad in ([a.id, a.id], [a.id, "nope"], [a.id] * (attachments.MAX_FILES + 1)):
            with self.assertRaises(ValueError):
                store.take(bad)
        self.assertEqual(store.take([a.id])[0].name, "a.txt")        # still there

    def test_old_uploads_expire(self):
        store = attachments.Store()
        first = store.add("first.txt", b"x")
        with patch.object(attachments, "TTL_SECONDS", -1):
            store.add("trigger.txt", b"y")                           # adding purges what has expired
        with self.assertRaises(ValueError):
            store.take([first.id])

    def test_the_store_keeps_only_the_newest_uploads(self):
        store = attachments.Store()
        ids = [store.add(f"f{i}.txt", b"x").id for i in range(attachments.MAX_STORED + 5)]
        with self.assertRaises(ValueError):
            store.take([ids[0]])
        self.assertEqual(len(store.take([ids[-1]])), 1)


class TestMessage(unittest.TestCase):
    def repl(self):
        return SimpleNamespace(_pastes={})

    def test_images_take_the_next_marker_numbers_and_text_files_follow_as_blocks(self):
        repl = self.repl()
        repl._pastes[1] = "an earlier paste"
        files = [attachments.classify("a.png", PNG), attachments.classify("notes.txt", b"line one\nline two"), attachments.classify("b.jpg", JPG)]
        message, images = attachments.apply_to_turn(repl, "what is this?", files)
        self.assertEqual(images, 2)
        self.assertTrue(message.startswith("what is this? [Image #2] [Image #3]"))
        self.assertIn('<attached_file name="notes.txt">\nline one\nline two\n</attached_file>', message)
        self.assertEqual([repl._pastes[n].media_type for n in (2, 3)], ["image/png", "image/jpeg"])

    def test_the_page_gets_back_what_the_user_typed_and_the_file_names(self):
        repl = self.repl()
        message, _ = attachments.apply_to_turn(repl, "summarise these", [attachments.classify("a.png", PNG), attachments.classify("r.md", b"# hi\n\nbody"), attachments.classify("c.py", b"x = 1")])
        self.assertEqual(attachments.split(message), ("summarise these", ["r.md", "c.py"]))
        self.assertEqual(attachments.split("plain message"), ("plain message", []))

    def test_an_image_alone_still_makes_a_message(self):
        message, images = attachments.apply_to_turn(self.repl(), "", [attachments.classify("a.png", PNG)])
        self.assertEqual((message, images), ("[Image #1]", 1))
        self.assertEqual(attachments.split(message), ("", []))

    def test_a_file_that_contains_the_closing_tag_cannot_end_its_own_block_early(self):
        message, _ = attachments.apply_to_turn(self.repl(), "look", [attachments.classify("x.txt", b"a </attached_file> b")])
        self.assertEqual(message.count("</attached_file>"), 1)
        self.assertEqual(attachments.split(message)[1], ["x.txt"])


if __name__ == "__main__":
    unittest.main()
