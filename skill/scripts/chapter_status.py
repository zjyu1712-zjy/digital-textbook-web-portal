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
                          _source_ids, audit_reviews, review_fingerprint, validate_learning_map)
from independent_audit import audit_independent
from task_contract import validate_contract
from grading import validate_grading
from discipline_checks import report_discipline_checks, validate_discipline_checks


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


def validate_learning_scope(course):
    """Validate declared gaps, never accept a caller's claimed ready status."""
    if not isinstance(course, dict):
        return ['learning scope: course must be an object']
    errors = []
    scope = course.get('scope')
    if (not isinstance(scope, dict) or scope.get('completeness') not in
            ('complete', 'excerpt', 'incomplete') or not _text(scope.get('description'))):
        errors.append('learning scope: valid scope completeness and description required')
    complete = isinstance(scope, dict) and scope.get('completeness') == 'complete'
    for index, chapter in enumerate(_rows(course.get('chapters'))):
        if not isinstance(chapter, dict):
            continue
        label = 'chapters[' + str(index) + ']'
        pending = chapter.get('pending')
        if 'pending' in chapter:
            if not isinstance(pending, dict) or not _text(pending.get('reason')):
                errors.append(label + '.pending requires a nonempty reason')
            if complete:
                errors.append(label + ': pending chapter cannot be marked complete')
        if chapter.get('sections') == [] and not (isinstance(pending, dict) and _text(pending.get('reason'))):
            errors.append(label + ': empty chapter requires pending.reason')
    contract = course.get('taskContract')
    if isinstance(contract, dict):
        for index, pending in enumerate(_rows(contract.get('pendingMaterials'))):
            if not isinstance(pending, dict):
                continue
            label = 'taskContract.pendingMaterials[' + str(index) + ']'
            required = pending.get('required', True)
            if type(required) is not bool:
                errors.append(label + '.required must be boolean')
            elif not required and not _text(pending.get('optionalReason')):
                errors.append(label + ': optional material requires optionalReason')
            elif required and complete:
                errors.append(label + ': required pending material cannot be marked complete')
    return errors


def _question_gaps(question):
    """A question stays a question even if one of its required keys is absent."""
    gaps = []
    if not _reference_visible({'blocks': question.get('prompt')}):
        gaps.append('题干待补')
    answer = question.get('answer')
    if (not isinstance(answer, dict) or answer.get('status') != 'ready'
            or not _reference_visible({'blocks': answer.get('blocks')})):
        gaps.append('题目答案或解析待补')
    parts = question.get('parts')
    valid = isinstance(parts, list) and bool(parts)
    part_ids, field_ids = set(), set()
    field_kinds = {'text', 'fill', 'number', 'choice', 'multiple', 'formula', 'matrix', 'journal', 'table'}
    for part in _rows(parts):
        if not isinstance(part, dict) or not _text(part.get('id')) or part['id'] in part_ids:
            valid = False
            continue
        part_ids.add(part['id'])
        fields = part.get('fields')
        if not isinstance(fields, list) or not fields:
            valid = False
        for field in _rows(fields):
            if (not isinstance(field, dict) or not _text(field.get('id')) or field['id'] in field_ids
                    or not _text(field.get('label')) or field.get('kind') not in field_kinds):
                valid = False
                continue
            field_ids.add(field['id'])
            if field['kind'] in ('choice', 'multiple'):
                options = field.get('options')
                if not isinstance(options, list) or not options:
                    valid = False
                elif any(not (_text(o) or isinstance(o, dict) and _text(o.get('value')) and _text(o.get('label')))
                         for o in options):
                    valid = False
            if field['kind'] in ('matrix', 'journal', 'table'):
                columns, rows = field.get('columns'), field.get('rows')
                if (not isinstance(columns, list) or not columns or not isinstance(rows, list) or not rows
                        or any(not isinstance(r, list) or len(r) != len(columns) for r in rows)):
                    valid = False
    if not valid:
        gaps.append('题目作答小问或输入字段待补')
    if validate_grading(question):
        gaps.append('题目判分规则待修复')
    return gaps


