"""Exercise CLI boundaries: preparing evidence never fabricates a review pass."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pipeline


class QualityCliTests(unittest.TestCase):
    def setUp(self):
        self.course = json.loads((ROOT / 'examples/demo-course.json').read_text(encoding='utf-8'))
        self.course.pop('independentReview', None)
        self.course.pop('chapterChecks', None)
        self.inventory = json.loads((ROOT / 'examples/demo-inventory.json').read_text(encoding='utf-8'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.source = self.work / 'course.json'
        self.inv = self.work / 'inventory.json'
        self.source.write_text(json.dumps(self.course), encoding='utf-8')
        self.inv.write_text(json.dumps(self.inventory), encoding='utf-8')

    def call(self, name, *extra):
        out = self.work / (name + '.json')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/pipeline.py'), name,
                                 str(self.source), '--inventory', str(self.inv), '--out', str(out),
                                 *extra], capture_output=True, text=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        return result, out

    def test_plan_and_source_packet_have_no_assessment_or_generated_content(self):
        result, plan = self.call('independent-plan', '--producer', 'fixture-author')
        self.assertEqual(result.returncode, 0, result.stderr)
        p = json.loads(plan.read_text())
        self.assertTrue(p['samples'])
        result, packet = self.call('independent-packet', '--plan', str(plan))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(packet.read_text())
        self.assertEqual(data['phase'], 'source')
        self.assertNotIn('semanticReviews', data)
        self.assertNotIn('learningMap', data)
        self.assertTrue(all('targets' not in row for row in data['samples']))
        result, state = self.call('independent-state', '--required')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(state.read_text())['status'], 'not-reviewed')

    def test_compare_requires_prior_source_observation(self):
        _, plan = self.call('independent-plan', '--producer', 'fixture-author')
        result, packet = self.call('independent-packet', '--plan', str(plan), '--phase', 'compare')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packet.exists())

    def test_chapter_report_does_not_create_verification(self):
        result, out = self.call('chapter-state')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(out.read_text())['chapters']
        self.assertTrue(rows)
        self.assertTrue(all(c['verification']['offline']['status'] == 'not-verified' for c in rows))
        result, out = self.call('chapter-binding', '--chapter', 'ch1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('result', json.loads(out.read_text()))

    def test_required_sampling_blocks_a_complete_build(self):
        self.course['independentReview'] = {'required': True,
            'plan': pipeline.create_plan(self.course, self.inventory, 'fixture-author'), 'records': []}
        original = copy.deepcopy(self.course)
        dest = self.work / 'should-not-build.html'
        with self.assertRaises(ValueError):
            pipeline.build(self.course, self.inventory, dest, self.work)
        self.assertFalse(dest.exists())
        self.assertEqual(original, self.course)

    def test_required_must_be_boolean(self):
        self.course['independentReview'] = {'required': 'yes',
            'plan': pipeline.create_plan(self.course, self.inventory, 'fixture-author'), 'records': []}
        self.assertTrue(any('required' in e for e in pipeline.validate(self.course, self.inventory)))

    def test_course_required_flag_is_respected_without_cli_flag(self):
        self.course['independentReview'] = {'required': True,
            'plan': pipeline.create_plan(self.course, self.inventory, 'fixture-author'), 'records': []}
        self.source.write_text(json.dumps(self.course), encoding='utf-8')
        result, out = self.call('independent-state')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(out.read_text())['required'])

    def test_incomplete_output_uses_its_final_scope_for_verification(self):
        self.course['chapterChecks'] = [{
            'chapterId': 'ch1', 'kind': 'offline', 'result': 'pass', 'reviewer': 'fixture',
            'method': 'Synthetic test only', 'evidence': 'Synthetic target scope',
            'checkedAt': '2026-11-12T00:00:00Z', 'targetIds': ['k1', 'k-recap', 'k-ref', 'ex1', 'q1'],
            'checks': ['synthetic-open'], 'artifactSHA256': 'a' * 64,
            'binding': pipeline.chapter_binding(self.course, self.inventory, 'ch1')}]
        self.course['independentReview'] = {'required': True,
            'plan': pipeline.create_plan(self.course, self.inventory, 'fixture-author'), 'records': []}
        dest = self.work / 'incomplete.html'
        with patch.object(pipeline.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            validation = pipeline.build(self.course, self.inventory, dest, self.work,
                                        allow_incomplete=True, node='fixture-not-executed')
        self.assertTrue(dest.exists())
        self.assertEqual(validation['chapterStatus']['chapters'][0]['verification']['offline']['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
