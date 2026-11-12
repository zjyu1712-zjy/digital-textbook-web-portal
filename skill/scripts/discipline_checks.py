"""Deterministic checks over explicitly located course blocks, not copied values.

These rules check only declared arithmetic and dimensions. They neither grade a
learner's answer nor establish account choice, statistical meaning or correctness
of a derivation. A course without configured rules is not marked as passed.
"""
from decimal import Decimal, InvalidOperation, localcontext
import math
import re


DECIMAL = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
KINDS = {'journal_balance', 'table_sum', 'percentage_total', 'frequency_total', 'matrix_shape'}
AREAS = {'blocks', 'prompt', 'answer.blocks'}
REFERENCE_KEYS = {'targetId', 'area', 'blockPath'}
NOTE = '只检查明确配置且绑定实际内容的规则；通过不证明科目选择、统计口径、题意或推导正确，不用于学生自动判分。'


class RuleInputError(ValueError):
    def __init__(self, message, location=None, actual=None, expected=None, code='invalid_input', scope='configuration'):
        super().__init__(message)
        self.location = location or {}
        self.actual = actual
        self.expected = expected
        self.code = code
        self.scope = scope


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _location(reference, row=None, column=None):
    result = {k: reference.get(k) for k in ('targetId', 'area', 'blockPath')}
    if row is not None:
        result['row'] = row
    if column is not None:
        result['column'] = column
    return result


def _safe(value, depth=0):
    """Keep failure reports valid JSON even when the supplied input is not."""
    if depth > 12:
        return '[nested value omitted]'
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, list):
        return [_safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item, depth + 1) for key, item in value.items()}
    return '[' + type(value).__name__ + ']'


def _issue(rule_id, status, message, location=None, actual=None, expected=None, code='mismatch', scope='content'):
    return {'ruleId': rule_id, 'status': status, 'code': code, 'message': message,
            'scope': scope, 'location': _safe(location or {}), 'actual': _safe(actual), 'expected': _safe(expected)}


def _decimal(value, location=None):
    # JSON decimal numbers are read through their supplied decimal spelling.
    # High precision source quantities should use strings, never binary floats.
    scope = 'content' if location and 'row' in location and 'column' in location else 'configuration'
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RuleInputError('需要明确的有限十进制数；缺测、布尔值不能当作0。', location, value, 'finite decimal', scope=scope)
    if isinstance(value, float) and not math.isfinite(value):
        raise RuleInputError('不接受NaN或Infinity。', location, str(value), 'finite decimal', scope=scope)
    try:
        text = value.strip() if isinstance(value, str) else str(value)
    except ValueError as error:
        raise RuleInputError('数字超过可处理的十进制文本长度。', location, None, 'decimal text <=4096 characters', scope=scope) from error
    if len(text) > 4096 or not DECIMAL.fullmatch(text):
        raise RuleInputError('需要十进制字面量；不执行算式、不删除单位或百分号。', location, text[:160], 'finite decimal literal', scope=scope)
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise RuleInputError('十进制数无效。', location, text, 'finite decimal', scope=scope) from error
    if not number.is_finite() or abs(number.as_tuple().exponent) > 10000:
        raise RuleInputError('数值指数超出可检查范围。', location, text, 'finite decimal; exponent within +/-10000', scope=scope)
    return number


def _arithmetic(values, subtract=False):
    """Use sufficient Decimal precision even for long coefficients and exponents."""
    values = list(values)
    if not values:
        return Decimal(0)
    highest = max(v.adjusted() if v else 0 for v in values)
    lowest = min(v.as_tuple().exponent for v in values)
    with localcontext() as context:
        context.prec = max(34, highest - lowest + len(str(len(values))) + 3)
        if subtract:
            return values[0] - values[1]
        return sum(values, Decimal(0))


def _places(number):
    digits = list(number.as_tuple().digits)
    exponent = number.as_tuple().exponent
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return max(0, -exponent) if digits else 0


