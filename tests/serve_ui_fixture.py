"""Isolated UI test server. Never imported by the product or enabled by config.

Only the repository's exact, self-authored general-source.txt is accepted. The
converter packages the matching committed fixture; it does NOT interpret books
or contact a model. Every progress message declares this test-only limitation.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portal.config import Config
from portal.server import create_app
from portal.__main__ import ThreadedServer

EXPECTED_SOURCE_SHA256 = "2dc18a77faebcf6d12a873a478c7e9d1ee42359f10370baab3f576403cb6075d"
PREFIX = "测试样本，未调用真实模型："


class FixedSampleConverter:
    def __init__(self, config):
        self.config = config

    def run(self, job_dir, manifest, emit, cancelled):
        files = manifest.get("files", [])
        if len(files) != 1:
            raise ValueError(PREFIX + "仅接受指定的一份测试源文件")
        payload = (job_dir / files[0]["path"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != EXPECTED_SOURCE_SHA256:
            raise ValueError(PREFIX + "上传资料并非指定测试源文件，已拒绝处理")
        fixture = self.config.skill_dir / "tests" / "fixtures"
        if hashlib.sha256((fixture / "general-source.txt").read_bytes()).hexdigest() != EXPECTED_SOURCE_SHA256:
            raise ValueError(PREFIX + "内置测试源文件校验失败")
        emit("extracting", PREFIX + "已核对自写小样本的固定校验值")
        if cancelled():
            return {"status": "cancelled", "message": PREFIX + "已取消", "checks": []}
        script = self.config.skill_dir / "scripts" / "pipeline.py"
        output = job_dir / "test-sample.html"
        emit("generating", PREFIX + "复用 Skill 打包已审定的对应测试数据")
        command = [sys.executable, str(script), "build", str(fixture / "general.json"), "--inventory", str(fixture / "inventory.json"), "--out", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise ValueError(PREFIX + "测试成品构建失败")
        emit("validating", PREFIX + "检查生成 HTML 的资源与结构")
        inspected = subprocess.run([sys.executable, str(script), "inspect", str(output)], capture_output=True, text=True, timeout=30)
        if inspected.returncode != 0:
            raise ValueError(PREFIX + "测试成品资源检查失败")
        checks = [
            {"name": "仅限自写固定测试样本", "status": "pass", "detail": "上传文件与指定源文件 SHA-256 一致；未执行真实模型转换。"},
            {"name": "真实 Skill 构建与单文件检查", "status": "pass", "detail": "已执行 Skill 的 build 与 inspect；浏览器端测试另行记录。"},
        ]
        (job_dir / "fixture-receipt.json").write_text(json.dumps({"fixture": True, "realModelCalled": False, "sha256": EXPECTED_SOURCE_SHA256, "source": "skill/tests/fixtures/general-source.txt", "buildReturnCode": result.returncode, "inspectReturnCode": inspected.returncode}), encoding="utf-8")
        return {"status": "ready", "message": PREFIX + "对应的自写样本已构建，供入口与下载链路测试。", "checks": checks, "artifact": output.name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--unconfigured", action="store_true")
    parser.add_argument("--provider", choices=("openai", "bailian"), default="openai")
    args = parser.parse_args()
    # Never use persistent project or user data, and never read real API keys.
    with tempfile.TemporaryDirectory(prefix="textbook-ui-fixture-") as tmp:
        config = Config(
            data_dir=Path(tmp), skill_dir=ROOT / "skill", static_dir=ROOT / "static",
            api_key="" if args.unconfigured else "fixture-not-a-real-key",
            model="" if args.unconfigured else "fixed-self-authored-fixture",
            public_origin=f"http://127.0.0.1:{args.port}", access_code="ui-test-access",
            min_free_bytes=0,
            provider=args.provider, bailian_workspace_id="test-space" if args.provider == "bailian" else "",
        )
        app = create_app(config, converter_factory=FixedSampleConverter)
        try:
            with make_server("127.0.0.1", args.port, app, server_class=ThreadedServer) as server:
                signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
                print(json.dumps({"ready": True, "port": args.port, "testOnly": True, "realModelCalled": False}), flush=True)
                server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass
        finally:
            app.close()


if __name__ == "__main__":
    main()
