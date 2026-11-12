"""Persist task-specific material roles; never infer PPT priority from its presence.

This module checks the shape and consistency of recorded agreements. It does not
claim that a user approved them, nor determine pedagogical quality from metadata.
"""

MODES = {'textbook', 'slides', 'outline', 'combined'}
USAGES = {'primary', 'explanation', 'example', 'practice', 'reference'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _rows(value, label, errors):
    if not isinstance(value, list):
        errors.append(label + ': expected a list')
        return []
    rows = []
    for index, row in enumerate(value):
        if isinstance(row, dict):
            rows.append(row)
        else:
            errors.append(f'{label}[{index}]: expected an object')
    return rows


def _identifiers(rows, label, errors):
    found = set()
    for row in rows:
        value = row.get('id')
        if not _text(value):
            errors.append(label + ': missing or invalid id')
        elif value in found:
            errors.append(label + ': duplicate id ' + value)
        else:
            found.add(value)
    return found


def _id_list(value, label, errors, allowed=None):
    if not isinstance(value, list) or not value:
        errors.append(label + ': expected a nonempty ID list')
        return []
    ids = []
    for item in value:
        if not _text(item):
            errors.append(label + ': invalid ID')
        elif item in ids:
            errors.append(label + ': duplicate ID ' + item)
        elif allowed is not None and item not in allowed:
            errors.append(label + ': unknown ID ' + item)
        else:
            ids.append(item)
    return ids


def _organization(organization, source_ids, errors):
    if not isinstance(organization, dict):
        errors.append('organization: expected an object')
        return None, []
    mode = organization.get('mode')
    if not isinstance(mode, str) or mode not in MODES:
        errors.append('organization.mode: invalid material mode')
        mode = None
    ids = _id_list(organization.get('primarySourceIds'),
                   'organization.primarySourceIds', errors, source_ids)
    return mode, ids


def _plan_summary(plans):
    """Summarize already validated plans; do not infer their modes from file roles."""
    modes = {p['mode'] for p in plans}
    mode = next(iter(modes)) if len(modes) == 1 else 'combined'
    primary_ids = []
    for plan in plans:
        for source_id in plan['primarySourceIds']:
            if source_id not in primary_ids:
                primary_ids.append(source_id)
    return mode, primary_ids


def validate_contract(course):
    """Return consistency errors for a course's explicit per-task agreement.

    Source uses are scoped to named chapters. Every chapter has one plan and
    every supplied source has at least one use. A source may serve different
    purposes in different chapters, but only one stated use in a given chapter.
    """
    errors = []
    if not isinstance(course, dict):
        return ['taskContract: course must be an object']
    sources = _rows(course.get('sources'), 'sources', errors)
    chapters = _rows(course.get('chapters'), 'chapters', errors)
    source_ids = _identifiers(sources, 'sources', errors)
    chapter_ids = _identifiers(chapters, 'chapters', errors)
    if not source_ids:
        errors.append('taskContract: no valid supplied sources')
    if not chapter_ids:
        errors.append('taskContract: no valid chapters')
    contract = course.get('taskContract')
    if not isinstance(contract, dict):
        return errors + ['taskContract: expected an object']
    if type(contract.get('version')) is not int or contract['version'] != 1:
        errors.append('taskContract.version: expected 1')
    for field in ('goal', 'basis'):
        if not _text(contract.get(field)):
            errors.append('taskContract.' + field + ': nonempty text required')

    assignments = {}
    used_sources = set()
    for index, use in enumerate(_rows(contract.get('sourceUses'), 'taskContract.sourceUses', errors)):
        label = f'taskContract.sourceUses[{index}]'
        source_id = use.get('sourceId')
        valid_source = _text(source_id) and source_id in source_ids
        if not valid_source:
            errors.append(label + '.sourceId: unknown or invalid source')
        usage = use.get('usage')
        valid_usage = isinstance(usage, str) and usage in USAGES
        if not valid_usage:
            errors.append(label + '.usage: invalid usage')
        if not _text(use.get('purpose')):
            errors.append(label + '.purpose: nonempty text required')
        ids = _id_list(use.get('chapterIds'), label + '.chapterIds', errors, chapter_ids)
        if valid_source and valid_usage and ids:
            used_sources.add(source_id)
            for chapter_id in ids:
                key = (source_id, chapter_id)
                if key in assignments:
                    errors.append(label + ': duplicate or conflicting source use for '
                                  + source_id + '/' + chapter_id)
                else:
                    assignments[key] = usage
    for source_id in sorted(source_ids - used_sources):
        errors.append('taskContract.sourceUses: source has no explicit use: ' + source_id)

    plans = []
    planned_chapters = set()
    for index, plan in enumerate(_rows(contract.get('chapterPlans'), 'taskContract.chapterPlans', errors)):
        label = f'taskContract.chapterPlans[{index}]'
        chapter_id = plan.get('chapterId')
        valid_chapter = _text(chapter_id) and chapter_id in chapter_ids
        if not valid_chapter:
            errors.append(label + '.chapterId: unknown or invalid chapter')
        elif chapter_id in planned_chapters:
            errors.append(label + '.chapterId: duplicate plan for ' + chapter_id)
        else:
            planned_chapters.add(chapter_id)
        mode = plan.get('mode')
        valid_mode = isinstance(mode, str) and mode in MODES
        if not valid_mode:
            errors.append(label + '.mode: invalid material mode')
        ids = _id_list(plan.get('primarySourceIds'), label + '.primarySourceIds', errors, source_ids)
        if not _text(plan.get('emphasis')):
            errors.append(label + '.emphasis: nonempty text required')
        if valid_chapter:
            assigned_primary = {source_id for (source_id, cid), usage in assignments.items()
                                if cid == chapter_id and usage == 'primary'}
            if set(ids) != assigned_primary:
                errors.append(label + ': primarySourceIds do not match primary sourceUses for ' + chapter_id)
        if valid_chapter and valid_mode and ids:
            plans.append({'chapterId': chapter_id, 'mode': mode, 'primarySourceIds': ids})
    for chapter_id in sorted(chapter_ids - planned_chapters):
        errors.append('taskContract.chapterPlans: chapter has no plan: ' + chapter_id)

    for index, item in enumerate(_rows(contract.get('pendingMaterials', []),
                                       'taskContract.pendingMaterials', errors)):
        chapter_id = item.get('chapterId')
        if not _text(chapter_id) or chapter_id not in chapter_ids:
            errors.append(f'taskContract.pendingMaterials[{index}].chapterId: unknown or invalid chapter')
        if not _text(item.get('description')):
            errors.append(f'taskContract.pendingMaterials[{index}].description: nonempty text required')

    organization_mode, organization_ids = _organization(course.get('organization'), source_ids, errors)
    if plans:
        summary_mode, summary_ids = _plan_summary(plans)
        if set(organization_ids) != set(summary_ids):
            errors.append('organization.primarySourceIds: must equal the union of chapterPlans primary sources')
        # "combined" is a valid whole-book umbrella even when chapters share a
        # mode. A more specific whole-book mode must agree with every chapter.
        if organization_mode not in (summary_mode, 'combined'):
            errors.append('organization.mode: conflicts with taskContract chapterPlans')
    return errors


def _disciplines(evidence):
    if isinstance(evidence, str):
        text = evidence
    elif isinstance(evidence, list):
        text = ' '.join(value for value in evidence if isinstance(value, str))
    else:
        text = ''
    terms = [
        ('math', ['矩阵', '定理', '行列式', '证明']),
        ('theory', ['方法论', '原理', '材料分析']),
        ('models', ['均衡', '曲线', '坐标']),
        ('accounting', ['借贷', '分录', '账户', '试算']),
        ('statistics', ['统计量', '置信', '概率分布', '抽样分布', '样本均值', '方差', '假设检验']),
    ]
    return [key for key, words in terms if any(word in text for word in words)] or ['general']


def classify(sources, evidence, organization=None, contract=None, chapter_id=None):
    """Return an advisory classification without writing or inventing agreements.

    An existing organization is authoritative for the whole book; a valid task
    contract refines it per chapter. Disagreement is reported, never silently
    resolved. Legacy explicit primary flags remain usable with a warning.
    """
    errors = []
    warnings = []
    rows = _rows(sources, 'sources', errors)
    source_ids = set()
    for source in rows:
        if 'id' in source:
            source_id = source['id']
            if not _text(source_id):
                errors.append('sources: invalid source id')
            elif source_id in source_ids:
                errors.append('sources: duplicate source id ' + source_id)
            else:
                source_ids.add(source_id)
    mode = None
    primary_ids = []
    basis = 'undetermined'

    if contract is not None:
        if not isinstance(contract, dict):
            errors.append('taskContract: expected an object')
        else:
            raw_plans = _rows(contract.get('chapterPlans'), 'taskContract.chapterPlans', errors)
            # Full course chapter objects are not part of the classifier input;
            # the contract's explicit plans define its classification scope.
            chapter_rows = [{'id': plan.get('chapterId')} for plan in raw_plans]
            usable_plans = [plan for plan in raw_plans
                            if _text(plan.get('chapterId'))
                            and isinstance(plan.get('mode'), str) and plan['mode'] in MODES
                            and isinstance(plan.get('primarySourceIds'), list)
                            and plan['primarySourceIds']
                            and all(_text(value) for value in plan['primarySourceIds'])]
            inferred = None
            if usable_plans:
                summary_mode, summary_ids = _plan_summary(usable_plans)
                inferred = {'mode': summary_mode, 'primarySourceIds': summary_ids}
            effective_organization = organization if organization is not None else inferred
            errors.extend(validate_contract({'sources': rows, 'chapters': chapter_rows,
                                              'taskContract': contract,
                                              'organization': effective_organization}))
            if not errors:
                if chapter_id is not None:
                    selected = next((p for p in usable_plans if p['chapterId'] == chapter_id), None)
                    if selected is None:
                        errors.append('taskContract.chapterPlans: requested chapter is not recorded')
                    else:
                        mode, primary_ids = selected['mode'], list(selected['primarySourceIds'])
                else:
                    mode = effective_organization['mode']
                    primary_ids = list(effective_organization['primarySourceIds'])
                basis = 'taskContract'
    elif organization is not None:
        mode, primary_ids = _organization(organization, source_ids, errors)
        basis = 'organization'
    else:
        primary = [source for source in rows if source.get('primary') is True]
        if primary:
            roles = {source.get('role') for source in primary if isinstance(source.get('role'), str)}
            if len(primary) > 1 and len(roles) > 1:
                mode = 'combined'
            elif len(roles) == 1:
                mode = {'textbook': 'textbook', 'teacher_slides': 'slides',
                        'outline': 'outline'}.get(next(iter(roles)))
            primary_ids = [source['id'] for source in primary if _text(source.get('id'))]
            basis = 'legacy-primary'
            warnings.append('兼容 sources[].primary；请将已有主次记录到 organization 和 taskContract。')
        elif len(rows) == 1 and rows[0].get('role') == 'textbook' and rows[0].get('primary') is not False:
            mode = 'textbook'
            primary_ids = [rows[0]['id']] if _text(rows[0].get('id')) else []
            basis = 'single-textbook'

    if organization is not None or contract is not None:
        if any(source.get('primary') is True for source in rows):
            warnings.append('已有 organization/taskContract 优先；不使用旧 sources[].primary 改写约定。')
    if errors:
        mode, primary_ids, basis = None, [], 'invalid-or-conflicting'
    needs_decision = mode is None
    status = ('待判断；依据本次任务确定资料主次，不按文件类型猜测。' if needs_decision else
              '沿用已记录的资料主次；学科分类仍须核对实际内容。' if basis in ('organization', 'taskContract') else
              '建议；仅单教材默认或兼容显式主资料标记，须核对本次要求。')
    return {'materialMode': mode, 'primarySourceIds': primary_ids,
            'disciplines': _disciplines(evidence), 'needsDecision': needs_decision,
            'decisionBasis': basis, 'status': status, 'warnings': warnings, 'errors': errors}