def _index(value, size, label, location=None):
    if type(value) is not int or not 0 <= value < size:
        raise RuleInputError(label + '必须是范围内的零基整数索引。', location, value, {'minimum': 0, 'maximum': size - 1})
    return value


def _targets(course):
    targets = {}
    chapters, questions = course.get('chapters'), course.get('questions')
    if not isinstance(chapters, list) or not isinstance(questions, list):
        raise RuleInputError('课程chapters与questions必须为数组。')
    for chapter in chapters:
        if not isinstance(chapter, dict) or not isinstance(chapter.get('sections'), list):
            raise RuleInputError('章节与sections结构无效。')
        for section in chapter['sections']:
            if not isinstance(section, dict) or not _text(section.get('id')):
                raise RuleInputError('学习小节缺少有效ID。')
            if section['id'] in targets:
                raise RuleInputError('目标ID重复，不能确定实际内容：' + section['id'])
            targets[section['id']] = ('section', section)
    for question in questions:
        if not isinstance(question, dict) or not _text(question.get('id')):
            raise RuleInputError('题目缺少有效ID。')
        if question['id'] in targets:
            raise RuleInputError('目标ID重复，不能确定实际内容：' + question['id'])
        targets[question['id']] = ('question', question)
    return targets


def _reference(reference, targets, expected_kind):
    if not isinstance(reference, dict) or set(reference) != REFERENCE_KEYS:
        raise RuleInputError('内容定位只能包含targetId、area和blockPath。', actual=reference, expected=sorted(REFERENCE_KEYS))
    tid, area, path = (reference.get(k) for k in ('targetId', 'area', 'blockPath'))
    location = _location(reference)
    if not _text(tid) or tid not in targets:
        raise RuleInputError('内容定位的targetId不存在。', location, tid, 'existing section/question ID')
    target_kind, target = targets[tid]
    valid_areas = {'blocks'} if target_kind == 'section' else {'prompt', 'answer.blocks'}
    if not isinstance(area, str) or area not in valid_areas:
        raise RuleInputError('内容区域与实际目标类型不符。', location, area, sorted(valid_areas))
    if not isinstance(path, list) or not path or len(path) > 32 or any(type(x) is not int or x < 0 for x in path):
        raise RuleInputError('blockPath需要1至32个非负整数，只沿details.blocks定位。', location, path, 'nonnegative block index list')
    if area == 'answer.blocks':
        answer = target.get('answer')
        blocks = answer.get('blocks') if isinstance(answer, dict) else None
    else:
        blocks = target.get(area)
    block = None
    for offset, index in enumerate(path):
        if not isinstance(blocks, list) or index >= len(blocks) or not isinstance(blocks[index], dict):
            raise RuleInputError('指定内容块不存在或结构无效。', location, path[:offset + 1], 'existing block')
        block = blocks[index]
        if offset < len(path) - 1:
            if block.get('type') != 'details':
                raise RuleInputError('嵌套定位只能穿过details.blocks。', location, block.get('type'), 'details')
            blocks = block.get('blocks')
    if block.get('type') != expected_kind:
        raise RuleInputError('规则与实际内容块类型不匹配。', location, block.get('type'), expected_kind)
    return block


def _table(reference, targets):
    block = _reference(reference, targets, 'table')
    columns, rows = block.get('columns'), block.get('rows')
    if not isinstance(columns, list) or not columns or not isinstance(rows, list) or not rows:
        raise RuleInputError('表格必须有明确的列和数据行。', _location(reference), scope='content')
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            raise RuleInputError('实际表格行列数不一致。', _location(reference, index), len(row) if isinstance(row, list) else None, len(columns), scope='content')
    return columns, rows


def _cell_expected(value, targets):
    if not isinstance(value, dict):
        return _decimal(value), None
    if set(value) != REFERENCE_KEYS | {'row', 'column'}:
        raise RuleInputError('期望值只能是十进制字面量或明确定位的实际表格单元格。', actual=value)
    ref = {k: value[k] for k in REFERENCE_KEYS}
    columns, rows = _table(ref, targets)
    row = _index(value['row'], len(rows), 'row', _location(ref))
    column = _index(value['column'], len(columns), 'column', _location(ref, row))
    location = _location(ref, row, column)
    return _decimal(rows[row][column], location), location


