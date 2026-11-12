"""Offline build helpers; structural validation does not establish semantic correctness."""
from pathlib import Path
import argparse,base64,copy,hashlib,html,json,mimetypes,os,re,shutil,subprocess,sys
from html.parser import HTMLParser
from task_contract import classify,validate_contract
from review_audit import validate_learning_map,review_fingerprint,audit_reviews
from grading import validate_grading
from independent_audit import create_plan,review_packet,audit_independent
from chapter_status import chapter_binding,chapter_status,validate_chapter_checks
SKILL=Path(__file__).resolve().parents[1]
MODES={'textbook','slides','outline','combined'}
DISCIPLINES={'math','theory','models','accounting','statistics','general'}
FIELDS={'text','fill','number','choice','multiple','formula','matrix','journal','table'}
BLOCKS={'paragraph','heading','list','math','matrix','table','image','details','diagram'}
ORIGINS={'textbook_example','textbook_exercise','teacher_exercise','exam','auxiliary_exercise','ai_supplement'}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,d):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def stable(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def walk_blocks(bs):
 for b in bs:
  yield b
  if b.get('type')=='details':yield from walk_blocks(b.get('blocks',[]))
def all_blocks(d):
 for c in d.get('chapters',[]):
  for s in c.get('sections',[]):yield from walk_blocks(s.get('blocks',[]))
 for q in d.get('questions',[]):
  yield from walk_blocks(q.get('prompt',[]));yield from walk_blocks(q.get('answer',{}).get('blocks',[]))
 for e in d.get('exams',[]):yield from walk_blocks(e.get('instructions',[]))
def substantive(bs):return any(b.get('text','').strip() or any(r.get('text')or r.get('tex')for r in b.get('runs',[])) or b.get('tex') or b.get('rows') or b.get('items') or b.get('path') or b.get('lines') for b in walk_blocks(bs) if b.get('type')!='heading')
def validate(d,inv):
 e=[];ids={};targets={};questions={};sources={s.get('id'):s for s in d.get('sources',[])}
 def ident(o,kind):
  k=o.get('id')
  if not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,180}',k):e.append(f'{kind}: invalid ID')
  elif k in ids:e.append('duplicate ID '+k)
  else:ids[k]=kind
 def refs(rs,label,required=True):
  if required and not rs:e.append(label+': missing source references')
  for r in rs or []:
   if r.get('sourceId') not in sources or not r.get('locator'):e.append(label+': invalid source locator')
 if d.get('schemaVersion')not in (1,2):e.append('unsupported schemaVersion')
 ident(d,'book')
 if not all(d.get(k)for k in ['title','edition','version']):e.append('book metadata incomplete')
 for s in d.get('sources',[]):
  ident(s,'source')
  if not all(s.get(k)for k in ['title','role','identity','sha256','locator']):e.append('source metadata incomplete')
 org=d.get('organization',{})
 if org.get('mode') not in MODES or not org.get('reason'):e.append('material mode/reason required')
 if not org.get('primarySourceIds') or any(x not in sources for x in org.get('primarySourceIds',[])):e.append('primary sources invalid')
 if not d.get('disciplines') or not set(d['disciplines'])<=DISCIPLINES:e.append('discipline invalid')
 if d.get('scope',{}).get('completeness') not in ('excerpt','complete','incomplete') or not d.get('scope',{}).get('description'):e.append('scope required')
 chids={c.get('id')for c in d.get('chapters',[])};sids={s.get('id')for c in d.get('chapters',[])for s in c.get('sections',[])}
 for c in d.get('chapters',[]):
  ident(c,'chapter')
  if not c.get('sections'):e.append('empty chapter')
  for s in c.get('sections',[]):
   ident(s,'section');targets[s.get('id')]=s
   if not substantive(s.get('blocks',[])):e.append(str(s.get('id'))+': title without body')
   refs(s.get('sourceRefs'),str(s.get('id')))
 for q in d.get('questions',[]):
  ident(q,'question');targets[q.get('id')]=q;questions[q.get('id')]=q
  if not substantive(q.get('prompt',[])):e.append('problem statement absent')
  if q.get('origin') not in ORIGINS:e.append('question origin invalid')
  if not q.get('version') or not q.get('number'):e.append('question version/number missing')
  if not q.get('chapterIds') or not set(q['chapterIds'])<=chids:e.append('chapter mapping invalid')
  if not set(q.get('knowledgeIds',[]))<=sids:e.append('knowledge link invalid')
  refs(q.get('sourceRefs'),str(q.get('id')),q.get('origin')!='ai_supplement')
  ps=set();fs=set()
  for part in q.get('parts',[]):
   if not part.get('id') or part['id'] in ps:e.append('subquestion ID missing/duplicated')
   ps.add(part.get('id'))
   if not part.get('fields'):e.append('subquestion not answerable')
   for f in part.get('fields',[]):
    if not f.get('id') or f.get('id')in fs or not f.get('label') or f.get('kind')not in FIELDS:e.append('invalid answer field')
    fs.add(f.get('id'))
    if f.get('kind')in ('choice','multiple')and not f.get('options'):e.append('choice options absent')
    if f.get('kind')in ('matrix','journal','table')and(not f.get('columns')or not f.get('rows')):e.append('table shape absent')
  if not ps:e.append('question has no parts')
  a=q.get('answer',{})
  if a.get('provenance')not in ('original','teacher','unconfirmed','ai')or not a.get('version'):e.append('answer provenance/version required')
  if a.get('status')not in ('ready','pending','missing'):e.append('answer status required')
  if a.get('status')=='ready'and not substantive(a.get('blocks',[])):e.append('ready answer lacks solution')
  refs(a.get('sourceRefs',[]),'answer '+str(q.get('id')),a.get('provenance')in ('original','teacher'))
  e.extend(validate_grading(q))
 for b in all_blocks(d):
  t=b.get('type')
  if t not in BLOCKS:e.append('unsupported block '+str(t))
  if t=='math'and not b.get('tex'):e.append('empty formula')
  if t=='paragraph'and 'runs'in b:
   if not isinstance(b['runs'],list)or any(r.get('type')not in ('text','math')or not r.get('text'if r.get('type')=='text'else'tex')for r in b['runs']):e.append('invalid inline paragraph')
  if t=='matrix'and(not b.get('rows')or len({len(r)for r in b['rows']})!=1):e.append('ragged matrix')
  if t=='image'and(not b.get('alt')or not b.get('path')or re.match(r'^(?:\w+:|//)',b.get('path',''))):e.append('image requires local path and alt')
  if t=='image'and d.get('schemaVersion')==2 and not re.fullmatch(r'[0-9a-f]{64}',str(b.get('sha256',''))):e.append('v2 image requires actual sha256 digest')
  if t=='table'and(not b.get('columns')or any(len(r)!=len(b['columns'])for r in b.get('rows',[]))):e.append('table column count mismatch')
 for ex in d.get('exams',[]):
  ident(ex,'exam')
  if not ex.get('questionIds')or any(x not in questions or questions[x]['origin']!='exam'for x in ex['questionIds']):e.append('exam membership invalid')
 cover={};reviewed=set();itemids=set()
 for row in d.get('coverage',[]):
  if row.get('sourceItemId')in cover:e.append('duplicate coverage record')
  cover[row.get('sourceItemId')]=row
 for r in d.get('semanticReviews',[]):
  if r.get('result')=='pass'and all(r.get(k)for k in ('reviewer','method','evidence')):reviewed.update(r.get('targetIds',[]))
 for item in inv.get('items',[]):
  k=item.get('id')
  if k in itemids:e.append('duplicate source item')
  itemids.add(k);refs([{'sourceId':item.get('sourceId'),'locator':item.get('locator')}],str(k))
  row=cover.get(k,{})
  if row.get('status')!='covered'or not row.get('targets'):e.append(str(k)+': not covered');continue
  actual=set()
  for tid in row['targets']:
   if tid not in targets:e.append(str(k)+': nonexistent target '+str(tid));continue
   if tid not in reviewed:e.append(str(tid)+': semantic review not recorded')
   actual.update(p.get('id')for p in targets[tid].get('parts',[]))
  if not set(item.get('expectedParts',[]))<=actual:e.append(str(k)+': omitted subquestions')
 if not itemids:e.append('independent source inventory missing')
 if set(cover)-itemids:e.append('ungrounded inventory entries')
 if d.get('schemaVersion')==2:
  e.extend(validate_contract(d));e.extend(validate_learning_map(d,inv));e.extend(audit_reviews(d,inv)['errors'])
 elif any(r.get('binding')for r in d.get('semanticReviews',[])if isinstance(r,dict)):
  e.extend(audit_reviews(d,inv)['errors'])
 e.extend(validate_chapter_checks(d,inv))
 independent=d.get('independentReview')
 required=isinstance(independent,dict)and independent.get('required')is True
 if isinstance(independent,dict)and 'required'in independent and type(independent['required'])is not bool:e.append('independentReview.required must be boolean')
 sampled=audit_independent(d,inv,required=required)
 e.extend(sampled['errors'])
 if sampled['status']in ('failed','invalid','stale')or(required and sampled['status']!='sampled-pass'):e.append('independent review: '+sampled['status'])
 return list(dict.fromkeys(e))
