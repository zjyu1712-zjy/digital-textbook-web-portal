"""Trace material use and check whether human review still matches current content.

These helpers do not read private source files, generate teaching, or award a pass.
Source file hashes must be refreshed by the input inventory workflow. A matching
fingerprint proves which supplied content was reviewed, not academic correctness.
"""
import hashlib
import json
import re


TARGET_FIELDS = ('explanationTargets', 'summaryTargets', 'emphasisTargets')
LEARNING_USAGES = {'primary', 'explanation', 'example', 'practice'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _list(value):
    return value if isinstance(value, list) else []


def _strings(value):
    return isinstance(value, list) and all(_text(x) for x in value)


def _index(rows, label):
    if not isinstance(rows, list):
        raise ValueError(label + ' must be an array')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not _text(row.get('id')):
            raise ValueError(label + ' contains an invalid ID')
        key = row['id']
        if key in result:
            raise ValueError(label + ': duplicate ID ' + key)
        result[key] = row
    return result


def _context(course, inventory):
    if not isinstance(course, dict) or not isinstance(inventory, dict):
        raise ValueError('course and inventory must be objects')
    sources = _index(course.get('sources', []), 'sources')
    items = _index(inventory.get('items', []), 'inventory.items')
    chapters = _index(course.get('chapters', []), 'chapters')
    targets, locations = {}, {}
    for chapter_id, chapter in chapters.items():
        sections = _index(chapter.get('sections', []), 'sections')
        for target_id, section in sections.items():
            if target_id in targets:
                raise ValueError('duplicate target ID ' + target_id)
            targets[target_id] = section
            locations[target_id] = [chapter_id]
    for target_id, question in _index(course.get('questions', []), 'questions').items():
        if target_id in targets:
            raise ValueError('duplicate target ID ' + target_id)
        if not _strings(question.get('chapterIds', [])):
            raise ValueError('invalid question chapter IDs: ' + target_id)
        if any(x not in chapters for x in question.get('chapterIds', [])):
            raise ValueError('unknown question chapter ID: ' + target_id)
        targets[target_id] = question
        locations[target_id] = question.get('chapterIds', [])
    return sources, items, chapters, targets, locations


def _map_targets(row):
    if not isinstance(row, dict):
        return set()
    return {x for field in TARGET_FIELDS for x in _list(row.get(field)) if _text(x)}


def _coverage_targets(row):
    if not isinstance(row, dict):
        return set()
    return {x for x in _list(row.get('targets')) if _text(x)}


def _source_ids(value):
    """Include question-answer references and any explicitly located content blocks."""
    result = set()
    if isinstance(value, dict):
        for ref in _list(value.get('sourceRefs')):
            if isinstance(ref, dict) and _text(ref.get('sourceId')):
                result.add(ref['sourceId'])
        for key, nested in value.items():
            if key != 'sourceRefs':
                result.update(_source_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            result.update(_source_ids(nested))
    return result


def _has_readable_text(blocks):
    """Reject obvious page-only/heading-only/math-only claims; meaning needs review."""
    for block in _list(blocks):
        if not isinstance(block, dict):
            continue
        kind = block.get('type')
        if kind == 'paragraph':
            if _text(block.get('text')):
                return True
            if any(isinstance(run, dict) and run.get('type') == 'text' and _text(run.get('text'))
                   for run in _list(block.get('runs'))):
                return True
        if kind == 'list' and any(_text(x) for x in _list(block.get('items'))):
            return True
        if kind == 'table' and any(_text(cell) for row in _list(block.get('rows'))
                                   for cell in _list(row)):
            return True
        if kind == 'details' and _has_readable_text(block.get('blocks')):
            return True
    return False


def _teaching(target):
    if 'blocks' in target:
        return _has_readable_text(target.get('blocks'))
    answer = target.get('answer', {})
    return (_has_readable_text(target.get('prompt'))
            or (isinstance(answer, dict) and _has_readable_text(answer.get('blocks'))))


def validate_learning_map(course, inventory):
    """Validate trace locations and explicit reference-only uses, not their meaning."""
    errors = []
    try:
        sources, items, chapters, targets, locations = _context(course, inventory)
    except ValueError as exc:
        return [str(exc)]
    legacy = course.get('schemaVersion') == 1
    rows = course.get('learningMap')
    if legacy and rows is None:
        return []
    if not isinstance(rows, list):
        return ['learningMap must be an array']
    if not items:
        errors.append('learningMap requires an independent source inventory')
    if not isinstance(course.get('coverage'), list):
        errors.append('coverage must be an array')
    coverage = {}
    for row in _list(course.get('coverage')):
        if not isinstance(row, dict) or not _text(row.get('sourceItemId')):
            errors.append('invalid coverage row')
            continue
        item_id = row['sourceItemId']
        if item_id in coverage:
            errors.append('duplicate coverage row: ' + item_id)
        coverage[item_id] = row
    uses = {}
    contract = course.get('taskContract', {})
    if not isinstance(contract, dict):
        contract = {}
    for use in _list(contract.get('sourceUses')):
        if not isinstance(use, dict) or not _text(use.get('sourceId')):
            continue
        for chapter_id in _list(use.get('chapterIds')):
            if _text(chapter_id):
                key = (use['sourceId'], chapter_id)
                if key in uses:
                    errors.append('ambiguous source use: ' + use['sourceId'] + '/' + chapter_id)
                uses[key] = use.get('usage')
    seen = set()
    for number, row in enumerate(rows):
        label = 'learningMap[' + str(number) + ']'
        if not isinstance(row, dict) or not _text(row.get('sourceItemId')):
            errors.append(label + ': invalid sourceItemId')
            continue
        item_id = row['sourceItemId']
        label = 'learningMap ' + item_id
        if item_id in seen:
            errors.append(label + ': duplicate item')
        seen.add(item_id)
        item = items.get(item_id)
        if item is None:
            errors.append(label + ': unknown inventory item')
            continue
        source_id = item.get('sourceId')
        if not _text(source_id) or source_id not in sources:
            errors.append(label + ': unknown item source')
            continue
        disposition = row.get('disposition')
        if disposition not in ('integrated', 'reference-only', 'pending'):
            errors.append(label + ': invalid disposition')
        if disposition == 'pending':
            errors.append(label + ': integration is pending')
        if not _text(row.get('evidence')):
            errors.append(label + ': actual integration evidence is required')
        all_links = set()
        for field in TARGET_FIELDS:
            links = row.get(field, [])
            if not _strings(links):
                errors.append(label + ': ' + field + ' must contain target IDs')
                continue
            if len(links) != len(set(links)):
                errors.append(label + ': duplicated ' + field)
            for target_id in links:
                all_links.add(target_id)
                if target_id not in targets:
                    errors.append(label + ': unknown target ' + target_id)
                elif disposition == 'integrated' and not _teaching(targets[target_id]):
                    errors.append(label + ': target lacks readable teaching text: ' + target_id)
        if disposition in ('integrated', 'reference-only') and not _list(row.get('explanationTargets')):
            errors.append(label + ': explanation/reference location is required')
        if disposition == 'integrated':
            for prefix in ('summary', 'emphasis'):
                if not _list(row.get(prefix + 'Targets')) and not _text(row.get(prefix + 'Note')):
                    errors.append(label + ': ' + prefix + ' needs a target or a reasoned note')
        if disposition == 'reference-only' and (_list(row.get('summaryTargets')) or _list(row.get('emphasisTargets'))):
            errors.append(label + ': reference-only material cannot be recorded as teaching summary/emphasis')
        cover = coverage.get(item_id, {})
        if cover.get('status') != 'covered' or not _strings(cover.get('targets')):
            errors.append(label + ': matching covered source record is required')
        if not all_links.issubset(_coverage_targets(cover)):
            errors.append(label + ': teaching locations must also appear in coverage targets')
        if disposition == 'reference-only' and all_links != _coverage_targets(cover):
            errors.append(label + ': reference-only must declare every covered location')
        for target_id in all_links:
            target = targets.get(target_id)
            if target is None:
                continue
            if source_id not in _source_ids(target):
                errors.append(label + ': source is not located in target ' + target_id)
            scope = locations.get(target_id, [])
            if not scope:
                errors.append(label + ': target has no chapter scope: ' + target_id)
            for chapter_id in scope:
                usage = uses.get((source_id, chapter_id))
                if disposition == 'reference-only' and usage != 'reference':
                    errors.append(label + ': reference-only requires explicit reference use in ' + chapter_id)
                if disposition == 'integrated' and (not _text(usage) or usage not in LEARNING_USAGES):
                    errors.append(label + ': source is not assigned a learning use in ' + chapter_id)
    for item_id in sorted(set(items) - seen):
        errors.append('learningMap ' + item_id + ': item has no integration treatment')
    return list(dict.fromkeys(errors))


def _clean(value):
    """Discard only the derived image payload added by build()."""
    if isinstance(value, dict):
        return {key: _clean(nested) for key, nested in value.items()
                if not (value.get('type') == 'image' and key == 'data')}
    if isinstance(value, list):
        return [_clean(nested) for nested in value]
    return value


def review_fingerprint(course, inventory, target_ids):
    """Return a deterministic dependency digest without altering a review result."""
    try:
        sources, items, chapters, targets, locations = _context(course, inventory)
        if not _strings(target_ids) or not target_ids or len(target_ids) != len(set(target_ids)):
            raise ValueError('review target IDs must be a nonempty array of unique IDs')
        if any(target_id not in targets for target_id in target_ids):
            raise ValueError('review target ID does not exist')
        selected = set(target_ids)
        related_items, related_targets = set(), set(selected)
        coverage_rows, mapping_rows = [], []
        for row in _list(course.get('coverage')):
            if _coverage_targets(row) & selected:
                coverage_rows.append(row)
                related_items.add(row.get('sourceItemId'))
                related_targets.update(_coverage_targets(row))
        for row in _list(course.get('learningMap')):
            if _map_targets(row) & selected:
                mapping_rows.append(row)
                related_items.add(row.get('sourceItemId'))
                related_targets.update(_map_targets(row))
        # Include both records for each relevant item even if their target sets differ.
        coverage_rows = [row for row in _list(course.get('coverage'))
                         if isinstance(row, dict) and row.get('sourceItemId') in related_items]
        mapping_rows = [row for row in _list(course.get('learningMap'))
                        if isinstance(row, dict) and row.get('sourceItemId') in related_items]
        for row in coverage_rows:
            related_targets.update(_coverage_targets(row))
        for row in mapping_rows:
            related_targets.update(_map_targets(row))
        if any(item_id not in items for item_id in related_items):
            raise ValueError('review depends on an unknown inventory item')
        if any(target_id not in targets for target_id in related_targets):
            raise ValueError('review depends on an unknown linked target')
        source_ids = {items[item_id].get('sourceId') for item_id in related_items}
        for target_id in related_targets:
            source_ids.update(_source_ids(targets[target_id]))
        exams = _index(course.get('exams', []), 'exams')
        related_exams = []
        for exam_id in sorted(exams):
            exam = exams[exam_id]
            members = exam.get('questionIds', [])
            if not _strings(members):
                raise ValueError('invalid exam question IDs: ' + exam_id)
            if set(members) & related_targets:
                related_exams.append(_clean(exam))
                source_ids.update(_source_ids(exam))
        if any(source_id not in sources for source_id in source_ids):
            raise ValueError('review depends on an unknown source')
        target_rows = []
        for target_id in sorted(related_targets):
            target_rows.append({'id': target_id, 'content': _clean(targets[target_id]),
                                'chapters': [{'id': c, 'title': chapters[c].get('title')}
                                             for c in sorted(locations[target_id])]})
        payload = {
            'fingerprintVersion': 1,
            'schemaVersion': course.get('schemaVersion'),
            'book': {'id': course.get('id'), 'edition': course.get('edition')},
            'reviewTargets': sorted(selected),
            'organization': course.get('organization'),
            'taskContract': course.get('taskContract'),
            'targets': target_rows,
            'examContext': related_exams,
            'sources': [sources[source_id] for source_id in sorted(source_ids)],
            'inventoryItems': [items[item_id] for item_id in sorted(related_items)],
            'coverage': sorted(coverage_rows, key=lambda row: row.get('sourceItemId', '')),
            'learningMap': sorted(mapping_rows, key=lambda row: row.get('sourceItemId', '')),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()
    except (TypeError, KeyError, RecursionError) as exc:
        raise ValueError('invalid review fingerprint input: ' + str(exc)) from exc


def audit_reviews(course, inventory):
    """Assess supplied reviews; never manufacture a pass or modify either input.

    Historical unbound/stale entries may coexist with a fresh rereview. Conflicting
    pending/fail reviews bound to the same current input prevent an overall pass.
    Legacy v1 records never acquire v2 assurance just by being opened or rebuilt.
    """
    try:
        _, _, _, targets, _ = _context(course, inventory)
    except ValueError as exc:
        return {'status': 'invalid', 'errors': [str(exc)], 'targets': []}
    legacy = course.get('schemaVersion') == 1
    map_errors = [] if legacy else validate_learning_map(course, inventory)
    errors = list(map_errors)
    malformed_records = False
    required = set()
    for row in _list(course.get('coverage')):
        required.update(_coverage_targets(row))
    for row in _list(course.get('learningMap')):
        required.update(_map_targets(row))
    if not required:
        errors.append('review: no covered learning/reference targets were supplied')
    decisions = {target_id: [] for target_id in required}
    records = course.get('semanticReviews', [])
    if not isinstance(records, list):
        errors.append('semanticReviews must be an array')
        malformed_records = True
        records = []
    for number, record in enumerate(records):
        label = 'semanticReviews[' + str(number) + ']'
        if not isinstance(record, dict):
            errors.append(label + ': record must be an object')
            malformed_records = True
            continue
        ids = record.get('targetIds')
        if (not _strings(ids) or not ids or len(ids) != len(set(ids))
                or any(target_id not in targets for target_id in ids)):
            errors.append(label + ': invalid target IDs')
            malformed_records = True
            continue
        binding = record.get('binding')
        state, reason = 'unreviewed', 'No content-bound review was recorded.'
        current_bound = False
        metadata_ok = all(_text(record.get(key)) for key in ('reviewer', 'method', 'evidence'))
        result = record.get('result')
        if not metadata_ok or result not in ('pass', 'pending', 'fail'):
            state, reason = 'invalid', 'Review metadata or result is incomplete.'
        elif binding is None:
            if legacy and result == 'pass':
                state, reason = 'legacy-unverified', 'The historical pass has no content binding.'
            elif result in ('pending', 'fail'):
                state = 'pending' if result == 'pending' else 'failed'
                reason = 'Review is ' + result + ' and has no current content binding.'
        elif (not isinstance(binding, dict) or type(binding.get('version')) is not int
              or binding.get('version') != 1 or not isinstance(binding.get('fingerprint'), str)
              or not re.fullmatch(r'[0-9a-f]{64}', binding.get('fingerprint', ''))):
            state, reason = 'invalid', 'Review binding is malformed.'
        else:
            try:
                current = review_fingerprint(course, inventory, ids)
                if current != binding['fingerprint']:
                    state, reason = 'stale', 'Teaching, linked material, or task agreement changed after review.'
                else:
                    current_bound = True
                    if result == 'pass':
                        state, reason = 'fresh', 'The recorded pass matches the supplied current content.'
                    else:
                        state = 'pending' if result == 'pending' else 'failed'
                        reason = 'A current content-bound review is ' + result + '.'
            except ValueError as exc:
                state, reason = 'invalid', str(exc)
        if state == 'invalid':
            errors.append(label + ': ' + reason)
            malformed_records = True
        for target_id in ids:
            if target_id in decisions:
                decisions[target_id].append({'status': state, 'reason': reason,
                                             'currentBound': current_bound})
    result_rows = []
    for target_id in sorted(required):
        candidates = decisions[target_id]
        if target_id not in targets:
            chosen = {'status': 'invalid', 'reason': 'Mapped target does not exist.'}
        else:
            current = [r for r in candidates if r['currentBound']]
            chosen = None
            for status in ('failed', 'pending', 'fresh'):
                chosen = next((r for r in current if r['status'] == status), None)
                if chosen:
                    break
            if chosen is None:
                for status in ('invalid', 'stale', 'failed', 'pending', 'legacy-unverified', 'unreviewed'):
                    chosen = next((r for r in candidates if r['status'] == status), None)
                    if chosen:
                        break
            if chosen is None:
                chosen = {'status': 'unreviewed', 'reason': 'No review includes this target.'}
        result_rows.append({'targetId': target_id, 'status': chosen['status'], 'reason': chosen['reason']})
        if chosen['status'] != 'fresh' and not (legacy and chosen['status'] in ('legacy-unverified', 'unreviewed')):
            errors.append('review ' + target_id + ': ' + chosen['status'] + ' — ' + chosen['reason'])
        elif not legacy and chosen['status'] != 'fresh':
            errors.append('review ' + target_id + ': ' + chosen['status'] + ' — ' + chosen['reason'])
    states = {row['status'] for row in result_rows}
    if legacy:
        status = 'legacy-unverified'
    elif ('invalid' in states or malformed_records
          or any(not e.endswith(': integration is pending') for e in map_errors)):
        status = 'invalid'
    elif 'stale' in states:
        status = 'stale'
    elif errors or states != {'fresh'}:
        status = 'needs-review'
    else:
        status = 'pass'
    return {'status': status, 'errors': list(dict.fromkeys(errors)), 'targets': result_rows}
