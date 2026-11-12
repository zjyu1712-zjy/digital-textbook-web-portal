"""A hard resource limit must not replace a prior deliverable or be bypassed."""
import copy
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline


class ResourceBuildTests(unittest.TestCase):
    def setUp(self):
        self.course = json.loads((ROOT / "tests/fixtures/general.json").read_text(encoding='utf-8'))
        self.inventory = json.loads((ROOT / "tests/fixtures/inventory.json").read_text(encoding='utf-8'))

    def test_actual_file_bytes_match_report_and_sum(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "教材.html"
            report = Path(folder) / "size.json"
            result = pipeline.build(self.course, self.inventory, dest, folder, size_report=report)
            size = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(size["totalBytes"], dest.stat().st_size)
            self.assertEqual(sum(size["parts"].values()), size["totalBytes"])
            self.assertEqual(result["resources"], size)
            self.assertEqual(pipeline.inspect_html(dest), [])

    def test_limit_preserves_existing_output_and_writes_failure_report(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "教材.html"
            dest.write_text("previous intact file")
            report = Path(folder) / "size.json"
            for incomplete in (False, True):
                with self.assertRaises(ValueError):
                    pipeline.build(self.course, self.inventory, dest, folder,
                                   allow_incomplete=incomplete, warning_bytes=1,
                                   limit_bytes=2, size_report=report)
                self.assertEqual(dest.read_text(encoding='utf-8'), "previous intact file")
                self.assertGreater(json.loads(report.read_text(encoding='utf-8'))["totalBytes"], 2)

    def test_report_cannot_overwrite_html(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "教材.html"
            dest.write_text("original")
            with self.assertRaises(ValueError):
                pipeline.build(self.course, self.inventory, dest, folder, size_report=dest)
            self.assertEqual(dest.read_text(encoding='utf-8'), "original")

    def test_neither_output_can_overwrite_a_referenced_source_image(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "source.png"
            original = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
            image.write_bytes(original)
            self.course["chapters"][0]["sections"][0]["blocks"].append({"type":"image","path":"source.png","alt":"Synthetic dot"})
            for dest, report in [(Path(folder)/"book.html",image),(image,Path(folder)/"size.json")]:
                with self.assertRaises(ValueError):
                    pipeline.build(self.course,self.inventory,dest,folder,size_report=report)
                self.assertEqual(image.read_bytes(), original)

    def test_cli_default_report_is_written(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "中文教材.html"
            run = subprocess.run([sys.executable, str(ROOT / "scripts/pipeline.py"), "build",
                str(ROOT / "tests/fixtures/general.json"), "--inventory",
                str(ROOT / "tests/fixtures/inventory.json"), "--out", str(dest)],
                capture_output=True, text=True, env=os.environ.copy())
            self.assertEqual(run.returncode, 0, run.stderr)
            size = json.loads(Path(str(dest) + ".size.json").read_text(encoding='utf-8'))
            self.assertEqual(size["totalBytes"], dest.stat().st_size)

    def test_cli_report_cannot_replace_course_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "course.json"
            original = json.dumps(self.course, ensure_ascii=False)
            source.write_text(original, encoding="utf-8")
            run = subprocess.run([sys.executable, str(ROOT / "scripts/pipeline.py"), "build",
                str(source), "--inventory", str(ROOT / "tests/fixtures/inventory.json"),
                "--out", str(Path(folder) / "book.html"), "--size-report", str(source)],
                capture_output=True, env=os.environ.copy())
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(source.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
