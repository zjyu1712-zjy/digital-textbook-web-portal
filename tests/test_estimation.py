import copy
import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'portal/estimation.py'
spec = importlib.util.spec_from_file_location('portal_estimation_test', MODULE)
estimation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(estimation)


class PortalEstimationTests(unittest.TestCase):
    def setUp(self):
        self.extraction = {'pages': [{'id': 'p' + str(i)} for i in range(10)]}
        self.inventory = {'items': [{'id': 'i' + str(i), 'pageId': 'p' + str(i)} for i in range(10)]}
        self.plan = {'chapters': [{'id': 'ch1', 'units': [
            {'id': 'u1', 'itemIds': ['i' + str(i) for i in range(4)]},
            {'id': 'u2', 'itemIds': ['i4', 'i5']}]}]}

    def test_before_plan_only_observed_page_count_and_limit_are_supplied(self):
        scope = estimation.scope_from_job(self.extraction, max_model_calls=300)
        self.assertEqual(scope, {'pageCount': 10, 'maxModelCalls': 300, 'spentModelCalls': 0})
        self.assertNotIn('unitCount', scope)
        self.assertNotIn('sampleCount', scope)

    def test_plan_uses_real_units_and_selected_original_pages(self):
        scope = estimation.scope_from_job(self.extraction, self.inventory, self.plan,
                                          {'samples': [{'sampleId': 'one'}, {'sampleId': 'two'}]})
        self.assertEqual(scope, {'pageCount': 10, 'includedPageCount': 6, 'chapterCount': 1,
                                 'unitCount': 2, 'sampleCount': 2, 'spentModelCalls': 0})

    def test_more_than_eight_pages_is_not_silently_accepted(self):
        plan = {'chapters': [{'id': 'ch1', 'units': [{'id': 'u1', 'itemIds': ['i' + str(i) for i in range(9)]}]}]}
        with self.assertRaises(ValueError):
            estimation.scope_from_job(self.extraction, self.inventory, plan)

    def test_duplicate_or_unknown_material_cannot_distort_counts(self):
        for change in [['i0', 'i0'], ['missing'], [['i0']]]:
            plan = copy.deepcopy(self.plan)
            plan['chapters'][0]['units'][0]['itemIds'] = change
            with self.subTest(change=change), self.assertRaises(ValueError):
                estimation.scope_from_job(self.extraction, self.inventory, plan)
        plan = copy.deepcopy(self.plan)
        plan['chapters'][0]['units'][1]['itemIds'] = ['i0']
        with self.assertRaises(ValueError):
            estimation.scope_from_job(self.extraction, self.inventory, plan)

    def test_duplicate_pages_chapters_units_and_samples_are_rejected(self):
        with self.assertRaises(ValueError):
            estimation.scope_from_job({'pages': [{'id': 'a'}, {'id': 'a'}]})
        plan = copy.deepcopy(self.plan)
        plan['chapters'][0]['units'][1]['id'] = 'u1'
        with self.assertRaises(ValueError):
            estimation.scope_from_job(self.extraction, self.inventory, plan)
        with self.assertRaises(ValueError):
            estimation.scope_from_job(self.extraction, sample_plan={'samples': [{'sampleId': 'a'}, {'sampleId': 'a'}]})

    def test_estimate_job_delegates_to_pinned_estimator_without_model_calls(self):
        received = []
        def estimator(scope, **kwargs):
            received.append((scope, kwargs))
            return {'status': 'partial'}
        result = estimation.estimate_job(estimator, self.extraction, max_model_calls=30)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(received[0][0], {'pageCount': 10, 'maxModelCalls': 30, 'spentModelCalls': 0})


if __name__ == '__main__':
    unittest.main()
