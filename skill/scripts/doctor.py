"""Probe local prerequisites only; never install tools, call a model, or launch a browser."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


SKILL = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "SKILL.md", "scripts/pipeline.py", "scripts/check_math.cjs",
    "scripts/task_contract.py", "scripts/review_audit.py",
    "scripts/grading.py", "assets/grading.js", "scripts/independent_audit.py", "scripts/chapter_status.py",
    "assets/mistakes.js", "assets/mistakes.css", "assets/quality.js", "assets/quality.css",
    "assets/shell.html", "assets/style.css", "assets/storage.js", "assets/app.js",
    "assets/vendor/katex.min.js", "assets/vendor/katex.min.css",
    "references/schema.md", "references/quality.md", "references/preferences.md",
    "references/workflow.md", "references/testing.md", "tests/runtime-check.cjs",
)
MANUAL_CHECKS = (
    ("sourceReading", "需调用环境实际读取原文、原页与图表；本工具没有读取教材。"),
    ("ocr", "扫描件识别能力需按输入实测；纯文本资料可在转换报告中标为不适用。"),
    ("semanticReview", "教材理解、条件、推导、原题与答案须另作有范围的语义核查。"),
    ("fileStorage", "尚未运行真实 file:// 离线、保存、关闭重开与备份检查。"),
    ("visualReview", "尚未查看实际生成 HTML 的宽窄屏截图、公式与表格。"),
)


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _run(command, workspace, input_text=None):
    return subprocess.run(command, cwd=workspace, input=input_text, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=15)


def missing_resources(skill):
    missing = [name for name in REQUIRED_FILES
               if not (skill / name).is_file() or not within((skill / name).resolve(), skill)]
    if "assets/vendor/katex.min.css" not in missing:
        try:
            css = (skill / "assets/vendor/katex.min.css").read_text(encoding="utf-8")
            for url in re.findall(r"url\(([^)]+)\)", css):
                name = Path(url.strip("\"' ")).name
                name = re.sub(r"\.(woff|ttf)$", ".woff2", name)
                file = skill / "assets/vendor" / name
                if not file.is_file() or not within(file.resolve(), skill):
                    missing.append("assets/vendor/" + name)
        except (OSError, UnicodeError):
            missing.append("assets/vendor/katex.min.css (unreadable)")
    return sorted(set(missing))


def probe_workspace(workspace):
    """Probe the requested directory itself, without creating a child directory.

    Exclusive creation protects existing files. Every attempted stage is recorded;
    cleanup failures preserve the exact leftover name instead of hiding the error.
    """
    labels = {"createDirectory": "创建或确认工作区", "createFile": "创建唯一探测文件",
              "write": "写入", "read": "读回", "delete": "删除探测文件"}
    steps = [{"id": name, "status": "unverified", "detail": "未执行"} for name in labels]
    by_id = {step["id"]: step for step in steps}
    probe, descriptor = None, None
    stage = "createDirectory"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        by_id[stage].update(status="pass", detail="工作区目录已存在或已创建。")
        stage = "createFile"
        descriptor, name = tempfile.mkstemp(prefix="dth-doctor-", suffix=".tmp", dir=workspace)
        probe = Path(name)
        by_id[stage].update(status="pass", detail="在工作区直接创建了不覆盖现有文件的探测文件。")
        stage = "write"
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None  # The context manager owns and closes the descriptor.
            stream.write("数字教材：本地写读检查")
        by_id[stage].update(status="pass", detail="UTF-8 内容已写入并关闭文件。")
        stage = "read"
        if probe.read_text(encoding="utf-8") != "数字教材：本地写读检查":
            raise OSError("读回内容与写入内容不一致")
        by_id[stage].update(status="pass", detail="实际读回的内容与写入内容一致。")
    except (OSError, UnicodeError) as exc:
        by_id[stage].update(status="fail", detail=labels[stage] + "失败：" + str(exc))
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                by_id["delete"].update(status="fail", detail="关闭探测文件失败：" + str(exc))
        if probe is not None:
            try:
                probe.unlink()
                if by_id["delete"]["status"] != "fail":
                    by_id["delete"].update(status="pass", detail="已删除本次探测文件。")
            except OSError as exc:
                by_id["delete"].update(status="fail", detail="删除探测文件失败：" + str(exc))
    passed = all(step["status"] == "pass" for step in steps)
    detail = "已在指定工作区实际创建、写入、读回并删除唯一探测文件。" if passed else (
        "；".join(step["detail"] for step in steps if step["status"] == "fail")
        + "。请检查目录权限或选择可写的非受控工作区；未修改目录权限。")
    result = {"status": "pass" if passed else "fail", "detail": detail, "steps": steps}
    if probe is not None and by_id["delete"]["status"] == "fail":
        result["leftoverProbe"] = str(probe)
        result["detail"] += " 如该探测文件仍存在，请自行清理：" + str(probe)
    return result


def run_doctor(workspace, node=None, out=None, skill=SKILL):
    """Return JSON-compatible evidence. Only requested workspace/output may be written."""
    skill = Path(skill).expanduser().resolve()
    workspace = Path(workspace).expanduser().resolve()
    out = Path(out).expanduser().resolve() if out is not None else None
    report = {
        "schemaVersion": 1, "scope": "local prerequisites only; no conversion or browser run",
        "skillDirectory": str(skill), "workspace": str(workspace),
        "buildReady": False, "fullConversionVerified": False, "checks": [],
    }

    def add(name, status, detail, required=False, **evidence):
        report["checks"].append({"id": name, "status": status,
                                 "requiredForBuild": required, "detail": detail, **evidence})

    for name, detail in MANUAL_CHECKS:
        add(name, "unverified", detail)
    if within(workspace, skill) or (out is not None and within(out, skill)):
        add("pathBoundary", "fail", "工作区和报告必须在 Skill 安装目录之外；未写入安装目录。", True)
        return report
    if out is not None and not within(out, workspace):
        add("pathBoundary", "fail", "--out 必须位于 --workspace 指定的工作区内。", True)
        return report
    add("pathBoundary", "pass", "输出与临时探测文件限定在独立工作区。", True)
    add("python", "pass" if sys.version_info >= (3, 9) else "fail",
        "Python " + sys.version.split()[0] + "；构建需要 3.9 或更新版。", True)
    missing = missing_resources(skill)
    add("resources", "fail" if missing else "pass",
        "缺少或不可读取的资源：" + ", ".join(missing) if missing else
        "构建脚本、学习组件、必需引用和 CSS 对应字体均存在。", True)
    workspace_result = probe_workspace(workspace)
    workspace_ok = workspace_result["status"] == "pass"
    add("workspace", required=True, **workspace_result)
    # These commands only read installed resources. Their execution directory does
    # not depend on the workspace being writable (or even being a valid directory).
    probe_cwd = skill if skill.is_dir() else Path(__file__).resolve().parent

    chosen_node = node or os.environ.get("NODE_BINARY") or "node"
    executable = shutil.which(chosen_node)
    node_ok = False
    if not executable:
        add("node", "fail", "未找到指定的 Node；没有回退到其他配置或自动安装。", True)
    else:
        executable = str(Path(executable).resolve())
        try:
            result = _run([executable, "--version"], probe_cwd)
            version = result.stdout.strip()
            node_ok = result.returncode == 0 and bool(re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+].*)?", version))
            add("node", "pass" if node_ok else "fail",
                version if node_ok else "Node 版本探测失败，未宣称可运行。", True)
        except (OSError, subprocess.TimeoutExpired):
            add("node", "fail", "无法启动 Node 或版本探测超时。", True)

    math_missing = [name for name in ("scripts/check_math.cjs", "assets/vendor/katex.min.js")
                    if name in missing]
    if not node_ok or math_missing:
        add("math", "unverified", "缺少可运行的 Node 或公式资源，未执行公式检查；不代表公式检查失败。", True)
    else:
        try:
            expressions = [r"\frac{1}{2}", r"\begin{pmatrix}1&2\\3&4\end{pmatrix}"]
            result = _run([executable, str(skill / "scripts/check_math.cjs"),
                           str(skill / "assets/vendor/katex.min.js")], probe_cwd,
                          json.dumps(expressions))
            passed = result.returncode == 0 and json.loads(result.stdout).get("checked") == len(expressions)
            add("math", "pass" if passed else "fail",
                "实际验证了两条合成公式；不代表教材公式已核查。" if passed else
                "本地 KaTeX 合成公式探测失败。", True)
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            add("math", "fail", "本地公式检查不可执行、超时或未返回有效证据。", True)

    browser_path = None
    if node_ok:
        # Resolve from the requested workspace first, then the installation; never install.
        script = """const requested=process.argv[1],skill=process.argv[2],workspace=process.argv[3];
