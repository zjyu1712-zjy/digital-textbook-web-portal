"""Derive chapter-level progress from supplied, content-bound evidence.

Mapping completeness is not factual correctness. Browser/visual records are
claims about an explicit tested scope, never inferred from a successful build.
"""
from pathlib import Path
import datetime
import hashlib
import json
import re

from review_audit import (_context, _coverage_targets, _map_targets, _teaching,
                          audit_reviews, review_fingerprint, validate_learning_map)
from independent_audit import audit_independent
from task_contract import validate_contract


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _rows(value):
    return value if isinstance(value, list) else []


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value):
    return isinstance(value, list) and all(_text(x) for x in value) and len(value) == len(set(value))


def _reference_visible(target):
    if _teaching(target):
        return True
    def visible(blocks):
        for block in _rows(blocks):
            if not isinstance(block, dict):
                continue
            kind = block.get('type')
            if kind == 'image' and _text(block.get('path')):
                return True
            if kind == 'math' and _text(block.get('tex')):
                return True
            if kind in ('table', 'matrix') and block.get('rows'):
                return True
            if kind == 'diagram' and block.get('lines'):
                return True
            if kind == 'details' and visible(block.get('blocks')):
                return True
        return False
    return visible(target.get('blocks', target.get('prompt', [])))


def renderer_fingerprint():
    """Bind verification to the actual local builder and packaged UI bytes."""
    root = Path(__file__).resolve().parents[1]
    paths = list((root / 'assets').rglob('*'))
    paths += [root / 'scripts' / name for name in
              ('pipeline.py', 'chapter_status.py', 'independent_audit.py',
               'grading.py', 'review_audit.py', 'task_contract.py')]
    return _digest({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(paths) if p.is_file()})


def chapter_binding(course, inventory, chapter_id):
    _, _, chapters, targets, locations = _context(course, inventory)
    if chapter_id not in chapters:
        raise ValueError('unknown verification chapter: ' + str(chapter_id))
    ids = sorted(t for t in targets if chapter_id in locations[t])
    if not ids:
        raise ValueError('cannot verify an empty chapter')
    # Include inventory even when a source item is accidentally left unmapped.
    payload = {'version': 1, 'chapterId': chapter_id,
               'reviewFingerprint': review_fingerprint(course, inventory, ids),
               'inventory': inventory, 'courseVersion': course.get('version'),
               'bookTitle': course.get('title'), 'scope': course.get('scope'),
               'chapterNavigation': [{'id': c['id'], 'title': c.get('title')}
                                     for c in course.get('chapters', [])]}
    return {'version': 1, 'fingerprint': _digest(payload),
            'rendererFingerprint': renderer_fingerprint()}


def _record_errors(record, chapters, targets, locations):
    if not isinstance(record, dict):
        return ['record must be an object']
    errors = []
    cid = record.get('chapterId')
    if not isinstance(cid, str) or cid not in chapters:
        errors.append('unknown chapterId')
    if record.get('kind') not in ('offline', 'visual'):
        errors.append('kind must be offline or visual')
    if record.get('result') not in ('pass', 'fail', 'pending'):
        errors.append('invalid result')
    if not all(_text(record.get(k)) for k in ('reviewer', 'method', 'evidence', 'checkedAt')):
        errors.append('verification requires reviewer, method, evidence and checkedAt')
    else:
        try:
            when = datetime.datetime.fromisoformat(record['checkedAt'].replace('Z', '+00:00'))
            if when.tzinfo is None:
                errors.append('checkedAt must include a timezone')
        except ValueError:
            errors.append('checkedAt is not an ISO date/time')
    ids = record.get('targetIds')
    if not _strings(ids) or not ids or any(t not in targets or cid not in locations.get(t, []) for t in ids):
        errors.append('targetIds must name actual tested content in this chapter')
    if not _strings(record.get('checks')) or not record.get('checks'):
        errors.append('checks must list actual performed checks')
    if not re.fullmatch(r'[0-9a-f]{64}', str(record.get('artifactSHA256', ''))):
        errors.append('artifactSHA256 is required')
    binding = record.get('binding')
    if (not isinstance(binding, dict) or type(binding.get('version')) is not int
            or binding.get('version') != 1 or any(not re.fullmatch(r'[0-9a-f]{64}', str(binding.get(k, '')))
            for k in ('fingerprint', 'rendererFingerprint'))):
        errors.append('verification binding is malformed')
    return errors


