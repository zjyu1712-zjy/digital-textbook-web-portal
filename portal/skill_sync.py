"""Pinned local skill integrity; no network access and no automatic latest upgrade."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil


REPOSITORY = 'https://github.com/zjyu1712-zjy/digital-textbook-html'


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('技能清单路径无效')
    parts = PurePosixPath(value).parts
    if value.startswith('/') or any(p in ('.', '..', '') for p in value.split('/')) or ':' in value:
        raise ValueError('技能清单路径无效：' + value)
    if any(p in {'.git', '.env', '__pycache__', 'node_modules', 'data'} for p in parts):
        raise ValueError('技能清单包含运行数据：' + value)
    return value


def _file(root, name):
    name = _safe_path(name)
    path = Path(root)
    for part in name.split('/'):
        path /= part
        if path.is_symlink():
            raise ValueError('技能文件不可为软链接：' + name)
    if not path.is_file():
        raise ValueError('技能文件缺失：' + name)
    return path


def skill_metadata(skill_dir):
    """Expose actual installed identity, including a digest for cache invalidation."""
    root = Path(skill_dir)
    if root.is_symlink():
        raise ValueError('技能根目录不能为软链接')
    release = _read(root / 'RELEASE.json')
    if not isinstance(release, dict) or not isinstance(release.get('version'), str) or type(release.get('contentSchemaVersion')) is not int:
        raise ValueError('技能版本元数据无效')
    names = _read(root / 'PACKAGE_FILES.json')
    if (not isinstance(names, list) or not all(isinstance(name, str) for name in names)
            or len(names) != len({name.casefold() for name in names})
            or not {'PACKAGE_FILES.json', 'RELEASE.json', 'SKILL.md'} <= set(names)):
        raise ValueError('技能文件清单无效')
    rows = {name: hashlib.sha256(_file(root, name).read_bytes()).hexdigest() for name in sorted(names)}
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return {'version': release['version'], 'contentSchemaVersion': release['contentSchemaVersion'],
            'fingerprint': fingerprint, 'files': rows}


def verify_skill(skill_dir, lock_path, upstream_dir=None):
    """Compare exact local files against the explicitly pinned upstream snapshot."""
    root = Path(skill_dir)
    lock = _read(lock_path)
    if not isinstance(lock, dict):
        raise ValueError('技能锁定记录无效')
    if (lock.get('formatVersion') != 1 or lock.get('repository') != REPOSITORY
            or not re.fullmatch(r'[0-9a-f]{40}|v\d+\.\d+\.\d+', str(lock.get('upstreamRef', '')))):
        raise ValueError('技能锁定来源无效')
    actual = skill_metadata(root)
    expected = lock.get('files')
    if not isinstance(expected, dict):
        raise ValueError('技能锁定清单无效')
    differences = sorted(name for name in set(actual['files']) | set(expected)
                         if actual['files'].get(name) != expected.get(name))
    listed = set(actual['files'])
    extras = [p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'
              and p.relative_to(root).as_posix() not in listed]
    differences.extend(sorted(extras))
    if (differences or actual['version'] != lock.get('version')
            or actual['fingerprint'] != lock.get('fingerprint')):
        raise ValueError('技能副本与锁定版本不一致：' + ', '.join(differences or ['version/fingerprint']))
    if upstream_dir is not None:
        upstream = skill_metadata(upstream_dir)
        if upstream != actual:
            names = sorted(name for name in set(upstream['files']) | set(actual['files']) if upstream['files'].get(name) != actual['files'].get(name))
            raise ValueError('技能副本与指定上游快照不一致：' + ', '.join(names or ['version/fingerprint']))
    return {k:v for k,v in actual.items() if k != 'files'} | {'upstreamRef': lock['upstreamRef']}


def sync_skill(source, target, lock_path, upstream_ref):
    if Path(source).is_symlink() or Path(target).is_symlink():
        raise ValueError('技能根目录不能为软链接')
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('来源与目标技能目录必须独立')
    if not re.fullmatch(r'[0-9a-f]{40}|v\d+\.\d+\.\d+', upstream_ref):
        raise ValueError('请指定完整提交摘要或固定版本标签')
    metadata = skill_metadata(source)
    if upstream_ref.startswith('v') and upstream_ref != 'v' + metadata['version']:
        raise ValueError('版本标签与来源RELEASE.json不一致')
    target.mkdir(parents=True, exist_ok=True)
    # This directory is generated vendor content. Refuse unexpected files instead
    # of silently deleting a user's patch or runtime record.
    extras = [p for p in target.rglob('*') if p.is_file() and '__pycache__' not in p.parts
              and p.suffix != '.pyc' and p.relative_to(target).as_posix() not in metadata['files']]
    if extras:
        raise ValueError('目标有上游清单之外的文件，请先核对备份：' + ', '.join(str(p.relative_to(target)) for p in extras))
    for name in metadata['files']:
        dest = target / name
        for ancestor in [dest, *dest.parents]:
            if ancestor == target.parent:
                break
            if ancestor.is_symlink():
                raise ValueError('目标不可经过软链接')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_file(source, name), dest)
    lock = {'formatVersion': 1, 'repository': REPOSITORY, 'upstreamRef': upstream_ref, **metadata}
    Path(lock_path).write_text(json.dumps(lock, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return verify_skill(target, lock_path)
