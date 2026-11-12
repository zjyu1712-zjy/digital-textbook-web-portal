"""Actual scope, rather than a global success label, determines chapter evidence."""
import copy
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from portal.chapter_checks import browser_chapter_records


class ChapterCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'book.html'
        self.path.write_text('<!doctype html><title>Self-authored test fixture</title>')
        self.course = {'chapters': [{'id':'ch1','sections':[{'id':'k1'},{'id':'k2'}]},
                                    {'id':'ch2','sections':[{'id':'k3'}]}],
                       'questions':[{'id':'q1','chapterIds':['ch1']}, {'id':'q2','chapterIds':['ch2']}]}
        self.pipeline = SimpleNamespace(chapter_binding=lambda course, inventory, chapter:
            {'version':1,'fingerprint':chapter,'rendererFingerprint':'test-only'})
        self.report = {'status':'pass','opening':'file://','file':str(self.path.resolve()),
            'browser':'test-only-process-double','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'checks':[{'name':'all-routes-layout','status':'pass'}],
            'scope':{'chapters':['ch1'],'questions':['q1'],'exercisedQuestions':['q1']}}

    def tearDown(self):
        self.tmp.cleanup()

    def records(self, report=None):
        return browser_chapter_records(self.pipeline, self.course, {}, report or self.report, self.path)

    def test_opened_chapter_and_questions_only(self):
        rows = self.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['chapterId'], 'ch1')
        self.assertEqual(rows[0]['targetIds'], ['k1','k2','q1'])
        self.assertEqual(rows[0]['kind'], 'offline')
        self.assertEqual(rows[0]['artifactSHA256'], self.report['sha256'])
        self.assertIn('q1', rows[0]['evidence'])

    def test_question_only_check_does_not_certify_chapter_sections(self):
        self.report['scope']['chapters'] = []
        self.assertEqual(self.records()[0]['targetIds'], ['q1'])

    def test_shared_component_tests_are_not_chapter_verification(self):
        self.report['checks'] = [{'name':'three-immutable-attempts','status':'pass'}]
        self.assertEqual(self.records(), [])

    def test_legacy_or_failed_report_never_gains_chapter_success(self):
        original = copy.deepcopy(self.report)
        self.report.pop('scope')
        self.assertEqual(self.records(), [])
        original['status'] = 'fail'
        self.assertEqual(self.records(original), [])

    def test_changed_html_or_online_report_is_rejected(self):
        self.path.write_text('changed content')
        with self.assertRaisesRegex(ValueError, '不匹配'):
            self.records()
        self.report['sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.report['opening'] = 'http://'
        with self.assertRaisesRegex(ValueError, '不匹配'):
            self.records()

    def test_unknown_targets_and_inflated_exercise_scope_are_rejected(self):
        self.report['scope']['chapters'].append('unknown')
        with self.assertRaisesRegex(ValueError, '无效'):
            self.records()
        self.report['scope']['chapters'].pop()
        self.report['scope']['exercisedQuestions'].append('q2')
        with self.assertRaisesRegex(ValueError, '作答'):
            self.records()


if __name__ == '__main__':
    unittest.main()
