"""Local estimation integration; synthetic observations stay explicitly marked."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from portal.config import Config
from portal.estimation import JobEstimate, public_estimate


class JobEstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root / 'job'; self.job.mkdir()
        self.skill = self.root / 'skill'; (self.skill / 'scripts').mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / 'skill/scripts/estimate_work.py'
        shutil.copy2(source, self.skill / 'scripts/estimate_work.py')
        self.config = Config(skill_dir=self.skill, model='test-model', max_model_calls=40)
        self.extraction = {'pages': [{'id': 'p' + str(i)} for i in range(10)]}
        self.inventory = {'items': [{'id': 'i' + str(i), 'pageId': 'p' + str(i)} for i in range(10)]}
        self.plan = {'chapters': [{'id': 'ch1', 'units': [
            {'id': 'u1', 'itemIds': ['i' + str(i) for i in range(5)]},
            {'id': 'u2', 'itemIds': ['i' + str(i) for i in range(5, 10)]}]}]}
        patched = patch('portal.skill_sync.skill_metadata', return_value={'fingerprint': 'a' * 64})
        patched.start(); self.addCleanup(patched.stop)

    def write_usage(self, calls, usage=None, **extra):
        value = {'formatVersion': 2, 'provider': 'openai', 'model': 'test-model',
                 'skillFingerprint': 'a' * 64, 'calls': calls, 'usage': usage or [], **extra}
        (self.job / 'model-usage.json').write_text(json.dumps(value), encoding='utf-8')

    def test_page_unit_sample_counts_update_and_completed_work_is_not_billed_twice(self):
        tracker = JobEstimate(self.config, self.job, self.extraction, test_double=True)
        before = tracker.refresh()
        self.assertEqual(before['scope']['pageCount'], 10)
        self.assertIsNone(before['scope']['unitCount'])
        self.assertIsNone(before['calls']['networkAttempts']['high'])
        self.write_usage(13, testDouble=True)
        planned = tracker.update(inventory=self.inventory, plan=self.plan, completed=['inventory', 'plan'])
        self.assertEqual(planned['calls']['spentModelCalls'], 13)
        self.assertEqual(planned['calls']['availableModelCalls'], 27)
        self.assertEqual(planned['calls']['successfulResponses']['low'], 8)
        sampled = tracker.update(sample_plan={'samples': [{'sampleId': 's1'}, {'sampleId': 's2'}, {'sampleId': 's3'}]},
                                 completed=['generation', 'review', 'global-review'])
        self.assertEqual(sampled['calls']['successfulResponses'], {'low': 7, 'high': 7})
        self.assertEqual(sampled['scope']['sampleCount'], 3)
        self.assertEqual(sampled['successfulResponseEstimates']['cost']['status'], 'unknown')

    def test_test_double_observations_cannot_calibrate_real_prices_or_usage(self):
        self.write_usage(1, [{'stage': 'plan', 'status': 'success', 'elapsedSeconds': 2,
                              'tokens': {'input_tokens': 20, 'output_tokens': 10}}])
        report = JobEstimate(self.config, self.job, self.extraction, test_double=True).refresh()
        self.assertEqual(report['usage']['status'], 'no-real-observations')
        self.assertIsNone(report['usage']['totals']['totalTokens']['knownTotal'])
        self.assertEqual(report['calibration']['status'], 'not-calibrated')
        self.assertTrue(public_estimate(self.job / 'work-estimate.json')['testDouble'])

    def test_explicit_prices_need_stage_observations_and_do_not_appear_by_default(self):
        tracker = JobEstimate(self.config, self.job, self.extraction)
        stages = tracker.module.STAGES
        calibration = self.root / 'calibration.json'
        calibration.write_text(json.dumps({'kind': 'user-supplied', 'basis': 'hypothetical explicit observation example',
            'stages': {name: [{'inputTokens': 100, 'outputTokens': 10, 'elapsedSeconds': 2}] for name in stages}}), encoding='utf-8')
        prices = self.root / 'prices.json'
        prices.write_text(json.dumps({'currency': 'EXAMPLE', 'inputPerMillion': 2, 'outputPerMillion': 4}), encoding='utf-8')
        tracker = JobEstimate(replace(self.config, estimation_calibration_file=str(calibration)), self.job, self.extraction)
        tracker.update(inventory=self.inventory, plan=self.plan, sample_plan={'samples': [{'sampleId': 'one'}]})
        self.assertIsNone(public_estimate(self.job / 'work-estimate.json')['metrics']['cost']['low'])
        tracker = JobEstimate(replace(self.config, estimation_calibration_file=str(calibration),
                                     estimation_prices_file=str(prices)), self.job, self.extraction)
        report = tracker.update(inventory=self.inventory, plan=self.plan, sample_plan={'samples': [{'sampleId': 'one'}]})
        public = public_estimate(self.job / 'work-estimate.json')
        self.assertEqual(public['metrics']['cost']['status'], 'conditional')
        self.assertGreater(public['metrics']['cost']['low'], 0)
        self.assertEqual(public['metrics']['cost']['currency'], 'EXAMPLE')
        self.assertNotIn(str(self.root), json.dumps(public))
        self.assertNotIn('hypothetical explicit observation', json.dumps(public))
        self.assertEqual(report['explicitInputs']['prices']['source'], 'explicit-server-configuration')

    def test_measured_calibration_requires_same_provider_model_and_skill(self):
        calibration = self.root / 'calibration.json'
        calibration.write_text(json.dumps({'kind': 'measured', 'identity': {'provider': 'openai',
            'model': 'different-model', 'skillFingerprint': 'a' * 64}, 'stages': {}}), encoding='utf-8')
        tracker = JobEstimate(replace(self.config, estimation_calibration_file=str(calibration)), self.job, self.extraction)
        with self.assertRaisesRegex(ValueError, '不一致'):
            tracker.refresh()

    def test_legacy_calls_remain_spent_with_unclassified_history(self):
        self.write_usage(12, [{'stage': 'plan', 'tokens': {'total_tokens': 5}}], formatVersion=1)
        report = JobEstimate(self.config, self.job, self.extraction).refresh()
        self.assertEqual(report['calls']['availableModelCalls'], 28)
        self.assertEqual(report['usage']['unclassifiedAttempts'], 11)
        self.assertIsNone(report['successfulResponseEstimates']['inputTokens']['low'])

    def test_public_projection_excludes_ledger_rows_source_paths_and_unrequested_prices(self):
        self.write_usage(1, [{'stage': 'plan', 'status': 'success', 'elapsedSeconds': 2, 'tokens': None}])
        tracker = JobEstimate(self.config, self.job, self.extraction)
        raw = tracker.refresh()
        raw['private'] = 'secret content'
        raw['successfulResponseEstimates']['cost'] = {'status': 'conditional', 'low': 123, 'high': 999, 'currency': 'USD'}
        path = self.job / 'work-estimate.json'; path.write_text(json.dumps(raw), encoding='utf-8')
        public = public_estimate(path)
        self.assertNotIn('secret content', json.dumps(public))
        self.assertNotIn('observations', json.dumps(public))
        self.assertNotIn('skillFingerprint', json.dumps(public))
        self.assertIsNone(public['metrics']['cost']['low'])
        self.assertIsNone(public['usage']['totals']['totalTokens']['knownTotal'])
        self.assertEqual(public['usage']['outcomes']['success'], 1)

    def test_public_projection_does_not_crash_on_oversized_json_integer(self):
        tracker = JobEstimate(self.config, self.job, self.extraction)
        raw = tracker.refresh()
        raw['calls']['spentModelCalls'] = 10 ** 400
        path = self.job / 'work-estimate.json'; path.write_text(json.dumps(raw), encoding='utf-8')
        self.assertIsNone(public_estimate(path)['calls']['spentModelCalls'])

    def test_unreadable_or_symlink_estimate_does_not_expose_files(self):
        self.assertIsNone(public_estimate(self.job / 'missing'))
        path = self.job / 'bad'; path.write_text('not JSON', encoding='utf-8')
        self.assertIsNone(public_estimate(path))
        link = self.job / 'linked'; link.symlink_to(path)
        self.assertIsNone(public_estimate(link))


if __name__ == '__main__':
    unittest.main()
