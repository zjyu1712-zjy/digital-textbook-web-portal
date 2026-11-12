"""Packaging regressions use only synthetic temporary files."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_skill.py"
spec = importlib.util.spec_from_file_location("package_skill", SCRIPT)
package_skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_skill)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "skill"
        self.root.mkdir()
        (self.root / "SKILL.md").write_text("---\nname: digital-textbook-html\n---\n测试\n", encoding="utf-8")
        (self.root / "RELEASE.json").write_text(json.dumps({"name": "digital-textbook-html", "version": "test-1"}), encoding="utf-8")
        self.paths = ["PACKAGE_FILES.json", "RELEASE.json", "SKILL.md"]
        self.out = self.base / "release.zip"
        self.write_manifest()

    def write_manifest(self):
        (self.root / "PACKAGE_FILES.json").write_text(json.dumps(self.paths, ensure_ascii=False), encoding="utf-8")

    def test_independent_archive_and_verified_hashes(self):
        (self.root / "assets").mkdir()
        (self.root / "assets/样本.txt").write_text("合成示例", encoding="utf-8")
        self.paths.append("assets/样本.txt")
        self.write_manifest()
        result = package_skill.pack(self.root, self.out)
        self.assertEqual(result["version"], "test-1")
        self.assertEqual(result["sha256"], hashlib.sha256(self.out.read_bytes()).hexdigest())
        with zipfile.ZipFile(self.out) as archive:
            expected = {"digital-textbook-html/" + p for p in self.paths}
            expected.add("digital-textbook-html/PACKAGE-MANIFEST.json")
            self.assertEqual(set(archive.namelist()), expected)
            target = self.base / "unpacked"
            archive.extractall(target)
        unpacked = target / "digital-textbook-html"
        self.assertEqual((unpacked / "assets/样本.txt").read_text(encoding="utf-8"), "合成示例")
        manifest = package_skill.verify_archive(self.out)
        self.assertEqual(manifest["version"], "test-1")
        for row in manifest["files"]:
            self.assertEqual(row["sha256"], hashlib.sha256((unpacked / row["path"]).read_bytes()).hexdigest())
        package_skill.pack(unpacked, self.base / "repacked.zip")
        self.assertEqual(self.out.read_bytes(), (self.base / "repacked.zip").read_bytes())

    def test_unlisted_private_bait_is_not_scanned_or_packaged(self):
        (self.root / "private").mkdir()
        (self.root / "private/textbook.pdf").write_bytes(b"PRIVATE-TEXTBOOK")
        (self.root / ".env").write_text("PRIVATE-KEY", encoding="utf-8")
        (self.root / "notes.txt").write_text("PRIVATE-RESPONSE", encoding="utf-8")
        package_skill.pack(self.root, self.out)
        with zipfile.ZipFile(self.out) as archive:
            joined = b"".join(archive.read(name) for name in archive.namelist())
        for bait in [b"PRIVATE-TEXTBOOK", b"PRIVATE-KEY", b"PRIVATE-RESPONSE"]:
            self.assertNotIn(bait, joined)

    def test_unsafe_paths_and_forbidden_files_are_rejected(self):
        for bad in ["../escape", "/absolute", "C:/drive", "C:drive", "x\\escape", "x/../escape", "x//file", "./SKILL.md", ".git/config", "node_modules/x", "__pycache__/x.pyc", "sources/book.pdf", "inputs/book.pdf", "private/data.json", "assets/.env", "assets/api-key.txt", "credentials.json", "auth.json", ".ssh/config", "drafts/record.json", "PACKAGE-MANIFEST.json"]:
            with self.subTest(path=bad):
                self.paths = ["PACKAGE_FILES.json", "RELEASE.json", "SKILL.md", bad]
                self.write_manifest()
                with self.assertRaises(ValueError):
                    package_skill.pack(self.root, self.out)
                self.assertFalse(self.out.exists())

    def test_missing_duplicate_nonstring_and_nonarray_are_rejected(self):
        for paths in [self.paths + ["missing.txt"], self.paths + ["SKILL.md"], self.paths + [4], {"files": self.paths}, ["SKILL.md"]]:
            with self.subTest(paths=paths):
                self.paths = paths
                self.write_manifest()
                with self.assertRaises((ValueError, FileNotFoundError)):
                    package_skill.pack(self.root, self.out)
                self.assertFalse(self.out.exists())

    def test_file_parent_and_manifest_symlinks_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "file.txt").write_text("outside", encoding="utf-8")
        (self.root / "linked.txt").symlink_to(outside / "file.txt")
        (self.root / "linked-dir").symlink_to(outside, target_is_directory=True)
        for name in ["linked.txt", "linked-dir/file.txt"]:
            self.paths = ["PACKAGE_FILES.json", "RELEASE.json", "SKILL.md", name]
            self.write_manifest()
            with self.assertRaises(ValueError):
                package_skill.pack(self.root, self.out)
        source = self.root / "PACKAGE_FILES.json"
        source.rename(outside / "manifest.json")
        source.symlink_to(outside / "manifest.json")
        with self.assertRaises(ValueError):
            package_skill.pack(self.root, self.out)

    def test_output_inside_skill_existing_or_symlink_refused(self):
        with self.assertRaises(ValueError):
            package_skill.pack(self.root, self.root / "bundle.zip")
        self.out.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            package_skill.pack(self.root, self.out)
        self.assertEqual(self.out.read_bytes(), b"keep")
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            package_skill.pack(self.root, alias / "bundle.zip")
        broken = self.base / "broken.zip"
        broken.symlink_to(self.base / "absent")
        with self.assertRaises(FileExistsError):
            package_skill.pack(self.root, broken)

    def test_tampered_archive_fails_hash_verification(self):
        package_skill.pack(self.root, self.out)
        broken = self.base / "tampered.zip"
        with zipfile.ZipFile(self.out) as original, zipfile.ZipFile(broken, "w") as modified:
            for name in original.namelist():
                modified.writestr(name, b"tampered" if name.endswith("/SKILL.md") else original.read(name))
        with self.assertRaises(ValueError):
            package_skill.verify_archive(broken)

    def test_cli_unicode_output_path_under_ascii_terminal(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        copied = scripts / "package_skill.py"
        copied.write_bytes(SCRIPT.read_bytes())
        output = self.base / "中文教材🧮.zip"
        environment = dict(os.environ, PYTHONIOENCODING="ascii")
        result = subprocess.run([sys.executable, str(copied), "--out", str(output)],
                                env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stderr, b"")
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(report["output"], str(output))
        self.assertEqual(report["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        package_skill.verify_archive(output)
        # An ordinary refusal must also remain readable, without an encoding traceback.
        repeated = subprocess.run([sys.executable, str(copied), "--out", str(output)],
                                  env=environment, capture_output=True)
        self.assertEqual(repeated.returncode, 1)
        self.assertIn("输出已存在", repeated.stderr.decode("utf-8"))
        self.assertNotIn(b"UnicodeEncodeError", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
