#!/usr/bin/env python3
"""Synchronize a reviewed local upstream snapshot, or verify the pinned copy."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portal.skill_sync import sync_skill, verify_skill


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check-source', help='另行取出的固定上游快照；只比较，不写入')
    group.add_argument('--source', help='已下载并验证的主技能目录；省略时仅校验')
    parser.add_argument('--upstream-ref', help='完整上游提交摘要或固定版本标签')
    args = parser.parse_args()
    try:
        if args.source:
            if not args.upstream_ref:
                parser.error('--source 需要 --upstream-ref')
            result = sync_skill(args.source, ROOT / 'skill', ROOT / 'skill-lock.json', args.upstream_ref)
        else:
            result = verify_skill(ROOT / 'skill', ROOT / 'skill-lock.json', args.check_source)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'fail', 'detail': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({'status': 'pass', **result}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
