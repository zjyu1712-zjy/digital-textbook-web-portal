"""The gate must reject missing tools, stale/malformed evidence and timeouts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from portal.quality import run_browser


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.html = self.root / "course.html"
        self.html.write_text("<!doctype html><title>test</title>", encoding="utf-8")
        self.reports = self.root / "checks"
        self.env = patch.dict(os.environ, {"NODE_BINARY": "node"}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def process(self, report_transform=None, returncode=0, raw=None, missing_report=False,
                stdout="", stderr=""):
        def start(command, **kwargs):
            output = Path(command[-1])
            shot = output.parent / "screen.png"
            shot.write_bytes(b"test screenshot placeholder; unit test only")
            report = {
                "status": "pass", "file": str(self.html.resolve()),
                "sha256": hashlib.sha256(self.html.read_bytes()).hexdigest(),
                "opening": "file://", "browser": "unit-test-process-stub",
                "checks": [{"name": "probe", "status": "pass"}],
                "screenshots": [str(shot)],
            }
            if report_transform:
                report_transform(report)
            if not missing_report:
                output.write_text(raw if raw is not None else json.dumps(report), encoding="utf-8")
            proc = Mock(returncode=returncode)
            proc.communicate.return_value = (stdout, stderr)
            return proc
        return start

    def run_mock(self, **kwargs):
        with patch("portal.quality.shutil.which", return_value="/test/node"), \
             patch("portal.quality.subprocess.Popen", side_effect=self.process(**kwargs)):
            return run_browser(self.html, self.reports)

    def test_missing_html_is_failure(self):
        self.assertEqual(run_browser(self.root / "absent.html", self.reports)["status"], "fail")

    def test_missing_node_is_unverified(self):
        with patch("portal.quality.shutil.which", return_value=None):
            self.assertEqual(run_browser(self.html, self.reports)["status"], "unverified")

    def test_configured_missing_browser_is_unverified(self):
        with patch.dict(os.environ, {"BROWSER_EXECUTABLE": str(self.root / "missing-browser")}), \
             patch("portal.quality.shutil.which", return_value="/test/node"):
            self.assertEqual(run_browser(self.html, self.reports)["status"], "unverified")

    def test_start_permission_error_is_unverified(self):
        with patch("portal.quality.shutil.which", return_value="/test/node"), \
             patch("portal.quality.subprocess.Popen", side_effect=PermissionError):
            self.assertEqual(run_browser(self.html, self.reports)["status"], "unverified")

    def test_malformed_report_fails(self):
        for raw in ("not json", "[]", "null", '{"status":"pass"}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_mock(raw=raw)["status"], "fail")

    def assert_private_process_log(self, result, stdout, stderr):
        logs = list(self.reports.glob("browser-*/process.log"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_text(encoding="utf-8"), stdout + "\n" + stderr)
        public_result = json.dumps(result, ensure_ascii=False)
        for private in (stdout, stderr, str(logs[0])):
            self.assertNotIn(private, public_result)

    def test_malformed_report_keeps_private_process_log(self):
        stdout, stderr = "private browser output", "private browser diagnostic"
        result = self.run_mock(raw="not json", stdout=stdout, stderr=stderr)
        self.assertEqual(result["status"], "fail")
        self.assert_private_process_log(result, stdout, stderr)

    def test_missing_report_keeps_private_process_log(self):
        stdout, stderr = "private startup output", "private module failure"
        result = self.run_mock(missing_report=True, returncode=1, stdout=stdout, stderr=stderr)
        self.assertEqual(result["status"], "fail")
        self.assert_private_process_log(result, stdout, stderr)

    def test_log_write_error_does_not_change_invalid_report_status(self):
        write_text = Path.write_text
        def deny_log(path, *args, **kwargs):
            if path.name == "process.log":
                raise PermissionError("private diagnostic write error")
            return write_text(path, *args, **kwargs)
        with patch.object(Path, "write_text", deny_log):
            result = self.run_mock(raw="not json")
        self.assertEqual(result["status"], "fail")
        self.assertNotIn("private diagnostic", json.dumps(result))

    def test_stale_hash_fails(self):
        result = self.run_mock(report_transform=lambda r:r.update(sha256="0" * 64))
        self.assertEqual(result["status"], "fail")

    def test_wrong_file_fails(self):
        self.assertEqual(self.run_mock(report_transform=lambda r:r.update(file="/different/book.html"))["status"], "fail")

    def test_failed_process_cannot_report_pass(self):
        self.assertEqual(self.run_mock(returncode=1)["status"], "fail")

    def test_empty_or_failed_checks_cannot_report_pass(self):
        for checks in ([], [{"name":"save", "status":"fail"}], [{"name":"save", "status":"unverified"}], ["pass"]):
            with self.subTest(checks=checks):
                self.assertEqual(self.run_mock(report_transform=lambda r:r.update(checks=checks))["status"], "fail")

    def test_missing_or_external_screenshot_fails(self):
        for screenshots in ([], [str(self.html)], [str(self.root / "missing.png")]):
            with self.subTest(screenshots=screenshots):
                self.assertEqual(self.run_mock(report_transform=lambda r:r.update(screenshots=screenshots))["status"], "fail")

    def test_http_cannot_substitute_for_file(self):
        self.assertEqual(self.run_mock(report_transform=lambda r:r.update(opening="http://localhost"))["status"], "fail")

    def test_real_check_failure_preserved(self):
        result = self.run_mock(returncode=1, report_transform=lambda r:r.update(status="fail", detail="保存失败", checks=[{"name":"save", "status":"fail"}]))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["detail"], "保存失败")

    def test_valid_report_preserves_manual_visual_limit(self):
        result = self.run_mock(report_transform=lambda r:r.update(visualReview={"status":"unverified"}))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["visualReview"]["status"], "unverified")
        self.assertTrue(Path(result["reportPath"]).is_file())

    def test_timeout_kills_process_group_and_never_passes(self):
        stdout, stderr = "private buffered output", "private timeout diagnostic"
        proc = Mock(pid=98765)
        proc.communicate.side_effect = [subprocess.TimeoutExpired("node", 1), (stdout, stderr)]
        with patch("portal.quality.shutil.which", return_value="/test/node"), \
             patch("portal.quality.subprocess.Popen", return_value=proc), \
             patch("portal.quality.os.killpg") as kill:
            result = run_browser(self.html, self.reports, timeout=1)
            self.assertEqual(result["status"], "unverified")
            if os.name == "posix":
                kill.assert_called_once()
        self.assert_private_process_log(result, stdout, stderr)

    def test_timeout_process_exit_race_keeps_private_process_log(self):
        stdout, stderr = "private final output", "private exit diagnostic"
        proc = Mock(pid=98765)
        proc.communicate.side_effect = [subprocess.TimeoutExpired("node", 1), (stdout, stderr)]
        proc.kill.side_effect = ProcessLookupError
        with patch("portal.quality.shutil.which", return_value="/test/node"), \
             patch("portal.quality.subprocess.Popen", return_value=proc), \
             patch("portal.quality.os.killpg", side_effect=ProcessLookupError):
            result = run_browser(self.html, self.reports, timeout=1)
        self.assertEqual(result["status"], "unverified")
        self.assertIn("超时", result["detail"])
        self.assert_private_process_log(result, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