def _require_keys(rule, additional):
    allowed = {'id', 'kind', 'target', 'description'} | set(additional)
    unknown = sorted(set(rule) - allowed)
    if unknown:
        raise RuleInputError('规则包含未知字段，未按猜测执行。', actual=unknown, expected=sorted(allowed), code='unknown_option')
    if 'description' in rule and not _text(rule['description']):
        raise RuleInputError('description须为非空说明文字。', actual=rule['description'])


def _rule_target_ids(rule, targets):
    """Only known targets of explicit references, never text guessed from cells."""
    return sorted({ref['targetId'] for key in ('target', 'other', 'result', 'expected')
                   for ref in [rule.get(key)] if isinstance(ref, dict)
                   and _text(ref.get('targetId')) and ref['targetId'] in targets})


def _configuration(rule, targets):
    """Validate every declared option/reference before inspecting cell values.

    A content error must not conceal a second, globally invalid configuration.
    Bounds that depend on a valid table shape are checked by the rule itself.
    """
    kind = rule['kind']
    if kind == 'journal_balance':
        options = {'debitColumn', 'creditColumn', 'accountColumn', 'accounts', 'decimalPlaces'}
    elif kind == 'matrix_shape':
        options = {'operation', 'other', 'result'}
    else:
        options = {'axis', 'index', 'indices'}
        if kind != 'percentage_total':
            options.add('expected')
        if kind != 'frequency_total':
            options.add('tolerance')
    _require_keys(rule, options)
    block = _reference(rule['target'], targets, 'matrix' if kind == 'matrix_shape' else 'table')
    def index_literal(value, label):
        if type(value) is not int or value < 0:
            raise RuleInputError(label + '须为非负整数索引。', _location(rule['target']), value)
    def bounds(value, actual_axis, label, reference):
        if isinstance(actual_axis, list):
            _index(value, len(actual_axis), label, _location(reference))
    if kind == 'matrix_shape':
        operation = rule.get('operation')
        if operation not in ('add', 'multiply', 'transpose', 'square'):
            raise RuleInputError('未知矩阵维度规则。', actual=operation)
        if operation in ('add', 'multiply') and 'other' not in rule:
            raise RuleInputError('加法或乘法检查需要第二个实际矩阵定位。')
        if operation == 'transpose' and 'result' not in rule:
            raise RuleInputError('转置检查需要实际结果矩阵定位。')
        if operation in ('transpose', 'square') and 'other' in rule or operation == 'square' and 'result' in rule:
            raise RuleInputError('矩阵操作包含不适用的额外定位。')
        for key in ('other', 'result'):
            if key in rule:
                _reference(rule[key], targets, 'matrix')
    elif kind == 'journal_balance':
        columns = [rule.get(key) for key in ('debitColumn', 'creditColumn', 'accountColumn')]
        for value in columns:
            index_literal(value, '借贷/科目列')
            bounds(value, block.get('columns'), '借贷/科目列', rule['target'])
        if len(set(columns)) != 3:
            raise RuleInputError('借方、贷方与科目列必须是不同的明确列。')
        if 'accounts' in rule:
            accounts = rule['accounts']
            if (not isinstance(accounts, list) or not accounts or any(not _text(a) for a in accounts)
                    or len(accounts) != len(set(accounts))):
                raise RuleInputError('科目表必须是非空且不重复的科目名称数组。')
        if 'decimalPlaces' in rule and (type(rule['decimalPlaces']) is not int or not 0 <= rule['decimalPlaces'] <= 100):
            raise RuleInputError('decimalPlaces须为0至100的整数。')
    else:
        if rule.get('axis') not in ('row', 'column'):
            raise RuleInputError('axis须明确为row或column，不从表头猜测。')
        index_literal(rule.get('index'), 'index')
        bounds(rule['index'], block.get('rows' if rule['axis'] == 'row' else 'columns'), 'index', rule['target'])
        if 'indices' in rule:
            indices = rule['indices']
            if not isinstance(indices, list) or not indices:
                raise RuleInputError('indices须为非空索引数组。')
            for index in indices:
                index_literal(index, 'indices')
                bounds(index, block.get('columns' if rule['axis'] == 'row' else 'rows'), 'indices', rule['target'])
            if len(set(indices)) != len(indices):
                raise RuleInputError('indices不得重复。')
        if kind != 'percentage_total':
            expected = rule.get('expected')
            if isinstance(expected, dict):
                if set(expected) != REFERENCE_KEYS | {'row', 'column'}:
                    raise RuleInputError('期望值单元格定位字段无效。')
                expected_ref = {key: expected[key] for key in REFERENCE_KEYS}
                expected_block = _reference(expected_ref, targets, 'table')
                index_literal(expected['row'], 'expected.row')
                index_literal(expected['column'], 'expected.column')
                bounds(expected['row'], expected_block.get('rows'), 'expected.row', expected_ref)
                bounds(expected['column'], expected_block.get('columns'), 'expected.column', expected_ref)
                selected_axis = 'column' if rule['axis'] == 'row' else 'row'
                if (expected_ref == rule['target'] and expected[rule['axis']] == rule['index']
                        and ('indices' not in rule or expected[selected_axis] in rule['indices'])):
                    raise RuleInputError('期望合计单元格不能同时计入被相加的数据，不能用自身验证自身。', _location(expected_ref, expected['row'], expected['column']), code='self_referential_total')
            else:
                number = _decimal(expected)
                if kind == 'frequency_total' and (number < 0 or _places(number) != 0):
                    raise RuleInputError('样本量须为明确的非负整数。')
        if kind != 'frequency_total' and _decimal(rule.get('tolerance', '0')) < 0:
            raise RuleInputError('容差不得为负数。')


