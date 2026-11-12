"""Source priority and per-task material agreements use synthetic inputs only."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from task_contract import classify, validate_contract


def course():
    return {
        'sources': [
            {'id': 'book', 'role': 'textbook'},
            {'id': 'slides', 'role': 'teacher_slides'},
            {'id': 'outline', 'role': 'outline'},
        ],
        'chapters': [{'id': 'c1'}, {'id': 'c2'}],
        'organization': {
            'mode': 'combined',
            'primarySourceIds': ['book', 'outline'],
            'reason': '第一章教材主导，第二章提纲主导。',
        },
        'taskContract': {
            'version': 1,
            'goal': '理解两章材料，并按已约定的主线复习。',
            'basis': '用户明确指定各章主线与课件用途。',
            'sourceUses': [
                {'sourceId': 'book', 'usage': 'primary', 'chapterIds': ['c1'],
                 'purpose': '按教材顺序展开第一章。'},
                {'sourceId': 'book', 'usage': 'explanation', 'chapterIds': ['c2'],
                 'purpose': '补充提纲涉及概念的定义与条件。'},
                {'sourceId': 'slides', 'usage': 'example', 'chapterIds': ['c1'],
                 'purpose': '补充课堂案例，不改变教材顺序。'},
                {'sourceId': 'slides', 'usage': 'reference', 'chapterIds': ['c2'],
                 'purpose': '仅作原页对照。'},
                {'sourceId': 'outline', 'usage': 'primary', 'chapterIds': ['c2'],
                 'purpose': '逐条组织第二章。'},
            ],
            'chapterPlans': [
                {'chapterId': 'c1', 'mode': 'textbook', 'primarySourceIds': ['book'],
                 'emphasis': '按教材解释定义及条件。'},
                {'chapterId': 'c2', 'mode': 'outline', 'primarySourceIds': ['outline'],
                 'emphasis': '逐条展开提纲，并解释相互关系。'},
            ],
            'pendingMaterials': [{'chapterId': 'c2', 'description': '用户说明后续补习题解析。'}],
        },
    }


class ClassificationTests(unittest.TestCase):
    def test_mixed_materials_without_priority_do_not_choose_slides(self):
        for roles in [('textbook', 'teacher_slides'), ('outline', 'teacher_slides'),
                      ('textbook', 'outline'), ('teacher_slides',)]:
            with self.subTest(roles=roles):
                result = classify([{'id': str(i), 'role': role} for i, role in enumerate(roles)], [])
                self.assertIsNone(result['materialMode'])
                self.assertTrue(result['needsDecision'])

    def test_only_one_textbook_can_use_default(self):
        result = classify([{'id': 'b', 'role': 'textbook'}], ['定义'])
        self.assertEqual(result['materialMode'], 'textbook')
        self.assertEqual(result['primarySourceIds'], ['b'])
        self.assertFalse(result['needsDecision'])
        self.assertTrue(classify([{'role': 'textbook'}, {'role': 'textbook'}], [])['needsDecision'])

    def test_existing_organization_wins_over_file_types_and_legacy_marks(self):
        sources = [{'id': 'b', 'role': 'textbook'},
                   {'id': 'p', 'role': 'teacher_slides', 'primary': True}]
        result = classify(sources, [], {'mode': 'textbook', 'primarySourceIds': ['b']})
        self.assertEqual(result['materialMode'], 'textbook')
        self.assertEqual(result['primarySourceIds'], ['b'])
        self.assertFalse(result['needsDecision'])
        self.assertTrue(result['warnings'])

    def test_explicit_outline_with_slides_is_respected(self):
        result = classify([{'id': 'o', 'role': 'outline'}, {'id': 'p', 'role': 'teacher_slides'}],
                          [], {'mode': 'outline', 'primarySourceIds': ['o']})
        self.assertEqual(result['materialMode'], 'outline')

    def test_legacy_explicit_primary_is_supported_without_becoming_default(self):
        result = classify([{'role': 'teacher_slides', 'primary': True}, {'role': 'textbook'}], [])
        self.assertEqual(result['materialMode'], 'slides')
        self.assertFalse(result['needsDecision'])
        self.assertEqual(result['decisionBasis'], 'legacy-primary')
        self.assertTrue(result['warnings'])

    def test_contract_selects_chapter_specific_plan(self):
        d = course()
        result = classify(d['sources'], [], d['organization'], d['taskContract'], 'c1')
        self.assertEqual(result['materialMode'], 'textbook')
        self.assertEqual(result['primarySourceIds'], ['book'])
        result = classify(d['sources'], [], d['organization'], d['taskContract'], 'c2')
        self.assertEqual(result['materialMode'], 'outline')
        self.assertEqual(result['primarySourceIds'], ['outline'])

    def test_contract_without_global_organization_is_sufficient(self):
        d = course()
        result = classify(d['sources'], [], contract=d['taskContract'])
        self.assertEqual(result['materialMode'], 'combined')
        self.assertEqual(set(result['primarySourceIds']), {'book', 'outline'})
        self.assertFalse(result['needsDecision'])

    def test_conflicting_contract_and_organization_are_not_silently_resolved(self):
        d = course()
        wrong = {'mode': 'slides', 'primarySourceIds': ['slides']}
        result = classify(d['sources'], [], wrong, d['taskContract'])
        self.assertIsNone(result['materialMode'])
        self.assertTrue(result['needsDecision'])
        self.assertTrue(result['errors'])

    def test_unknown_primary_and_missing_chapter_fail_honestly(self):
        d = course()
        self.assertTrue(classify(d['sources'], [], {'mode': 'textbook', 'primarySourceIds': ['gone']})['needsDecision'])
        result = classify(d['sources'], [], d['organization'], d['taskContract'], 'gone')
        self.assertTrue(result['needsDecision'])
        self.assertTrue(result['errors'])

    def test_discipline_detection_stays_independent(self):
        result = classify([{'role': 'textbook'}, {'role': 'teacher_slides'}], ['均衡曲线，矩阵证明'])
        self.assertTrue(result['needsDecision'])
        self.assertEqual(result['disciplines'], ['math', 'models'])

    def test_malformed_inputs_return_errors_instead_of_throwing(self):
        cases = [({'wrong': 'sources'}, [], None, None),
                 ([None, []], [], None, None),
                 ([{'id': []}], [], None, None),
                 ([{'id': 'b', 'role': 'textbook'}], [], [], None),
                 ([{'id': 'b', 'role': 'textbook'}], [], {'mode': [], 'primarySourceIds': [[]]}, None),
                 ([{'id': 'b', 'role': 'textbook'}], [], None, []),
                 ([{'id': 'b', 'role': 'textbook'}], [], None, {'chapterPlans': [None]})]
        for args in cases:
            with self.subTest(args=args):
                result = classify(*args)
                self.assertTrue(result['needsDecision'])
                self.assertTrue(result['errors'])


class ContractValidationTests(unittest.TestCase):
    def test_valid_contract_allows_different_chapter_priorities(self):
        self.assertEqual(validate_contract(course()), [])

    def test_input_is_not_mutated(self):
        d = course(); before = copy.deepcopy(d)
        validate_contract(d)
        classify(d['sources'], [], d['organization'], d['taskContract'])
        self.assertEqual(d, before)

    def test_missing_purpose_goal_basis_and_plan_are_rejected(self):
        for path in [('goal',), ('basis',), ('sourceUses', 0, 'purpose'),
                     ('chapterPlans', 0, 'emphasis')]:
            d = course(); node = d['taskContract']
            for key in path[:-1]: node = node[key]
            node[path[-1]] = ''
            with self.subTest(path=path): self.assertTrue(validate_contract(d))
        d = course(); d['taskContract']['chapterPlans'].pop()
        self.assertTrue(validate_contract(d))

    def test_all_provided_sources_need_an_explicit_use(self):
        d = course(); d['sources'].append({'id': 'extra', 'role': 'solution'})
        self.assertTrue(any('extra' in e for e in validate_contract(d)))

    def test_source_chapter_and_usage_are_validated(self):
        for key, value in [('sourceId', 'unknown'), ('chapterIds', ['unknown']),
                           ('chapterIds', []), ('chapterIds', ['c1', 'c1']),
                           ('usage', 'dominant-because-PPT')]:
            d = course(); d['taskContract']['sourceUses'][0][key] = value
            with self.subTest(key=key, value=value): self.assertTrue(validate_contract(d))

    def test_duplicate_or_conflicting_use_in_one_chapter_is_rejected(self):
        d = course(); row = copy.deepcopy(d['taskContract']['sourceUses'][0])
        row['usage'] = 'reference'; d['taskContract']['sourceUses'].append(row)
        self.assertTrue(validate_contract(d))

    def test_primary_use_and_chapter_plan_must_agree(self):
        d = course(); d['taskContract']['chapterPlans'][0]['primarySourceIds'] = ['slides']
        self.assertTrue(validate_contract(d))
        d = course(); d['taskContract']['sourceUses'][2]['usage'] = 'primary'
        self.assertTrue(validate_contract(d))

    def test_global_primary_union_and_mode_must_agree(self):
        d = course(); d['organization']['primarySourceIds'] = ['book']
        self.assertTrue(validate_contract(d))
        d = course(); d['organization']['mode'] = 'textbook'
        self.assertTrue(validate_contract(d))

    def test_user_mode_is_not_inferred_from_source_file_role(self):
        d = course(); d['taskContract']['chapterPlans'][0]['mode'] = 'combined'
        self.assertEqual(validate_contract(d), [])

    def test_pending_materials_are_optional_but_scoped_when_present(self):
        d = course(); d['taskContract'].pop('pendingMaterials')
        self.assertEqual(validate_contract(d), [])
        d['taskContract']['pendingMaterials'] = [{'chapterId': 'missing', 'description': '待补'}]
        self.assertTrue(validate_contract(d))

    def test_malformed_nested_inputs_report_errors(self):
        mutations = [('sourceUses', None), ('sourceUses', [None]),
                     ('sourceUses', [{'sourceId': [], 'usage': [], 'chapterIds': [[]], 'purpose': {}}]),
                     ('chapterPlans', {}), ('chapterPlans', [None]),
                     ('chapterPlans', [{'chapterId': [], 'mode': {}, 'primarySourceIds': [[]]}]),
                     ('pendingMaterials', [None]), ('version', True)]
        for key, value in mutations:
            d = course(); d['taskContract'][key] = value
            with self.subTest(key=key, value=value): self.assertTrue(validate_contract(d))
        for d in [None, [], {}, {'sources': [None], 'chapters': [[]], 'taskContract': []}]:
            with self.subTest(d=d): self.assertTrue(validate_contract(d))


if __name__ == '__main__':
    unittest.main()
