"""Validate declared automatic rules; never infer grading for subjective answers."""
import math


def _finite(value):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and not (value == math.trunc(value) and abs(value) > 9007199254740991))
    except OverflowError:
        return False


def validate_grading(question):
    """Require complete, typed rules so malformed data cannot produce a pass."""
    if not isinstance(question, dict):
        return ['grading: question must be an object']
    label = str(question.get('id', 'question')) + ': grading '
    grading = question.get('grading', {'kind': 'self'})
    if not isinstance(grading, dict):
        return [label + 'must be an object']
    kind = grading.get('kind')
    if kind == 'self':
        return []
    if kind not in ('numeric', 'choice'):
        return [label + 'unsupported kind; use self assessment']
    errors = []
    if not isinstance(question.get('answer'), dict) or question['answer'].get('status') != 'ready':
        errors.append(label + 'requires a ready reference answer')
    if not isinstance(grading.get('rationale'), str) or not grading['rationale'].strip():
        errors.append(label + 'requires a rationale')
    fields = {}
    parts = question.get('parts')
    if not isinstance(parts, list):
        return errors + [label + 'requires fields']
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get('fields'), list):
            errors.append(label + 'invalid fields')
            continue
        for field in part['fields']:
            if not isinstance(field, dict) or not isinstance(field.get('id'), str) or not field['id']:
                errors.append(label + 'invalid field ID')
                continue
            if field['id'] in fields:
                errors.append(label + 'duplicate field ID ' + field['id'])
            fields[field['id']] = field
    rules = grading.get('rules')
    if not isinstance(rules, list) or not rules:
        return errors + [label + 'requires nonempty rules']
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get('fieldId'), str):
            errors.append(label + 'invalid rule')
            continue
        field_id = rule['fieldId']
        if field_id in seen:
            errors.append(label + 'duplicate rule for ' + field_id)
        seen.add(field_id)
        field = fields.get(field_id)
        if field is None:
            errors.append(label + 'unknown field ' + field_id)
            continue
        if kind == 'numeric':
            if field.get('kind') not in ('number', 'fill'):
                errors.append(label + 'numeric requires number/fill field ' + field_id)
            if not _finite(rule.get('expected')):
                errors.append(label + 'expected must be finite with integers inside the safe range for ' + field_id)
            if 'tolerance' in rule and (not _finite(rule['tolerance']) or rule['tolerance'] < 0):
                errors.append(label + 'tolerance must be finite, nonnegative and within the safe integer range for ' + field_id)
        else:
            if field.get('kind') not in ('choice', 'multiple'):
                errors.append(label + 'choice requires choice/multiple field ' + field_id)
                continue
            options = field.get('options')
            if not isinstance(options, list) or not options:
                errors.append(label + 'choice options missing for ' + field_id)
                continue
            values = [o.get('value') if isinstance(o, dict) else str(i) if isinstance(o, str) else None
                      for i, o in enumerate(options)]
            if any(not isinstance(v, str) or not v for v in values) or len(set(v for v in values if isinstance(v, str))) != len(values):
                errors.append(label + 'choice option values must be unique strings for ' + field_id)
                continue
            expected = rule.get('expected')
            if field['kind'] == 'choice':
                if not isinstance(expected, str) or expected not in values:
                    errors.append(label + 'expected must name an option for ' + field_id)
            elif (not isinstance(expected, list) or not expected
                  or any(not isinstance(v, str) or v not in values for v in expected)
                  or len(set(v for v in expected if isinstance(v, str))) != len(expected)):
                errors.append(label + 'expected must contain unique options for ' + field_id)
    if not fields or set(fields) != seen:
        errors.append(label + 'must cover every answer field exactly once; use self for mixed subjective answers')
    return list(dict.fromkeys(errors))
