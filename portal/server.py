"""Same-origin WSGI portal; production uses one Gunicorn worker with threads."""
import atexit
import base64
import binascii
import hashlib
import hmac
from http import HTTPStatus
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
import unicodedata
from urllib.parse import quote, urlsplit
import uuid
from wsgiref.util import FileWrapper
import zipfile

from .config import Config
from .store import QueueFull, Store


FORMATS = ("pdf", "txt", "md", "docx", "pptx")
ROLES = {"textbook", "teacher_slides", "outline", "solution", "exam", "auxiliary"}
MODES = {"auto", "textbook", "slides", "outline", "combined"}
JOB_ROUTE = re.compile(r"^/api/jobs/([0-9a-f]{32})(?:/(cancel|retry|download))?$")
LOGGER = logging.getLogger(__name__)


class HTTPError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def _date(timestamp):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _factory(config):
    # Delayed import keeps the upload service bootable before converter dependencies load.
    from .runner import Converter
    return Converter(config)


def _same_origin(value, expected):
    try:
        a, b = urlsplit(value), urlsplit(expected)
        return (a.scheme, a.hostname, a.port or (443 if a.scheme == "https" else 80)) == (b.scheme, b.hostname, b.port or (443 if b.scheme == "https" else 80)) and not (a.username or a.password or a.query or a.fragment or a.path not in {"", "/"})
    except ValueError:
        return False


