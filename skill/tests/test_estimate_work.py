import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/estimate_work.py'
spec = importlib.util.spec_from_file_location('estimate_work_test', SCRIPT)
estimate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(estimate)


def document(data, name='model-usage.json'):
    raw = json.dumps(data, sort_keys=True).encode()
    return {'source': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'data': data}


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.scope = {'pageCount': 16, 'includedPageCount': 12, 'chapterCount': 2,
                      'unitCount': 3, 'sampleCount': 4}

    def test_stage_formula_and_network_retries_are_separate(self):
        result = estimate.estimate_work(self.scope)
        self.assertEqual(result['calls']['successfulResponses'], {'low': 33, 'high': 45})
        self.assertEqual(result['calls']['networkAttempts'], {'low': 33, 'high': 135})
        self.assertEqual(result['calibration']['status'], 'not-calibrated')
        for item in result['successfulResponseEstimates'].values():
            self.assertEqual(item['status'], 'unknown')
            self.assertIsNone(item['low'])
        self.assertEqual(result['excludedOverheads']['failedRequestBilling'], 'unknown')

    def test_page_count_does_not_invent_units_or_sample_upper_bound(self):
        result = estimate.estimate_work({'pageCount': 300})
        self.assertEqual(result['minimumUnitCount'], 38)
        self.assertEqual(result['calls']['successfulResponses']['low'], 381)
        self.assertIsNone(result['calls']['successfulResponses']['high'])
        self.assertEqual(set(result['unknownPlanningFields']), {'unitCount', 'sampleCount'})

    def test_only_observed_included_pages_bound_units(self):
        result = estimate.estimate_work({'pageCount': 300, 'includedPageCount': 8,
                                        'chapterCount': 1, 'unitCount': 1, 'sampleCount': 1})
        self.assertEqual(result['calls']['successfulResponses']['low'], 307)
        self.assertEqual(result['minimumUnitCount'], 1)

    def test_cannot_fit_more_than_eight_pages_or_multiple_chapters_in_one_unit(self):
        for change in ({'includedPageCount': 16, 'unitCount': 1}, {'chapterCount': 4}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                estimate.estimate_work({**self.scope, **change})

    def test_invalid_counts_and_nonfinite_values_are_rejected(self):
        for key, value in [('pageCount', True), ('unitCount', 0), ('sampleCount', -1),
                           ('chapterCount', 1.5), ('includedPageCount', 17), ('spentModelCalls', -1)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                estimate.estimate_work({**self.scope, key: value})
        with self.assertRaises(ValueError):
            estimate.estimate_work(self.scope, prices={'currency': 'USD', 'inputPerMillion': float('nan'), 'outputPerMillion': 1})

    def test_only_confirmed_stage_cache_hits_reduce_requests(self):
        result = estimate.estimate_work(self.scope, confirmed_cache_hits={'inventory': 16, 'plan': 1})
        self.assertEqual(result['calls']['successfulResponses'], {'low': 16, 'high': 28})
        with self.assertRaises(ValueError):
            estimate.estimate_work(self.scope, confirmed_cache_hits={'review': 4})
        with self.assertRaises(ValueError):
            estimate.estimate_work(self.scope, confirmed_cache_hits={'whole-chapter': 1})

    def test_falsy_nonobject_cache_input_and_oversized_rates_are_rejected(self):
        for hits in [[], False, 0, '']:
            with self.subTest(hits=hits), self.assertRaises(ValueError):
                estimate.estimate_work(self.scope, confirmed_cache_hits=hits)
        with self.assertRaises(ValueError):
            estimate.estimate_work(self.scope, prices={'currency': 'USD', 'inputPerMillion': 10 ** 400, 'outputPerMillion': 1})

    def test_budget_limit_is_not_falsely_used_as_a_completion_estimate(self):
        result = estimate.estimate_work({**self.scope, 'maxModelCalls': 40, 'spentModelCalls': 10})
        self.assertEqual(result['calls']['availableModelCalls'], 30)
        self.assertEqual(result['calls']['limitAssessment'], 'below-minimum')
        self.assertEqual(result['calls']['networkAttempts']['high'], 135)

    def test_partial_calibration_keeps_missing_totals_unknown(self):
        result = estimate.estimate_work(self.scope, calibration={'kind': 'user-supplied',
            'stages': {'inventory': [{'inputTokens': 10, 'outputTokens': 20, 'elapsedSeconds': 2}]}})
        self.assertEqual(result['successfulResponseEstimates']['inputTokens']['status'], 'unknown')
        self.assertIn('generation', result['successfulResponseEstimates']['inputTokens']['missingStages'])

    def test_explicit_samples_and_prices_produce_conditional_not_measured_cost(self):
        calibration = {'kind': 'user-supplied', 'stages': {
            stage: [{'inputTokens': 100, 'outputTokens': 10, 'elapsedSeconds': 2},
                    {'inputTokens': 200, 'outputTokens': 20, 'elapsedSeconds': 3}]
            for stage in estimate.STAGES}}
        result = estimate.estimate_work(self.scope, calibration,
                                        {'currency': 'USD', 'inputPerMillion': 2, 'outputPerMillion': 8})
        metrics = result['successfulResponseEstimates']
        self.assertEqual(metrics['inputTokens']['low'], 3300)
        self.assertEqual(metrics['inputTokens']['high'], 9000)
        self.assertEqual(metrics['elapsedSeconds']['low'], 66)
        self.assertEqual(metrics['elapsedSeconds']['high'], 135)
        self.assertAlmostEqual(metrics['cost']['low'], .00924)
        self.assertAlmostEqual(metrics['cost']['high'], .0252)
        self.assertEqual(metrics['cost']['status'], 'conditional')

    def test_completed_stages_are_not_charged_again_against_remaining_budget(self):
        result = estimate.estimate_work({**self.scope, 'spentModelCalls': 20, 'maxModelCalls': 40},
                                        completed_stages=['inventory', 'plan'])
        self.assertEqual(result['calls']['successfulResponses'], {'low': 16, 'high': 28})
        self.assertEqual(result['calls']['availableModelCalls'], 20)
        self.assertEqual(result['calls']['limitAssessment'], 'may-stop-before-worst-case')
        self.assertEqual(result['stages'][0]['fullLogicalRequests'], {'low': 16, 'high': 16})
        self.assertEqual(result['estimateScope'], 'remaining-stages')
        for completed in ['inventory', ['inventory', 'inventory'], ['invented']]:
            with self.assertRaises(ValueError):
                estimate.estimate_work(self.scope, completed_stages=completed)
        with self.assertRaises(ValueError):
            estimate.estimate_work(self.scope, completed_stages=['inventory'], confirmed_cache_hits={'inventory': 1})

    def test_completed_work_needs_no_missing_calibration(self):
        result = estimate.estimate_work(self.scope, completed_stages=list(estimate.STAGES))
        self.assertEqual(result['calls']['networkAttempts'], {'low': 0, 'high': 0})
        self.assertEqual(result['successfulResponseEstimates']['elapsedSeconds']['low'], 0)
        self.assertEqual(result['successfulResponseEstimates']['cost']['status'], 'unknown')

    def test_synthetic_calibration_and_unknown_stage_are_rejected(self):
        for calibration in [{'kind': 'measured', 'testDouble': True, 'stages': {}},
                            {'kind': 'user-supplied', 'stages': {'magic': [{}]}},
                            {'kind': 'user-supplied', 'stages': {'plan': [{'testDouble': True}]}}]:
            with self.assertRaises(ValueError):
                estimate.estimate_work(self.scope, calibration)


class UsageTests(unittest.TestCase):
    def test_upgraded_legacy_log_keeps_historical_outcomes_incomplete(self):
        result = estimate.usage_baseline([document({'formatVersion': 2, 'calls': 2,
            'legacyHistoryComplete': False, 'usage': [{'stage': 'plan', 'status': 'success',
            'elapsedSeconds': None, 'tokens': None, 'provider': None, 'model': None,
            'skillFingerprint': None}, {'stage': 'review:u1:0', 'status': 'pending'}]})])
        self.assertFalse(result['outcomes']['failureHistoryComplete'])
        self.assertFalse(result['outcomes']['cacheHistoryComplete'])
        self.assertEqual(result['unclassifiedAttempts'], 1)
        self.assertIsNone(result['calibration'])

    def test_openai_and_bailian_token_shapes(self):
        a = estimate.normalize_tokens({'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120,
                                       'input_tokens_details': {'cached_tokens': 40}})
        b = estimate.normalize_tokens({'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
                                       'prompt_tokens_details': {'cached_tokens': 40}})
        self.assertEqual(a, b)
        self.assertEqual(a['inputTokens'], 100)
        self.assertEqual(a['cachedInputTokens'], 40)

    def test_absent_or_total_only_usage_does_not_invent_input_output(self):
        for value in [None, {}, {'total_tokens': 7}]:
            result = estimate.normalize_tokens(value)
            self.assertIsNone(result['inputTokens'])
            self.assertIsNone(result['outputTokens'])
        self.assertIsNone(estimate.normalize_tokens({})['totalTokens'])

    def test_conflicting_and_noninteger_provider_counts_are_flagged(self):
        for value in [{'input_tokens': True}, {'prompt_tokens': 1.2},
                      {'input_tokens': 1, 'prompt_tokens': 2},
                      {'input_tokens': 3, 'output_tokens': 4, 'total_tokens': 99}]:
            self.assertTrue(estimate.normalize_tokens(value)['issues'])

    def test_real_success_failure_and_cache_are_separate(self):
        data = {'formatVersion': 2, 'calls': 2, 'provider': 'openai', 'model': 'example-model',
                'skillFingerprint': 'a' * 64, 'usage': [
                    {'stage': 'unit:u1:attempt:0', 'status': 'success', 'elapsedSeconds': 4,
                     'tokens': {'input_tokens': 100, 'output_tokens': 50}},
                    {'stage': 'unit:u1:attempt:0', 'status': 'cache-hit', 'elapsedSeconds': .01},
                    {'stage': 'review:u1:0', 'status': 'failed', 'elapsedSeconds': 2}]}
        result = estimate.usage_baseline([document(data)])
        self.assertEqual(result['recordedNetworkAttempts'], 2)
        self.assertEqual(result['outcomes']['cacheHits'], 1)
        self.assertEqual(result['outcomes']['failed'], 1)
        self.assertEqual(result['totals']['inputTokens']['knownTotal'], 100)
        self.assertEqual(result['totals']['inputTokens']['missingRecords'], 1)
        self.assertEqual(result['totals']['elapsedSeconds']['knownTotal'], 6)
        self.assertEqual(list(result['calibration']['stages']), ['generation'])

    def test_old_logs_preserve_unclassified_attempts_and_unknown_time(self):
        result = estimate.usage_baseline([document({'calls': 3, 'usage': [
            {'stage': 'plan', 'tokens': {'input_tokens': 10, 'output_tokens': 20}}]})])
        self.assertEqual(result['unclassifiedAttempts'], 2)
        self.assertEqual(result['outcomes']['failed'], 0)
        self.assertFalse(result['outcomes']['failureHistoryComplete'])
        self.assertIsNone(result['totals']['elapsedSeconds']['knownTotal'])
        self.assertIsNone(result['calibration'])

    def test_test_double_logs_and_rows_never_enter_measured_calibration(self):
        data = {'testDouble': True, 'calls': 1, 'usage': [
            {'stage': 'plan', 'tokens': {'input_tokens': 1, 'output_tokens': 2}, 'elapsedSeconds': 1}]}
        result = estimate.usage_baseline([document(data)])
        self.assertEqual(result['status'], 'no-real-observations')
        self.assertEqual(result['excludedTestDoubleRecords'], 1)
        self.assertIsNone(result['declaredNetworkCalls'])
        self.assertEqual(result['calibrations'], [])

    def test_models_are_not_silently_pooled(self):
        data = {'calls': 1, 'provider': 'x', 'model': 'a', 'skillFingerprint': 'c', 'usage': [
            {'stage': 'plan', 'tokens': {'input_tokens': 1, 'output_tokens': 2}, 'elapsedSeconds': 1}]}
        other = {**data, 'model': 'b'}
        result = estimate.usage_baseline([document(data, 'a.json'), document(other, 'b.json')])
        self.assertEqual(len(result['calibrations']), 2)
        self.assertIsNone(result['calibration'])

    def test_no_calls_counter_keeps_coverage_unknown(self):
        result = estimate.usage_baseline([document({'usage': [
            {'stage': 'plan', 'tokens': {'input_tokens': 1, 'output_tokens': 2}, 'elapsedSeconds': 1}]})])
        self.assertIsNone(result['declaredNetworkCalls'])
        self.assertIsNone(result['totals']['inputTokens']['missingRecords'])
        self.assertFalse(result['totals']['inputTokens']['complete'])

    def test_duplicate_logs_are_not_counted_twice(self):
        log = document({'calls': 0, 'usage': []})
        with self.assertRaises(ValueError):
            estimate.usage_baseline([log, copy.deepcopy(log)])

    def test_v2_missing_outcome_is_not_assumed_success(self):
        result = estimate.usage_baseline([document({'formatVersion': 2, 'calls': 1,
            'usage': [{'stage': 'plan', 'tokens': {'input_tokens': 1, 'output_tokens': 2}}]})])
        self.assertEqual(result['outcomes']['success'], 0)
        self.assertEqual(result['unclassifiedAttempts'], 1)
        self.assertTrue(result['issues'])

    def test_malformed_test_double_marker_cannot_become_measured(self):
        for data in [{'testDouble': 'true', 'calls': 0, 'usage': []},
                     {'calls': 1, 'usage': [{'stage': 'plan', 'testDouble': 'false'}]}]:
            with self.assertRaises(ValueError):
                estimate.usage_baseline([document(data)])

    def test_files_are_hashed_and_cli_will_not_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'model-usage.json'
            source.write_text('{"calls":0,"usage":[]}', encoding='utf-8')
            original = source.read_bytes()
            result = estimate.baseline_from_files([source])
            self.assertEqual(result['sources'][0]['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(estimate.main(['baseline', str(source), '--out', str(source)]), 1)
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
