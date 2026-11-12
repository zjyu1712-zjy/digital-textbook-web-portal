import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from grading import validate_grading


def numeric():
    return {'id': 'q', 'parts': [{'fields': [{'id': 'n', 'kind': 'number'}]}],
            'answer': {'status': 'ready'},
            'grading': {'kind': 'numeric', 'rationale': 'Exact count in the source.',
                        'rules': [{'fieldId': 'n', 'expected': 1000, 'tolerance': 0}]}}


class GradingTests(unittest.TestCase):
    def test_valid_numeric_and_self(self):
        self.assertEqual(validate_grading(numeric()), [])
        self.assertEqual(validate_grading({'grading': {'kind': 'self'}}), [])

    def test_numeric_reference_is_required_finite_number(self):
        for value in [None, True, False, '', '1000', math.nan, math.inf, -math.inf, 9007199254740992, 9007199254740993, 1e30, [], {}]:
            q = numeric(); q['grading']['rules'][0]['expected'] = value
            with self.subTest(value=value): self.assertTrue(validate_grading(q))
        q = numeric(); del q['grading']['rules'][0]['expected']
        self.assertTrue(validate_grading(q))

    def test_tolerance_cannot_be_negative_or_non_numeric(self):
        for value in [-1, None, True, '0', math.nan, math.inf, 9007199254740992]:
            q = numeric(); q['grading']['rules'][0]['tolerance'] = value
            with self.subTest(value=value): self.assertTrue(validate_grading(q))
        q = numeric(); del q['grading']['rules'][0]['tolerance']
        self.assertEqual(validate_grading(q), [])

    def test_rule_covers_each_field_once(self):
        q = numeric(); q['grading']['rules'] *= 2
        self.assertTrue(validate_grading(q))
        q = numeric(); q['parts'][0]['fields'].append({'id': 'other', 'kind': 'number'})
        self.assertTrue(validate_grading(q))
        q = numeric(); q['grading']['rules'][0]['fieldId'] = 'missing'
        self.assertTrue(validate_grading(q))

    def test_numeric_does_not_grade_subjective_or_formula_fields(self):
        for kind in ['text', 'formula', 'matrix', 'table', 'journal', 'choice', 'multiple']:
            q = numeric(); q['parts'][0]['fields'][0]['kind'] = kind
            with self.subTest(kind=kind): self.assertTrue(validate_grading(q))

    def test_choice_validates_expected_against_options(self):
        q = numeric(); q['parts'][0]['fields'][0] = {'id': 'n', 'kind': 'choice', 'options': [{'value': 'a', 'label': 'A'}, {'value': 'b', 'label': 'B'}]}
        q['grading'] = {'kind': 'choice', 'rationale': 'Source choice.', 'rules': [{'fieldId': 'n', 'expected': 'a'}]}
        self.assertEqual(validate_grading(q), [])
        for value in [None, True, 0, ['a'], 'c']:
            bad = copy.deepcopy(q); bad['grading']['rules'][0]['expected'] = value
            with self.subTest(value=value): self.assertTrue(validate_grading(bad))
        q['parts'][0]['fields'][0]['kind'] = 'multiple'
        q['grading']['rules'][0]['expected'] = ['a', 'b']
        self.assertEqual(validate_grading(q), [])
        for value in [[], ['a', 'a'], ['a', 'c'], 'a']:
            bad = copy.deepcopy(q); bad['grading']['rules'][0]['expected'] = value
            with self.subTest(value=value): self.assertTrue(validate_grading(bad))

    def test_plain_options_use_string_index_values(self):
        q = numeric(); q['parts'][0]['fields'][0] = {'id': 'n', 'kind': 'choice', 'options': ['A', 'B']}
        q['grading'] = {'kind': 'choice', 'rationale': 'Source choice.', 'rules': [{'fieldId': 'n', 'expected': '0'}]}
        self.assertEqual(validate_grading(q), [])
        q['parts'][0]['fields'][0]['options'] = [{'value': 'a'}, {'value': 'a'}]
        self.assertTrue(validate_grading(q))

    def test_incomplete_or_malformed_rule_cannot_pass(self):
        for g in [None, [], {'kind': 'automatic'}, {'kind': 'numeric', 'rules': []},
                  {'kind': 'numeric', 'rules': [None], 'rationale': 'test'}]:
            q = numeric(); q['grading'] = g
            with self.subTest(grading=g): self.assertTrue(validate_grading(q))
        q = numeric(); q['answer']['status'] = 'pending'
        self.assertTrue(validate_grading(q))


if __name__ == '__main__': unittest.main()
