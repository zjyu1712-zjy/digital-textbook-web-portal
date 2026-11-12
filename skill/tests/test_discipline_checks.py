"""Rules read actual located blocks; missing values and bad rules never pass."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from discipline_checks import report_discipline_checks, validate_discipline_checks


def ref(index=0, target='lesson', area='blocks', path=None):
    return {'targetId': target, 'area': area, 'blockPath': [index] if path is None else path}


def course():
    return {'schemaVersion': 2, 'chapters': [{'id': 'ch1', 'sections': [{'id': 'lesson', 'blocks': [
        {'type': 'table', 'columns': ['科目', '借方', '贷方'],
         'rows': [['材料', '100.10', '0'], ['现金', '0', '100.10']]},
        {'type': 'table', 'columns': ['组别', '频数', '百分比'],
         'rows': [['A', '4', '40'], ['B', '6', '60'], ['合计', '10', '100']]},
        {'type': 'matrix', 'rows': [['a', 'b', 'c'], ['d', 'e', 'f']]},
        {'type': 'matrix', 'rows': [[1, 0], [0, 1], [1, 1]]},
        {'type': 'matrix', 'rows': [[1, 2], [3, 4]]},
        {'type': 'details', 'title': 'Nested original table', 'blocks': [
            {'type': 'table', 'columns': ['value', 'total'], 'rows': [['0.1', '0.3'], ['0.2', '0']]}]},
    ]}]}], 'questions': [{'id': 'q1', 'chapterIds': ['ch1'],
        'prompt': [{'type': 'matrix', 'rows': [[1, 2], [3, 4]]}],
        'answer': {'blocks': [{'type': 'matrix', 'rows': [[1, 3], [2, 4]]}]}}]}


def journal():
    return {'id': 'journal', 'kind': 'journal_balance', 'target': ref(0),
            'accountColumn': 0, 'debitColumn': 1, 'creditColumn': 2,
            'decimalPlaces': 2, 'accounts': ['材料', '现金']}


def summed(kind='table_sum', **extra):
    rule = {'id': 'total', 'kind': kind, 'target': ref(1), 'axis': 'column', 'index': 1, 'indices': [0, 1]}
    if kind != 'percentage_total':
        rule['expected'] = '10'
    rule.update(extra)
    return rule


class DisciplineTests(unittest.TestCase):
    def setUp(self):
        self.course = course()

    @property
    def blocks(self):
        return self.course['chapters'][0]['sections'][0]['blocks']

    def run_rule(self, rule):
        self.course['disciplineChecks'] = [rule]
        return report_discipline_checks(self.course)

    def assert_status(self, expected, rule):
        report = self.run_rule(rule)
        self.assertEqual(report['status'], expected, report)
        json.dumps(report, allow_nan=False)
        return report

    def test_missing_or_empty_rules_are_not_full_discipline_pass(self):
        self.assertEqual(report_discipline_checks(self.course)['status'], 'not-configured')
        self.course['disciplineChecks'] = []
        self.assertEqual(report_discipline_checks(self.course)['status'], 'not-configured')
        self.assertEqual(validate_discipline_checks(self.course), [])
        self.course['schemaVersion'] = 1
        self.assertEqual(report_discipline_checks(self.course)['status'], 'not-configured')

    def test_bad_course_rules_and_duplicate_ids_are_invalid(self):
        for rules in [None, {}, 'journal', [None], [{}], [journal(), journal()]]:
            with self.subTest(rules=rules):
                self.course['disciplineChecks'] = rules
                self.assertEqual(report_discipline_checks(self.course)['status'], 'invalid')
        self.assertEqual(report_discipline_checks(None)['status'], 'invalid')

    def test_unknown_rule_and_copied_pass_data_are_not_accepted(self):
        self.assert_status('invalid', {'id': 'unknown', 'kind': 'made_up', 'target': ref()})
        self.assert_status('invalid', {**journal(), 'rows': [['材料', '100', '100']]})
        self.assert_status('invalid', {'id': 'copy', 'kind': 'journal_balance', 'data': [['材料', 1, 1]]})

    def test_journal_balance_reads_real_cells_without_mutating_course(self):
        self.course['disciplineChecks'] = [journal()]
        before = copy.deepcopy(self.course)
        self.assertEqual(report_discipline_checks(self.course)['status'], 'pass')
        self.assertEqual(self.course, before)
        self.blocks[0]['rows'][1][2] = '99.10'
        report = report_discipline_checks(self.course)
        self.assertEqual(report['status'], 'fail')
        error = report['errors'][0]
        self.assertEqual(error['code'], 'unbalanced_journal')
        self.assertEqual(error['actual']['difference'], '1.00')
        self.assertEqual(error['location'], ref(0))
        self.assertIn('journal', validate_discipline_checks(self.course)[0])

    def test_journal_chart_and_precision_locate_actual_cell(self):
        self.blocks[0]['rows'][0] = ['未知科目', '100.101', '0']
        report = self.assert_status('fail', journal())
        errors = {e['code']: e for e in report['errors']}
        self.assertEqual(errors['account_not_allowed']['location']['column'], 0)
        self.assertEqual(errors['amount_precision']['location']['row'], 0)
        self.assertEqual(errors['amount_precision']['location']['column'], 1)
        self.assertEqual(errors['amount_precision']['expected'], {'maximumDecimalPlaces': 2})

    def test_journal_negative_posting_and_blank_rows_are_not_hidden(self):
        self.blocks[0]['rows'][0][1] = '-100.10'
        self.assert_status('fail', journal())
        self.blocks[0]['rows'][0] = ['', '', '']
        report = self.assert_status('invalid', journal())
        self.assertEqual(report['errors'][0]['code'], 'empty_row')

    def test_missing_journal_side_is_not_inferred_as_zero(self):
        self.blocks[0]['rows'][0][2] = ''
        report = self.assert_status('invalid', journal())
        self.assertEqual(report['errors'][0]['location']['column'], 2)
        self.assertEqual(report['checks'][0]['observations'], [])

    def test_columns_must_be_distinct_explicit_indices(self):
        for change in [{'debitColumn': '借方'}, {'debitColumn': True}, {'debitColumn': 3},
                       {'debitColumn': 2}, {'accountColumn': -1}, {'decimalPlaces': True},
                       {'decimalPlaces': None}, {'accounts': None}, {'accounts': []}]:
            with self.subTest(change=change):
                self.assert_status('invalid', {**journal(), **change})

    def test_decimal_addition_is_exact_beyond_default_context_precision(self):
        self.blocks[0]['rows'] = [['材料', '1000000000000000000000000000000.01', '0'],
                                ['材料', '0.02', '0'], ['现金', '0', '1000000000000000000000000000000.03']]
        self.assert_status('pass', journal())
        self.blocks[0]['rows'][2][2] = '1000000000000000000000000000000.04'
        report = self.assert_status('fail', journal())
        self.assertEqual(report['errors'][0]['actual']['difference'], '-0.01')

    def test_fractional_decimal_and_trailing_zero_precision(self):
        self.blocks[0]['rows'] = [['材料', '0.1000', '0'], ['材料', '0.2', '0'], ['现金', '0', '0.30']]
        self.assert_status('pass', journal())

    def test_bad_numeric_tokens_are_invalid_not_zero(self):
        for value in [None, '', ' ', True, False, 'NaN', 'Infinity', '-Infinity', float('nan'), float('inf'),
                      '1/2', '10%', '100元', '1,000', '0x10', '1+1', '1e10001', {}, []]:
            with self.subTest(value=value):
                self.blocks[0]['rows'][0][1] = value
                self.assert_status('invalid', journal())

    def test_row_and_column_totals_use_actual_cells(self):
        self.assert_status('pass', summed())
        self.assert_status('pass', summed(axis='row', index=0, indices=[1, 2], expected='44'))
        self.blocks[1]['rows'][1][1] = '5'
        report = self.assert_status('fail', summed())
        self.assertEqual(report['errors'][0]['actual']['sum'], '9')
        self.assertEqual(report['checks'][0]['observations'][0]['cells'], [{'row': 0, 'column': 1}, {'row': 1, 'column': 1}])

    def test_total_can_reference_actual_total_cell(self):
        expected = {**ref(1), 'row': 2, 'column': 1}
        self.assert_status('pass', summed(expected=expected))
        self.blocks[1]['rows'][2][1] = '11'
        report = self.assert_status('fail', summed(expected=expected))
        self.assertEqual(report['errors'][0]['expected']['location'], expected)
        self.assertEqual(report['errors'][0]['expected']['sum'], '11')

    def test_expected_total_cannot_be_part_of_selected_data(self):
        rule = summed(expected={**ref(1), 'row': 0, 'column': 1}, indices=[0])
        report = self.assert_status('invalid', rule)
        self.assertEqual(report['errors'][0]['code'], 'self_referential_total')

    def test_percentage_99_fails_and_exact_tolerance_boundary_passes(self):
        rule = summed(kind='percentage_total', index=2)
        self.blocks[1]['rows'][1][2] = '59'
        report = self.assert_status('fail', rule)
        self.assertEqual(report['errors'][0]['actual']['sum'], '99')
        self.assert_status('pass', {**rule, 'tolerance': '1'})
        self.assert_status('fail', {**rule, 'tolerance': '0.999'})
        self.assert_status('invalid', {**rule, 'tolerance': '-1'})

    def test_percentage_decimal_rounding_with_explicit_tolerance(self):
        self.blocks[1]['rows'] = [['A', 1, '33.33'], ['B', 1, '33.33'], ['C', 1, '33.33']]
        rule = summed(kind='percentage_total', index=2, indices=[0, 1, 2], tolerance='0.01')
        self.assert_status('pass', rule)
        self.assert_status('fail', {**rule, 'tolerance': '0.009'})

    def test_frequency_requires_real_nonnegative_integer_counts(self):
        rule = summed(kind='frequency_total', expected={**ref(1), 'row': 2, 'column': 1})
        self.assert_status('pass', rule)
        self.blocks[1]['rows'][0][1] = '3'
        self.assert_status('fail', rule)
        for bad in ['-1', '1.5']:
            self.blocks[1]['rows'][0][1] = bad
            self.assert_status('fail', rule)
        self.assert_status('invalid', {**rule, 'expected': '10.5'})
        self.assert_status('invalid', {**rule, 'tolerance': '1'})

    def test_missing_statistic_prevents_sum_observation(self):
        self.blocks[1]['rows'][1][1] = None
        report = self.assert_status('invalid', summed())
        self.assertEqual(report['checks'][0]['observations'], [])
        self.assertEqual(report['errors'][0]['location']['row'], 1)

    def test_invalid_or_ambiguous_statistic_selectors_rejected(self):
        for change in [{'axis': 'guess'}, {'axis': []}, {'index': '频数'}, {'index': False},
                       {'indices': []}, {'indices': [0, 0]}, {'indices': [3]}, {'indices': [False]},
                       {'indices': [0, '1']}, {'expected': {'value': 10}}]:
            with self.subTest(change=change):
                self.assert_status('invalid', summed(**change))

    def test_nested_table_path_uses_real_details_block(self):
        rule = summed(target=ref(path=[5, 0]), index=0, expected='0.3', indices=[0, 1])
        self.assert_status('pass', rule)
        self.blocks[5]['blocks'][0]['rows'][1][0] = '0.3'
        self.assert_status('fail', rule)

    def test_bad_or_malicious_paths_do_not_access_arbitrary_properties(self):
        bad = [ref(target='absent'), ref(area='__dict__'), ref(path=[]), ref(path=['__class__']),
               ref(path=[-1]), ref(path=[True]), ref(path=[99]), ref(path=[0, 0]),
               {'targetId': 'lesson', 'area': 'blocks', 'blockPath': [0], 'path': '../../private'},
               {'targetId': 'lesson', 'area': 'blocks', 'blockPath': [0], 'rows': [[0]]}]
        for reference in bad:
            with self.subTest(reference=reference):
                self.assert_status('invalid', {**journal(), 'target': reference})

    def test_question_prompt_and_answer_blocks_are_resolved_by_identity(self):
        rule = {'id': 'transpose-answer', 'kind': 'matrix_shape', 'operation': 'transpose',
                'target': ref(target='q1', area='prompt'), 'result': ref(target='q1', area='answer.blocks')}
        self.assert_status('pass', rule)
        self.course['questions'][0]['answer']['blocks'][0]['rows'] = [[1, 3, 5], [2, 4, 6]]
        self.assert_status('fail', rule)
        self.assert_status('invalid', {**rule, 'target': ref(target='q1', area='blocks')})

    def test_matrix_multiplication_checks_operand_and_result_shapes(self):
        rule = {'id': 'multiply', 'kind': 'matrix_shape', 'operation': 'multiply', 'target': ref(2), 'other': ref(3), 'result': ref(4)}
        self.assert_status('pass', rule)
        self.assert_status('fail', {**rule, 'other': ref(4)})
        self.assert_status('fail', {**rule, 'result': ref(3)})

    def test_matrix_addition_requires_matching_shapes(self):
        rule = {'id': 'add', 'kind': 'matrix_shape', 'operation': 'add', 'target': ref(2), 'other': ref(3)}
        self.assert_status('fail', rule)
        self.assert_status('pass', {**rule, 'other': ref(2)})

    def test_transpose_and_determinant_square_rules(self):
        rule = {'id': 'transpose', 'kind': 'matrix_shape', 'operation': 'transpose', 'target': ref(2), 'result': ref(3)}
        self.assert_status('pass', rule)
        self.assert_status('fail', {**rule, 'result': ref(4)})
        self.assert_status('invalid', {k: v for k, v in rule.items() if k != 'result'})
        self.assert_status('fail', {'id': 'square', 'kind': 'matrix_shape', 'operation': 'square', 'target': ref(2)})
        self.assert_status('pass', {'id': 'square', 'kind': 'matrix_shape', 'operation': 'square', 'target': ref(4)})

    def test_matrix_missing_ragged_or_nonfinite_cells_are_invalid(self):
        rule = {'id': 'square', 'kind': 'matrix_shape', 'operation': 'square', 'target': ref(4)}
        for rows in [None, [], [[1], [1, 2]], [[None, 1], [2, 3]], [[True, 1], [2, 3]], [[float('nan'), 1], [2, 3]], [['NaN', 1], [2, 3]], [['Infinity', 1], [2, 3]], [['false', 1], [2, 3]]]:
            with self.subTest(rows=rows):
                self.blocks[4]['rows'] = rows
                self.assert_status('invalid', rule)

    def test_wrong_block_kind_and_extra_operation_fields_are_invalid(self):
        self.assert_status('invalid', {**journal(), 'target': ref(2)})
        self.assert_status('invalid', {'id': 'square', 'kind': 'matrix_shape', 'operation': 'square', 'target': ref(4), 'result': ref(4)})
        self.assert_status('invalid', {'id': 'unknown', 'kind': 'matrix_shape', 'operation': 'solve', 'target': ref(4)})

    def test_duplicate_target_ids_do_not_select_first_matching_block(self):
        self.course['chapters'][0]['sections'].append(copy.deepcopy(self.course['chapters'][0]['sections'][0]))
        report = self.assert_status('invalid', journal())
        self.assertTrue(report['errors'])

    def test_mixed_rule_results_keep_failures_and_invalids_visible(self):
        self.course['disciplineChecks'] = [journal(), summed(expected='11'), {'id': 'unknown', 'kind': 'no-rule'}]
        report = report_discipline_checks(self.course)
        self.assertEqual(report['status'], 'invalid')
        self.assertEqual((report['passedCount'], report['failedCount'], report['invalidCount']), (1, 1, 1))
        self.assertEqual(len(validate_discipline_checks(self.course)), 2)

    def test_bad_matrix_result_reference_is_not_hidden_by_incompatible_operands(self):
        rule = {'id': 'multiply', 'kind': 'matrix_shape', 'operation': 'multiply',
                'target': ref(2), 'other': ref(4), 'result': ref(target='absent')}
        report = self.assert_status('invalid', rule)
        self.assertEqual(report['errors'][0]['scope'], 'configuration')

    def test_bad_configuration_is_checked_before_bad_source_cells(self):
        self.blocks[1]['rows'] = [None]
        for rule in [summed(tolerance='-1'), summed(index=999), summed(expected={'targetId': 'absent', 'area': 'blocks', 'blockPath': [0], 'row': 0, 'column': 0})]:
            with self.subTest(rule=rule):
                report = self.assert_status('invalid', rule)
                self.assertEqual(report['errors'][0]['scope'], 'configuration')

    def test_invalid_sample_count_in_actual_cell_is_content_error(self):
        rule = summed(kind='frequency_total', expected={**ref(1), 'row': 2, 'column': 1})
        for value in ['10.5', '-1']:
            with self.subTest(value=value):
                self.blocks[1]['rows'][2][1] = value
                report = self.assert_status('invalid', rule)
                self.assertEqual(report['errors'][0]['scope'], 'content')


if __name__ == '__main__':
    unittest.main()