def _journal(rule, targets):
    _require_keys(rule, {'debitColumn', 'creditColumn', 'accountColumn', 'accounts', 'decimalPlaces'})
    reference = rule['target']
    columns, rows = _table(reference, targets)
    dc, cc, ac = [_index(rule.get(k), len(columns), k, _location(reference))
                  for k in ('debitColumn', 'creditColumn', 'accountColumn')]
    if len({dc, cc, ac}) != 3:
        raise RuleInputError('借方、贷方与科目列必须是不同的明确列。', _location(reference), [dc, cc, ac], 'three distinct column indices')
    accounts = rule.get('accounts')
    if 'accounts' in rule and (not isinstance(accounts, list) or not accounts
            or any(not _text(a) for a in accounts) or len(accounts) != len(set(accounts))):
        raise RuleInputError('科目表必须是非空且不重复的科目名称数组。', _location(reference))
    precision = rule.get('decimalPlaces')
    if 'decimalPlaces' in rule and (type(precision) is not int or not 0 <= precision <= 100):
        raise RuleInputError('decimalPlaces须为0至100的整数。', _location(reference), precision)
    debit, credit, issues = [], [], []
    for ri, row in enumerate(rows):
        if all(cell is None or isinstance(cell, str) and not cell.strip() for cell in row):
            issues.append(_issue(rule['id'], 'invalid', '分录包含空行；未将空行当作0。', _location(reference, ri), row, 'nonempty posting', 'empty_row'))
            continue
        account = row[ac]
        if not _text(account):
            issues.append(_issue(rule['id'], 'invalid', '科目名称缺失。', _location(reference, ri, ac), account, 'account name', 'missing_account'))
        elif accounts is not None and account not in accounts:
            issues.append(_issue(rule['id'], 'fail', '科目不在本规则明确给出的科目表内。', _location(reference, ri, ac), account, accounts, 'account_not_allowed'))
        for ci, values in ((dc, debit), (cc, credit)):
            location = _location(reference, ri, ci)
            try:
                amount = _decimal(row[ci], location)
            except RuleInputError as error:
                issues.append(_issue(rule['id'], 'invalid', str(error), error.location, error.actual, error.expected, error.code, error.scope))
                continue
            if amount < 0:
                issues.append(_issue(rule['id'], 'fail', '借贷栏金额须为非负数；方向由明确列决定。', location, str(amount), '>=0', 'negative_posting'))
            if precision is not None and _places(amount) > precision:
                issues.append(_issue(rule['id'], 'fail', '金额超过明确指定的小数精度。', location, str(amount), {'maximumDecimalPlaces': precision}, 'amount_precision'))
            values.append(amount)
    observations = []
    if len(debit) == len(rows) and len(credit) == len(rows):
        dr, cr = _arithmetic(debit), _arithmetic(credit)
        difference = _arithmetic([dr, cr], subtract=True)
        observations.append({'debitTotal': str(dr), 'creditTotal': str(cr), 'difference': str(difference)})
        if difference:
            issues.append(_issue(rule['id'], 'fail', '借贷合计不相等。', _location(reference),
                {'debitTotal': str(dr), 'creditTotal': str(cr), 'difference': str(difference)}, 'equal debit and credit totals', 'unbalanced_journal'))
    return issues, observations


