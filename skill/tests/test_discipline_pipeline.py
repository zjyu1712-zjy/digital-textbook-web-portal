"""Real build and chapter readiness must use configured content checks."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pipeline
import chapter_status
from test_usable_chapters import course_with_chapters, rereview


def journal_rule(target, index=0):
    return {'id': 'balance', 'kind': 'journal_balance',
            'target': {'targetId': target, 'area': 'blocks', 'blockPath': [index]},
            'debitColumn': 1, 'creditColumn': 2, 'accountColumn': 0}


def journal(amount='10'):
    return {'type': 'table', 'columns': ['科目', '借方', '贷方'],
            'rows': [['材料', '10', '0'], ['现金', '0', amount]]}


class DisciplinePipelineTests(unittest.TestCase):
    def setUp(self):
        self.course = pipeline.read(ROOT / 'tests/fixtures/general.json')
        self.inventory = pipeline.read(ROOT / 'tests/fixtures/inventory.json')
        section = self.course['chapters'][0]['sections'][0]
        section['blocks'].append(journal())
        self.course['disciplineChecks'] = [journal_rule(section['id'], len(section['blocks']) - 1)]

    def test_actual_content_failure_blocks_build_and_preserves_previous_file(self):
        self.course['chapters'][0]['sections'][0]['blocks'][-1]['rows'][1][2] = '9'
        self.assertTrue(any('disciplineChecks balance' in e for e in pipeline.validate(self.course, self.inventory)))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'book.html'
            output.write_text('previous deliverable', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'disciplineChecks balance'):
                pipeline.build(self.course, self.inventory, output, folder)
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous deliverable')

    def test_allow_incomplete_keeps_failure_and_does_not_change_grading(self):
        self.course['chapters'][0]['sections'][0]['blocks'][-1]['rows'][1][2] = '9'
        original = copy.deepcopy(self.course)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'book.html'
            result = pipeline.build(self.course, self.inventory, output, folder, allow_incomplete=True)
            self.assertEqual(result['disciplineChecks']['status'], 'fail')
            embedded = json.loads(re.search(r'<script id="course-data" type="application/json">(.*?)</script>', output.read_text(encoding='utf-8'), re.S).group(1))
            self.assertEqual(embedded['scope']['completeness'], 'incomplete')
            self.assertEqual(embedded['validation']['disciplineChecks']['status'], 'fail')
            self.assertEqual(embedded['questions'], original['questions'])
            self.assertEqual(self.course, original)
            self.assertEqual(pipeline.inspect_html(output), [])

    def test_pass_build_and_no_config_report_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            result = pipeline.build(self.course, self.inventory, Path(folder) / 'book.html', folder)
            self.assertEqual(result['disciplineChecks']['status'], 'pass')
            self.course.pop('disciplineChecks')
            result = pipeline.build(self.course, self.inventory, Path(folder) / 'book.html', folder)
            self.assertEqual(result['disciplineChecks']['status'], 'not-configured')

    def test_invalid_rule_configuration_cannot_build_as_complete(self):
        for change in [{'debitColumn': '借方'}, {'target': {'targetId': 'missing', 'area': 'blocks', 'blockPath': [0]}}, {'kind': 'guessed'}]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                course = copy.deepcopy(self.course)
                course['disciplineChecks'][0].update(change)
                self.assertTrue(any('disciplineChecks' in e for e in pipeline.validate(course, self.inventory)))
                with self.assertRaises(ValueError):
                    pipeline.build(course, self.inventory, Path(folder) / 'book.html', folder)

    def test_cli_validation_exports_structured_discipline_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source, dest = Path(folder) / 'course.json', Path(folder) / 'validation.json'
            source.write_text(json.dumps(self.course), encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/pipeline.py'), 'validate', str(source),
                '--inventory', str(ROOT / 'tests/fixtures/inventory.json'), '--out', str(dest)],
                capture_output=True, text=True, env=os.environ.copy())
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(report['disciplineChecks']['status'], 'pass')

    def test_failed_actual_block_only_prevents_its_chapter_being_ready(self):
        course, inventory = course_with_chapters(3)
        course['chapters'][0]['sections'][0]['blocks'] = [journal('9')]
        course['disciplineChecks'] = [journal_rule('k1')]
        rereview(course, inventory)
        report = chapter_status.chapter_status(course, inventory)
        self.assertEqual([c['availability']['status'] for c in report['chapters']], ['partial', 'ready', 'ready'])
        self.assertEqual([c['disciplineChecks']['status'] for c in report['chapters']], ['fail', 'not-configured', 'not-configured'])
        self.assertEqual(report['learningRange']['readyRanges'][0]['chapterIds'], ['ch2', 'ch3'])

    def test_actual_missing_cell_is_local_but_invalid_configuration_is_global(self):
        course, inventory = course_with_chapters(3)
        course['chapters'][0]['sections'][0]['blocks'] = [journal(None)]
        course['disciplineChecks'] = [journal_rule('k1')]
        rereview(course, inventory)
        report = chapter_status.chapter_status(course, inventory)
        self.assertEqual([c['availability']['status'] for c in report['chapters']], ['partial', 'ready', 'ready'])
        course['disciplineChecks'][0]['creditColumn'] = 'inferred'
        report = chapter_status.chapter_status(course, inventory)
        self.assertEqual(report['learningRange']['status'], 'invalid')
        self.assertEqual(report['learningRange']['readyChapterCount'], 0)
        self.assertTrue(all(c['disciplineChecks']['configurationErrors'] for c in report['chapters']))

    def test_cross_chapter_rule_scopes_both_actual_references(self):
        course, inventory = course_with_chapters(3)
        course['chapters'][0]['sections'][0]['blocks'] = [{'type': 'table', 'columns': ['n'], 'rows': [['4'], ['6']]}]
        course['chapters'][1]['sections'][0]['blocks'] = [{'type': 'table', 'columns': ['total'], 'rows': [['9']]}]
        course['disciplineChecks'] = [{'id': 'sum', 'kind': 'frequency_total',
            'target': {'targetId': 'k1', 'area': 'blocks', 'blockPath': [0]}, 'axis': 'column', 'index': 0,
            'expected': {'targetId': 'k2', 'area': 'blocks', 'blockPath': [0], 'row': 0, 'column': 0}}]
        rereview(course, inventory)
        report = chapter_status.chapter_status(course, inventory)
        self.assertEqual([c['availability']['status'] for c in report['chapters']], ['partial', 'partial', 'ready'])
        self.assertEqual(report['disciplineChecks']['checks'][0]['targetIds'], ['k1', 'k2'])

    def test_rule_configuration_changes_verification_binding_and_checkpoint(self):
        course, inventory = course_with_chapters(3)
        course['chapters'][0]['sections'][0]['blocks'] = [journal()]
        course['disciplineChecks'] = [journal_rule('k1')]
        rereview(course, inventory)
        old_binding = chapter_status.chapter_binding(course, inventory, 'ch1')
        old_checkpoint = pipeline.checkpoint(course)
        course['disciplineChecks'][0]['decimalPlaces'] = 2
        self.assertNotEqual(old_binding, chapter_status.chapter_binding(course, inventory, 'ch1'))
        self.assertNotEqual(old_checkpoint, pipeline.checkpoint(course))
        current = chapter_status.chapter_binding(course, inventory, 'ch1')
        course['validation'] = {'disciplineChecks': {'status': 'pass'}}
        self.assertEqual(current, chapter_status.chapter_binding(course, inventory, 'ch1'))

    def test_malformed_table_or_matrix_rows_report_errors_without_crashing(self):
        for kind, rows in [('table', None), ('table', [None]), ('matrix', None), ('matrix', [None])]:
            with self.subTest(kind=kind, rows=rows), tempfile.TemporaryDirectory() as folder:
                course = copy.deepcopy(self.course)
                block = course['chapters'][0]['sections'][0]['blocks'][-1]
                block.update(type=kind, rows=rows)
                if kind == 'matrix':
                    course['disciplineChecks'][0] = {'id': 'square', 'kind': 'matrix_shape', 'operation': 'square',
                        'target': course['disciplineChecks'][0]['target']}
                self.assertTrue(pipeline.validate(course, self.inventory))
                # Incomplete delivery may retain failed arithmetic, but not a
                # block that the renderer cannot display without an exception.
                with self.assertRaisesRegex(ValueError, '行列结构'):
                    pipeline.build(course, self.inventory, Path(folder) / 'book.html', folder, allow_incomplete=True)
                if kind == 'matrix':
                    with self.assertRaisesRegex(ValueError, 'invalid rows'):
                        list(pipeline.math_expressions(course))


if __name__ == '__main__':
    unittest.main()