def checkpoint(d):
 shared={k:d.get(k)for k in ['organization','taskContract','disciplines','sources','edition','preferencesVersion']}
 return {c['id']:hashlib.sha256(stable({'shared':shared,'chapter':c,'questions':[q for q in d.get('questions',[])if c['id']in q['chapterIds']]}).encode()).hexdigest()for c in d['chapters']}
def changed(a,b):return sorted(k for k in a.keys()|b.keys()if a.get(k)!=b.get(k))
def math_expressions(d):
 for b in all_blocks(d):
  if b['type']=='math':yield b['tex']
  elif b['type']=='paragraph':
   for run in b.get('runs',[]):
    if run['type']=='math':yield run['tex']
  elif b['type']=='matrix':yield r'\begin{pmatrix}'+r'\\'.join('&'.join(str(c)for c in row)for row in b['rows'])+r'\end{pmatrix}'
def inspect_html(path):
 class Check(HTMLParser):
  def __init__(self):super().__init__();self.errors=[]
  def handle_starttag(self,tag,attrs):
   a=dict(attrs)
   for k in ('src','href','poster'):
    v=a.get(k,'')
    if v and not v.startswith(('data:','#')):self.errors.append('external resource '+v[:100])
   if any(k.startswith('on')for k in a):self.errors.append('inline event handler')
 p=Check();s=Path(path).read_text(encoding="utf-8");p.feed(s)
 for u in re.findall(r'url\(([^)]+)\)',s):
  if not u.strip('"\' ').startswith(('data:','#')):p.errors.append('external CSS URL '+u[:80])
 return p.errors