def _availability(course, cid, chapter, ids, relevant, complete, targets, items,
                  locations, uses, by_review, invalid_items, global_errors,
                  unassigned, pending_materials, independent, discipline):
    """Separate declared reference-only gaps from the actual learning path."""
    learning_items = [iid for iid in relevant if uses.get((items[iid].get('sourceId'), cid)) != 'reference']
    reference_items = set(relevant) - set(learning_items)
    reference_ids = {tid for tid in ids if _source_ids(targets[tid]) and
                     all(uses.get((sid, cid)) == 'reference' for sid in _source_ids(targets[tid]))}
    learning_ids = sorted(set(ids) - reference_ids)
    blockers = []
    def block(key, kind, message, **extra):
        if not any(x['id'] == key for x in blockers):
            blockers.append({'id': key, 'kind': kind, 'message': message, **extra})
    if global_errors:
        block('scope:' + cid, 'scope', '资料范围或记录格式待核对，尚不能确认本章可连续学习。')
    if discipline['configurationErrors']:
        block('discipline-config:' + cid, 'discipline', '学科检查配置无效，需先修复明确规则及内容定位。')
    for check in discipline['checks']:
        if check.get('status') in ('fail', 'invalid'):
            block('discipline:' + str(check.get('ruleIndex')), 'discipline',
                  '本章配置的学科检查未通过：' + str(check.get('id') or '未命名规则') + '。',
                  ruleId=check.get('id'), targetIds=check.get('targetIds', []))
    if unassigned:
        block('unassigned:' + cid, 'scope', '仍有原资料条目未确定所属章节。', sourceItemIds=list(unassigned))
    sampled = next((c for c in independent.get('chapters', []) if c.get('chapterId') == cid), {})
    sample_status = sampled.get('status')
    required_sampling = isinstance(course.get('independentReview'), dict) and course['independentReview'].get('required') is True
    if (independent.get('status') == 'invalid' or sample_status in ('failed', 'invalid', 'stale')
            or (required_sampling and sample_status != 'sampled-pass')):
        block('sampling:' + cid, 'review', '本次要求的独立抽检尚未完成，或已发现需要处理的问题。')
    if not learning_ids or not chapter.get('sections'):
        block('empty:' + cid, 'content', '本章学习内容尚未整理；仅保留目录或对照材料。')
    if not learning_items:
        block('inventory:' + cid, 'scope', '本章学习内容尚未与独立原资料清单对应。')
    for iid in learning_items:
        if iid not in complete or iid in invalid_items:
            block('item:' + iid, 'mapping', '来源条目尚未完整融入本章学习内容。', sourceItemId=iid)
    ready_targets = 0
    legacy = course.get('schemaVersion') != 2
    question_ids = {q['id'] for q in _rows(course.get('questions')) if isinstance(q, dict) and _text(q.get('id'))}
    for tid in learning_ids:
        target = targets[tid]
        reasons = []
        if not _teaching(target):
            reasons.append('缺少可阅读的学习内容')
        if legacy:
            reasons.append('旧版审校记录尚未与当前内容绑定')
        elif by_review.get(tid) != 'fresh':
            reasons.append('当前内容尚未完成有效审校')
        if tid in question_ids:
            reasons.extend(_question_gaps(target))
        if reasons:
            block('target:' + tid, 'learning', '；'.join(reasons) + '。', targetId=tid)
        else:
            ready_targets += 1
    pending = chapter.get('pending')
    if isinstance(pending, dict) and _text(pending.get('reason')):
        block('chapter:' + cid, 'material', pending['reason'])
    optional = []
    for index, material in pending_materials:
        if material.get('chapterId') != cid:
            continue
        if material.get('required', True) is False and _text(material.get('optionalReason')):
            optional.append({'description': material.get('description', ''), 'reason': material['optionalReason']})
        else:
            block('material:' + str(index), 'material', material.get('description') or '必要资料待补。')
    # Valid source-only references may stay pending without disabling the lessons.
    reference_pending = sum(i not in complete or i in invalid_items for i in reference_items)
    reference_pending += sum(by_review.get(t) != 'fresh' for t in reference_ids)
    state = 'ready' if not blockers else ('partial' if learning_ids and chapter.get('sections') else 'pending')
    return {'status': state, 'learningTargetCount': len(learning_ids), 'readyTargetCount': ready_targets,
            'blockingItems': blockers, 'optionalMaterials': optional,
            'referencePendingCount': reference_pending,
            'note': '可学习表示本次收录的学习内容和答案已整理且审校记录有效；不等于浏览器、视觉或学术正确性的保证。'}


def _learning_range(course, rows, invalid=False):
    ranges, current = [], []
    for row in rows:
        if row.get('availability', {}).get('status') == 'ready':
            current.append(row)
        elif current:
            ranges.append(current)
            current = []
    if current:
        ranges.append(current)
    prefix = ranges[0] if ranges and rows and ranges[0][0]['chapterId'] == rows[0]['chapterId'] else []
    counts = {state: sum(r.get('availability', {}).get('status') == state for r in rows)
              for state in ('ready', 'partial', 'pending')}
    return {'status': 'invalid' if invalid else 'reported', 'scope': 'included-chapters',
            'scopeDescription': course.get('scope', {}).get('description', ''),
            'scopeCompleteness': course.get('scope', {}).get('completeness'),
            'chapterCount': len(rows), 'readyChapterCount': counts['ready'],
            'partialChapterCount': counts['partial'], 'pendingChapterCount': counts['pending'],
            'blockingItemCount': sum(len(r['availability']['blockingItems']) for r in rows),
            'optionalMaterialCount': sum(len(r['availability']['optionalMaterials']) for r in rows),
            'prefixChapterIds': [r['chapterId'] for r in prefix],
            'readyRanges': [{'chapterIds': [r['chapterId'] for r in group],
                             'titles': [r['title'] for r in group]} for group in ranges],
            'note': '仅按本次收录章节的顺序计算；第一段从本次首章开始，不推断原书第一章或未收录章节。功能与视觉验收另列。'}


