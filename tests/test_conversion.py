"""Contract tests use a clearly isolated model double, never a public demo mode."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
import urllib.request
import zipfile

from portal.config import Config
from portal.extract import InputProblem, extract_sources
from portal.model import ResponsesModel, ModelProblem, NoRedirect
from portal.runner import Converter, stabilize_ids

ROOT = Path(__file__).resolve().parents[1]


class FixtureModel:
    """Only for orchestration tests; assertions exercise real builder/validators."""
    def __init__(self, config, root, cancelled):
        self.calls = []

    def ask(self, stage, instructions, data, images=()):
        self.calls.append(stage)
        if stage.startswith('inventory:'):
            return {'readability':'clear','pageKind':'teaching','reason':'自编测试节选', 'issues':[], 'items':[
                {'kind':'lesson','label':'标签','chapterHint':'第一章','summary':'三个字段与缺失标记','expectedParts':[]},
                {'kind':'example','label':'例1-1','chapterHint':'第一章','summary':'S01 与 S10 冲突','expectedParts':['a']},
                {'kind':'exercise','label':'练习1','chapterHint':'第一章','summary':'字段与日期缺失','expectedParts':['a','b']} ]}
        if stage == 'plan':
            return {'title':'测试用标本记录','edition':'自编测试版','mode':'textbook','reason':'仅一本节选','disciplines':['general'],
                    'scopeDescription':'仅所上传的自编测试节选','completeness':'excerpt','issues':[], 'excluded':[],
                    'chapters':[{'id':'ch1','title':'第一章 标本标签','units':[{'id':'u01','itemIds':[i['id'] for i in data['inventory']]}]}]}
        if stage.startswith('unit:'):
            fixture = json.loads((ROOT/'skill/tests/fixtures/general.json').read_text())
            mapping = {'k1':'u01_k1','q1':'u01_q1','ex1':'u01_ex1'}
            fixture['chapters'][0]['sections'][0]['id'] = mapping['k1']
            for q in fixture['questions']:
                q['id'] = mapping[q['id']]
                q['knowledgeIds'] = ['u01_k1']
            for row, item in zip(fixture['coverage'], data['inventory']):
                row['sourceItemId'] = item['id']
                row['targets'] = [mapping[x] for x in row['targets']]
            return {'sections':fixture['chapters'][0]['sections'],'questions':fixture['questions'],'coverage':fixture['coverage'],'exams':[],'issues':[]}
        if stage.startswith('review:'):
            return {'pass':True,'reviewedItemIds':[i['id'] for i in data['context']['inventory']], 'evidence':'测试替身：核查三项来源，仅用于测试流程', 'issues':[]}
        if stage == 'global-review':
            return {'pass':True,'evidence':'测试替身：索引完整', 'issues':[]}
        if stage == 'visual-review':
            return {'pass':True,'scope':'测试替身，不代表实际视觉核查','evidence':'单元测试依赖注入','issues':[]}
        raise AssertionError(stage)


def browser_double(html, report, timeout):
    report.mkdir(parents=True, exist_ok=True)
    shot = report/'test.png'
    shot.write_bytes(b'test-only-not-a-real-screenshot')
    return {'status':'pass','checks':[{'name':'injected browser test double','status':'pass'}], 'screenshots':[str(shot)], 'detail':'TEST DOUBLE'}


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = replace(Config(), api_key='test-only', model='test-model')
        content = (ROOT/'skill/tests/fixtures/general-source.txt').read_bytes()
        (self.root/'input.txt').write_bytes(content)
        self.manifest = {'id':'test','title':'测试','mode':'auto','scope':'','files':[{'id':'s1','name':'input.txt','path':'input.txt','role':'textbook','primary':True,'sha256':hashlib.sha256(content).hexdigest()}]}
    def tearDown(self):
        self.temp.cleanup()
    def run_conversion(self, model=FixtureModel, browser=browser_double):
        return Converter(self.config,model,browser).run(self.root,self.manifest,lambda *a,**kw:None,lambda:False)
    def test_full_flow_real_builder_with_explicit_model_and_browser_doubles(self):
        self.assertNotIn('modelProvider', self.manifest)
        r=self.run_conversion()
        self.assertEqual(r['status'],'ready',r)
        self.assertNotIn('modelProvider', self.manifest)
        self.assertTrue((self.root/r['artifact']).is_file())
        course=json.loads((self.root/'course.json').read_text())
        self.assertEqual(len(course['questions']),2)
        self.assertEqual(course['scope']['completeness'],'excerpt')
        self.assertTrue(course['version'].startswith('v-'))
        self.assertTrue((self.root/'full-source-inventory.json').exists())
        self.assertTrue((self.root/'checks/browser-final.json').exists())
    def test_stable_question_ids_do_not_depend_on_processing_unit_name(self):
        a=json.loads((ROOT/'skill/tests/fixtures/general.json').read_text())
        b=copy.deepcopy(a)
        b['questions'][0]['id']='another_processing_unit_example'
        b['coverage'][1]['targets']=['another_processing_unit_example']
        b['semanticReviews'][0]['targetIds'][1]='another_processing_unit_example'
        stabilize_ids(a);stabilize_ids(b)
        self.assertEqual(a['questions'][0]['id'],b['questions'][0]['id'])
        self.assertEqual(a['coverage'],b['coverage'])
    def test_bailian_provenance_in_finished_course(self):
        self.config=replace(self.config,provider='bailian',bailian_workspace_id='test-space')
        self.manifest['modelProvider']='bailian'
        result=self.run_conversion()
        self.assertEqual(result['status'],'ready',result)
        course=json.loads((self.root/'course.json').read_text())
        self.assertTrue(all(r['reviewer']=='阿里云百炼/test-model' for r in course['semanticReviews']))
        self.assertIn('阿里云百炼',course['acceptance'][0]['text'])
        self.assertNotIn('OpenAI',course['acceptance'][0]['text'])
    def test_direct_converter_rejects_provider_change_before_model_construction(self):
        constructed=[]
        def model_factory(*args):
            constructed.append(args[0].provider)
            return FixtureModel(*args)
        self.config=replace(self.config,provider='bailian',bailian_workspace_id='test-space')
        for recorded in ('missing', 'openai', None, 'unknown'):
            with self.subTest(recorded=recorded):
                if recorded == 'missing':
                    self.manifest.pop('modelProvider', None)
                else:
                    self.manifest['modelProvider']=recorded
                before=copy.deepcopy(self.manifest)
                result=self.run_conversion(model_factory)
                self.assertEqual(result['status'],'needs_attention')
                self.assertIn('重新上传',result['message'])
                self.assertNotIn('artifact',result)
                self.assertEqual(self.manifest,before)
        self.assertEqual(constructed,[])
    def test_unclear_page_blocks_generation(self):
        class Unclear(FixtureModel):
            def ask(self,stage,*a,**kw):
                result=super().ask(stage,*a,**kw)
                if stage.startswith('inventory:'):result['readability']='uncertain'
                return result
        r=self.run_conversion(Unclear)
        self.assertEqual(r['status'],'needs_attention')
        self.assertNotIn('artifact',r)
    def test_inventory_omission_in_plan_blocks(self):
        class Omit(FixtureModel):
            def ask(self,stage,*a,**kw):
                result=super().ask(stage,*a,**kw)
                if stage=='plan':result['chapters'][0]['units'][0]['itemIds'].pop()
                return result
        self.assertEqual(self.run_conversion(Omit)['status'],'needs_attention')
    def test_unauthorized_scope_exclusion_blocks(self):
        class Exclude(FixtureModel):
            def ask(self,stage,*a,**kw):
                result=super().ask(stage,*a,**kw)
                if stage=='plan':result['excluded']=[{'itemId':result['chapters'][0]['units'][0]['itemIds'].pop(),'reason':'过长'}]
                return result
        self.assertEqual(self.run_conversion(Exclude)['status'],'needs_attention')
    def test_missing_subquestion_repaired_then_retested(self):
        class Repair(FixtureModel):
            attempts=0
            def ask(self,stage,*a,**kw):
                result=super().ask(stage,*a,**kw)
                if stage.startswith('unit:'):
                    type(self).attempts+=1
                    if type(self).attempts==1:result['questions'][1]['parts'].pop()
                return result
        self.assertEqual(self.run_conversion(Repair)['status'],'ready')
        self.assertEqual(Repair.attempts,2)
    def test_repeated_bad_source_stops_after_three_and_never_downloads(self):
        class Broken(FixtureModel):
            attempts=0
            def ask(self,stage,*a,**kw):
                result=super().ask(stage,*a,**kw)
                if stage.startswith('unit:'):
                    type(self).attempts+=1
                    result['questions'][1]['parts'].pop()
                return result
        self.assertEqual(self.run_conversion(Broken)['status'],'needs_attention')
        self.assertEqual(Broken.attempts,3)
    def test_unreviewed_item_cannot_pass(self):
        class Review(FixtureModel):
            def ask(self,stage,*a,**kw):
                result=super().ask(stage,*a,**kw)
                if stage.startswith('review:'):result['reviewedItemIds'].pop()
                return result
        self.assertEqual(self.run_conversion(Review)['status'],'needs_attention')
    def test_unavailable_browser_cannot_download(self):
        result=self.run_conversion(browser=lambda *a:{'status':'unverified','detail':'missing browser'})
        self.assertEqual(result['status'],'needs_attention')
        self.assertNotIn('artifact',result)
    def test_final_retest_failure_cannot_download(self):
        count=[]
        def check(*args):
            count.append(1)
            return browser_double(*args) if len(count)==1 else {'status':'fail','detail':'regression'}
        self.assertEqual(self.run_conversion(browser=check)['status'],'needs_attention')
    def test_tampered_input_is_blocked(self):
        (self.root/'input.txt').write_text('changed')
        self.assertEqual(self.run_conversion()['status'],'needs_attention')
    def test_cancelled_task_stops(self):
        r=Converter(self.config,FixtureModel,browser_double).run(self.root,self.manifest,lambda *a,**kw:None,lambda:True)
        self.assertEqual(r['status'],'needs_attention')
    def test_text_pages_are_not_silently_truncated(self):
        text=('一段正文\n'*1000+'\n')*3
        (self.root/'input.txt').write_text(text)
        self.manifest['files'][0]['sha256']=hashlib.sha256(text.encode()).hexdigest()
        with self.assertRaises(InputProblem):extract_sources(self.root,self.manifest,max_pages=1)
    def test_office_notes_require_pdf_instead_of_silent_omission(self):
        p=self.root/'input.docx'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('word/document.xml','<document><p><t>正文</t></p></document>')
            z.writestr('word/footnotes.xml','<notes>重要条件</notes>')
        self.manifest['files'][0].update(name=p.name,path=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        with self.assertRaisesRegex(InputProblem,'脚注'):extract_sources(self.root,self.manifest)
    def test_pdf_original_pages_render_with_locators(self):
        try:
            from pypdf import PdfWriter
            import pypdfium2
        except ImportError:self.skipTest('PDF runtime not installed')
        pdf=self.root/'input.pdf'
        writer=PdfWriter();writer.add_blank_page(width=612,height=792);writer.write(pdf)
        self.manifest['files'][0].update(name=pdf.name,path=pdf.name,sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
        data=extract_sources(self.root,self.manifest)
        self.assertEqual(data['pages'][0]['locator'],'PDF 物理页 1')
        self.assertTrue((self.root/data['pages'][0]['image']).is_file())
    def test_pptx_uses_presentation_order_not_creation_filenames(self):
        p=self.root/'reordered.pptx'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="2" r:id="r2"/><p:sldId id="1" r:id="r1"/></p:sldIdLst></p:presentation>')
            z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/><Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>')
            z.writestr('ppt/slides/slide1.xml','<slide><p><t>应当在第二页</t></p></slide>')
            z.writestr('ppt/slides/slide2.xml','<slide><p><t>应当在第一页</t></p></slide>')
        self.manifest['files'][0].update(name=p.name,path=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        data=extract_sources(self.root,self.manifest)
        self.assertIn('第一页',data['pages'][0]['text'])
        self.assertIn('第二页',data['pages'][1]['text'])


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=replace(Config(),api_key='only-test',model='test-model')
    def tearDown(self):self.tmp.cleanup()
    def opener(self, response):
        class Opener:
            def open(self,request,timeout):
                self.request=request
                return io.BytesIO(json.dumps(response).encode())
        return Opener()
    def test_completed_result_cached_and_store_disabled(self):
        opener=self.opener({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]})
        with patch('urllib.request.build_opener',return_value=opener) as mocked:
            client=ResponsesModel(self.config,self.root)
            self.assertTrue(client.ask('test','rules',{})['ok'])
            self.assertTrue(client.ask('test','rules',{})['ok'])
            self.assertEqual(mocked.call_count,1)
            self.assertFalse(json.loads(opener.request.data)['store'])
            self.assertEqual(opener.request.full_url,'https://api.openai.com/v1/responses')
    def test_truncated_response_is_not_used(self):
        with patch('urllib.request.build_opener',return_value=self.opener({'status':'incomplete'})):
            with self.assertRaisesRegex(ModelProblem,'完整'):ResponsesModel(self.config,self.root).ask('a','rules',{})
    def test_refusal_is_not_empty_success(self):
        response={'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'no'}]}]}
        with patch('urllib.request.build_opener',return_value=self.opener(response)):
            with self.assertRaises(ModelProblem):ResponsesModel(self.config,self.root).ask('a','rules',{})
    def test_budget_persists_across_resume(self):
        (self.root/'model-usage.json').write_text('{"calls":1200,"usage":[]}')
        with self.assertRaisesRegex(ModelProblem,'限额'):ResponsesModel(self.config,self.root).ask('a','rules',{})
    def test_redirect_never_carries_secret_to_second_host(self):
        with self.assertRaises(ModelProblem):
            NoRedirect().redirect_request(urllib.request.Request('https://api.openai.com/v1/responses'),None,302,'',{},'https://elsewhere.invalid')


if __name__=='__main__':unittest.main()
