"""Environment probes are not source, semantic, or browser acceptance evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "doctor.py"


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "portable environment checker is not implemented")
        spec = importlib.util.spec_from_file_location("dth_doctor_test", SCRIPT)
        self.doctor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.doctor)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "工作 区"
        self.browser = self.root / "browser"
        self.browser.write_text("test executable placeholder", encoding="utf-8")
        self.browser.chmod(0o700)
        self.module = self.root / "playwright.js"
        self.module.write_text("test module placeholder", encoding="utf-8")

    def transport(self, command, **kwargs):
        self.assertFalse(kwargs.get("shell", False))
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "v24.1.0\n", "")
        if any(str(value).endswith("check_math.cjs") for value in command):
            return subprocess.CompletedProcess(command, 0, '{"checked":2}', "")
        if "-e" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "modulePath": str(self.module), "browserPath": str(self.browser),
            }), "")
        self.fail("Unexpected process: " + str(command))

    def probe(self, transport=None, **kwargs):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(self.doctor.shutil, "which", return_value="/test/node"), \
             patch.object(self.doctor.subprocess, "run", side_effect=transport or self.transport):
            return self.doctor.run_doctor(self.workspace, **kwargs)

    def check(self, report, name):
        return next(item for item in report["checks"] if item["id"] == name)

    def test_ready_environment_never_claims_conversion_or_browser_verified(self):
        report = self.probe()
        self.assertTrue(report["buildReady"])
        self.assertFalse(report["fullConversionVerified"])
        self.assertEqual(self.check(report, "browserExecutable")["status"], "pass")
        for name in ("sourceReading", "ocr", "semanticReview", "fileStorage", "visualReview"):
            self.assertEqual(self.check(report, name)["status"], "unverified")
        self.assertEqual(list(self.workspace.iterdir()), [], "Probe files must be removed")

    def test_missing_node_fails_basic_readiness_without_starting_any_process(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(self.doctor.shutil, "which", return_value=None), \
             patch.object(self.doctor.subprocess, "run") as run:
            report = self.doctor.run_doctor(self.workspace, node="absent-node")
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "node")["status"], "fail")
        run.assert_not_called()

    def test_playwright_process_exit_is_not_a_successful_browser_probe(self):
        def transport(command, **kwargs):
            if "-e" in command:
                return subprocess.CompletedProcess(command, 1, "", "Playwright requires Node.js 20 or higher")
            return self.transport(command, **kwargs)
        report = self.probe(transport)
        self.assertTrue(report["buildReady"])
        self.assertEqual(self.check(report, "playwright")["status"], "unverified")
        self.assertEqual(self.check(report, "browserExecutable")["status"], "unverified")
        self.assertFalse(report["fullConversionVerified"])

    def test_missing_explicit_browser_stays_unverified(self):
        with patch.dict(os.environ, {"BROWSER_EXECUTABLE": str(self.root / "absent")}, clear=True), \
             patch.object(self.doctor.shutil, "which", return_value="/test/node"), \
             patch.object(self.doctor.subprocess, "run", side_effect=self.transport):
            report = self.doctor.run_doctor(self.workspace)
        self.assertTrue(report["buildReady"])
        self.assertEqual(self.check(report, "browserExecutable")["status"], "unverified")

    def test_failed_math_probe_prevents_build_readiness(self):
        def transport(command, **kwargs):
            if any(str(value).endswith("check_math.cjs") for value in command):
                return subprocess.CompletedProcess(command, 1, "", "math resource failed")
            return self.transport(command, **kwargs)
        report = self.probe(transport)
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "math")["status"], "fail")

    def test_missing_resource_is_not_silently_accepted(self):
        skill = self.root / "incomplete-skill"
        skill.mkdir()
        report = self.probe(skill=skill)
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "resources")["status"], "fail")
        self.assertIn("SKILL.md", self.check(report, "resources")["detail"])

    def test_missing_runtime_dependency_is_reported(self):
        original = Path.is_file
        for name in ("scripts/task_contract.py", "scripts/review_audit.py", "scripts/grading.py", "assets/grading.js"):
            with self.subTest(module=name):
                def exists(path):
                    return False if path == ROOT / name else original(path)
                with patch.object(Path, "is_file", exists):
                    report = self.probe()
                self.assertFalse(report["buildReady"])
                self.assertIn(name, self.check(report, "resources")["detail"])
                self.assertEqual(self.check(report, "math")["status"], "pass")

    def test_temporary_subdirectory_restriction_does_not_hide_working_workspace(self):
        with patch.object(self.doctor.tempfile, "TemporaryDirectory", side_effect=PermissionError):
            report = self.probe()
        self.assertTrue(report["buildReady"])
        self.assertEqual(self.check(report, "workspace")["status"], "pass")
        self.assertEqual(self.check(report, "node")["status"], "pass")
        self.assertEqual(self.check(report, "math")["status"], "pass")

    def test_probe_file_creation_denied_does_not_skip_node_or_math(self):
        with patch.object(self.doctor.tempfile, "mkstemp", side_effect=PermissionError("blocked")):
            report = self.probe()
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "workspace")["status"], "fail")
        self.assertEqual(self.check(report, "node")["status"], "pass")
        self.assertEqual(self.check(report, "math")["status"], "pass")
        steps = self.check(report, "workspace")["steps"]
        self.assertEqual(next(s for s in steps if s["id"] == "createFile")["status"], "fail")
        self.assertIn("工作区", self.check(report, "workspace")["detail"])

    def test_failed_workspace_directory_still_checks_node_in_safe_existing_directory(self):
        self.workspace.write_text("not a directory", encoding="utf-8")
        calls = []
        def transport(command, **kwargs):
            calls.append(kwargs["cwd"])
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            return self.transport(command, **kwargs)
        report = self.probe(transport)
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "node")["status"], "pass")
        self.assertEqual(self.check(report, "math")["status"], "pass")
        self.assertTrue(calls)
        self.assertEqual(self.workspace.read_text(encoding="utf-8"), "not a directory")

    def test_probe_read_mismatch_is_reported_and_file_is_removed(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.parent == self.workspace.resolve() and path.name.startswith("dth-doctor-"):
                return "changed"
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            report = self.probe()
        self.assertFalse(report["buildReady"])
        steps = self.check(report, "workspace")["steps"]
        self.assertEqual(next(s for s in steps if s["id"] == "read")["status"], "fail")
        self.assertEqual(next(s for s in steps if s["id"] == "delete")["status"], "pass")
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_write_failure_still_closes_and_removes_exclusive_probe(self):
        with patch.object(self.doctor.os, "fdopen", side_effect=PermissionError("write blocked")):
            report = self.probe()
        steps = self.check(report, "workspace")["steps"]
        self.assertFalse(report["buildReady"])
        self.assertEqual(next(s for s in steps if s["id"] == "write")["status"], "fail")
        self.assertEqual(next(s for s in steps if s["id"] == "read")["status"], "unverified")
        self.assertEqual(next(s for s in steps if s["id"] == "delete")["status"], "pass")
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertEqual(self.check(report, "node")["status"], "pass")
        self.assertEqual(self.check(report, "math")["status"], "pass")

    def test_non_math_resource_failure_does_not_skip_actual_math_probe(self):
        with patch.object(self.doctor, "missing_resources", return_value=["SKILL.md"]):
            report = self.probe()
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "resources")["status"], "fail")
        self.assertEqual(self.check(report, "math")["status"], "pass")

    def test_cleanup_failure_names_leftover_file_without_hiding_node(self):
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.parent == self.workspace.resolve() and path.name.startswith("dth-doctor-"):
                raise PermissionError("cleanup denied")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink):
            report = self.probe()
        check = self.check(report, "workspace")
        self.assertFalse(report["buildReady"])
        self.assertEqual(check["status"], "fail")
        self.assertEqual(next(s for s in check["steps"] if s["id"] == "delete")["status"], "fail")
        self.assertEqual(self.check(report, "node")["status"], "pass")
        leftover = Path(check["leftoverProbe"])
        self.assertEqual(leftover.parent, self.workspace.resolve())
        self.assertTrue(leftover.is_file())
        self.assertIn(str(leftover), check["detail"])
        leftover.unlink()

    def test_missing_math_dependency_is_unverified_not_a_failed_execution(self):
        with patch.object(self.doctor.shutil, "which", return_value=None):
            report = self.doctor.run_doctor(self.workspace, node="absent-node")
        self.assertEqual(self.check(report, "math")["status"], "unverified")
        self.assertIn("未执行", self.check(report, "math")["detail"])

    def test_existing_user_files_are_never_overwritten_or_deleted(self):
        self.workspace.mkdir()
        original = self.workspace / "dth-doctor-user-file.txt"
        original.write_text("keep", encoding="utf-8")
        report = self.probe()
        self.assertTrue(report["buildReady"])
        self.assertEqual(original.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(self.workspace.iterdir()), [original])

    def test_older_node_is_reported_without_a_false_minimum_for_formula_probe(self):
        def transport(command, **kwargs):
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, "v18.20.0\n", "")
            if "-e" in command:
                return subprocess.CompletedProcess(command, 1, "", "Playwright requires Node 20+")
            return self.transport(command, **kwargs)
        report = self.probe(transport)
        self.assertTrue(report["buildReady"])
        self.assertEqual(self.check(report, "node")["detail"], "v18.20.0")
        self.assertEqual(self.check(report, "math")["status"], "pass")
        self.assertEqual(self.check(report, "playwright")["status"], "unverified")

    def test_workspace_and_report_inside_installation_are_rejected_before_writes(self):
        for workspace, out in ((ROOT, None), (ROOT / "do-not-create", None),
                               (self.workspace, ROOT / "do-not-write.json")):
            with self.subTest(workspace=workspace, out=out):
                with patch.object(self.doctor.tempfile, "TemporaryDirectory") as temporary, \
                     patch.object(self.doctor.subprocess, "run") as process:
                    report = self.doctor.run_doctor(workspace, out=out)
                self.assertFalse(report["buildReady"])
                temporary.assert_not_called()
                process.assert_not_called()
        self.assertFalse((ROOT / "do-not-create").exists())
        self.assertFalse((ROOT / "do-not-write.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_into_installation_does_not_bypass_workspace_boundary(self):
        link = self.root / "linked-skill"
        try:
            link.symlink_to(ROOT, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks not permitted in this environment")
        report = self.probe(out=link / "do-not-write.json")
        self.assertFalse(report["buildReady"])
        self.assertFalse((ROOT / "do-not-write.json").exists())

    def test_report_outside_workspace_is_rejected(self):
        out = self.root / "elsewhere.json"
        report = self.probe(out=out)
        self.assertFalse(report["buildReady"])
        self.assertFalse(out.exists())

    def test_timeout_is_reported_without_success(self):
        def timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 10)
        report = self.probe(timeout)
        self.assertFalse(report["buildReady"])
        self.assertEqual(self.check(report, "node")["status"], "fail")

    def test_cli_works_from_foreign_directory_and_writes_utf8_report(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        out = self.workspace / "checks" / "环境.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.workspace),
                                 "--node", str(self.root / "absent-node"), "--out", str(out)],
                                cwd=foreign, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), report)
        self.assertFalse(report["buildReady"])
        self.assertFalse(report["fullConversionVerified"])
        self.assertEqual(list(foreign.iterdir()), [])

    def test_cli_json_remains_utf8_when_terminal_default_is_ascii(self):
        environment = dict(os.environ, PYTHONIOENCODING="ascii")
        result = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.workspace),
                                 "--node", str(self.root / "absent-node")],
                                env=environment, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stderr, b"", "Environment failure must return JSON, not an encoding traceback")
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertFalse(report["buildReady"])
        self.assertEqual(report["workspace"], str(self.workspace.resolve()))


if __name__ == "__main__":
    unittest.main()