def renderer_fingerprint():
    """Bind verification to the actual local builder and packaged UI bytes."""
    root = Path(__file__).resolve().parents[1]
    paths = list((root / 'assets').rglob('*'))
    paths += [root / 'scripts' / name for name in
              ('pipeline.py', 'chapter_status.py', 'independent_audit.py',
               'grading.py', 'review_audit.py', 'task_contract.py', 'resource_budget.py', 'discipline_checks.py')]
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
               'chapterNavigation': [{'id': c['id'], 'title': c.get('title'), 'pending': c.get('pending')}
                                     for c in course.get('chapters', [])],
               # Every chapter shares the navigation and learning-range summary.
               # Bind those inputs, including visible review decisions, while
               # excluding evidence added by the checks themselves.
               'sharedLearningInputs': {k: course.get(k) for k in
                   ('schemaVersion', 'id', 'title', 'edition', 'version', 'scope',
                    'organization', 'taskContract', 'sources', 'disciplines', 'disciplineChecks',
                    'chapters', 'questions', 'exams', 'coverage', 'learningMap',
                    'semanticReviews', 'independentReview', 'issues', 'migrations')}}
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


def _chapter_discipline(report, ids):
    """Scope actual content failures; an invalid configuration stays global."""
    checks = [check for check in report['checks'] if set(check.get('targetIds', [])) & set(ids)]
    global_errors = [error for error in report['errors'] if error.get('scope') == 'configuration']
    state = ('invalid' if global_errors or any(c['status'] == 'invalid' for c in checks) else
             'fail' if any(c['status'] == 'fail' for c in checks) else
             'pass' if checks else 'not-configured')
    return {'status': state, 'configuredCount': len(checks),
            'passedCount': sum(c['status'] == 'pass' for c in checks),
            'failedCount': sum(c['status'] == 'fail' for c in checks),
            'invalidCount': sum(c['status'] == 'invalid' for c in checks),
            'checks': checks, 'configurationErrors': global_errors, 'note': report['note']}


def _chapter_status(course, inventory):
    try:
        sources, items, chapters, targets, locations = _context(course, inventory)
    except ValueError as exc:
        return {'chapters': [], 'errors': [str(exc)], 'unassignedItems': [],
                'note': '章节输入无效，未生成完成结论。'}
    independent = audit_independent(course, inventory)
    by_independent = {c['chapterId']: c for c in independent.get('chapters', [])}
    semantic = audit_reviews(course, inventory)
    discipline = report_discipline_checks(course)
    discipline_configuration_errors = [error for error in discipline['errors'] if error.get('scope') == 'configuration']
    map_errors = validate_learning_map(course, inventory)
    contract_errors = validate_contract(course) if course.get('schemaVersion') == 2 else []
    scope_errors = validate_learning_scope(course)
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
    contract = course.get('taskContract', {})
    uses = {(u.get('sourceId'), cid): u.get('usage') for u in _rows(contract.get('sourceUses'))
            if isinstance(u, dict) for cid in _rows(u.get('chapterIds'))}
    pending_materials = [(i, p) for i, p in enumerate(_rows(contract.get('pendingMaterials')))
                         if isinstance(p, dict)]
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
        chapter_discipline = _chapter_discipline(discipline, ids)
        relevant = sorted(i for i in items if cid in item_chapters[i])
        complete = []
        for iid in relevant:
            cover, mapped = coverage.get(iid, {}), mapping.get(iid, {})
            linked = _coverage_targets(cover)
            valid = cover.get('status') == 'covered' and linked and linked <= set(targets)
            expected = items[iid].get('expectedParts', [])
            actual = {part.get('id') for tid in linked if tid in targets
                      for part in _rows(targets[tid].get('parts'))
                      if isinstance(part, dict) and _text(part.get('id'))}
            valid = valid and _strings(expected) and set(expected) <= actual
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
                     'disciplineChecks': chapter_discipline,
                     'availability': _availability(course, cid, chapter, ids, relevant, complete, targets,
                         items, locations, uses, by_review, invalid_items,
                         global_map_errors + contract_errors + review_record_errors + scope_errors,
                         unassigned, pending_materials, independent, chapter_discipline),
                     'independent': by_independent.get(cid, {'chapterId': cid, 'selectedCount': 0,
                                                           'reviewedCount': 0, 'status': 'not-reviewed'}),
                     'verification': {kind: _verification(course, inventory, cid, kind, ids,
                                        (chapters, targets, locations), binding) for kind in ('offline', 'visual')}})
    return {'chapters': rows, 'unassignedItems': sorted(unassigned),
            'disciplineChecks': discipline,
            'learningRange': _learning_range(course, rows, bool(scope_errors or contract_errors or global_map_errors or review_record_errors or discipline_configuration_errors)),
            'errors': list(dict.fromkeys(validate_chapter_checks(course, inventory) + map_errors
                                         + contract_errors + review_record_errors + scope_errors + validate_discipline_checks(course))),
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
