"""Synthetic source-fusion and review-freshness cases; no private course inputs."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'scripts/review_audit.py'
spec = importlib.util.spec_from_file_location('review_audit', MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def sample():
    course = {
        'schemaVersion': 2, 'id': 'synthetic-fusion', 'version': '1',
        'edition': 'Synthetic edition',
        'organization': {'mode': 'textbook', 'primarySourceIds': ['s1', 's2'],
                         'reason': 'The user selected the textbook sequence.'},
        'sources': [
            {'id': 's1', 'role': 'textbook', 'sha256': 'source-one-v1'},
            {'id': 's2', 'role': 'textbook', 'sha256': 'source-two-v1'},
        ],
        'taskContract': {
            'version': 1, 'goal': 'Explain observation records.', 'basis': 'Synthetic user request.',
            'sourceUses': [
                {'sourceId': 's1', 'usage': 'primary', 'chapterIds': ['ch1'], 'purpose': 'Label fields.'},
                {'sourceId': 's2', 'usage': 'primary', 'chapterIds': ['ch2'], 'purpose': 'Record comparison.'},
            ],
            'chapterPlans': [
                {'chapterId': 'ch1', 'mode': 'textbook', 'primarySourceIds': ['s1'], 'emphasis': 'Identity.'},
                {'chapterId': 'ch2', 'mode': 'textbook', 'primarySourceIds': ['s2'], 'emphasis': 'Differences.'},
            ], 'pendingMaterials': [],
        },
        'chapters': [
            {'id': 'ch1', 'title': 'Labels', 'sections': [
                {'id': 'k1', 'title': 'Fields', 'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
                 'blocks': [{'type': 'paragraph', 'text': 'A date identifies the observation batch.'}]},
                {'id': 'recap1', 'title': 'Review', 'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
                 'blocks': [{'type': 'list', 'items': ['Keep the date and the observation identifier.']}]},
            ]},
            {'id': 'ch2', 'title': 'Comparison', 'sections': [
                {'id': 'k2', 'title': 'Conflict', 'sourceRefs': [{'sourceId': 's2', 'locator': 'p2'}],
                 'blocks': [{'type': 'paragraph', 'text': 'Keep conflicting records until verification.'}]},
            ]},
        ], 'questions': [],
        'coverage': [
            {'sourceItemId': 'i1', 'targets': ['k1', 'recap1'], 'status': 'covered'},
            {'sourceItemId': 'i2', 'targets': ['k2'], 'status': 'covered'},
        ],
        'learningMap': [
            {'sourceItemId': 'i1', 'disposition': 'integrated', 'explanationTargets': ['k1'],
             'summaryTargets': ['recap1'], 'emphasisTargets': [],
             'summaryNote': '', 'emphasisNote': 'The recap reinforces identity fields.',
             'evidence': 'The source date requirement is explained as a batch identifier.'},
            {'sourceItemId': 'i2', 'disposition': 'integrated', 'explanationTargets': ['k2'],
             'summaryTargets': [], 'emphasisTargets': [],
             'summaryNote': 'The short paragraph also states the complete takeaway.',
             'emphasisNote': 'No separate classroom weighting was provided.',
             'evidence': 'The paragraph explains why conflicting identifiers are retained.'},
        ], 'semanticReviews': [],
    }
    inventory = {'source': 'Synthetic independent two-page source.', 'items': [
        {'id': 'i1', 'sourceId': 's1', 'locator': 'p1', 'kind': 'definition', 'expectedParts': []},
        {'id': 'i2', 'sourceId': 's2', 'locator': 'p2', 'kind': 'lesson', 'expectedParts': []},
    ]}
    return course, inventory


def reviewed(course, inventory, target_ids=None):
    """Author-asserted synthetic fixture review, deliberately outside production helpers."""
    ids = target_ids or ['k1', 'recap1', 'k2']
    record = {'targetIds': ids, 'reviewer': 'synthetic-fixture-author',
              'method': 'Read the tiny synthetic source and compare the explanation.',
              'evidence': 'Synthetic source i1 and i2.', 'result': 'pass',
              'binding': {'version': 1,
                          'fingerprint': audit.review_fingerprint(course, inventory, ids)}}
    course['semanticReviews'].append(record)
    return record


class LearningMapTests(unittest.TestCase):
    def test_valid_integrated_explanation_and_summary(self):
        d, inv = sample()
        self.assertEqual(audit.validate_learning_map(d, inv), [])

    def test_image_title_and_formula_alone_are_not_teaching(self):
        for block in [{'type': 'image', 'path': 'page.png', 'alt': 'original page'},
                      {'type': 'heading', 'text': 'Already included'},
                      {'type': 'math', 'tex': 'x=1'}]:
            with self.subTest(block=block):
                d, inv = sample()
                d['chapters'][0]['sections'][0]['blocks'] = [block]
                self.assertTrue(audit.validate_learning_map(d, inv))

    def test_nested_prose_and_inline_formula_are_teaching(self):
        d, inv = sample()
        d['chapters'][0]['sections'][0]['blocks'] = [{'type': 'details', 'title': 'Explanation',
            'blocks': [{'type': 'paragraph', 'runs': [
                {'type': 'text', 'text': 'When the count is '}, {'type': 'math', 'tex': 'n=1'},
                {'type': 'text', 'text': ', the observation is unique.'}]}]}]
        self.assertEqual(audit.validate_learning_map(d, inv), [])

    def test_summary_and_emphasis_need_location_or_specific_note(self):
        for prefix in ['summary', 'emphasis']:
            d, inv = sample()
            d['learningMap'][0][prefix + 'Targets'] = []
            d['learningMap'][0][prefix + 'Note'] = ' '
            self.assertTrue(audit.validate_learning_map(d, inv))

    def test_unknown_duplicate_missing_and_uncovered_items_fail(self):
        for mutation in [lambda d: d['learningMap'].append(copy.deepcopy(d['learningMap'][0])),
                         lambda d: d['learningMap'].pop(),
                         lambda d: d['learningMap'][0].update(sourceItemId='missing'),
                         lambda d: d['learningMap'][0].update(summaryTargets=['unknown']),
                         lambda d: d['learningMap'][0].update(summaryTargets=['k2']),
                         lambda d: d['learningMap'][0].update(disposition='pending')]:
            d, inv = sample()
            mutation(d)
            self.assertTrue(audit.validate_learning_map(d, inv))

    def test_reference_only_requires_explicit_reference_use(self):
        d, inv = sample()
        row = d['learningMap'][0]
        row.update(disposition='reference-only', explanationTargets=['k1', 'recap1'], summaryTargets=[],
                   summaryNote='Original page only, as requested.', emphasisNote='Not a teaching priority.')
        d['chapters'][0]['sections'][0]['blocks'] = [{'type': 'image', 'path': 'page.png', 'alt': 'page'}]
        self.assertTrue(audit.validate_learning_map(d, inv))
        d['taskContract']['sourceUses'][0]['usage'] = 'reference'
        self.assertEqual(audit.validate_learning_map(d, inv), [])

    def test_reference_source_cannot_silently_become_integrated(self):
        d, inv = sample()
        d['taskContract']['sourceUses'][0]['usage'] = 'reference'
        self.assertTrue(audit.validate_learning_map(d, inv))

    def test_reference_only_cannot_hide_another_coverage_location(self):
        d, inv = sample()
        d['taskContract']['sourceUses'][0]['usage'] = 'reference'
        row = d['learningMap'][0]
        row.update(disposition='reference-only', explanationTargets=['k1'], summaryTargets=[])
        # recap1 remains covered but was omitted from the reference-only declaration.
        self.assertTrue(audit.validate_learning_map(d, inv))
        row['explanationTargets'].append('recap1')
        self.assertEqual(audit.validate_learning_map(d, inv), [])

    def test_reference_only_checks_every_covered_chapter_use(self):
        d, inv = sample()
        d['taskContract']['sourceUses'][0]['usage'] = 'reference'
        d['taskContract']['sourceUses'].append(
            {'sourceId': 's1', 'usage': 'primary', 'chapterIds': ['ch2'], 'purpose': 'Main teaching.'})
        d['chapters'][1]['sections'][0]['sourceRefs'].append({'sourceId': 's1', 'locator': 'p1'})
        d['coverage'][0]['targets'].append('k2')
        row = d['learningMap'][0]
        row.update(disposition='reference-only', explanationTargets=['k1', 'recap1', 'k2'], summaryTargets=[])
        self.assertTrue(audit.validate_learning_map(d, inv))

    def test_legacy_map_optional(self):
        d, inv = sample()
        d['schemaVersion'] = 1
        del d['learningMap']
        self.assertEqual(audit.validate_learning_map(d, inv), [])

    def test_malformed_map_returns_errors_not_traceback(self):
        for value in [None, 'map', [None], [{'sourceItemId': 'i1', 'explanationTargets': {}}]]:
            d, inv = sample()
            d['learningMap'] = value
            self.assertTrue(audit.validate_learning_map(d, inv))

    def test_malformed_source_and_usage_are_reported_without_traceback(self):
        for field in ['source', 'usage']:
            d, inv = sample()
            if field == 'source':
                inv['items'][0]['sourceId'] = ['s1']
            else:
                d['taskContract']['sourceUses'][0]['usage'] = ['primary']
            self.assertTrue(audit.validate_learning_map(d, inv))


class FingerprintTests(unittest.TestCase):
    def test_stable_order_and_no_mutation(self):
        d, inv = sample()
        before = copy.deepcopy((d, inv))
        a = audit.review_fingerprint(d, inv, ['k1', 'recap1'])
        self.assertEqual(a, audit.review_fingerprint(d, inv, ['recap1', 'k1']))
        self.assertEqual((d, inv), before)

    def test_teaching_source_inventory_contract_and_map_changes_invalidate(self):
        mutations = [
            lambda d, inv: d['chapters'][0]['sections'][0]['blocks'][0].update(text='A different explanation.'),
            lambda d, inv: d['chapters'][0]['sections'][1]['blocks'][0].update(items=['Different summary.']),
            lambda d, inv: d['sources'][0].update(sha256='source-one-v2'),
            lambda d, inv: inv['items'][0].update(locator='p2 corrected'),
            lambda d, inv: d['taskContract']['sourceUses'][0].update(purpose='Different learning purpose.'),
            lambda d, inv: d['learningMap'][0].update(emphasisNote='Different emphasis.'),
            lambda d, inv: d['organization'].update(reason='Changed ordering decision.'),
        ]
        for change in mutations:
            d, inv = sample()
            before = audit.review_fingerprint(d, inv, ['k1'])
            change(d, inv)
            self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['k1']))

    def test_unrelated_source_and_chapter_do_not_invalidate(self):
        d, inv = sample()
        before = audit.review_fingerprint(d, inv, ['k1'])
        d['sources'][1]['sha256'] = 'source-two-v2'
        d['chapters'][1]['sections'][0]['blocks'][0]['text'] = 'Unrelated revision.'
        self.assertEqual(before, audit.review_fingerprint(d, inv, ['k1']))

    def test_packaging_fields_are_ignored_but_image_path_is_not(self):
        d, inv = sample()
        d['chapters'][0]['sections'][0]['blocks'].append({'type': 'image', 'path': 'figure.png', 'alt': 'figure'})
        before = audit.review_fingerprint(d, inv, ['k1'])
        d['chapters'][0]['sections'][0]['blocks'][-1]['data'] = 'data:image/png;base64,AAAA'
        d['validation'] = {'counts': {'synthetic': 2}}
        d['sourceInventory'] = copy.deepcopy(inv)
        self.assertEqual(before, audit.review_fingerprint(d, inv, ['k1']))
        d['chapters'][0]['sections'][0]['blocks'][-1]['path'] = 'different.png'
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['k1']))

    def test_replaced_image_digest_is_bound_even_at_same_path(self):
        d, inv = sample()
        image = {'type': 'image', 'path': 'figure.png', 'alt': 'figure', 'sha256': 'a' * 64}
        d['chapters'][0]['sections'][0]['blocks'].append(image)
        before = audit.review_fingerprint(d, inv, ['k1'])
        image['sha256'] = 'b' * 64
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['k1']))

    def test_question_answer_and_input_conditions_are_bound(self):
        d, inv = sample()
        d['questions'] = [{'id': 'q1', 'chapterIds': ['ch1'], 'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
                          'prompt': [{'type': 'paragraph', 'text': 'Compare the two records.'}],
                          'parts': [{'id': 'a', 'fields': [{'id': 'response', 'kind': 'text', 'label': 'Explain.'}]}],
                          'answer': {'version': '1', 'blocks': [{'type': 'paragraph', 'text': 'Keep both records.'}]}}]
        before = audit.review_fingerprint(d, inv, ['q1'])
        d['questions'][0]['answer']['blocks'][0]['text'] = 'Replace both records.'
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['q1']))
        d['questions'][0]['answer']['blocks'][0]['text'] = 'Keep both records.'
        d['questions'][0]['parts'][0]['fields'][0]['label'] = 'Choose one record.'
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['q1']))

    def test_shared_exam_conditions_and_membership_are_bound_to_questions(self):
        d, inv = sample()
        d['questions'] = [{'id': 'q1', 'chapterIds': ['ch1'], 'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
                          'prompt': [{'type': 'paragraph', 'text': 'Compare the two records.'}]}]
        d['exams'] = [{'id': 'exam1', 'title': 'Synthetic paper', 'version': '1', 'questionIds': ['q1'],
                       'instructions': [{'type': 'paragraph', 'text': 'Assume all records belong to one batch.'}]}]
        before = audit.review_fingerprint(d, inv, ['q1'])
        d['exams'][0]['instructions'][0]['text'] = 'Assume the records come from different batches.'
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['q1']))
        d['exams'][0]['instructions'][0]['text'] = 'Assume all records belong to one batch.'
        d['exams'][0]['questionIds'] = []
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['q1']))

    def test_exam_instruction_sources_are_also_bound(self):
        d, inv = sample()
        d['questions'] = [{'id': 'q1', 'chapterIds': ['ch1'], 'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
                          'prompt': [{'type': 'paragraph', 'text': 'Compare the two records.'}]}]
        d['exams'] = [{'id': 'exam1', 'questionIds': ['q1'], 'sourceRefs': [{'sourceId': 's2', 'locator': 'paper rules'}],
                       'instructions': [{'type': 'paragraph', 'text': 'Use the stated observation convention.'}]}]
        before = audit.review_fingerprint(d, inv, ['q1'])
        d['sources'][1]['sha256'] = 'rules-source-v2'
        self.assertNotEqual(before, audit.review_fingerprint(d, inv, ['q1']))

    def test_missing_or_invalid_target_rejected(self):
        d, inv = sample()
        for ids in [[], ['unknown'], ['k1', 'k1'], 'k1', [None]]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                audit.review_fingerprint(d, inv, ids)


class AuditTests(unittest.TestCase):
    def test_unreviewed_and_current_review(self):
        d, inv = sample()
        self.assertEqual(audit.audit_reviews(d, inv)['status'], 'needs-review')
        reviewed(d, inv)
        state = audit.audit_reviews(d, inv)
        self.assertEqual(state['status'], 'pass')
        self.assertEqual(state['errors'], [])
        self.assertTrue(all(x['status'] == 'fresh' for x in state['targets']))

    def test_changed_explanation_makes_old_review_stale(self):
        d, inv = sample()
        reviewed(d, inv)
        d['chapters'][0]['sections'][0]['blocks'][0]['text'] = 'Completely replaced teaching.'
        state = audit.audit_reviews(d, inv)
        self.assertEqual(state['status'], 'stale')
        self.assertTrue(state['errors'])
        self.assertNotIn('fresh', {x['status'] for x in state['targets']})

    def test_pending_integration_cannot_be_certified_by_fresh_review(self):
        d, inv = sample()
        d['learningMap'][0]['disposition'] = 'pending'
        reviewed(d, inv)
        result = audit.audit_reviews(d, inv)
        self.assertEqual(result['status'], 'needs-review')
        self.assertTrue(result['errors'])

    def test_only_reviewed_targets_pass(self):
        d, inv = sample()
        reviewed(d, inv, ['k1'])
        state = audit.audit_reviews(d, inv)
        statuses = {x['targetId']: x['status'] for x in state['targets']}
        self.assertEqual(statuses['k1'], 'fresh')
        self.assertEqual(statuses['recap1'], 'unreviewed')
        self.assertEqual(state['status'], 'needs-review')

    def test_fresh_rereview_can_follow_old_stale_record(self):
        d, inv = sample()
        reviewed(d, inv)
        d['chapters'][0]['sections'][0]['blocks'][0]['text'] += ' Reviewed revision.'
        reviewed(d, inv)
        self.assertEqual(audit.audit_reviews(d, inv)['status'], 'pass')

    def test_current_failure_or_pending_blocks_current_pass(self):
        for result, expected in [('fail', 'failed'), ('pending', 'pending')]:
            d, inv = sample()
            first = reviewed(d, inv)
            conflicting = copy.deepcopy(first)
            conflicting['result'] = result
            d['semanticReviews'].append(conflicting)
            state = audit.audit_reviews(d, inv)
            self.assertNotEqual(state['status'], 'pass')
            self.assertTrue(all(x['status'] == expected for x in state['targets']))

    def test_unbound_pass_cannot_claim_current_assurance(self):
        d, inv = sample()
        record = reviewed(d, inv)
        del record['binding']
        self.assertEqual(audit.audit_reviews(d, inv)['status'], 'needs-review')

    def test_legacy_unbound_review_stays_unverified(self):
        d, inv = sample()
        record = reviewed(d, inv)
        d['schemaVersion'] = 1
        del record['binding']
        self.assertEqual(audit.audit_reviews(d, inv)['status'], 'legacy-unverified')

    def test_legacy_existing_binding_still_checked(self):
        d, inv = sample()
        d['schemaVersion'] = 1
        reviewed(d, inv)
        self.assertTrue(all(x['status'] == 'fresh' for x in audit.audit_reviews(d, inv)['targets']))
        d['chapters'][0]['sections'][0]['blocks'][0]['text'] = 'Changed.'
        result = audit.audit_reviews(d, inv)
        self.assertEqual(result['status'], 'legacy-unverified')
        self.assertTrue(result['errors'])
        self.assertTrue(all(x['status'] == 'stale' for x in result['targets']))

    def test_unknown_review_target_and_bad_binding_are_not_accepted(self):
        for mutate in [lambda r: r.update(targetIds=['unknown']),
                       lambda r: r.update(binding={'version': 1, 'fingerprint': 'not-a-hash'}),
                       lambda r: r.update(reviewer=' ')]:
            d, inv = sample()
            r = reviewed(d, inv)
            mutate(r)
            result = audit.audit_reviews(d, inv)
            self.assertNotEqual(result['status'], 'pass')
            self.assertTrue(result['errors'])

    def test_audit_never_writes_or_creates_pass(self):
        d, inv = sample()
        before = json.dumps((d, inv), sort_keys=True)
        audit.audit_reviews(d, inv)
        self.assertEqual(json.dumps((d, inv), sort_keys=True), before)
        self.assertEqual(d['semanticReviews'], [])


if __name__ == '__main__':
    unittest.main()
