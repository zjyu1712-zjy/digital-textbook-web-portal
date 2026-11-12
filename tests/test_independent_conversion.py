"""Source-first orchestration tests use self-authored material and explicit doubles."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from portal.independent_review import run_independent_review, _sample_pages
from portal.runner import load_pipeline
from test_conversion import FixtureModel

ROOT = Path(__file__).resolve().parents[1]


class IndependentRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        skill = ROOT / 'skill'
        self.pipeline = load_pipeline(skill)
        self.course = json.loads((skill / 'tests/fixtures/fusion.json').read_text())
        self.inventory = json.loads((skill / 'tests/fixtures/fusion-inventory.json').read_text())
        raw = {sid:(skill / 'tests/fixtures' / name).read_text() for sid,name in [
            ('s1','general-source.txt'),('s2','fusion-supplement.txt'),('s3','fusion-reference.txt')]}
        self.pages = []
        for item in self.inventory['items']:
            item['pageId'] = 'page-' + item['id']
            self.pages.append({'id':item['pageId'],'sourceId':item['sourceId'],
                               'locator':item['locator'],'text':raw[item['sourceId']], 'image':''})
        self.plan = {'chapters':[{'units':[{'itemIds':[i['id'] for i in self.inventory['items']]}]}]}
        self.model = FixtureModel(None, self.root, lambda:False)
        self.events = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_review(self, model=None):
        return run_independent_review(self.pipeline, self.course, self.inventory, model or self.model,
            self.root, self.pages, self.plan, 'test-only-model',
            lambda *a,**k:self.events.append(a), lambda:None)

    def test_source_packets_blind_to_generator_claims_and_reading_precedes_comparison(self):
        sentinel = 'UNTRUSTED_GENERATOR_ALREADY_PASSED_CLAIM'
        self.course['semanticReviews'][0]['evidence'] = sentinel
        self.course['learningMap'][0]['evidence'] = sentinel
        self.course['learningMap'][0]['summaryNote'] = sentinel
        seen = []
        outer = self
        class Inspect(FixtureModel):
            def ask(self, stage, instructions, data, images=()):
                seen.append((stage, copy.deepcopy(data)))
                outer.assertNotIn(sentinel, json.dumps(data))
                outer.assertEqual(len(data['packet']['samples']), 1)
                outer.assertTrue(data['originalPages'])
                if stage.startswith('independent-source:'):
                    outer.assertNotIn('targets', data['packet']['samples'][0])
                    outer.assertNotIn('sourceRead', data['packet'])
                else:
                    saved = outer.root / 'checks/independent-review/source-read.json'
                    outer.assertTrue(saved.exists())
                    outer.assertEqual(len(json.loads(saved.read_text())['observations']),
                                      len(outer.course['independentReview']['plan']['samples']))
                return super().ask(stage, instructions, data, images)
        report = self.run_review(Inspect(None, self.root, lambda:False))
        self.assertEqual(report['status'], 'sampled-pass')
        total = report['selectedCount']
        self.assertTrue(all(stage.startswith('independent-source:') for stage,_ in seen[:total]))
        self.assertTrue(all(stage.startswith('independent-compare:') for stage,_ in seen[total:]))
        self.assertTrue(self.course['independentReview']['required'])
        self.assertTrue(self.course['independentReview']['execution']['sameModel'])
        self.assertNotEqual(self.course['independentReview']['plan']['producerId'],
                            self.course['independentReview']['sourceRead']['reviewerId'])

    def test_reference_sample_preserves_reference_purpose(self):
        report = self.run_review()
        self.assertEqual(report['status'], 'sampled-pass')
        reference = next(r for r in self.course['independentReview']['records'] if r['sampleId'] == 'i5')
        self.assertEqual(reference['checks']['summary'], 'not-applicable')
        self.assertEqual(reference['checks']['emphasis'], 'not-applicable')

    def test_failed_fusion_is_retained_not_rewritten_as_success(self):
        class Fail(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                if stage.startswith('independent-compare:'):
                    result['record'].update(result='fail', issues=[{'aspect':'explanation','description':'测试替身：本样本仅附原页，未融入讲解'}])
                    result['record']['checks']['explanation'] = 'fail'
                return result
        report = self.run_review(Fail(None, self.root, lambda:False))
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(all(r['result'] == 'fail' for r in self.course['independentReview']['records']))

    def test_incomplete_checks_do_not_gain_default_pass(self):
        class EmptyChecks(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                if stage.startswith('independent-compare:'):
                    result['record'].pop('checks')
                return result
        self.assertEqual(self.run_review(EmptyChecks(None, self.root, lambda:False))['status'], 'invalid')

    def test_missing_source_observation_stops_before_comparing(self):
        class Missing(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                super().ask(stage, *args, **kwargs)
                return {'problem':'缺少可辨认的原页'}
        model = Missing(None, self.root, lambda:False)
        with self.assertRaisesRegex(ValueError, '无法独立读明'):
            self.run_review(model)
        self.assertTrue(all(s.startswith('independent-source:') for s in model.calls))

    def test_wrong_sample_response_is_rejected(self):
        class Wrong(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                result['observation']['sampleId'] = 'unrequested'
                return result
        with self.assertRaisesRegex(ValueError, '对应本次请求'):
            self.run_review(Wrong(None, self.root, lambda:False))

    def test_missing_actual_page_is_rejected(self):
        self.pages.clear()
        with self.assertRaisesRegex(ValueError, '缺少其实际原页'):
            self.run_review()
        self.assertEqual(self.model.calls, [])

    def test_original_image_changed_during_review_is_rejected(self):
        image = self.root / 'page.png'
        image.write_bytes(b'not-real-image-unit-test-only')
        self.pages[0]['image'] = image.name
        class Changed(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                if stage.startswith('independent-compare:'):
                    image.write_bytes(b'changed-unit-test-image')
                return result
        with self.assertRaisesRegex(ValueError, '原页图片'):
            self.run_review(Changed(None, self.root, lambda:False))

    def test_distant_exam_conditions_are_read_without_generated_instructions(self):
        pages = [{'id':'p'+str(n),'sourceId':'s1','locator':'PDF 物理页 '+str(n),
                  'text':'真实共用条件' if n == 1 else '原题正文','image':''} for n in range(1,11)]
        sample = {'sourceItemId':'exam-q','sourceId':'s1','locator':'PDF 物理页 10','targetIds':['q1']}
        inventory = {'items':[{'id':'exam-q','sourceId':'s1','pageId':'p10'}]}
        course = {'questions':[{'id':'q1','sourceRefs':[{'sourceId':'s1','locator':'PDF 物理页 10'}]}],
                  'exams':[{'id':'paper','questionIds':['q1'],'instructions':[{'type':'paragraph','text':'GENERATED_COMMON_CONDITION'}],
                            'sourceRefs':[{'sourceId':'s1','locator':'PDF 物理页 1'}]}]}
        original = _sample_pages(sample, inventory, pages, {'chapters':[]}, course)
        self.assertIn('p1', [p['id'] for p in original])
        self.assertIn('p10', [p['id'] for p in original])
        self.assertNotIn('GENERATED_COMMON_CONDITION', json.dumps(original))

    def test_unlocatable_common_condition_is_never_replaced_by_candidate_text(self):
        sample = {'sourceItemId':'i1','sourceId':'s1','locator':'第1页/1.1','targetIds':['q1']}
        self.course['exams'] = [{'id':'paper','questionIds':['q1'],
            'instructions':[{'type':'paragraph','text':'生成的公共题设，不能作为原文'}]}]
        with self.assertRaisesRegex(ValueError, '共同条件缺少可定位'):
            _sample_pages(sample, self.inventory, self.pages, self.plan, self.course)
        self.inventory['items'][1]['kind'] = 'exam_conditions'
        original = _sample_pages(sample, self.inventory, self.pages, self.plan, self.course)
        self.assertIn(self.inventory['items'][1]['pageId'], [p['id'] for p in original])


if __name__ == '__main__':
    unittest.main()
