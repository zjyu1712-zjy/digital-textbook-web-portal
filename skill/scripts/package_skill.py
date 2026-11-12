#!/usr/bin/env python3
"""Build a verified Agent Skills ZIP from PACKAGE_FILES.json only (Python 3.9+)."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

NAME = "digital-textbook-html"
MANIFEST = "PACKAGE-MANIFEST.json"
REQUIRED = {"PACKAGE_FILES.json", "RELEASE.json", "SKILL.md"}
FORBIDDEN = {
    ".git", ".hg", ".svn", ".ssh", ".aws", ".gnupg", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "cache", "caches",
    "private", "sources", "source-materials", "inputs", "input", "uploads", "upload",
    "outputs", "output", "work", "workspace", "archives", "archive", "evidence",
    "user-data", "userdata", "learning-records", "attachments", "backups", "data",
    "sessions", "records", "history", "drafts", "attempts",
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def safe_path(name):
    """Accept canonical portable POSIX paths; reject private/cache/credential names."""
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("清单必须使用安全的相对 POSIX 路径")
    parts = name.split("/")
    if any(p in {"", ".", ".."} for p in parts) or PurePosixPath(name).is_absolute():
        raise ValueError("拒绝绝对路径、空路径段和目录穿越: " + name)
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("路径包含控制字符")
    for part in parts:
        lower = part.casefold()
        if (lower in FORBIDDEN or lower == MANIFEST.casefold() or lower.startswith(".env")
                or lower.endswith((".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx"))
                or re.search(r"(^|[._-])(secret|secrets|credential|credentials|password|passwords|token|tokens|cookie|cookies|key|auth|login|session|api[._-]?key|id_rsa|id_dsa|id_ecdsa|id_ed25519)([._-]|$)", lower)):
            raise ValueError("清单包含禁止发布的文件或目录: " + name)
    return name


def listed_file(root, name):
    safe_path(name)
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink():
            raise ValueError("拒绝文件或父目录软链接: " + name)
    if not path.is_file():
        raise FileNotFoundError("清单文件不存在或不是普通文件: " + name)
    return path


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def verify_archive(filename):
    """Verify an archive without extracting it. This checks integrity, not authorship."""
    with zipfile.ZipFile(filename) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("ZIP 包含重复文件")
        metadata = json.loads(archive.read(NAME + "/" + MANIFEST).decode("utf-8"))
        if (not isinstance(metadata, dict) or metadata.get("formatVersion") != 1 or metadata.get("name") != NAME
                or not isinstance(metadata.get("version"), str) or not metadata["version"]
                or not isinstance(metadata.get("files"), list)):
            raise ValueError("ZIP 清单格式错误")
        expected = {NAME + "/" + MANIFEST}
        seen = set()
        for row in metadata["files"]:
            name = safe_path(row["path"])
            if name.casefold() in seen:
                raise ValueError("ZIP 清单包含重复路径")
            seen.add(name.casefold())
            entry = NAME + "/" + name
            content = archive.read(entry)
            if len(content) != row["size"] or digest(content) != row["sha256"]:
                raise ValueError("ZIP 文件摘要核对失败: " + name)
            expected.add(entry)
        if set(names) != expected or not REQUIRED.issubset({row["path"] for row in metadata["files"]}):
            raise ValueError("ZIP 实际文件与清单不一致")
        return metadata


def pack(root, dest):
    """Package exact allowlisted files, refuse overwrite, and reread every ZIP hash."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Skill 根目录必须是实际目录，不能是软链接")
    root = root.resolve()
    dest = Path(dest).absolute()
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("输出已存在，拒绝覆盖: " + str(dest))
    resolved_dest = dest.resolve()
    if resolved_dest == root or root in resolved_dest.parents:
        raise ValueError("--out 必须位于 Skill 目录外部")
    if not dest.parent.is_dir():
        raise ValueError("请先创建外部输出目录")
    if dest.suffix.lower() != ".zip":
        raise ValueError("输出文件必须以 .zip 结尾")
    paths = json.loads(listed_file(root, "PACKAGE_FILES.json").read_text(encoding="utf-8"))
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("PACKAGE_FILES.json 必须是相对路径字符串数组")
    for name in paths:
        safe_path(name)
    if len(paths) != len({p.casefold() for p in paths}) or not REQUIRED.issubset(paths):
        raise ValueError("清单重复或缺少 PACKAGE_FILES.json、RELEASE.json、SKILL.md")
    payload = {name: listed_file(root, name).read_bytes() for name in sorted(paths)}
    release = json.loads(payload["RELEASE.json"].decode("utf-8"))
    if (not isinstance(release, dict) or release.get("name") != NAME or not isinstance(release.get("version"), str)
            or not release["version"].strip()):
        raise ValueError("RELEASE.json 必须包含正确 name 和非空 version")
    metadata = {"formatVersion": 1, "name": NAME, "version": release["version"], "files": [
        {"path": name, "sha256": digest(content), "size": len(content)}
        for name, content in payload.items()
    ]}
    payload[MANIFEST] = json_bytes(metadata)
    # Exclusive creation closes the existence-check race; no existing output is removed.
    with dest.open("xb") as handle:
        try:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in payload.items():
                    info = zipfile.ZipInfo(NAME + "/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, content)
            handle.flush()
            if verify_archive(dest) != metadata:
                raise ValueError("ZIP 内嵌清单与本次构建不一致")
        except BaseException:
            handle.close()
            dest.unlink()
            raise
    return {"output": str(dest), "version": release["version"], "files": len(paths),
            "sha256": digest(dest.read_bytes())}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Skill 外部、不存在的 .zip 输出路径")
    args = parser.parse_args()
    try:
        result = pack(Path(__file__).resolve().parents[1], args.out)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
