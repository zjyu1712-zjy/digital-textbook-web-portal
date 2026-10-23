"""Accept only the expected missing-model state from the real browser preflight."""
import argparse
import json
from pathlib import Path


REQUIRED_CHECKS = {
    "模型配置", "pypdf", "pypdfium2", "PIL", "公式运行组件", "任务数据目录", "真实离线浏览器",
}
MISSING_MODEL = "管理员尚未配置模型 API 凭据；管理员尚未指定转换模型"


def validate_report(report, exit_code):
    if exit_code != 1:
        raise ValueError(f"Expected preflight exit 1 for missing model configuration, got {exit_code}")
    if not isinstance(report, dict) or report.get("readyForFirstLiveTrial") is not False:
        raise ValueError("Preflight must retain readyForFirstLiveTrial=false")
    checks = report.get("checks")
    if not isinstance(checks, list) or not all(isinstance(check, dict) for check in checks):
        raise ValueError("Preflight checks must be a list of objects")
    names = [check.get("name") for check in checks]
    if not all(isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise ValueError("Preflight check names must be unique strings")
    if not REQUIRED_CHECKS.issubset(names):
        raise ValueError("Preflight is missing a required check, including the real browser check")
    for check in checks:
        if check["name"] == "模型配置":
            if check.get("status") != "unverified" or check.get("detail") != MISSING_MODEL:
                raise ValueError("Only missing API credentials and model name are expected")
        elif check.get("status") != "pass":
            raise ValueError(f"Preflight check did not pass: {check['name']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("exit_code", type=int)
    args = parser.parse_args()
    try:
        validate_report(json.loads(args.report.read_text(encoding="utf-8")), args.exit_code)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print("PASS: all runtime checks, including the real browser, passed; model configuration remains unverified")


if __name__ == "__main__":
    main()
