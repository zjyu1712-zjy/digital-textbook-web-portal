"""Declared placeholders can ship only with an explicit partial scope."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline


class PendingChapterTests(unittest.TestCase):
    def setUp(self):
        self.course = json.loads((ROOT / "tests/fixtures/general.json").read_text(encoding="utf-8"))
        self.inventory = json.loads((ROOT / "tests/fixtures/inventory.json").read_text(encoding="utf-8"))
        self.course["chapters"].append({"id":"later", "title":"后续章节", "sections":[],
                                        "pending":{"reason":"后续原资料尚未提供"}})

    def test_excerpt_keeps_empty_placeholder_visible(self):
        self.course["scope"]["completeness"] = "excerpt"
        self.assertEqual(pipeline.validate(self.course, self.inventory), [])
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "book.html"
            report = pipeline.build(self.course, self.inventory, dest, folder)
            self.assertEqual(report["chapterStatus"]["chapters"][-1]["availability"]["status"], "pending")
            self.assertIn("后续原资料尚未提供", dest.read_text(encoding="utf-8"))

    def test_complete_scope_cannot_conceal_a_placeholder(self):
        self.course["scope"]["completeness"] = "complete"
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "book.html"
            with self.assertRaises(ValueError):
                pipeline.build(self.course, self.inventory, dest, folder)
            self.assertFalse(dest.exists())

    def test_an_empty_chapter_without_reason_remains_invalid(self):
        del self.course["chapters"][-1]["pending"]
        self.assertIn("empty chapter", pipeline.validate(self.course, self.inventory))


if __name__ == "__main__":
    unittest.main()
