"""Exercise user priorities and honest review status through the public CLI."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/pipeline.py'
FIXTURES = ROOT / 'tests/fixtures'


class AssuranceCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=self.work, capture_output=True, text=True,
                              encoding='utf-8', env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})

    def classify(self, organization=None):
        data = {'sources': [{'id': 'book', 'role': 'textbook'},
                            {'id': 'slides', 'role': 'teacher_slides'}]}
        if organization:
            data['organization'] = organization
        src, out = self.work / 'input.json', self.work / 'result.json'
        src.write_text(json.dumps(data), encoding='utf-8')
        result = self.run_cli('classify', src, '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(out.read_text(encoding='utf-8'))

    def test_existing_organization_survives_slides_input(self):
        result = self.classify({'mode': 'textbook', 'primarySourceIds': ['book'],
                                'reason': '用户要求按教材学习，课件补例证'})
        self.assertEqual(result['materialMode'], 'textbook')
        self.assertEqual(result['primarySourceIds'], ['book'])

    def test_mixed_materials_without_user_priority_need_decision(self):
        result = self.classify()
        self.assertIsNone(result['materialMode'])
        self.assertTrue(result['needsDecision'])

    def test_legacy_review_state_is_explicit_and_read_only(self):
        course = FIXTURES / 'general.json'
        before = course.read_bytes()
        out = self.work / 'state.json'
        result = self.run_cli('review-state', course, '--inventory', FIXTURES / 'inventory.json', '--out', out)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(out.read_text())['status'], 'legacy-unverified')
        self.assertEqual(course.read_bytes(), before)

    def test_legacy_stale_binding_exits_failure_not_unverified(self):
        course = self.work / 'legacy-bound.json'
        data = json.loads((FIXTURES / 'general.json').read_text(encoding='utf-8'))
        course.write_text(json.dumps(data), encoding='utf-8')
        binding_file = self.work / 'legacy-binding.json'
        record = data['semanticReviews'][0]
        bound = self.run_cli('review-binding', course, '--inventory', FIXTURES / 'inventory.json',
                             '--targets', *record['targetIds'], '--out', binding_file)
        self.assertEqual(bound.returncode, 0, bound.stderr)
        record['binding'] = json.loads(binding_file.read_text(encoding='utf-8'))['binding']
        course.write_text(json.dumps(data), encoding='utf-8')
        state = self.work / 'legacy-state.json'
        current = self.run_cli('review-state', course, '--inventory', FIXTURES / 'inventory.json',
                               '--out', state)
        self.assertEqual(current.returncode, 2, current.stderr)
        self.assertEqual(json.loads(state.read_text(encoding='utf-8'))['errors'], [])

        data['chapters'][0]['sections'][0]['blocks'][0]['text'] += ' 内容已经改动，旧绑定尚未复核。'
        course.write_text(json.dumps(data), encoding='utf-8')
        before = course.read_bytes()
        stale = self.run_cli('review-state', course, '--inventory', FIXTURES / 'inventory.json',
                             '--out', state)
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        report = json.loads(state.read_text(encoding='utf-8'))
        self.assertTrue(report['errors'])
        self.assertTrue(any(row['status'] == 'stale' for row in report['targets']))
        self.assertEqual(course.read_bytes(), before)

    def test_review_binding_does_not_create_or_change_pass(self):
        course = self.work / 'course.json'
        data = json.loads((FIXTURES / 'general.json').read_text())
        data['semanticReviews'] = []
        course.write_text(json.dumps(data), encoding='utf-8')
        before = course.read_bytes()
        out = self.work / 'binding.json'
        result = self.run_cli('review-binding', course, '--inventory', FIXTURES / 'inventory.json',
                              '--targets', 'k1', '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        binding = json.loads(out.read_text())
        self.assertEqual(binding['binding']['version'], 1)
        self.assertEqual(len(binding['binding']['fingerprint']), 64)
        self.assertNotIn('result', binding)
        self.assertEqual(course.read_bytes(), before)

    def test_legacy_build_is_readable_without_claiming_current_review(self):
        dest = self.work / 'legacy.html'
        result = self.run_cli('build', FIXTURES / 'general.json', '--inventory',
                              FIXTURES / 'inventory.json', '--out', dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['assurance']['status'], 'legacy-unverified')
        self.assertIn('legacy-unverified', dest.read_text(encoding='utf-8'))

    def test_v2_fresh_course_passes_but_changed_explanation_requires_review(self):
        course = self.work / 'course.json'
        data = json.loads((FIXTURES / 'fusion.json').read_text())
        course.write_text(json.dumps(data), encoding='utf-8')
        out = self.work / 'validation.json'
        args = ('validate', course, '--inventory', FIXTURES / 'fusion-inventory.json', '--out', out)
        first = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(json.loads(out.read_text())['assurance']['status'], 'pass')
        data['chapters'][0]['sections'][0]['blocks'][0]['text'] += ' 新改写尚未重新审查。'
        course.write_text(json.dumps(data), encoding='utf-8')
        changed = self.run_cli(*args)
        self.assertEqual(changed.returncode, 1)
        self.assertNotEqual(json.loads(out.read_text())['assurance']['status'], 'pass')
        html = self.work / 'should-not-build.html'
        blocked = self.run_cli('build', course, '--inventory', FIXTURES / 'fusion-inventory.json', '--out', html)
        self.assertEqual(blocked.returncode, 1)
        self.assertFalse(html.exists())

    def test_changed_image_bytes_block_build_even_with_allow_incomplete(self):
        def png(rgb):
            def chunk(kind, content):
                return (struct.pack('>I', len(content)) + kind + content
                        + struct.pack('>I', zlib.crc32(kind + content) & 0xffffffff))
            return (b'\x89PNG\r\n\x1a\n'
                    + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(b'\x00' + bytes(rgb)))
                    + chunk(b'IEND', b''))

        original = png((255, 255, 255))
        replacement = png((0, 0, 0))
        asset = self.work / 'source-page.png'
        asset.write_bytes(original)
        data = json.loads((FIXTURES / 'fusion.json').read_text(encoding='utf-8'))
        data['chapters'][0]['sections'][0]['blocks'].append({
            'type': 'image', 'path': asset.name, 'alt': 'Synthetic one-pixel source illustration',
            'sha256': hashlib.sha256(original).hexdigest(),
        })
        course = self.work / 'image-course.json'
        course.write_text(json.dumps(data), encoding='utf-8')
        binding_file = self.work / 'image-binding.json'
        for record in data['semanticReviews']:
            bound = self.run_cli('review-binding', course, '--inventory', FIXTURES / 'fusion-inventory.json',
                                 '--targets', *record['targetIds'], '--out', binding_file)
            self.assertEqual(bound.returncode, 0, bound.stderr)
            record['binding'] = json.loads(binding_file.read_text(encoding='utf-8'))['binding']
        course.write_text(json.dumps(data), encoding='utf-8')
        current = self.run_cli('build', course, '--inventory', FIXTURES / 'fusion-inventory.json',
                               '--assets', self.work, '--out', self.work / 'fresh-image.html')
        self.assertEqual(current.returncode, 0, current.stdout + current.stderr)

        before = course.read_bytes()
        asset.write_bytes(replacement)
        self.assertNotEqual(hashlib.sha256(asset.read_bytes()).hexdigest(),
                            data['chapters'][0]['sections'][0]['blocks'][-1]['sha256'])
        for allow_incomplete in (False, True):
            with self.subTest(allow_incomplete=allow_incomplete):
                dest = self.work / ('changed-image-' + str(allow_incomplete) + '.html')
                args = ['build', course, '--inventory', FIXTURES / 'fusion-inventory.json',
                        '--assets', self.work, '--out', dest]
                if allow_incomplete:
                    args.append('--allow-incomplete')
                rejected = self.run_cli(*args)
                self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
                self.assertIn('image content changed', rejected.stderr)
                self.assertFalse(dest.exists())
        self.assertEqual(course.read_bytes(), before)

    def test_chapter_contract_reused_by_classification(self):
        out = self.work / 'classification.json'
        result = self.run_cli('classify', FIXTURES / 'fusion.json', '--chapter', 'ch1', '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = json.loads(out.read_text())
        self.assertEqual(answer['materialMode'], 'textbook')
        self.assertEqual(answer['primarySourceIds'], ['s1'])


if __name__ == '__main__':
    unittest.main()