def _sum_rule(rule, targets):
    kind = rule['kind']
    allowed = {'axis', 'index', 'indices'}
    if kind != 'percentage_total':
        allowed.add('expected')
    if kind != 'frequency_total':
        allowed.add('tolerance')
    _require_keys(rule, allowed)
    reference = rule['target']
    columns, rows = _table(reference, targets)
    axis = rule.get('axis')
    if axis not in ('row', 'column'):
        raise RuleInputError('axis须明确为row或column，不从表头猜测。', _location(reference), axis, ['row', 'column'])
    index = _index(rule.get('index'), len(rows) if axis == 'row' else len(columns), 'index', _location(reference))
    size = len(columns) if axis == 'row' else len(rows)
    selected = rule.get('indices', list(range(size)))
    if (not isinstance(selected, list) or not selected or any(type(i) is not int or i < 0 or i >= size for i in selected)
            or len(selected) != len(set(selected))):
        raise RuleInputError('indices须为不重复的有效零基索引，不能用空列表代表检查通过。', _location(reference), selected, {'minimum': 0, 'maximum': size - 1})
    expected, expected_location = (Decimal(100), None) if kind == 'percentage_total' else _cell_expected(rule.get('expected'), targets)
    tolerance = _decimal(rule.get('tolerance', '0'), _location(reference))
    if tolerance < 0:
        raise RuleInputError('容差不得为负数。', _location(reference), str(tolerance), '>=0')
    if kind == 'frequency_total' and (expected < 0 or _places(expected) != 0):
        raise RuleInputError('样本量须为明确的非负整数。', expected_location or _location(reference), str(expected), 'nonnegative integer', scope='content' if expected_location else 'configuration')
    values, issues, positions = [], [], []
    for offset in selected:
        ri, ci = (index, offset) if axis == 'row' else (offset, index)
        location = _location(reference, ri, ci)
        positions.append({'row': ri, 'column': ci})
        if expected_location == location:
            raise RuleInputError('期望合计单元格不能同时计入被相加的数据，不能用自身验证自身。', location, location, 'separate total cell', 'self_referential_total')
        try:
            number = _decimal(rows[ri][ci], location)
        except RuleInputError as error:
            issues.append(_issue(rule['id'], 'invalid', str(error), error.location, error.actual, error.expected, error.code, error.scope))
            continue
        if kind == 'frequency_total' and (number < 0 or _places(number) != 0):
            issues.append(_issue(rule['id'], 'fail', '频数须为非负整数。', location, str(number), 'nonnegative integer', 'invalid_frequency'))
        values.append(number)
    observations = []
    if len(values) == len(selected):
        actual = _arithmetic(values)
        difference = _arithmetic([actual, expected], subtract=True).copy_abs()
        observations.append({'sum': str(actual), 'expected': str(expected), 'tolerance': str(tolerance),
                             'cells': positions, 'expectedLocation': expected_location})
        if difference > tolerance:
            issues.append(_issue(rule['id'], 'fail', '合计与明确期望值不符，且超出容差。', _location(reference),
                {'sum': str(actual), 'difference': str(difference), 'cells': positions},
                {'sum': str(expected), 'tolerance': str(tolerance), 'location': expected_location}, 'sum_mismatch'))
    return issues, observations


