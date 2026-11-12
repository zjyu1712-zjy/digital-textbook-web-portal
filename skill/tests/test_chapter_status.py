"""Evidence must remain scoped and become stale when its dependencies change."""
import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import chapter_status as status
from test_review_audit import sample, reviewed


class ChapterStatusTests(unittest.TestCase):
    def setUp(self):
        self.course, self.inventory = sample()
        self.course['scope'] = {'description': 'Synthetic chapters', 'completeness': 'excerpt'}
        reviewed(self.course, self.inventory)

    def rows(self):
        return {r['chapterId']: r for r in status.chapter_status(self.course, self.inventory)['chapters']}

    def record(self, cid='ch1', kind='offline', ids=None, result='pass'):
        r = {'chapterId': cid, 'kind': kind, 'result': result,
             'reviewer': 'fixture-browser-runner', 'method': 'Open the declared targets offline.',
             'evidence': 'Synthetic test fixture only; no real user content.',
             'checkedAt': '2026-11-12T08:00:00+08:00',
             'targetIds': ids if ids is not None else ['k1', 'recap1'],
             'checks': ['chapter-open', 'navigation'], 'artifactSHA256': 'a' * 64,
             'binding': status.chapter_binding(self.course, self.inventory, cid)}
        self.course.setdefault('chapterChecks', []).append(r)
        return r

    def test_reviewed_content_does_not_invent_browser_or_sampling_pass(self):
        before = copy.deepcopy(self.course)
        c = self.rows()['ch1']
        self.assertEqual(c['content']['status'], 'mapped')
        self.assertEqual(c['review']['status'], 'current')
        self.assertEqual(c['independent']['status'], 'not-reviewed')
        self.assertEqual(c['verification']['offline']['status'], 'not-verified')
        self.assertEqual(c['verification']['visual']['status'], 'not-verified')
        self.assertEqual(before, self.course)

    def test_partial_verified_scope_does_not_certify_whole_chapter(self):
        self.record(ids=['k1'])
        r = self.rows()
        self.assertEqual(r['ch1']['verification']['offline']['status'], 'partial')
        self.assertEqual(r['ch1']['verification']['offline']['verifiedCount'], 1)
        self.assertEqual(r['ch2']['verification']['offline']['status'], 'not-verified')
        self.assertEqual(r['ch1']['verification']['visual']['status'], 'not-verified')

    def test_explicit_complete_scope_and_visual_are_separate(self):
        self.record()
        self.record(kind='visual', ids=['k1'])
        c = self.rows()['ch1']
        self.assertEqual(c['verification']['offline']['status'], 'pass')
        self.assertEqual(c['verification']['visual']['status'], 'partial')

    def test_content_source_task_and_inventory_changes_expire_evidence(self):
        mutations = [
            lambda c, i: c['chapters'][0]['sections'][0]['blocks'][0].update(text='Changed lesson.'),
            lambda c, i: c['sources'][0].update(sha256='changed-source'),
            lambda c, i: c['taskContract'].update(goal='Different user purpose'),
            lambda c, i: i['items'][0].update(locator='new page'),
            lambda c, i: c['chapters'][0].update(title='Changed title'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.setUp(); self.record(); mutate(self.course, self.inventory)
                self.assertEqual(self.rows()['ch1']['verification']['offline']['status'], 'stale')

    def test_renderer_changes_expire_old_verification(self):
        self.record()
        with patch.object(status, 'renderer_fingerprint', return_value='f' * 64):
            self.assertEqual(self.rows()['ch1']['verification']['offline']['status'], 'stale')

    def test_title_and_shared_navigation_changes_expire_visual_evidence(self):
        self.record(kind='visual')
        self.course['title'] = 'A different book title'
        self.assertEqual(self.rows()['ch1']['verification']['visual']['status'], 'stale')
        self.record(kind='visual')
        self.course['chapters'][1]['title'] = 'Changed sidebar label'
        self.assertEqual(self.rows()['ch1']['verification']['visual']['status'], 'stale')

    def test_visible_review_result_change_expires_chapter_verification(self):
        self.record(kind='visual')
        self.course['semanticReviews'][0]['result'] = 'fail'
        self.assertEqual(self.rows()['ch1']['verification']['visual']['status'], 'stale')

    def test_other_chapter_content_change_expires_shared_navigation_evidence(self):
        self.record(kind='visual')
        self.course['chapters'][1]['sections'][0]['blocks'][0]['text'] = 'Changed shared-scope learning content.'
        self.assertEqual(self.rows()['ch1']['verification']['visual']['status'], 'stale')

    def test_independent_review_change_is_bound_but_verification_records_are_not(self):
        before = status.chapter_binding(self.course, self.inventory, 'ch1')
        self.course['independentReview'] = {'required': True, 'records': []}
        after = status.chapter_binding(self.course, self.inventory, 'ch1')
        self.assertNotEqual(before, after)
        self.record()
        self.course['chapterChecks'][0]['evidence'] = 'A more specific verification note.'
        self.assertEqual(after, status.chapter_binding(self.course, self.inventory, 'ch1'))

    def test_fresh_review_binding_does_not_hide_invalid_integration(self):
        self.course['learningMap'][0]['summaryTargets'] = []
        self.course['learningMap'][0]['summaryNote'] = ''
        reviewed(self.course, self.inventory)
        report = status.chapter_status(self.course, self.inventory)
        c = report['chapters'][0]
        self.assertNotEqual(c['content']['status'], 'mapped')
        self.assertNotEqual(c['review']['status'], 'current')
        self.assertTrue(report['errors'])

    def test_malformed_mapping_contract_and_chapter_ids_report_invalid(self):
        for mutate in [lambda c, i: c['coverage'][0].update(sourceItemId=['i1']),
                       lambda c, i: i['items'][0].update(chapterIds=[['ch1']]),
                       lambda c, i: c.update(taskContract=None)]:
            with self.subTest(mutate=mutate):
                self.setUp(); mutate(self.course, self.inventory)
                self.inventory['items'].append({'id': 'missing', 'sourceId': 's1', 'locator': 'p9'})
                report = status.chapter_status(self.course, self.inventory)
                self.assertEqual(report['status'], 'invalid')
                self.assertTrue(report['errors'])

    def test_reference_page_is_not_required_to_be_rewritten_as_teaching(self):
        self.course['sources'].append({'id': 's3', 'role': 'reference', 'sha256': 'source-three'})
        self.course['taskContract']['sourceUses'].append({'sourceId': 's3', 'usage': 'reference',
            'chapterIds': ['ch1'], 'purpose': 'Keep the original page for comparison.'})
        self.course['chapters'][0]['sections'].append({'id': 'page-only', 'title': 'Reference',
            'sourceRefs': [{'sourceId': 's3', 'locator': 'p3'}],
            'blocks': [{'type': 'image', 'path': 'page.png', 'alt': 'Original reference page', 'sha256': 'a' * 64}]})
        self.inventory['items'].append({'id': 'i3', 'sourceId': 's3', 'locator': 'p3', 'kind': 'reference'})
        self.course['coverage'].append({'sourceItemId': 'i3', 'targets': ['page-only'], 'status': 'covered'})
        self.course['learningMap'].append({'sourceItemId': 'i3', 'disposition': 'reference-only',
            'explanationTargets': ['page-only'], 'summaryTargets': [], 'emphasisTargets': [],
            'evidence': 'Original page is retained under the reference-only user agreement.'})
        c = self.rows()['ch1']['content']
        self.assertEqual(c['status'], 'mapped')
        self.assertNotIn('page-only', c['emptyTargetIds'])

    def test_adding_evidence_does_not_change_the_content_binding(self):
        b = status.chapter_binding(self.course, self.inventory, 'ch1')
        self.record()
        self.course['acceptance'] = [{'type': 'paragraph', 'text': 'Evidence added later.'}]
        self.course['validation'] = {'derived': 'not source content'}
        self.assertEqual(b, status.chapter_binding(self.course, self.inventory, 'ch1'))

    def test_current_fail_or_pending_cannot_be_overruled_by_pass(self):
        for result, expected in [('fail', 'failed'), ('pending', 'pending')]:
            with self.subTest(result=result):
                self.setUp(); self.record(result=result); self.record()
                self.assertEqual(self.rows()['ch1']['verification']['offline']['status'], expected)

    def test_reverification_replaces_stale_effect_but_retains_history(self):
        self.record(result='fail')
        self.course['chapters'][0]['sections'][0]['blocks'][0]['text'] = 'Repaired content.'
        self.record()
        c = self.rows()['ch1']['verification']['offline']
        self.assertEqual(c['status'], 'pass')
        self.assertEqual(c['staleRecords'], 1)
        self.assertEqual(len(self.course['chapterChecks']), 2)

    def test_missing_source_item_is_not_dropped_from_chapter_count(self):
        self.inventory['items'].append({'id': 'forgotten', 'sourceId': 's1', 'locator': 'p1/extra'})
        c = self.rows()['ch1']['content']
        self.assertEqual(c['status'], 'partial')
        self.assertIn('forgotten', c['missingItemIds'])

    def test_completely_unassigned_item_keeps_scope_uncertain(self):
        self.course['sources'].append({'id': 's3'})
        self.inventory['items'].append({'id': 'forgotten', 'sourceId': 's3', 'locator': 'p3'})
        report = status.chapter_status(self.course, self.inventory)
        self.assertEqual(report['unassignedItems'], ['forgotten'])
        self.assertTrue(all(c['content']['status'] != 'mapped' for c in report['chapters']))
        self.assertTrue(report['errors'])

    def test_old_schema_keeps_review_unverified(self):
        self.course['schemaVersion'] = 1
        self.assertEqual(self.rows()['ch1']['review']['status'], 'legacy-unverified')
        self.assertEqual(status.validate_chapter_checks(self.course, self.inventory), [])

    def test_invalid_records_are_rejected_instead_of_counted(self):
        for field, value in [('targetIds', ['k2']), ('targetIds', ['k1', 'k1']),
                             ('checks', []), ('artifactSHA256', 'not-a-hash'),
                             ('checkedAt', '2026-11-12'), ('binding', {}),
                             ('reviewer', ''), ('result', 'yes')]:
            with self.subTest(field=field):
                self.setUp(); self.record()[field] = value
                self.assertTrue(status.validate_chapter_checks(self.course, self.inventory))
                self.assertEqual(self.rows()['ch1']['verification']['offline']['status'], 'invalid')

    def test_unknown_chapter_and_nonarray_are_validation_errors(self):
        self.record()['chapterId'] = 'missing'
        self.assertTrue(status.validate_chapter_checks(self.course, self.inventory))
        self.course['chapterChecks'] = None
        self.assertTrue(status.validate_chapter_checks(self.course, self.inventory))

    def test_invalid_source_links_can_be_reported_without_crashing(self):
        self.course['coverage'][0]['targets'].append('missing')
        report = status.chapter_status(self.course, self.inventory)
        self.assertEqual(report['chapters'][0]['content']['status'], 'partial')

    def test_empty_chapter_never_receives_validated_state(self):
        self.course['chapters'].append({'id': 'ch3', 'title': 'Later chapter', 'sections': []})
        c = self.rows()['ch3']
        self.assertEqual(c['content']['status'], 'empty')
        self.assertEqual(c['verification']['offline']['status'], 'not-verified')
        with self.assertRaises(ValueError):
            status.chapter_binding(self.course, self.inventory, 'ch3')


if __name__ == '__main__':
    unittest.main()
