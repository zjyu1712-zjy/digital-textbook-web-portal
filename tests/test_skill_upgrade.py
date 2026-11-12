"""Pinned skill and v2 orchestration regressions; no live model or private course."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from portal.config import Config
from portal.runner import Converter, load_pipeline, _unit_receipt, _verify_reviewed_units, QualityProblem
from portal.model import ResponsesModel
from portal.skill_sync import skill_metadata, sync_skill, verify_skill
from test_conversion import FixtureModel, browser_double

ROOT = Path(__file__).resolve().parents[1]


class SkillSyncTests(unittest.TestCase):
    def test_loader_isolates_other_cached_skill_modules(self):
        marker = object()
        before = list(sys.path)
        with patch.dict(sys.modules, {'task_contract': marker, 'review_audit': marker, 'grading': marker}):
            pipeline = load_pipeline(ROOT / 'skill')
            self.assertTrue(callable(pipeline.validate_contract))
            self.assertIs(sys.modules['task_contract'], marker)
            self.assertIs(sys.modules['review_audit'], marker)
        self.assertEqual(sys.path, before)

    def test_sync_pins_exact_files_then_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'skill'; lock = Path(tmp) / 'skill-lock.json'
            version = skill_metadata(ROOT / 'skill')['version']
            result = sync_skill(ROOT / 'skill', target, lock, 'v' + version)
            self.assertEqual(result['version'], version)
            self.assertEqual(verify_skill(target, lock)['fingerprint'], result['fingerprint'])
            (target / 'assets/app.js').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'assets/app.js'):
                verify_skill(target, lock)

    def test_unlisted_file_blocks_verification_and_is_not_silently_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'skill'; lock = Path(tmp) / 'skill-lock.json'
            version = skill_metadata(ROOT / 'skill')['version']
            sync_skill(ROOT / 'skill', target, lock, 'v' + version)
            extra = target / 'private-course.txt'; extra.write_text('private')
            with self.assertRaisesRegex(ValueError, 'private-course.txt'):
                verify_skill(target, lock)
            with self.assertRaises(ValueError):
                sync_skill(ROOT / 'skill', target, lock, 'v' + version)
            self.assertEqual(extra.read_text(), 'private')

    def test_consistent_local_lock_cannot_hide_a_different_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'skill'; lock = Path(tmp) / 'skill-lock.json'
            version = skill_metadata(ROOT / 'skill')['version']
            sync_skill(ROOT / 'skill', target, lock, 'v' + version)
            verify_skill(target, lock, ROOT / 'skill')
            (target / 'assets/app.js').write_text('local edited copy')
            pinned = json.loads(lock.read_text()); pinned.update(skill_metadata(target))
            lock.write_text(json.dumps(pinned))
            verify_skill(target, lock)
            with self.assertRaisesRegex(ValueError, '上游快照'):
                verify_skill(target, lock, ROOT / 'skill')

    def test_tag_must_match_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, '版本标签'):
                sync_skill(ROOT / 'skill', Path(tmp) / 'skill', Path(tmp) / 'lock', 'v0.0.0')


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.config = replace(Config(), api_key='test-only', model='test-only')
        raw = (ROOT / 'skill/tests/fixtures/general-source.txt').read_bytes()
        (self.root / 'input.txt').write_bytes(raw)
        self.manifest = {'title':'合成测试','mode':'auto','scope':'','files':[{'id':'s1','name':'input.txt','path':'input.txt','role':'textbook','primary':True,'usage':'primary','purpose':'按教材顺序解释字段与冲突','sha256':hashlib.sha256(raw).hexdigest()}]}

    def tearDown(self):
        self.tmp.cleanup()

    def run_course(self, model=FixtureModel):
        return Converter(self.config, model, browser_double).run(self.root, self.manifest, lambda *a,**k:None, lambda:False)

    def test_real_v2_binding_detects_body_question_answer_and_contract_changes(self):
        self.assertEqual(self.run_course()['status'], 'ready')
        original = json.loads((self.root / 'course.json').read_text())
        inventory = json.loads((self.root / 'source-inventory.json').read_text())
        pipeline = load_pipeline(self.config.skill_dir)
        self.assertEqual(original['schemaVersion'], 2)
        self.assertEqual(pipeline.audit_reviews(original, inventory)['status'], 'pass')
        edits = [lambda c:c['chapters'][0]['sections'][0]['blocks'][0].update(text='Changed'),
                 lambda c:c['questions'][0]['prompt'][0].update(text='Changed'),
                 lambda c:c['questions'][0]['answer']['blocks'][0].update(text='Changed'),
                 lambda c:c['taskContract'].update(goal='Changed')]
        for edit in edits:
            course = copy.deepcopy(original); edit(course)
            self.assertEqual(pipeline.audit_reviews(course, inventory)['status'], 'stale')

    def test_semantic_edit_after_review_cannot_be_rebound(self):
        base = json.loads((ROOT / 'skill/tests/fixtures/fusion.json').read_text())
        unit = {'sections':base['chapters'][0]['sections'],'questions':base['questions'],
                'coverage':base['coverage'],'learningMap':base['learningMap'],'exams':[]}
        receipt = _unit_receipt(unit, base['taskContract'], base['sources'])
        _verify_reviewed_units(base, [receipt])
        base['questions'][0]['answer']['blocks'][0]['text'] = 'Changed after review'
        with self.assertRaisesRegex(QualityProblem, '审校后改变'):
            _verify_reviewed_units(base, [receipt])

    def test_exam_merge_preserves_the_reviewed_unit_question_order(self):
        base = json.loads((ROOT / 'skill/tests/fixtures/fusion.json').read_text())
        exam = {'id':'e1','title':'合成卷','questionIds':['ex1','q1'],'instructions':[{'type':'paragraph','text':'保留原顺序'}]}
        base['exams'] = [copy.deepcopy(exam)]
        unit = {'sections':base['chapters'][0]['sections'],'questions':base['questions'],
                'coverage':base['coverage'],'learningMap':base['learningMap'],'exams':[exam]}
        receipt = _unit_receipt(unit, base['taskContract'], base['sources'])
        base['exams'][0]['questionIds'].append('later-unit-question')
        _verify_reviewed_units(base, [receipt])
        base['exams'][0]['questionIds'] = ['q1','ex1','later-unit-question']
        with self.assertRaisesRegex(QualityProblem, '公共题设或题序'):
            _verify_reviewed_units(base, [receipt])

    def test_no_primary_mixed_materials_do_not_choose_ppt_or_book(self):
        self.manifest['files'][0]['primary'] = False
        second = dict(self.manifest['files'][0], id='s2', role='teacher_slides')
        self.manifest['files'].append(second)
        constructed = []
        def factory(*args):
            constructed.append(True); return FixtureModel(*args)
        result = self.run_course(factory)
        self.assertEqual(result['status'], 'needs_attention')
        self.assertIn('明确主资料', result['message'])
        self.assertEqual(constructed, [])

    def test_textbook_primary_and_reference_slides_keep_explicit_purposes(self):
        raw = '旧模板仅供对照，不改变教材的缺失标记要求。'.encode()
        (self.root / 'reference.txt').write_bytes(raw)
        self.manifest['files'].append({'id':'s2','name':'reference.txt','path':'reference.txt',
            'role':'teacher_slides','primary':False,'usage':'reference','purpose':'只存档对照，不作为学习重点',
            'sha256':hashlib.sha256(raw).hexdigest()})
        class ReferenceSlides(FixtureModel):
            def ask(self, stage, instructions, data, images=()):
                result = super().ask(stage, instructions, data, images)
                if stage.startswith('inventory:') and data['source']['id'] == 's2':
                    result['items'] = [{'kind':'note','label':'旧模板','chapterHint':'第一章','summary':'旧模板仅存档，现行规则按教材','expectedParts':[]}]
                if stage.startswith('unit:'):
                    item = data['inventory'][-1]
                    result['sections'].append({'id':'u01_reference','title':'旧模板对照','sourceRefs':[{'sourceId':'s2','locator':item['locator']}],
                        'blocks':[{'type':'paragraph','text':'旧模板仅供对照，不改变教材的缺失标记要求。'}]})
                    result['coverage'].append({'sourceItemId':item['id'],'targets':['u01_reference'],'status':'covered'})
                    result['learningMap'].append({'sourceItemId':item['id'],'disposition':'reference-only','explanationTargets':['u01_reference'],
                        'summaryTargets':[],'emphasisTargets':[],'summaryNote':'明确仅对照','emphasisNote':'不加入重点','evidence':'按用户指定存档保留'})
                return result
        result = self.run_course(ReferenceSlides)
        self.assertEqual(result['status'], 'ready', result)
        course = json.loads((self.root / 'course.json').read_text())
        self.assertEqual(course['organization']['primarySourceIds'], ['s1'])
        self.assertEqual(course['organization']['mode'], 'textbook')
        uses = {r['sourceId']:r for r in course['taskContract']['sourceUses']}
        self.assertEqual(uses['s2']['usage'], 'reference')
        self.assertEqual(uses['s2']['purpose'], '只存档对照，不作为学习重点')
        self.assertEqual(course['learningMap'][-1]['disposition'], 'reference-only')

    def test_model_cannot_change_explicit_source_usage(self):
        class ChangeUse(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                if stage == 'plan':
                    result['taskContract']['sourceUses'][0]['usage'] = 'reference'
                return result
        self.assertEqual(self.run_course(ChangeUse)['status'], 'needs_attention')

    def test_model_cannot_claim_legacy_unit_without_fusion_map(self):
        class Legacy(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                if stage.startswith('unit:'):
                    result.pop('learningMap')
                return result
        self.assertEqual(self.run_course(Legacy)['status'], 'needs_attention')
        self.assertFalse((self.root / 'output/学习教材.html').exists())

    def test_source_changed_during_review_cannot_download(self):
        root = self.root
        class ChangeSource(FixtureModel):
            def ask(self, stage, *args, **kwargs):
                result = super().ask(stage, *args, **kwargs)
                if stage == 'global-review':
                    (root / 'input.txt').write_text('source changed')
                return result
        self.assertEqual(self.run_course(ChangeSource)['status'], 'needs_attention')
        self.assertFalse((self.root / 'output/学习教材.html').exists())

    def test_legacy_cache_cannot_supply_a_v2_result(self):
        cache = self.root / 'model-cache'; cache.mkdir()
        legacy = {'model':self.config.model,'stage':'same','instructions':'same rules','data':{},'images':[]}
        key = hashlib.sha256(json.dumps(legacy,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        (cache / (key + '.json')).write_text(json.dumps({'result':{'legacy':True}}))
        # Historical caches must retain their budget ledger. A missing ledger is
        # tested separately and must never reset the task's consumed calls.
        (self.root / 'model-usage.json').write_text(json.dumps({'calls': 1, 'usage': []}))
        class Opener:
            def open(self, request, timeout):
                return io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"new":true}'}]}]}).encode())
        with patch('urllib.request.build_opener', return_value=Opener()) as call:
            client = ResponsesModel(self.config, self.root)
            self.assertEqual(client.ask('same','same rules',{}), {'new':True})
            self.assertEqual(call.call_count, 1)
        self.assertTrue((cache / (key + '.json')).exists())
        self.assertEqual(json.loads((self.root / 'model-usage.json').read_text())['calls'], 2)


if __name__ == '__main__':
    unittest.main()
