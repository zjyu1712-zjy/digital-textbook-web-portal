"""Public, synthetic UI regression fixture; no course textbooks or private responses."""
import json,copy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'));import pipeline
def main(out):
 out=Path(out);d=pipeline.read(ROOT/'tests/fixtures/general.json');inv=pipeline.read(ROOT/'tests/fixtures/inventory.json');d['id']='synthetic-components';d['title']='组件测试 · 合成数据';d['scope']['description']='自编组件与边界测试，不来自任何真实教材。'
 s={'id':'k2','title':'公式、矩阵与表格组件','sourceRefs':[{'sourceId':'s1','locator':'自编组件测试扩展'}],'blocks':[{'type':'paragraph','text':'合成测试：x < 3 与 y > 1 应保留；<script>alert(1)</script> 是字面文字。'},{'type':'math','tex':r'\frac{1}{2}+\frac{1}{2}=1'},{'type':'matrix','rows':[['1','2'],['3','4']]},{'type':'table','columns':['列'+str(i)for i in range(12)],'rows':[['长表格单元'+str(i)for i in range(12)]]}]}
 d['chapters'].append({'id':'ch2','title':'合成组件测试','sections':[s]})
 fields=[{'id':'choice','kind':'choice','label':'单选','options':[{'value':'a','label':'选项A'},{'value':'b','label':'选项B'}]},{'id':'multiple','kind':'multiple','label':'多选','options':[{'value':'a','label':'多选A'},{'value':'b','label':'多选B'}]},{'id':'fill','kind':'fill','label':'填空'},{'id':'number','kind':'number','label':'数值'},{'id':'formula','kind':'formula','label':'公式'}]
 for kind in ['matrix','journal','table']:fields.append({'id':kind,'kind':kind,'label':kind,'columns':[{'label':'行标签','editable':False},'第1列','第2列'],'rows':[['行1','',''],['行2','','']]})
 q=copy.deepcopy(d['questions'][1]);q.update(id='components',number='合成测试1',title='多类型输入',origin='ai_supplement',chapterIds=['ch2'],knowledgeIds=['k2'],prompt=[{'type':'paragraph','text':'此题仅用于功能验证。请测试各输入类型，不对应教材原题。'}],parts=[{'id':'all','label':'所有组件','fields':fields}]);q['answer']['blocks']=[{'type':'paragraph','text':'仅用于输入恢复与自评；无唯一正确答案。'}];d['questions'].append(q)
 for id,target,kind,parts in [('i4','k2','lesson',[]),('i5','components','exercise',['all'])]:
  inv['items'].append({'id':id,'sourceId':'s1','locator':'自编组件测试扩展','kind':kind,'expectedParts':parts});d['coverage'].append({'sourceItemId':id,'targets':[target],'status':'covered'})
 d['semanticReviews'][0]['targetIds']+=['k2','components'];d['semanticReviews'][0]['evidence']+='；make_components.py显式自编组件'
 for name,book in [('components',d),('other',{**d,'id':'synthetic-other-book'}),('updated',copy.deepcopy(d))]:
  if name=='updated':book['version']='2';book['questions'][-1]['version']='2';book['questions'][-1]['answer']['version']='2';book['questions'][-1]['prompt']=[{'type':'paragraph','text':'内容版本2；旧作答快照应保留原题。'}]
  pipeline.build(book,inv,out/(name+'.html'),out)
 pipeline.write(out/'components.json',d);pipeline.write(out/'inventory.json',inv)
if __name__=='__main__':main(sys.argv[1])