def _shape(reference, targets):
    matrix = _reference(reference, targets, 'matrix')
    rows = matrix.get('rows')
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
        raise RuleInputError('矩阵必须有非空行列。', _location(reference), scope='content')
    columns = len(rows[0])
    for ri, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != columns:
            raise RuleInputError('矩阵各行长度不一致。', _location(reference, ri), len(row) if isinstance(row, list) else None, columns, scope='content')
        for ci, cell in enumerate(row):
            if (cell is None or isinstance(cell, bool) or not isinstance(cell, (str, int, float))
                    or isinstance(cell, str) and (not cell.strip() or cell.strip().lower() in
                        ('nan', '+nan', '-nan', 'infinity', '+infinity', '-infinity', 'inf', '+inf', '-inf', 'true', 'false'))
                    or isinstance(cell, float) and not math.isfinite(cell)):
                raise RuleInputError('矩阵存在缺失或无效单元格；不会将其补为0。', _location(reference, ri, ci), cell, 'number or nonempty mathematical expression', scope='content')
    return [len(rows), columns]


def _matrix(rule, targets):
    _require_keys(rule, {'operation', 'other', 'result'})
    operation = rule.get('operation')
    if operation not in ('add', 'multiply', 'transpose', 'square'):
        raise RuleInputError('未知矩阵维度规则。', actual=operation, expected=['add', 'multiply', 'transpose', 'square'])
    if operation in ('transpose', 'square') and 'other' in rule or operation == 'square' and 'result' in rule:
        raise RuleInputError('该矩阵操作包含不适用的额外定位，未静默忽略。')
    target = rule['target']
    left = _shape(target, targets)
    observations = [{'targetShape': left, 'operation': operation}]
    issues = []
    if operation == 'square':
        if left[0] != left[1]:
            issues.append(_issue(rule['id'], 'fail', '行列式规则要求方阵。', _location(target), left, 'rows equal columns', 'not_square'))
        return issues, observations
    if operation == 'transpose':
        if 'result' not in rule:
            raise RuleInputError('转置检查需要实际结果矩阵定位。', _location(target))
        expected = [left[1], left[0]]
    else:
        if 'other' not in rule:
            raise RuleInputError('加法或乘法检查需要第二个实际矩阵定位。', _location(target))
        right = _shape(rule['other'], targets)
        observations[0]['otherShape'] = right
        compatible = left == right if operation == 'add' else left[1] == right[0]
        if not compatible:
            issues.append(_issue(rule['id'], 'fail', '矩阵维度不满足' + ('加法' if operation == 'add' else '乘法') + '条件。',
                _location(rule['other']), {'targetShape': left, 'otherShape': right},
                'same shape' if operation == 'add' else 'left columns equal right rows', 'incompatible_shapes'))
            return issues, observations
        expected = left if operation == 'add' else [left[0], right[1]]
    if 'result' in rule:
        actual = _shape(rule['result'], targets)
        observations[0]['resultShape'] = actual
        observations[0]['expectedResultShape'] = expected
        if actual != expected:
            issues.append(_issue(rule['id'], 'fail', '实际结果矩阵的维度不符。', _location(rule['result']), actual, expected, 'result_shape_mismatch'))
    return issues, observations


