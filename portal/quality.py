"""Run the real, isolated file:// learning-product browser checks.

No server fallback and no synthetic success when a browser is unavailable.
Screenshots are evidence for a separate visual review, not proof of semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile


def _result(status: str, detail: str) -> dict:
    return {"status": status, "checks": [], "screenshots": [], "detail": detail}


def run_browser(html_path: Path, report_dir: Path, timeout: int = 180) -> dict:
    html_path, report_dir = Path(html_path).resolve(), Path(report_dir).resolve()
    if not html_path.is_file():
        return _result("fail", "待检查的 HTML 不存在。")
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node or not shutil.which(node):
        return _result("unverified", "缺少可运行的 Node，真实浏览器检查未执行。")
    executable = os.environ.get("BROWSER_EXECUTABLE")
    if executable and not Path(executable).is_file():
        return _result("unverified", "BROWSER_EXECUTABLE 指定的浏览器不存在。")
    report_dir.mkdir(parents=True, exist_ok=True)
    # Every invocation gets a fresh path; a stale successful report cannot pass.
    run_dir = Path(tempfile.mkdtemp(prefix="browser-", dir=report_dir))
    output = run_dir / "runtime-report.json"
    script = Path(__file__).resolve().parents[1] / "tests" / "runtime-check.cjs"
    expected_hash = hashlib.sha256(html_path.read_bytes()).hexdigest()
    timed_out = False
    try:
        process = subprocess.Popen(
            [node, str(script), str(html_path), str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout, stderr = process.communicate(timeout=max(1, timeout))
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass  # The process may exit between the timeout and kill.
            stdout, stderr = process.communicate()
            timed_out = True
    except OSError:
        return _result("unverified", "无法启动浏览器检查进程，请检查 Node 与运行权限。")
    # Preserve private diagnostics even when the report is absent or invalid.
    try:
        (run_dir / "process.log").write_text(stdout + "\n" + stderr, encoding="utf-8")
    except OSError:
        pass  # Diagnostic storage must not replace the report's verdict.
    if timed_out:
        return _result("unverified", "真实浏览器检查超时，未完成的检查不能视为通过。")
    try:
        report = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("report must be an object")
        valid = (report.get("status") in {"pass", "fail", "unverified"}
                 and report.get("sha256") == expected_hash
                 and hashlib.sha256(html_path.read_bytes()).hexdigest() == expected_hash
                 and report.get("file") == str(html_path)
                 and isinstance(report.get("checks"), list)
                 and isinstance(report.get("screenshots"), list))
        if not valid:
            raise ValueError("invalid report identity or structure")
        if not all(isinstance(c, dict) and isinstance(c.get("name"), str)
                   and c.get("status") in {"pass", "fail", "not_applicable", "unverified"}
                   for c in report["checks"]):
            raise ValueError("invalid checks")
        if not all(isinstance(s, str) and Path(s).is_file()
                   and Path(s).resolve().is_relative_to(run_dir)
                   for s in report["screenshots"]):
            raise ValueError("invalid screenshots")
        if report["status"] == "pass":
            valid = (process.returncode == 0 and report["checks"]
                     and report.get("opening") == "file://" and report.get("browser")
                     and not any(c["status"] in {"fail", "unverified"} for c in report["checks"])
                     and report["screenshots"])
            if not valid:
                raise ValueError("cannot accept success")
    except (OSError, ValueError, TypeError, AssertionError):
        return _result("fail", "浏览器未产生有效且对应当前 HTML 的检查报告，不能交付为已通过。")
    report["reportPath"] = str(output)
    report.setdefault("detail", "仅覆盖报告列出的真实浏览器检查；内容学术与视觉语义需单独核查。")
    return report