const resolved=require.resolve(requested,{paths:[workspace,skill]});
const pw=require(resolved);
console.log(JSON.stringify({modulePath:resolved,browserPath:pw.chromium.executablePath()}));"""
        try:
            result = _run([executable, "-e", script,
                           os.environ.get("PLAYWRIGHT_MODULE") or "playwright", str(skill), str(workspace)], probe_cwd)
            if result.returncode != 0:
                raise ValueError("module probe exited " + str(result.returncode))
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict) or not isinstance(payload.get("modulePath"), str) or not payload["modulePath"]:
                raise ValueError("invalid module evidence")
            candidate = payload.get("browserPath")
            browser_path = candidate if isinstance(candidate, str) and candidate else None
            add("playwright", "pass", "已实际加载本地 Playwright 模块；未启动浏览器。")
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            add("playwright", "unverified", "Playwright 未能加载或探测超时；可能缺依赖或 Node 版本不支持，未启动浏览器。")
    else:
        add("playwright", "unverified", "Node 不可用，未探测 Playwright。")

    browser_path = os.environ.get("BROWSER_EXECUTABLE") or browser_path
    if browser_path and Path(browser_path).is_file() and os.access(browser_path, os.X_OK):
        add("browserExecutable", "pass", "浏览器可执行文件存在；未启动，file:// 保存与功能尚未验证。")
    else:
        add("browserExecutable", "unverified", "未找到可执行浏览器；不能据此宣称浏览器检查通过。")

    report["buildReady"] = all(check["status"] == "pass" for check in report["checks"] if check["requiredForBuild"])
    if out is not None and workspace_ok:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            add("reportOutput", "fail", "环境报告无法保存到指定路径；JSON 仍输出到终端。", True)
            report["buildReady"] = False
    return report


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path, help="Writable directory outside the skill installation")
    parser.add_argument("--node", help="Node executable, otherwise NODE_BINARY or PATH")
    parser.add_argument("--out", type=Path, help="Optional UTF-8 report path inside the workspace")
    args = parser.parse_args(argv)
    report = run_doctor(args.workspace, node=args.node, out=args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["buildReady"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