def embedded_math_css():
 css=(SKILL/'assets/vendor/katex.min.css').read_text(encoding='utf-8')
 def font_sources(match):
  # All supported browsers read WOFF2; keep one bundled source per face.
  urls=re.findall(r'url\(([^)]+)\)',match.group(1))
  names=[Path(url.strip('"\' ')).name for url in urls]
  names=[name for name in names if name.endswith('.woff2')]
  if len(names)!=1:raise ValueError('font face requires exactly one bundled WOFF2 source')
  p=SKILL/'assets/vendor'/names[0]
  if not p.is_file():raise ValueError('missing font '+names[0])
  encoded=base64.b64encode(p.read_bytes()).decode()
  return 'src:url(data:font/woff2;base64,'+encoded+') format("woff2")'
 return re.sub(r'src:([^;}]+)',font_sources,css)
def build(data,inventory,dest,asset_root,allow_incomplete=False,node=None):
 d=copy.deepcopy(data);errors=validate(d,inventory)
 if errors and not allow_incomplete:raise ValueError('\n'.join(errors))
 if errors:d['scope']['completeness']='incomplete'
 d['validation']={'structuralErrors':errors,'sourceItems':len(inventory['items']),'counts':{k:sum(q['origin']==k for q in d['questions'])for k in sorted(ORIGINS)},'assurance':audit_reviews(d,inventory),'independent':audit_independent(d,inventory),'chapterStatus':chapter_status(d,inventory),'note':'结构和审校时效验证不证明学术正确；语义核查仍须实际对读。'};d['sourceInventory']=inventory
 expressions=list(math_expressions(d))
 if expressions:
  n=node or os.environ.get('NODE_BINARY')or shutil.which('node')
  if not n:raise ValueError('需Node验证公式；未完成公式核验，停止交付')
  r=subprocess.run([n,str(SKILL/'scripts/check_math.cjs'),str(SKILL/'assets/vendor/katex.min.js')],input=json.dumps(expressions),text=True,encoding="utf-8",capture_output=True)
  if r.returncode:raise ValueError('formula validation failed: '+r.stderr)
 root=Path(asset_root).resolve()
 for b in all_blocks(d):
  if b['type']=='image':
   p=(root/b['path']).resolve()
   if not p.is_relative_to(root):raise ValueError('asset outside approved input root')
   mime=mimetypes.guess_type(str(p))[0]
   if mime not in ('image/png','image/jpeg','image/webp','image/gif'):raise ValueError('image must be local raster; use structured diagram for SVG')
   if d.get('schemaVersion')==2 and sha(p)!=b.get('sha256'):raise ValueError('image content changed: update image sha256 and re-review '+str(b['path']))
   b['data']='data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()
 css=embedded_math_css()
 payload=json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
 values={'TITLE':html.escape(d['title']),'CSS':css+'\n'+'\n'.join((SKILL/'assets'/f).read_text(encoding="utf-8")for f in ['style.css','mistakes.css','quality.css']),'DATA':payload,'JS':'\n'.join((SKILL/'assets'/f).read_text(encoding="utf-8")for f in ['vendor/katex.min.js','storage.js','grading.js','mistakes.js','quality.js','app.js'])}
 shell=(SKILL/'assets/shell.html').read_text(encoding="utf-8")
 for k,v in values.items():shell=shell.replace('@@'+k+'@@',v)
 dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(shell,encoding="utf-8")
 issues=inspect_html(dest)
 if issues:raise ValueError('packaging validation: '+str(issues))
 return d['validation']
