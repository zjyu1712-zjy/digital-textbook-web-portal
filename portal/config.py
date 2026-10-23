"""Explicit deployment configuration. There is no demonstration conversion mode."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    data_dir: Path = ROOT / "data"
    skill_dir: Path = ROOT / "skill"
    static_dir: Path = ROOT / "static"
    api_key: str = ""
    model: str = ""
    public_origin: str = "http://127.0.0.1:8000"
    access_code: str = ""
    max_files: int = 10
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 60 * 1024 * 1024
    max_pages: int = 800
    max_model_calls: int = 1200
    browser_timeout: int = 180
    max_queue: int = 4
    max_stored_jobs: int = 32
    max_storage_bytes: int = 2 * 1024 * 1024 * 1024
    retention_hours: int = 24
    min_free_bytes: int = 128 * 1024 * 1024

    def __post_init__(self):
        for name in ("data_dir", "skill_dir", "static_dir"):
            object.__setattr__(self, name, Path(getattr(self, name)).expanduser().resolve())
        parsed = urlsplit(self.public_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("PORTAL_PUBLIC_ORIGIN 必须是完整且不含路径的 HTTP(S) 来源地址")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("PORTAL_PUBLIC_ORIGIN 端口无效") from exc
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("公开部署必须使用 HTTPS，HTTP 仅用于本机预览")
        object.__setattr__(self, "public_origin", self.public_origin.rstrip("/"))
        for name in ("max_files", "max_file_bytes", "max_total_bytes", "max_pages", "max_model_calls", "browser_timeout", "max_queue", "max_stored_jobs", "max_storage_bytes", "retention_hours"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) <= 0:
                raise ValueError(name + " 必须是正整数")
        if self.min_free_bytes < 0:
            raise ValueError("min_free_bytes 不能为负数")

    @classmethod
    def from_env(cls):
        fields = {}
        for name, env in {"data_dir": "PORTAL_DATA_DIR", "skill_dir": "PORTAL_SKILL_DIR", "api_key": "OPENAI_API_KEY", "model": "OPENAI_MODEL", "public_origin": "PORTAL_PUBLIC_ORIGIN", "access_code": "PORTAL_ACCESS_CODE"}.items():
            if env in os.environ:
                fields[name] = os.environ[env]
        for name in ("max_files", "max_file_bytes", "max_total_bytes", "max_pages", "max_model_calls", "browser_timeout", "max_queue", "max_stored_jobs", "max_storage_bytes", "retention_hours", "min_free_bytes"):
            env = "PORTAL_" + name.upper()
            if env in os.environ:
                fields[name] = int(os.environ[env])
        return cls(**fields)

    def readiness(self):
        reasons = []
        if not self.api_key.strip():
            reasons.append("管理员尚未配置模型 API 凭据")
        if not self.model.strip():
            reasons.append("管理员尚未指定转换模型")
        if not (self.skill_dir / "SKILL.md").is_file():
            reasons.append("转换 Skill 尚未安装到服务端")
        return reasons

    @property
    def ready(self):
        return not self.readiness()
