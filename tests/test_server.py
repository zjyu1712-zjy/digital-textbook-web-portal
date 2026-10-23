"""HTTP and queue contract tests. The converter is injected only by tests."""
import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile
from dataclasses import replace

from portal.config import Config
from portal.server import create_app


class GoodConverter:
    def __init__(self, config):
        self.config = config

    def run(self, job_dir, manifest, emit, cancelled):
        emit("quality", "正在检查")
        (job_dir / "book.html").write_text("<!doctype html><html lang='zh'><body>测试教材</body></html>", encoding="utf-8")
        return {"status": "ready", "message": "完成", "checks": [{"name": "test", "status": "pass"}], "artifact": "book.html"}


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        skill = root / "skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("test")
        self.config = Config(data_dir=root / "private", skill_dir=skill, api_key="test-secret", model="test-model", public_origin="http://127.0.0.1:8000")
        self.apps = []
        self.app = self.make_app()

    def make_app(self, **kwargs):
        app = create_app(kwargs.pop("config", self.config), converter_factory=kwargs.pop("converter_factory", GoodConverter), start_worker=kwargs.pop("start_worker", False), **kwargs)
        self.apps.append(app)
        return app

    def tearDown(self):
        for app in reversed(self.apps):
            app.close()
        self.tmp.cleanup()

    def call(self, path="/api/config", method="GET", body=None, token=None, app=None, **headers):
        raw = b"" if body is None else json.dumps(body).encode()
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "SERVER_NAME": "127.0.0.1", "SERVER_PORT": "8000", "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json", "HTTP_HOST": "127.0.0.1:8000"}
        if method in {"POST", "DELETE"}:
            env["HTTP_ORIGIN"] = "http://127.0.0.1:8000"
        if token:
            env["HTTP_AUTHORIZATION"] = "Bearer " + token
        env.update(headers)
        captured = {}
        def start(status, response_headers):
            captured.update(status=int(status.split()[0]), headers=dict(response_headers))
        iterable = (app or self.app)(env, start)
        try:
            data = b"".join(iterable)
        finally:
            if hasattr(iterable, "close"):
                iterable.close()
        captured["body"] = json.loads(data) if captured["headers"].get("Content-Type", "").startswith("application/json") else data
        return captured

    def payload(self, **updates):
        p = {"title": "测试课本", "mode": "auto", "scope": "所上传内容", "consent": True, "files": [{"name": "教材.txt", "role": "textbook", "primary": True, "data": base64.b64encode("第一章\n实际教材正文".encode()).decode()}]}
        p.update(updates)
        return p

    def submit(self, **kwargs):
        response = self.call("/api/jobs", "POST", self.payload(**kwargs))
        self.assertEqual(response["status"], 202, response)
        return response["body"]

    def path(self, job, suffix=""):
        return "/api/jobs/" + job["id"] + suffix

    def test_missing_credentials_rejected_before_input_is_stored(self):
        app = self.make_app(config=replace(self.config, api_key="", model=""))
        self.assertFalse(self.call(app=app)["body"]["ready"])
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), app=app)["status"], 503)
        self.assertEqual(list((self.config.data_dir / "jobs").iterdir()), [])

    def test_config_does_not_disclose_secrets(self):
        result = self.call()["body"]
        self.assertTrue(result["ready"])
        self.assertNotIn(self.config.api_key, json.dumps(result))

    def test_host_origin_and_fetch_metadata_are_checked(self):
        self.assertEqual(self.call(HTTP_HOST="evil.example")["status"], 403)
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), HTTP_ORIGIN="https://evil.example")["status"], 403)
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), HTTP_SEC_FETCH_SITE="cross-site")["status"], 403)
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), HTTP_ORIGIN="null")["status"], 403)

    def test_consent_is_explicit_and_access_code_is_optional(self):
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(consent=False))["status"], 400)
        app = self.make_app(config=replace(self.config, access_code="shared-code"))
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), app=app)["status"], 403)
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(accessCode="shared-code"), app=app)["status"], 202)

    def test_tokens_isolate_jobs_and_are_stored_as_hashes(self):
        first, second = self.submit(), self.submit(title="另一册")
        self.assertEqual(self.call(self.path(first), token=second["token"])["status"], 404)
        self.assertEqual(self.call(self.path(first))["status"], 404)
        result = self.call(self.path(first), token=first["token"])
        self.assertEqual(result["status"], 200)
        self.assertNotIn(first["token"], json.dumps(result["body"]))
        self.assertNotIn(first["token"].encode(), (self.config.data_dir / "jobs.sqlite3").read_bytes())

    def test_uploaded_paths_and_signatures_are_validated(self):
        for name, data in [("../../secret.txt", b"x"), ("attack.html", b"<script>x</script>"), ("false.pdf", b"not pdf"), ("false.docx", b"not zip"), ("binary.txt", b"\x00\xff")]:
            payload = self.payload()
            payload["files"][0].update(name=name, data=base64.b64encode(data).decode())
            with self.subTest(name=name):
                self.assertEqual(self.call("/api/jobs", "POST", payload)["status"], 400)

    def test_invalid_base64_and_duplicate_inputs_are_rejected(self):
        payload = self.payload()
        payload["files"][0]["data"] = "%%%"
        self.assertEqual(self.call("/api/jobs", "POST", payload)["status"], 400)
        payload = self.payload()
        payload["files"] *= 2
        self.assertEqual(self.call("/api/jobs", "POST", payload)["status"], 400)

    def test_size_file_count_and_queue_limits(self):
        app = self.make_app(config=replace(self.config, max_file_bytes=4))
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), app=app)["status"], 413)
        app = self.make_app(config=replace(self.config, max_files=1))
        p = self.payload()
        p["files"].append(dict(p["files"][0], name="other.txt"))
        self.assertEqual(self.call("/api/jobs", "POST", p, app=app)["status"], 400)
        app = self.make_app(config=replace(self.config, max_queue=1))
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), app=app)["status"], 202)
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), app=app)["status"], 429)

    def test_worker_and_download_and_delete(self):
        job = self.submit()
        self.assertEqual(self.call(self.path(job, "/download"), token=job["token"])["status"], 409)
        self.assertTrue(self.app.process_one())
        status = self.call(self.path(job), token=job["token"])["body"]
        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["downloadAvailable"])
        download = self.call(self.path(job, "/download"), token=job["token"])
        self.assertEqual(download["status"], 200)
        self.assertIn("attachment", download["headers"]["Content-Disposition"])
        self.assertIn("测试教材".encode(), download["body"])
        self.assertEqual(self.call(self.path(job), "DELETE", token=job["token"])["status"], 200)
        self.assertFalse((self.config.data_dir / "jobs" / job["id"]).exists())
        self.assertEqual(self.call(self.path(job), token=job["token"])["status"], 404)

    def test_cancel_and_retry_preserve_manifest_identifiers(self):
        job = self.submit()
        manifest_file = self.config.data_dir / "jobs" / job["id"] / "manifest.json"
        before = manifest_file.read_text()
        self.assertEqual(self.call(self.path(job, "/cancel"), "POST", {}, token=job["token"])["status"], 200)
        self.assertFalse(self.app.process_one())
        self.assertEqual(self.call(self.path(job), token=job["token"])["body"]["status"], "cancelled")
        self.assertEqual(self.call(self.path(job, "/retry"), "POST", {}, token=job["token"])["status"], 202)
        self.assertTrue(self.app.process_one())
        self.assertEqual(manifest_file.read_text(), before)

    def test_errors_do_not_leak_credentials_or_paths(self):
        class Broken(GoodConverter):
            def run(self, *args):
                raise ValueError("test-secret /private/credentials traceback")
        app = self.make_app(converter_factory=Broken)
        job = self.submit()
        app.process_one()
        response = self.call(self.path(job), token=job["token"])["body"]
        self.assertEqual(response["status"], "failed")
        self.assertNotIn("test-secret", json.dumps(response))
        self.assertNotIn("credentials", json.dumps(response))

    def test_failed_quality_cannot_enable_download(self):
        class BadQuality(GoodConverter):
            def run(self, *args):
                result = super().run(*args)
                result["checks"][0]["status"] = "unverified"
                return result
        app = self.make_app(converter_factory=BadQuality)
        job = self.submit()
        app.process_one()
        self.assertFalse(self.call(self.path(job), token=job["token"])["body"]["downloadAvailable"])
        self.assertEqual(self.call(self.path(job, "/download"), token=job["token"])["status"], 409)

    def test_artifact_must_stay_inside_job(self):
        class Escape(GoodConverter):
            def run(self, *args):
                result = super().run(*args)
                result["artifact"] = "../../secret.html"
                return result
        app = self.make_app(converter_factory=Escape)
        job = self.submit()
        app.process_one()
        self.assertEqual(self.call(self.path(job, "/download"), token=job["token"])["status"], 409)

    def test_restart_marks_inflight_interrupted_and_can_retry(self):
        job = self.submit()
        self.app.store.claim()
        self.app.store.recover_interrupted()
        self.assertEqual(self.call(self.path(job), token=job["token"])["body"]["status"], "interrupted")
        self.assertEqual(self.call(self.path(job, "/retry"), "POST", {}, token=job["token"])["status"], 202)

    def test_expired_jobs_are_deleted(self):
        job = self.submit()
        self.app.cleanup(now=time.time() + self.config.retention_hours * 3600 + 1)
        self.assertEqual(self.call(self.path(job), token=job["token"])["status"], 404)
        self.assertFalse((self.config.data_dir / "jobs" / job["id"]).exists())

    def test_running_cancel_cannot_be_retried_or_deleted_during_conversion(self):
        entered, released = threading.Event(), threading.Event()
        class Slow(GoodConverter):
            def run(self, job_dir, manifest, emit, cancelled):
                entered.set()
                released.wait(2)
                self.was_cancelled = cancelled()
                return super().run(job_dir, manifest, emit, cancelled)
        app = self.make_app(converter_factory=Slow)
        job = self.submit()
        thread = threading.Thread(target=app.process_one)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.call(self.path(job, "/cancel"), "POST", {}, token=job["token"])
        self.assertEqual(self.call(self.path(job, "/retry"), "POST", {}, token=job["token"])["status"], 409)
        self.call(self.path(job), "DELETE", token=job["token"])
        self.assertEqual(self.call(self.path(job), token=job["token"])["status"], 404)
        released.set()
        thread.join(3)
        self.assertFalse((self.config.data_dir / "jobs" / job["id"]).exists())

    def test_valid_office_container_is_accepted_without_executing_it(self):
        for extension, entry in [("docx", "word/document.xml"), ("pptx", "ppt/presentation.xml")]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr(entry, "<document>Test</document>")
            payload = self.payload()
            payload["files"][0].update(name="textbook." + extension, data=base64.b64encode(buffer.getvalue()).decode())
            self.assertEqual(self.call("/api/jobs", "POST", payload)["status"], 202)

    def test_zip_bombs_and_path_entries_are_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "x" * (2 * 1024 * 1024))
        p = self.payload()
        p["files"][0].update(name="bomb.docx", data=base64.b64encode(buffer.getvalue()).decode())
        self.assertEqual(self.call("/api/jobs", "POST", p)["status"], 400)

    def test_queue_survives_new_application_and_worker_runs(self):
        job = self.submit()
        app = self.make_app(start_worker=True)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            row = app.store.get(job["id"])
            if row["status"] == "ready":
                break
            time.sleep(0.01)
        self.assertEqual(row["status"], "ready")
        with self.assertRaisesRegex(RuntimeError, "workers 1"):
            self.make_app(start_worker=True)

    def test_http_public_deploy_and_embedded_credentials_are_rejected(self):
        for origin in ["http://public.example", "https://key@public.example", "https://public.example/path", "https://public.example:invalid"]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                replace(self.config, public_origin=origin)

    def test_storage_failure_does_not_report_success(self):
        app = self.make_app(config=replace(self.config, max_storage_bytes=1))
        self.assertEqual(self.call("/api/jobs", "POST", self.payload(), app=app)["status"], 507)
        self.assertEqual(list((self.config.data_dir / "jobs").iterdir()), [])

    def test_source_identifiers_match_across_independent_jobs(self):
        one, two = self.submit(), self.submit(title="再次转换")
        first = json.loads(self.app.store.get(one["id"])["manifest"])
        second = json.loads(self.app.store.get(two["id"])["manifest"])
        self.assertEqual(first["files"][0]["id"], second["files"][0]["id"])


if __name__ == "__main__":
    unittest.main()