def inventory_files(paths):
 rows=[]
 for name in paths:
  p=Path(name).resolve()
  if not p.is_file():raise ValueError('仅接收明确文件路径，不自动扫描目录：'+str(p))
  if re.search(r'cookie|secret|credential|token|\.env',p.name,re.I):raise ValueError('排除疑似凭证文件')
  rows.append({'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p),'role':'unclassified','identity':'pending content inspection'})
 return rows
def main():
 for stream in (sys.stdout,sys.stderr):
  if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
 ap=argparse.ArgumentParser(description=__doc__);sp=ap.add_subparsers(dest='cmd',required=True)
 a=sp.add_parser('inventory');a.add_argument('files',nargs='+');a.add_argument('--out',required=True)
 a=sp.add_parser('classify');a.add_argument('input');a.add_argument('--chapter');a.add_argument('--out',required=True)
 for cmd in ('review-state','review-binding'):
  a=sp.add_parser(cmd);a.add_argument('course');a.add_argument('--inventory',required=True);a.add_argument('--out',required=True)
  if cmd=='review-binding':a.add_argument('--targets',nargs='+',required=True)
 for cmd in ('independent-plan','independent-packet','independent-state','chapter-state','chapter-binding'):
  a=sp.add_parser(cmd);a.add_argument('course');a.add_argument('--inventory',required=True);a.add_argument('--out',required=True)
  if cmd=='independent-plan':
   a.add_argument('--producer',required=True);a.add_argument('--minimum-per-group',type=int,default=1);a.add_argument('--extra-items',nargs='*')
  if cmd=='independent-packet':
   a.add_argument('--plan',required=True);a.add_argument('--phase',choices=['source','compare'],default='source');a.add_argument('--source-read');a.add_argument('--sample')
  if cmd=='independent-state':a.add_argument('--required',action='store_true')
  if cmd=='chapter-binding':a.add_argument('--chapter',required=True)
 for cmd in ('validate','build'):
  a=sp.add_parser(cmd);a.add_argument('course');a.add_argument('--inventory',required=True);a.add_argument('--out',required=True)
  if cmd=='build':a.add_argument('--assets',default='.');a.add_argument('--allow-incomplete',action='store_true');a.add_argument('--node')
 a=sp.add_parser('inspect');a.add_argument('html')
 a=sp.add_parser('checkpoint');a.add_argument('course');a.add_argument('--out',required=True);a.add_argument('--previous')
 args=ap.parse_args()
 try:
  if args.cmd=='inventory':write(args.out,inventory_files(args.files))
  elif args.cmd=='classify':
   d=read(args.input);write(args.out,classify(d['sources'],d.get('evidence',[]),organization=d.get('organization'),contract=d.get('taskContract'),chapter_id=args.chapter))
  elif args.cmd=='review-state':
   report=audit_reviews(read(args.course),read(args.inventory));write(args.out,report);print(json.dumps({'status':report['status']},ensure_ascii=False));return 1 if report.get('errors')else(0 if report['status']=='pass'else(2 if report['status']=='legacy-unverified'else 1))
  elif args.cmd=='review-binding':
   fingerprint=review_fingerprint(read(args.course),read(args.inventory),args.targets)
   write(args.out,{'targetIds':args.targets,'binding':{'version':1,'fingerprint':fingerprint},'note':'仅计算当前内容指纹，不创建审查结论；实际核查完成后才可将绑定写入对应审校记录。'})
  elif args.cmd=='independent-plan':
   write(args.out,create_plan(read(args.course),read(args.inventory),args.producer,args.minimum_per_group,args.extra_items))
  elif args.cmd=='independent-packet':
   write(args.out,review_packet(read(args.course),read(args.inventory),read(args.plan),phase=args.phase,source_read=read(args.source_read)if args.source_read else None,sample_id=args.sample))
  elif args.cmd=='independent-state':
   report=audit_independent(read(args.course),read(args.inventory),required=args.required);write(args.out,report);print(json.dumps({'status':report['status'],'selectedCount':report['selectedCount'],'reviewedCount':report['reviewedCount']},ensure_ascii=False));return 0 if report['status']=='sampled-pass'else(2 if report['status']in ('not-reviewed','pending')and not report['required'] else 1)
  elif args.cmd=='chapter-binding':
   write(args.out,{'chapterId':args.chapter,'binding':chapter_binding(read(args.course),read(args.inventory),args.chapter),'note':'仅计算绑定，不生成验收结论。实际测试后记录检查范围、文件摘要与证据。'})
  elif args.cmd=='chapter-state':
   report=chapter_status(read(args.course),read(args.inventory));write(args.out,report);print(json.dumps({'chapters':len(report['chapters']),'errors':report['errors'],'note':report['note']},ensure_ascii=False));return bool(report['errors'])
  elif args.cmd=='validate':
   d=read(args.course);inv=read(args.inventory);e=validate(d,inv);write(args.out,{'errors':e,'structuralPass':not e,'assurance':audit_reviews(d,inv),'independent':audit_independent(d,inv),'chapterStatus':chapter_status(d,inv),'semanticMeaning':'结构及审校时效通过不等于学术正确；旧v1自由文本记录不证明本轮审校完成'});print(json.dumps({'errors':e},ensure_ascii=False));return bool(e)
  elif args.cmd=='build':print(json.dumps(build(read(args.course),read(args.inventory),args.out,args.assets,args.allow_incomplete,args.node),ensure_ascii=False))
  elif args.cmd=='inspect':
   e=inspect_html(args.html);print(json.dumps(e,ensure_ascii=False));return bool(e)
  elif args.cmd=='checkpoint':
   a=checkpoint(read(args.course));print(json.dumps({'affected':changed(read(args.previous),a)if args.previous else list(a)},ensure_ascii=False));write(args.out,a)
 except (ValueError,KeyError,OSError,json.JSONDecodeError)as e:print(str(e),file=sys.stderr);return 1
 return 0
if __name__=='__main__':sys.exit(main())
