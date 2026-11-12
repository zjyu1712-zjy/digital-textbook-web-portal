"""Learning ranges must follow real scoped coverage, reviews and missing content."""
import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import chapter_status as status
from test_review_audit import sample, reviewed


def course_with_chapters(count=7):
    course, inventory = sample()
    course['scope'] = {'completeness': 'excerpt', 'description': 'Only the supplied chapters.'}
    for n in range(3, count + 1):
        cid, sid, tid, iid = 'ch' + str(n), 's' + str(n), 'k' + str(n), 'i' + str(n)
        course['sources'].append({'id': sid, 'role': 'textbook', 'sha256': 'source-' + str(n)})
        course['organization']['primarySourceIds'].append(sid)
        course['taskContract']['sourceUses'].append({'sourceId': sid, 'usage': 'primary', 'chapterIds': [cid], 'purpose': 'Learning.'})
        course['taskContract']['chapterPlans'].append({'chapterId': cid, 'mode': 'textbook', 'primarySourceIds': [sid], 'emphasis': 'Record.'})
        course['chapters'].append({'id': cid, 'title': 'Included chapter ' + str(n), 'sections': [
            {'id': tid, 'title': 'Lesson', 'sourceRefs': [{'sourceId': sid, 'locator': 'p1'}],
             'blocks': [{'type': 'paragraph', 'text': 'Keep the observation and its date.'}]}]})
        inventory['items'].append({'id': iid, 'sourceId': sid, 'locator': 'p1', 'kind': 'lesson'})
        course['coverage'].append({'sourceItemId': iid, 'targets': [tid], 'status': 'covered'})
        course['learningMap'].append({'sourceItemId': iid, 'disposition': 'integrated', 'explanationTargets': [tid],
            'summaryTargets': [], 'summaryNote': 'The paragraph gives the summary.', 'emphasisTargets': [],
            'emphasisNote': 'Keep the observation.', 'evidence': 'Synthetic source is explained.'})
    rereview(course, inventory)
    return course, inventory


def rereview(course, inventory):
    course['semanticReviews'] = []
    for chapter in course['chapters']:
        for section in chapter['sections']:
            if section.get('id', '').startswith('reference'):
                continue
            reviewed(course, inventory, [section['id']])
    for question in course.get('questions', []):
        reviewed(course, inventory, [question['id']])


def leave_pending(course, inventory, numbers):
    for n in numbers:
        cid, iid = 'ch' + str(n), 'i' + str(n)
        chapter = next(c for c in course['chapters'] if c['id'] == cid)
        chapter['sections'] = []
        chapter['pending'] = {'reason': 'The source pages for this chapter are not yet supplied.'}
        cover = next(c for c in course['coverage'] if c['sourceItemId'] == iid)
        cover.update(status='pending', targets=[])
        mapped = next(c for c in course['learningMap'] if c['sourceItemId'] == iid)
        mapped.update(disposition='pending', explanationTargets=[], summaryTargets=[], emphasisTargets=[])
    rereview(course, inventory)