def report_discipline_checks(course):
    """Report pass/fail/invalid for configured rules, or explicit not-configured."""
    report = {'version': 1, 'status': 'not-configured', 'configuredCount': 0, 'passedCount': 0,
              'failedCount': 0, 'invalidCount': 0, 'checks': [], 'errors': [], 'note': NOTE}
    if not isinstance(course, dict):
        report.update(status='invalid', errors=[_issue(None, 'invalid', '课程必须为对象。', code='invalid_course', scope='configuration')])
        return report
    if 'disciplineChecks' not in course or course['disciplineChecks'] == []:
        return report
    rules = course['disciplineChecks']
    if not isinstance(rules, list):
        report.update(status='invalid', errors=[_issue(None, 'invalid', 'disciplineChecks必须为规则数组。', code='invalid_rules', scope='configuration')])
        return report
    report['configuredCount'] = len(rules)
    try:
        targets = _targets(course)
    except RuleInputError as error:
        report.update(status='invalid', errors=[_issue(None, 'invalid', str(error), error.location, error.actual, error.expected, error.code, error.scope)])
        return report
    seen = set()
    for index, rule in enumerate(rules):
        rule_id = rule.get('id') if isinstance(rule, dict) else None
        kind = rule.get('kind') if isinstance(rule, dict) else None
        result = {'id': rule_id if _text(rule_id) else None, 'ruleIndex': index,
                  'kind': kind if isinstance(kind, str) else None, 'status': 'invalid', 'issues': [], 'observations': [],
                  'targetIds': _rule_target_ids(rule, targets) if isinstance(rule, dict) else []}
        try:
            if not isinstance(rule, dict) or not _text(rule_id) or rule_id in seen:
                raise RuleInputError('每条规则需要唯一的非空ID。', actual=rule_id, code='invalid_rule_id')
            seen.add(rule_id)
            if not isinstance(kind, str) or kind not in KINDS:
                raise RuleInputError('未知规则类型；未配置适用检查，不能记为通过。', actual=kind, expected=sorted(KINDS), code='unknown_rule')
            if 'target' not in rule:
                raise RuleInputError('规则必须定位实际课程内容，不能传入复制的数据。', code='missing_target')
            _configuration(rule, targets)
            if kind == 'journal_balance':
                issues, observations = _journal(rule, targets)
            elif kind == 'matrix_shape':
                issues, observations = _matrix(rule, targets)
            else:
                issues, observations = _sum_rule(rule, targets)
            result.update(issues=issues, observations=observations,
                          status='invalid' if any(x['status'] == 'invalid' for x in issues) else 'fail' if issues else 'pass')
        except RuleInputError as error:
            result['issues'] = [_issue(result['id'], 'invalid', str(error), error.location, error.actual, error.expected, error.code, error.scope)]
        except (TypeError, KeyError, ValueError, AttributeError, OverflowError, InvalidOperation, RecursionError) as error:
            result['issues'] = [_issue(result['id'], 'invalid', '规则或目标数据格式无效：' + str(error), code='malformed_data', scope='configuration')]
        report['checks'].append(result)
        report['errors'].extend(result['issues'])
    for key, state in [('passedCount', 'pass'), ('failedCount', 'fail'), ('invalidCount', 'invalid')]:
        report[key] = sum(result['status'] == state for result in report['checks'])
    report['status'] = 'invalid' if report['invalidCount'] else 'fail' if report['failedCount'] else 'pass'
    return report


def validate_discipline_checks(course):
    """Blocking messages for pipeline.validate; inspect the report for details."""
    report = report_discipline_checks(course)
    messages = []
    for issue in report['errors']:
        location = issue['location']
        where = str(location.get('targetId', 'course'))
        if location.get('area'):
            where += '/' + str(location['area']) + '/' + str(location.get('blockPath', []))
        if 'row' in location:
            where += ' row=' + str(location['row'])
        if 'column' in location:
            where += ' column=' + str(location['column'])
        messages.append('disciplineChecks ' + str(issue['ruleId'] or '?') + ' [' + where + ']: ' + issue['message'])
    return messages
