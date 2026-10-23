"""Test the CI report gate only; these fixtures are not browser-run evidence."""
import copy
import unittest

from scripts.container_preflight_check import validate_report


VALID_REPORT = {
    "checks": [
        {"name": "模型配置", "status": "unverified",
         "detail": "管理员尚未配置模型 API 凭据；管理员尚未指定转换模型"},
        {"name": "pypdf", "status": "pass", "detail": "组件可加载"},
        {"name": "pypdfium2", "status": "pass", "detail": "组件可加载"},
        {"name": "PIL", "status": "pass", "detail": "组件可加载"},
        {"name": "公式运行组件", "status": "pass", "detail": "可用"},
        {"name": "任务数据目录", "status": "pass", "detail": "已实际写入和读回；不影响用户任务"},
        {"name": "真实离线浏览器", "status": "pass", "detail": "浏览器报告校验通过"},
    ],
    "readyForFirstLiveTrial": False,
    "liveModelCall": "未执行；首次上线需用明确授权的小样本完成真实转换验收",
}


class ContainerPreflightTests(unittest.TestCase):
    def test_accepts_only_expected_missing_model_state(self):
        report = copy.deepcopy(VALID_REPORT)
        validate_report(report, 1)
        self.assertEqual(report, VALID_REPORT)

    def test_rejects_unexpected_process_exit(self):
        for exit_code in (0, 2, 125, 137):
            with self.subTest(exit_code=exit_code), self.assertRaises(ValueError):
                validate_report(copy.deepcopy(VALID_REPORT), exit_code)

    def test_rejects_missing_checks_and_wrong_statuses(self):
        for expected in VALID_REPORT["checks"]:
            name = expected["name"]
            report = copy.deepcopy(VALID_REPORT)
            report["checks"] = [check for check in report["checks"] if check["name"] != name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                validate_report(report, 1)
            for status in ("pass", "fail", "unverified", "not_applicable"):
                if status == expected["status"]:
                    continue
                report = copy.deepcopy(VALID_REPORT)
                next(check for check in report["checks"] if check["name"] == name)["status"] = status
                with self.subTest(check=name, status=status), self.assertRaises(ValueError):
                    validate_report(report, 1)

    def test_rejects_invalid_or_weakened_reports(self):
        ready = copy.deepcopy(VALID_REPORT)
        ready["readyForFirstLiveTrial"] = True
        duplicate = copy.deepcopy(VALID_REPORT)
        duplicate["checks"].append(copy.deepcopy(duplicate["checks"][0]))
        missing_skill = copy.deepcopy(VALID_REPORT)
        missing_skill["checks"][0]["detail"] += "；转换 Skill 尚未安装到服务端"
        extra_unverified = copy.deepcopy(VALID_REPORT)
        extra_unverified["checks"].append({"name": "新增必要检查", "status": "unverified"})
        cases = (
            ("null", None), ("array", []), ("empty object", {}),
            ("missing readiness", {"checks": []}), ("unexpectedly ready", ready),
            ("duplicate check", duplicate), ("missing skill", missing_skill),
            ("another unverified check", extra_unverified),
        )
        for label, report in cases:
            with self.subTest(case=label), self.assertRaises(ValueError):
                validate_report(report, 1)


if __name__ == "__main__":
    unittest.main()