class Portal:
    def __init__(self, config, converter_factory=None, start_worker=True):
        self.config = config
        self.converter_factory = converter_factory or _factory
        self.config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config.data_dir.chmod(0o700)
        self.jobs_dir = config.data_dir / "jobs"
        self.jobs_dir.mkdir(exist_ok=True, mode=0o700)
        self.store = Store(config.data_dir / "jobs.sqlite3")
        self.stop = threading.Event()
        self.wake = threading.Event()
        self._upload_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._thread = None
        self._worker_lock = None
        if start_worker:
            self._start_worker()

    def _start_worker(self):
        import fcntl
        handle = (self.config.data_dir / "worker.lock").open("a")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError("此数据目录已有转换工作进程；请使用 Gunicorn --workers 1") from None
        self._worker_lock = handle
        self.store.recover_interrupted()
        self.cleanup()
        # A crash between saving files and committing the row can leave an orphan.
        # This sweep runs before serving requests, never beside an upload in progress.
        for directory in self.jobs_dir.iterdir():
            if directory.is_dir() and re.fullmatch(r"[0-9a-f]{32}", directory.name) and not self.store.get(directory.name):
                shutil.rmtree(directory)
        self._thread = threading.Thread(target=self._worker, name="textbook-converter", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def close(self):
        self.stop.set()
        self.wake.set()
        if self._thread and threading.current_thread() is not self._thread:
            self._thread.join(timeout=3)
        if self._worker_lock and not (self._thread and self._thread.is_alive()):
            self._worker_lock.close()
            self._worker_lock = None

    def _worker(self):
        last_cleanup = 0
        while not self.stop.is_set():
            try:
                if time.monotonic() - last_cleanup > 60:
                    self.cleanup()
                    last_cleanup = time.monotonic()
                if self.config.ready and self.process_one():
                    continue
            except Exception as exc:
                LOGGER.error("Worker cycle failed (%s)", type(exc).__name__)
            self.wake.wait(1)
            self.wake.clear()

    def _safe_text(self, value, length=1500):
        text = str(value)[:length]
        for secret in (self.config.api_key, self.config.access_code):
            if secret:
                text = text.replace(secret, "[已隐藏]")
        text = text.replace(str(self.config.data_dir), "[任务目录]").replace(str(self.config.skill_dir), "[转换组件]")
        return text

    def _checks(self, checks):
        if not isinstance(checks, list) or len(checks) > 2000 or any(not isinstance(c, dict) for c in checks):
            return [{"name": "转换报告", "status": "fail", "detail": "检查报告格式无效"}]
        return [{"name": self._safe_text(c.get("name", "检查"), 200), "status": c.get("status") if c.get("status") in {"pass", "fail", "unverified", "pending", "not_applicable"} else "unverified", "detail": self._safe_text(c.get("detail", ""), 4000)} for c in checks[:2000] if isinstance(c, dict)]

    def process_one(self):
        if not self._process_lock.acquire(blocking=False):
            return False
        try:
            row = self.store.claim()
            if not row:
                return False
            job_id = row["id"]
            job_dir = self.jobs_dir / job_id
            def cancelled():
                fresh = self.store.get(job_id)
                return self.stop.is_set() or not fresh or bool(fresh["cancel_requested"] or fresh["delete_requested"] or fresh["expires"] <= time.time())
            def emit(stage, message, **extras):
                self.store.event(job_id, self._safe_text(stage, 100), self._safe_text(message), self._checks(extras["checks"]) if "checks" in extras else None)
            try:
                manifest = json.loads(row["manifest"])
                if manifest.get("modelProvider", "openai") != self.config.provider:
                    message = "模型服务商已改变，请重新上传资料并确认新的服务商授权；本任务没有向新服务商发送资料。"
                    result = {"status": "needs_attention", "message": message,
                              "checks": [{"name": "模型服务商授权", "status": "fail", "detail": message}]}
                else:
                    result = self.converter_factory(self.config).run(job_dir, manifest, emit, cancelled)
                if not isinstance(result, dict):
                    raise ValueError("invalid converter result")
                checks = self._checks(result.get("checks", []))
                status = result.get("status")
                artifact = result.get("artifact")
                allowed = bool(checks) and all(c["status"] in {"pass", "not_applicable"} for c in checks)
                if status == "ready" and allowed:
                    self._artifact_path(job_dir, artifact)
                else:
                    status, artifact = "needs_attention", None
                current = self.store.get(job_id)
                if self.stop.is_set() and current and not current["cancel_requested"]:
                    status, artifact = "interrupted", None
                self.store.finish(job_id, status, self._safe_text(result.get("message", "检查完成")), checks, artifact)
            except Exception as exc:
                LOGGER.warning("Conversion %s failed (%s)", job_id, type(exc).__name__)
                self.store.finish(job_id, "interrupted" if self.stop.is_set() else "failed", "转换未完成。请核对资料是否完整、清晰且在支持范围内，再重试；管理员可根据任务编号检查服务配置。")
            finally:
                fresh = self.store.get(job_id)
                if fresh and (fresh["delete_requested"] or fresh["expires"] <= time.time()):
                    self.store.request_delete(job_id)
                    self._erase_job(job_id)
            return True
        finally:
            self._process_lock.release()

    def _artifact_path(self, job_dir, relative):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("artifact path invalid")
        candidate = job_dir / relative
        resolved = candidate.resolve()
        if job_dir.resolve() not in resolved.parents or candidate.is_symlink() or not resolved.is_file() or resolved.suffix.lower() != ".html":
            raise ValueError("artifact outside job")
        return resolved

    def _erase_job(self, job_id):
        row = self.store.get(job_id)
        if row and not row["active"]:
            try:
                shutil.rmtree(self.jobs_dir / job_id, ignore_errors=False)
            except FileNotFoundError:
                pass
            self.store.delete(job_id)

    def cleanup(self, now=None):
        for row in self.store.cleanup_candidates(time.time() if now is None else now):
            self._erase_job(row["id"])

    def _check_request_origin(self, env):
        expected = urlsplit(self.config.public_origin)
        supplied_host = env.get("HTTP_HOST", "")
        if not _same_origin(expected.scheme + "://" + supplied_host, self.config.public_origin):
            raise HTTPError(403, "请求地址与服务配置不一致")
        origin = env.get("HTTP_ORIGIN")
        if origin is not None and not _same_origin(origin, self.config.public_origin):
            raise HTTPError(403, "此请求来源不被允许")
        if env.get("HTTP_SEC_FETCH_SITE") not in {None, "", "none", "same-origin"}:
            raise HTTPError(403, "请从本站页面提交资料")
        if env["REQUEST_METHOD"] in {"POST", "DELETE"} and not origin:
            # Explicit bearer clients may omit Origin; unauthenticated submission may not.
            if not env.get("HTTP_AUTHORIZATION", "").startswith("Bearer "):
                raise HTTPError(403, "提交资料必须来自本站页面")

    def _json_body(self, env):
        if env.get("CONTENT_TYPE", "").split(";")[0].strip().lower() != "application/json":
            raise HTTPError(415, "请使用网页中的上传入口")
        try:
            length = int(env.get("CONTENT_LENGTH", ""))
        except (ValueError, TypeError):
            raise HTTPError(411, "上传请求缺少有效长度") from None
        max_encoded = ((self.config.max_total_bytes + 2) // 3) * 4 + self.config.max_files * 2048 + 16000
        if length < 0 or length > max_encoded:
            raise HTTPError(413, "资料总大小超过服务限额")
        try:
            raw = env["wsgi.input"].read(length)
            if len(raw) != length:
                raise ValueError()
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "上传请求不完整或格式错误") from None
        if not isinstance(body, dict):
            raise HTTPError(400, "上传请求必须是对象")
        return body

    def _validate_uploads(self, body):
        if body.get("consent") is not True:
            raise HTTPError(400, "请先确认有权上传资料并同意使用模型转换")
        if body.get("consentProvider") != self.config.provider:
            raise HTTPError(409, "模型服务商已改变或授权信息缺失，请刷新页面并重新确认服务商后提交。")
        if self.config.access_code and not hmac.compare_digest(str(body.get("accessCode", "")).encode("utf-8"), self.config.access_code.encode("utf-8")):
            raise HTTPError(403, "访问码不正确")
        title = body.get("title", "")
        scope = body.get("scope", "")
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise HTTPError(400, "请填写不超过120字的教材名称")
        if not isinstance(scope, str) or len(scope) > 4000:
            raise HTTPError(400, "转换范围说明过长")
        if body.get("mode") not in MODES:
            raise HTTPError(400, "资料组织模式无效")
        files = body.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= self.config.max_files:
            raise HTTPError(400, "上传文件数量超出服务限额")
        validated, total, hashes = [], 0, set()
        for item in files:
            if not isinstance(item, dict):
                raise HTTPError(400, "文件描述无效")
            name = item.get("name")
            if not isinstance(name, str) or not 1 <= len(name) <= 180 or any(c in name for c in "/\\\x00") or any(ord(c) < 32 for c in name):
                raise HTTPError(400, "文件名称无效")
            name = unicodedata.normalize("NFC", name)
            suffix = Path(name).suffix.lower().lstrip(".")
            if suffix not in FORMATS:
                raise HTTPError(400, "仅支持 PDF、TXT、MD、DOCX 和 PPTX 文件")
            if item.get("role") not in ROLES or type(item.get("primary")) is not bool:
                raise HTTPError(400, "请为每份资料选择有效角色及主次")
            encoded = item.get("data")
            if not isinstance(encoded, str):
                raise HTTPError(400, "文件内容无效")
            if len(encoded) > ((self.config.max_file_bytes + 2) // 3) * 4:
                raise HTTPError(413, "单个文件超过大小限额")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise HTTPError(400, "文件内容编码无效") from None
            total += len(content)
            if not content:
                raise HTTPError(400, "不能上传空文件")
            if len(content) > self.config.max_file_bytes or total > self.config.max_total_bytes:
                raise HTTPError(413, "资料大小超过服务限额")
            self._validate_signature(suffix, content)
            digest = hashlib.sha256(content).hexdigest()
            if digest in hashes:
                raise HTTPError(400, "同一份资料被重复上传，请保留一份并确定其角色")
            hashes.add(digest)
            validated.append({"id": "src-" + digest[:20], "name": name, "role": item["role"], "primary": item["primary"], "sha256": digest, "bytes": len(content), "content": content, "suffix": suffix})
        return title.strip(), scope, validated, total

    def _validate_signature(self, suffix, content):
        if suffix == "pdf":
            if not content.startswith(b"%PDF-"):
                raise HTTPError(400, "PDF 文件标识无效，请重新导出")
        elif suffix in {"txt", "md"}:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise HTTPError(400, "文字资料请使用 UTF-8 编码") from None
            if any(ord(c) < 32 and c not in "\r\n\t\f" for c in text):
                raise HTTPError(400, "文字文件包含无效二进制内容")
        else:
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    entries = archive.infolist()
                    names = {e.filename for e in entries}
                    required = "word/document.xml" if suffix == "docx" else "ppt/presentation.xml"
                    if len(entries) > 10000 or required not in names or "[Content_Types].xml" not in names:
                        raise ValueError()
                    size = sum(e.file_size for e in entries)
                    if size > 200 * 1024 * 1024 or size > max(len(content) * 500, 1024 * 1024):
                        raise ValueError()
                    for e in entries:
                        if e.flag_bits & 1 or e.filename.startswith("/") or ".." in Path(e.filename).parts or "vbaproject" in e.filename.lower() or "\\" in e.filename:
                            raise ValueError()
            except (ValueError, zipfile.BadZipFile, RuntimeError):
                raise HTTPError(400, "Office 文件损坏、加密、包含宏或超出安全解析限额；请转为 PDF 后上传") from None

    def _create_job(self, env):
        if not self.config.ready:
            raise HTTPError(503, "转换服务尚未配置完成，本次没有保存教材。" + "；".join(self.config.readiness()))
        body = self._json_body(env)
        title, scope, files, total = self._validate_uploads(body)
        with self._upload_lock:
            self.cleanup()
            if shutil.disk_usage(self.config.data_dir).free < total + self.config.min_free_bytes:
                raise HTTPError(507, "服务存储空间不足，本次没有保存教材")
            used = sum(p.stat().st_size for p in self.jobs_dir.rglob("*") if p.is_file())
            if used + total > self.config.max_storage_bytes:
                raise HTTPError(507, "服务资料存储已达到限额，请稍后再试")
            job_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            job_dir = self.jobs_dir / job_id
            job_dir.mkdir(mode=0o700)
            (job_dir / "uploads").mkdir(mode=0o700)
            manifest = {"id": job_id, "title": title, "mode": body["mode"], "scope": scope, "modelProvider": self.config.provider, "files": []}
            try:
                for item in files:
                    content, suffix = item.pop("content"), item.pop("suffix")
                    item["path"] = "uploads/" + item["id"] + "." + suffix
                    (job_dir / item["path"]).write_bytes(content)
                    (job_dir / item["path"]).chmod(0o600)
                    manifest["files"].append(item)
                (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                self.store.create(manifest, token, retention_hours=self.config.retention_hours, max_queue=self.config.max_queue, max_stored_jobs=self.config.max_stored_jobs)
            except BaseException:
                shutil.rmtree(job_dir)
                raise
        self.wake.set()
        return {"id": job_id, "token": token, "status": "queued"}

    def _public_job(self, row):
        available = False
        if row["status"] == "ready" and row["artifact"]:
            try:
                self._artifact_path(self.jobs_dir / row["id"], row["artifact"])
                available = True
            except ValueError:
                pass
        events = json.loads(row["events"])
        for event in events:
            event["at"] = _date(event["at"])
        return {"id": row["id"], "title": row["title"], "status": row["status"], "stage": row["stage"], "message": row["message"], "createdAt": _date(row["created"]), "updatedAt": _date(row["updated"]), "events": events, "checks": json.loads(row["checks"]), "downloadAvailable": available, "expiresAt": _date(row["expires"])}

    def _headers(self, content_type):
        return [("Content-Type", content_type), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"), ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"), ("Permissions-Policy", "camera=(), microphone=(), geolocation=()")]

    def _response(self, start, status, body, headers=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        start(str(status) + " " + HTTPStatus(status).phrase, self._headers("application/json; charset=utf-8") + [("Content-Length", str(len(data)))] + (headers or []))
        return [data]

    def __call__(self, env, start):
        try:
            self._check_request_origin(env)
            path, method = env.get("PATH_INFO", "/"), env.get("REQUEST_METHOD", "GET")
            if path in {"/api/config", "/healthz"} and method == "GET":
                body = {"status": "ok"} if path == "/healthz" else {"ready": self.config.ready, "reasons": self.config.readiness(), "limits": {"maxFiles": self.config.max_files, "maxFileBytes": self.config.max_file_bytes, "maxTotalBytes": self.config.max_total_bytes}, "formats": list(FORMATS), "retentionHours": self.config.retention_hours, "provider": self.config.provider_label, "providerId": self.config.provider, "accessCodeRequired": bool(self.config.access_code)}
                return self._response(start, 200, body)
            if path == "/api/jobs" and method == "POST":
                return self._response(start, 202, self._create_job(env))
            match = JOB_ROUTE.fullmatch(path)
            if match:
                job_id, action = match.groups()
                auth = env.get("HTTP_AUTHORIZATION", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
                row = self.store.authenticated(job_id, token)
                if not row:
                    raise HTTPError(404, "任务不存在、已过期，或访问凭据不正确")
                if not action and method == "GET":
                    return self._response(start, 200, self._public_job(row))
                if not action and method == "DELETE":
                    self.store.request_delete(job_id)
                    self._erase_job(job_id)
                    return self._response(start, 200, {"deleted": True})
                if action == "cancel" and method == "POST":
                    self.store.cancel(job_id)
                    return self._response(start, 200, self._public_job(self.store.get(job_id)))
                if action == "retry" and method == "POST":
                    if not self.config.ready:
                        raise HTTPError(503, "转换服务尚未配置完成")
                    if json.loads(row["manifest"]).get("modelProvider", "openai") != self.config.provider:
                        raise HTTPError(409, "模型服务商已改变，请重新上传资料并确认新的服务商授权。")
                    if not self.store.retry(job_id, self.config.max_queue):
                        raise HTTPError(409, "任务尚在处理中或当前状态不允许重试")
                    self.wake.set()
                    return self._response(start, 202, self._public_job(self.store.get(job_id)))
                if action == "download" and method == "GET":
                    if row["status"] != "ready" or not row["artifact"]:
                        raise HTTPError(409, "教材尚未通过全部必要检查，暂不能下载")
                    try:
                        artifact = self._artifact_path(self.jobs_dir / job_id, row["artifact"])
                        handle = artifact.open("rb")
                    except (ValueError, OSError):
                        raise HTTPError(409, "成品文件当前不可用，请重试转换") from None
                    download_name = re.sub(r'[\\/\x00-\x1f]', "_", row["title"]) + ".html"
                    headers = self._headers("application/octet-stream") + [("Content-Disposition", "attachment; filename=\"textbook.html\"; filename*=UTF-8''" + quote(download_name, safe="")), ("Content-Length", str(os.fstat(handle.fileno()).st_size))]
                    start("200 OK", headers)
                    return FileWrapper(handle)
                raise HTTPError(405, "此操作不支持该请求方法")
            if path.startswith("/api/"):
                raise HTTPError(404, "接口不存在")
            if method not in {"GET", "HEAD"}:
                raise HTTPError(405, "此操作不支持该请求方法")
            filename = "index.html" if path == "/" else path.lstrip("/")
            if "/" in filename or filename.startswith(".") or Path(filename).suffix not in {".html", ".js", ".css", ".svg", ".png", ".ico"}:
                raise HTTPError(404, "页面不存在")
            target = self.config.static_dir / filename
            if not target.is_file() or target.is_symlink():
                raise HTTPError(404, "页面不存在")
            types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
            data = target.read_bytes()
            start("200 OK", self._headers(types[target.suffix]) + [("Content-Length", str(len(data)))])
            return [data if method == "GET" else b""]
        except HTTPError as exc:
            return self._response(start, exc.status, {"error": exc.message})
        except QueueFull:
            return self._response(start, 429, {"error": "转换队列或资料保留数量已满，请稍后再试"}, [("Retry-After", "60")])
        except OSError:
            LOGGER.warning("Portal storage operation failed")
            return self._response(start, 507, {"error": "服务存储暂时不可用，请稍后重试"})
        except Exception as exc:
            LOGGER.error("Portal request failed (%s)", type(exc).__name__)
            return self._response(start, 500, {"error": "服务暂时无法处理请求，请稍后重试"})


def create_app(config=None, converter_factory=None, start_worker=True):
    return Portal(config or Config.from_env(), converter_factory, start_worker)


class _LazyApplication:
    def __init__(self):
        self.instance = None
        self.lock = threading.Lock()

    def __call__(self, env, start):
        if self.instance is None:
            with self.lock:
                if self.instance is None:
                    self.instance = create_app()
        return self.instance(env, start)


app = _LazyApplication()
application = app