class UsableChapterTests(unittest.TestCase):
    def setUp(self):
        self.course, self.inventory = course_with_chapters()

    def report(self):
        return status.chapter_status(self.course, self.inventory)

    def test_complete_learning_content_does_not_claim_browser_acceptance(self):
        before = copy.deepcopy(self.course)
        report = self.report()
        self.assertEqual(report['learningRange']['readyChapterCount'], 7)
        self.assertEqual(report['learningRange']['prefixChapterIds'], ['ch' + str(i) for i in range(1, 8)])
        self.assertTrue(all(c['verification']['offline']['status'] == 'not-verified' for c in report['chapters']))
        self.assertEqual(before, self.course)

    def test_three_missing_middle_chapters_preserve_other_ready_ranges(self):
        leave_pending(self.course, self.inventory, [3, 4, 5])
        report = self.report()
        summary = report['learningRange']
        self.assertEqual(summary['prefixChapterIds'], ['ch1', 'ch2'])
        self.assertEqual([r['chapterIds'] for r in summary['readyRanges']], [['ch1', 'ch2'], ['ch6', 'ch7']])
        self.assertEqual((summary['readyChapterCount'], summary['pendingChapterCount']), (4, 3))
        self.assertTrue(all(c['availability']['status'] == 'pending' for c in report['chapters'][2:5]))
        self.assertNotIn('empty chapter', report['errors'])

    def test_missing_first_chapter_has_no_first_chapter_prefix(self):
        leave_pending(self.course, self.inventory, [1])
        report = self.report()['learningRange']
        self.assertEqual(report['prefixChapterIds'], [])
        self.assertEqual(report['readyRanges'][0]['chapterIds'], ['ch2', 'ch3', 'ch4', 'ch5', 'ch6', 'ch7'])

    def test_excerpt_range_does_not_claim_original_book_numbering(self):
        self.course['chapters'][0]['title'] = '原书第八章'
        self.course['chapters'][1]['title'] = '原书第九章'
        rereview(self.course, self.inventory)
        report = self.report()['learningRange']
        self.assertEqual(report['scope'], 'included-chapters')
        self.assertEqual(report['scopeCompleteness'], 'excerpt')
        self.assertEqual(report['readyRanges'][0]['titles'][0], '原书第八章')

    def test_stale_review_breaks_only_affected_learning_range(self):
        self.course['chapters'][2]['sections'][0]['blocks'][0]['text'] = 'Changed observation rule.'
        report = self.report()
        self.assertEqual(report['chapters'][2]['availability']['status'], 'partial')
        self.assertEqual(report['learningRange']['prefixChapterIds'], ['ch1', 'ch2'])

    def test_legacy_reviews_never_produce_ready_chapters(self):
        self.course['schemaVersion'] = 1
        self.assertEqual(self.report()['learningRange']['readyChapterCount'], 0)

    def test_unmapped_learning_source_prevents_ready(self):
        self.inventory['items'].append({'id': 'extra', 'sourceId': 's1', 'locator': 'p2', 'chapterId': 'ch1'})
        report = self.report()
        self.assertEqual(report['chapters'][0]['availability']['status'], 'partial')
        self.assertIn('extra', [b.get('sourceItemId') for b in report['chapters'][0]['availability']['blockingItems']])

    def test_omitted_expected_subquestion_prevents_ready(self):
        self.inventory['items'][0]['expectedParts'] = ['missing-part']
        rereview(self.course, self.inventory)
        c = self.report()['chapters'][0]
        self.assertEqual(c['content']['status'], 'partial')
        self.assertEqual(c['availability']['status'], 'partial')

    def test_required_sampling_and_reported_failure_block_learning_range(self):
        self.course['independentReview'] = {'required': True}
        report = self.report()
        self.assertEqual(report['learningRange']['readyChapterCount'], 0)
        self.course.pop('independentReview')
        for result in ['failed', 'stale', 'invalid']:
            with self.subTest(result=result), patch.object(status, 'audit_independent', return_value={
                    'status': result, 'chapters': [{'chapterId': 'ch2', 'status': result,
                    'selectedCount': 1, 'reviewedCount': 1}]}):
                c = self.report()['chapters'][1]
                self.assertEqual(c['availability']['status'], 'partial')

    def test_required_material_defaults_to_blocking(self):
        self.course['taskContract']['pendingMaterials'].append({'chapterId': 'ch2', 'description': 'Teacher correction page.'})
        rereview(self.course, self.inventory)
        report = self.report()
        self.assertEqual(report['learningRange']['prefixChapterIds'], ['ch1'])
        self.assertEqual(report['chapters'][1]['availability']['status'], 'partial')

    def test_explicit_optional_material_is_visible_without_blocking(self):
        self.course['taskContract']['pendingMaterials'].append({'chapterId': 'ch2', 'description': 'Optional historical image.',
            'required': False, 'optionalReason': 'The user requested it only as later background reference.'})
        rereview(self.course, self.inventory)
        report = self.report()
        self.assertEqual(report['learningRange']['readyChapterCount'], 7)
        self.assertEqual(report['learningRange']['optionalMaterialCount'], 1)
        self.assertEqual(report['chapters'][1]['availability']['optionalMaterials'][0]['description'], 'Optional historical image.')

    def test_malformed_optional_flag_and_missing_reason_never_go_green(self):
        for change in [{'required': 'false'}, {'required': 0}, {'required': False}, {'required': None}]:
            with self.subTest(change=change):
                self.setUp()
                self.course['taskContract']['pendingMaterials'].append({'chapterId': 'ch2', 'description': 'Missing material.', **change})
                rereview(self.course, self.inventory)
                report = self.report()
                self.assertTrue(status.validate_learning_scope(self.course))
                self.assertEqual(report['learningRange']['status'], 'invalid')
                self.assertEqual(report['learningRange']['readyChapterCount'], 0)

    def test_pending_reference_only_page_does_not_block_reviewed_lessons(self):
        self.course['sources'].append({'id': 'reference-source', 'role': 'reference', 'sha256': 'ref-hash'})
        self.course['taskContract']['sourceUses'].append({'sourceId': 'reference-source', 'usage': 'reference', 'chapterIds': ['ch1'], 'purpose': 'Archive comparison.'})
        self.course['chapters'][0]['sections'].append({'id': 'reference-page', 'title': 'Archive',
            'sourceRefs': [{'sourceId': 'reference-source', 'locator': 'p1'}],
            'blocks': [{'type': 'image', 'path': 'reference.png', 'alt': 'Archive page.'}]})
        self.inventory['items'].append({'id': 'reference-item', 'sourceId': 'reference-source', 'locator': 'p1'})
        self.course['coverage'].append({'sourceItemId': 'reference-item', 'targets': ['reference-page'], 'status': 'pending'})
        self.course['learningMap'].append({'sourceItemId': 'reference-item', 'disposition': 'reference-only',
            'explanationTargets': ['reference-page'], 'summaryTargets': [], 'emphasisTargets': [], 'evidence': 'Archive only, still being checked.'})
        rereview(self.course, self.inventory)
        report = self.report()
        self.assertEqual(report['chapters'][0]['availability']['status'], 'ready')
        self.assertGreater(report['chapters'][0]['availability']['referencePendingCount'], 0)
        self.assertEqual(report['chapters'][0]['content']['status'], 'partial')

    def test_pending_question_answer_blocks_the_chapter(self):
        self.course['questions'].append({'id': 'q1', 'chapterIds': ['ch1'],
            'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
            'prompt': [{'type': 'paragraph', 'text': 'Which date belongs to this observation?'}],
            'answer': {'status': 'pending', 'blocks': [{'type': 'paragraph', 'text': 'Awaiting the original answer.'}]}})
        self.course['coverage'][0]['targets'].append('q1')
        self.course['learningMap'][0]['explanationTargets'].append('q1')
        rereview(self.course, self.inventory)
        c = self.report()['chapters'][0]
        self.assertEqual(c['availability']['status'], 'partial')
        self.assertTrue(any(b.get('targetId') == 'q1' for b in c['availability']['blockingItems']))

    def test_question_missing_required_keys_cannot_turn_into_ready_text(self):
        question = {'id': 'q1', 'chapterIds': ['ch1'], 'version': '1', 'number': '1',
            'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
            'prompt': [{'type': 'paragraph', 'text': 'State the observation date.'}],
            'parts': [{'id': 'p1', 'fields': [{'id': 'date', 'kind': 'text', 'label': 'Date'}]}],
            'answer': {'status': 'ready', 'version': '1', 'provenance': 'original',
                'blocks': [{'type': 'paragraph', 'text': 'Use the date on the original record.'}]}}
        self.course['questions'].append(question)
        self.course['coverage'][0]['targets'].append('q1')
        self.course['learningMap'][0]['explanationTargets'].append('q1')
        for missing in ('answer', 'prompt', 'parts'):
            with self.subTest(missing=missing):
                self.course['questions'][0] = copy.deepcopy(question)
                self.course['questions'][0].pop(missing)
                rereview(self.course, self.inventory)
                c = self.report()['chapters'][0]
                self.assertEqual(c['availability']['status'], 'partial')
                self.assertTrue(any(b.get('targetId') == 'q1' for b in c['availability']['blockingItems']))
        self.course['questions'][0] = question
        rereview(self.course, self.inventory)
        self.assertEqual(self.report()['chapters'][0]['availability']['status'], 'ready')

    def test_empty_or_malformed_question_parts_and_grading_do_not_go_ready(self):
        question = {'id': 'q1', 'chapterIds': ['ch1'], 'sourceRefs': [{'sourceId': 's1', 'locator': 'p1'}],
            'prompt': [{'type': 'paragraph', 'text': 'Count the observations.'}],
            'answer': {'status': 'ready', 'blocks': [{'type': 'paragraph', 'text': 'There are 3 observations.'}]},
            'parts': [{'id': 'p1', 'fields': [{'id': 'n', 'kind': 'number', 'label': 'Count'}]}]}
        self.course['coverage'][0]['targets'].append('q1')
        self.course['learningMap'][0]['explanationTargets'].append('q1')
        for parts in [None, [], [{}], [{'id': 'p1', 'fields': []}],
                      [{'id': 'p1', 'fields': [{'id': 'n', 'kind': 'unknown', 'label': 'Count'}]}]]:
            with self.subTest(parts=parts):
                self.course['questions'] = [{**question, 'parts': parts}]
                rereview(self.course, self.inventory)
                self.assertEqual(self.report()['chapters'][0]['availability']['status'], 'partial')
        self.course['questions'] = [{**question, 'grading': {'kind': 'numeric', 'rules': []}}]
        rereview(self.course, self.inventory)
        self.assertEqual(self.report()['chapters'][0]['availability']['status'], 'partial')

    def test_empty_placeholder_requires_explicit_reason(self):
        self.course['chapters'][2]['sections'] = []
        self.assertTrue(any('pending.reason' in e for e in status.validate_learning_scope(self.course)))
        self.course['chapters'][2]['pending'] = {'reason': 'Pages missing.'}
        self.assertEqual(status.validate_learning_scope(self.course), [])

    def test_complete_scope_rejects_declared_pending_chapters_and_required_material(self):
        self.course['scope']['completeness'] = 'complete'
        self.course['chapters'][0]['pending'] = {'reason': 'Missing part.'}
        self.assertTrue(any('pending chapter' in e for e in status.validate_learning_scope(self.course)))
        self.course['chapters'][0].pop('pending')
        self.course['taskContract']['pendingMaterials'] = [{'chapterId': 'ch1', 'description': 'Correction.'}]
        self.assertTrue(any('required pending' in e for e in status.validate_learning_scope(self.course)))

    def test_pending_metadata_changes_verification_binding(self):
        before = status.chapter_binding(self.course, self.inventory, 'ch1')
        self.course['chapters'][0]['pending'] = {'reason': 'Missing appendix.'}
        self.assertNotEqual(before, status.chapter_binding(self.course, self.inventory, 'ch1'))

    def test_invalid_scopes_cannot_generate_ready_ranges(self):
        for scope in [None, [], {'completeness': 'ready', 'description': 'unknown'}, {'completeness': 'excerpt'}]:
            with self.subTest(scope=scope):
                self.course['scope'] = scope
                r = self.report()
                self.assertEqual(r['status'], 'invalid')
                self.assertFalse(r.get('learningRange', {}).get('readyChapterCount', 0))


if __name__ == '__main__':
    unittest.main()
