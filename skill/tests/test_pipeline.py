import sys, json, copy, unittest, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pipeline as p

def sample():
 return json.loads((Path(__file__).parent/'fixtures/general.json').read_text())
def inventory():
 return json.loads((Path(__file__).parent/'fixtures/inventory.json').read_text())
class PipelineTests(unittest.TestCase):
 def test_valid_small_excerpt(self):self.assertEqual(p.validate(sample(),inventory()),[])
 def test_empty_body_not_coverage(self):
  d=sample();d['chapters'][0]['sections'][0]['blocks']=[]
  self.assertTrue(p.validate(d,inventory()))
 def test_missing_example_detected(self):
  d=sample();d['questions']=d['questions'][1:]
  self.assertTrue(p.validate(d,inventory()))
 def test_missing_subquestion_detected(self):
  d=sample();d['questions'][1]['parts'].pop()
  self.assertTrue(p.validate(d,inventory()))
 def test_duplicate_id(self):
  d=sample();d['questions'][1]['id']=d['questions'][0]['id']
  self.assertTrue(p.validate(d,inventory()))
 def test_official_answer_requires_source(self):
  d=sample();d['questions'][1]['answer']['provenance']='original'
  self.assertTrue(p.validate(d,inventory()))
 def test_missing_semantic_review_not_complete(self):
  d=sample();d['semanticReviews']=[]
  self.assertTrue(p.validate(d,inventory()))
 def test_unsupported_field_rejected(self):
  d=sample();d['questions'][1]['parts'][0]['fields'][0]['kind']='javascript'
  self.assertTrue(p.validate(d,inventory()))
 def test_unmapped_outline_item(self):
  i=inventory();i['items'].append({'id':'unmapped','sourceId':'s1','locator':'p.3','kind':'theorem','expectedParts':[]})
  self.assertTrue(p.validate(sample(),i))
 def test_foreign_resource_rejected(self):
  d=sample();d['chapters'][0]['sections'][0]['blocks']=[{'type':'image','path':'https://example.org/private.png','alt':'图'}]
  self.assertTrue(p.validate(d,inventory()))
 def test_source_boundary(self):
  d=sample();d['questions'][0]['sourceRefs'][0]['sourceId']='absent'
  self.assertTrue(p.validate(d,inventory()))
 def test_classification_no_course_name_hardcoding(self):
  self.assertEqual(p.classify([{'role':'textbook'}],['定义','标本'])['materialMode'],'textbook')
  self.assertEqual(p.classify([{'role':'teacher_slides','primary':True},{'role':'textbook'}],['均衡','坐标'])['materialMode'],'slides')
  self.assertIn('general',p.classify([{'role':'textbook'}],['标本'])['disciplines'])
 def test_sample_tracking_is_not_statistics(self):
  self.assertEqual(p.classify([{'role':'textbook'}],['给每个样本编唯一编号，保留采集日期。'])['disciplines'],['general'])
 def test_invalid_formula_fails_build(self):
  d=sample();d['chapters'][0]['sections'][0]['blocks'].append({'type':'math','tex':'\\notARealCommand{','display':True})
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):p.build(d,inventory(),Path(td)/'bad.html',Path(td))
 def test_inline_formula_preserves_paragraph_and_is_validated(self):
  d=sample();d['chapters'][0]['sections'][0]['blocks']=[{'type':'paragraph','runs':[{'type':'text','text':'当 '},{'type':'math','tex':'x<3'},{'type':'text','text':' 时成立。'}]}]
  self.assertEqual(p.validate(d,inventory()),[])
  self.assertIn('x<3',list(p.math_expressions(d)))
  d['chapters'][0]['sections'][0]['blocks'][0]['runs'][1]['tex']='\\notARealCommand{'
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):p.build(d,inventory(),Path(td)/'bad-inline.html',Path(td))
 def test_pack_escapes_script_and_embeds_resources(self):
  d=sample();d['title']='</script><script>alert(1)</script>'
  with tempfile.TemporaryDirectory() as td:
   dest=Path(td)/'out.html';p.build(d,inventory(),dest,Path(td));h=dest.read_text()
   self.assertNotIn(d['title'],h);self.assertIn('data:font/woff2;base64,',h)
   self.assertEqual(p.inspect_html(dest),[])
 def test_checkpoint_changes_only_affected_chapter(self):
  d=sample();a=p.checkpoint(d);d['chapters'][0]['sections'][0]['blocks'][0]['text']+='补充'
  self.assertEqual(p.changed(a,p.checkpoint(d)),['ch1'])
if __name__=='__main__':unittest.main(verbosity=2)