def validate_chapter_checks(course, inventory):
    if 'chapterChecks' not in course:
        return []
    records = course['chapterChecks']
    if not isinstance(records, list):
        return ['chapterChecks must be an array']
    try:
        _, _, chapters, targets, locations = _context(course, inventory)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    for i, record in enumerate(records):
        errors.extend('chapterChecks[' + str(i) + ']: ' + e
                      for e in _record_errors(record, chapters, targets, locations))
    return errors


def _verification(course, inventory, cid, kind, ids, context, current_binding):
    chapters, targets, locations = context
    matching = [r for r in _rows(course.get('chapterChecks'))
                if isinstance(r, dict) and r.get('chapterId') == cid and r.get('kind') == kind]
    reviewed, current, stale, invalid = set(), [], 0, 0
    for record in matching:
        if _record_errors(record, chapters, targets, locations):
            invalid += 1
        elif record['binding'] != current_binding:
            stale += 1
        else:
            current.append(record)
            if record['result'] == 'pass':
                reviewed.update(record['targetIds'])
    if invalid:
        status = 'invalid'
    elif any(r['result'] == 'fail' for r in current):
        status = 'failed'
    elif any(r['result'] == 'pending' for r in current):
        status = 'pending'
    elif reviewed:
        status = 'pass' if reviewed >= set(ids) else 'partial'
    elif stale:
        status = 'stale'
    else:
        status = 'not-verified'
    return {'status': status, 'verifiedCount': len(reviewed), 'targetCount': len(ids),
            'targetIds': sorted(reviewed), 'staleRecords': stale,
            'records': [{k: r.get(k) for k in ('result', 'reviewer', 'method', 'evidence',
                       'checkedAt', 'targetIds', 'checks', 'artifactSHA256')} for r in current]}


def _chapter_status(course, inventory):
    try:
        sources, items, chapters, targets, locations = _context(course, inventory)
    except ValueError as exc:
        return {'chapters': [], 'errors': [str(exc)], 'unassignedItems': [],
                'note': '章节输入无效，未生成完成结论。'}
    independent = audit_independent(course, inventory)
    by_independent = {c['chapterId']: c for c in independent.get('chapters', [])}
    semantic = audit_reviews(course, inventory)
    map_errors = validate_learning_map(course, inventory)
    contract_errors = validate_contract(course) if course.get('schemaVersion') == 2 else []
    invalid_items, global_map_errors = set(), []
    for error in map_errors:
        match = re.match(r'^learningMap ([^:]+):', error)
        if match and match.group(1) in items:
            invalid_items.add(match.group(1))
        else:
            global_map_errors.append(error)
    # An unscoped malformed review cannot be hidden by another valid pass.
    review_record_errors = [e for e in semantic['errors']
                            if e not in map_errors and not e.startswith('review ')]
    by_review = {r['targetId']: r['status'] for r in semantic.get('targets', [])}
    coverage = {r.get('sourceItemId'): r for r in _rows(course.get('coverage')) if isinstance(r, dict)}
    mapping = {r.get('sourceItemId'): r for r in _rows(course.get('learningMap')) if isinstance(r, dict)}
    reference_targets, learning_targets = set(), set()
    for mapped in mapping.values():
        (reference_targets if mapped.get('disposition') == 'reference-only' else learning_targets).update(_map_targets(mapped))
    reference_targets -= learning_targets
    item_chapters, unassigned = {}, []
    for iid, item in items.items():
        linked = _coverage_targets(coverage.get(iid)) | _map_targets(mapping.get(iid))
        assigned = {c for t in linked for c in locations.get(t, [])}
        explicit = item.get('chapterIds', [item['chapterId']] if item.get('chapterId') else [])
        assigned.update(c for c in _rows(explicit) if c in chapters)
        if not assigned:
            # An unmapped source item must remain visible; don't silently omit it.
            for use in _rows(course.get('taskContract', {}).get('sourceUses')):
                if isinstance(use, dict) and use.get('sourceId') == item.get('sourceId'):
                    assigned.update(c for c in _rows(use.get('chapterIds')) if c in chapters)
        if not assigned:
            unassigned.append(iid)
        item_chapters[iid] = assigned
    rows = []
    for cid, chapter in chapters.items():
        ids = sorted(t for t in targets if cid in locations[t])
        relevant = sorted(i for i in items if cid in item_chapters[i])
        complete = []
        for iid in relevant:
            cover, mapped = coverage.get(iid, {}), mapping.get(iid, {})
            linked = _coverage_targets(cover)
            valid = cover.get('status') == 'covered' and linked and linked <= set(targets)
            if course.get('schemaVersion') == 2:
                valid = valid and mapped.get('disposition') in ('integrated', 'reference-only')
            if valid and iid not in invalid_items and not global_map_errors and not contract_errors:
                complete.append(iid)
        empty = [t for t in ids if not (_reference_visible(targets[t]) if t in reference_targets else _teaching(targets[t]))]
        if not ids or not chapter.get('sections'):
            content = 'empty'
        elif len(complete) < len(relevant) or empty:
            content = 'partial'
        elif not relevant or unassigned:
            content = 'unknown'
        else:
            content = 'mapped'
        statuses = [by_review.get(t, 'unreviewed') for t in ids]
        if course.get('schemaVersion') == 1:
            review = 'legacy-unverified'
        elif not statuses:
            review = 'not-reviewed'
        elif (set(relevant) & invalid_items or global_map_errors or contract_errors or review_record_errors):
            review = 'invalid'
        elif set(statuses) == {'fresh'}:
            review = 'current'
        else:
            review = next((s for s in ('invalid', 'failed', 'pending', 'stale', 'unreviewed') if s in statuses), 'not-reviewed')
        try:
            binding = chapter_binding(course, inventory, cid) if ids else None
        except ValueError:
            binding = None
        rows.append({'chapterId': cid, 'title': chapter.get('title', cid),
                     'content': {'status': content, 'mappedCount': len(complete), 'itemCount': len(relevant),
                                 'missingItemIds': sorted(set(relevant) - set(complete)), 'emptyTargetIds': empty},
                     'review': {'status': review, 'currentCount': statuses.count('fresh'), 'targetCount': len(ids)},
                     'independent': by_independent.get(cid, {'chapterId': cid, 'selectedCount': 0,
                                                           'reviewedCount': 0, 'status': 'not-reviewed'}),
                     'verification': {kind: _verification(course, inventory, cid, kind, ids,
                                        (chapters, targets, locations), binding) for kind in ('offline', 'visual')}})
    return {'chapters': rows, 'unassignedItems': sorted(unassigned),
            'errors': list(dict.fromkeys(validate_chapter_checks(course, inventory) + map_errors
                                         + contract_errors + review_record_errors)),
            'note': '内容映射不是正确性结论；抽检仅覆盖所列样本；功能与视觉只汇总实际记录范围。'}


def chapter_status(course, inventory):
    """Report malformed supplied data instead of crashing or inventing a pass."""
    try:
        report = _chapter_status(course, inventory)
        report['status'] = 'invalid' if report['errors'] else 'reported'
        return report
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        return {'status': 'invalid', 'chapters': [], 'unassignedItems': [],
                'errors': ['invalid chapter status input: ' + str(exc)],
                'note': '章节输入无效，未生成完成结论。'}
