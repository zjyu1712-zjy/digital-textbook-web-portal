"""Offline build helpers; structural validation does not establish semantic correctness."""
from pathlib import Path
import argparse,base64,copy,hashlib,html,json,mimetypes,os,re,shutil,subprocess,sys
from html.parser import HTMLParser
SKILL=Path(__file__).resolve().parents[1]
MODES={'textbook','slides','outline','combined'}
DISCIPLINES={'math','theory','models','accounting','statistics','general'}
FIELDS={'text','fill','number','choice','multiple','formula','matrix','journal','table'}
BLOCKS={'paragraph','heading','list','math','matrix','table','image','details','diagram'}
ORIGINS={'textbook_example','textbook_exercise','teacher_exercise','exam','auxiliary_exercise','ai_supplement'}
def read(p):return json.loads(Path(p).read_text())
def write(p,d):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2))
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
 if d.get('schemaVersion')!=1:e.append('unsupported schemaVersion')
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
  g=q.get('grading',{'kind':'self'})
  if g.get('kind')not in ('self','choice','numeric'):e.append('unsupported grading; use self assessment')
  if g.get('kind')!='self':
   if a.get('status')!='ready'or not g.get('rules')or not g.get('rationale'):e.append('automatic judgment needs reliable rules')
   for r in g.get('rules',[]):
    if r.get('fieldId')not in fs:e.append('grading field missing')
 for b in all_blocks(d):
  t=b.get('type')
  if t not in BLOCKS:e.append('unsupported block '+str(t))
  if t=='math'and not b.get('tex'):e.append('empty formula')
  if t=='paragraph'and 'runs'in b:
   if not isinstance(b['runs'],list)or any(r.get('type')not in ('text','math')or not r.get('text'if r.get('type')=='text'else'tex')for r in b['runs']):e.append('invalid inline paragraph')
  if t=='matrix'and(not b.get('rows')or len({len(r)for r in b['rows']})!=1):e.append('ragged matrix')
  if t=='image'and(not b.get('alt')or not b.get('path')or re.match(r'^(?:\w+:|//)',b.get('path',''))):e.append('image requires local path and alt')
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
 return e
def classify(sources,evidence):
 primary=[s for s in sources if s.get('primary')];roles={s.get('role')for s in primary or sources};mode='textbook'
 if len(primary)>1 and len(roles)>1:mode='combined'
 elif 'teacher_slides'in roles:mode='slides'
 elif 'outline'in roles:mode='outline'
 text=' '.join(evidence);modes=[]
 for key,terms in [('math',['矩阵','定理','行列式','证明']),('theory',['方法论','原理','材料分析']),('models',['均衡','曲线','坐标']),('accounting',['借贷','分录','账户','试算']),('statistics',['统计量','置信','概率分布','抽样分布','样本均值','方差','假设检验'])]:
  if any(t in text for t in terms):modes.append(key)
 return {'materialMode':mode,'disciplines':modes or ['general'],'status':'建议；须核对真实内容与用户主次要求'}
def checkpoint(d):
 shared={k:d.get(k)for k in ['organization','disciplines','sources','edition','preferencesVersion']}
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
 p=Check();s=Path(path).read_text();p.feed(s)
 for u in re.findall(r'url\(([^)]+)\)',s):
  if not u.strip('"\' ').startswith(('data:','#')):p.errors.append('external CSS URL '+u[:80])
 return p.errors
def build(data,inventory,dest,asset_root,allow_incomplete=False,node=None):
 d=copy.deepcopy(data);errors=validate(d,inventory)
 if errors and not allow_incomplete:raise ValueError('\n'.join(errors))
 d['validation']={'structuralErrors':errors,'sourceItems':len(inventory['items']),'counts':{k:sum(q['origin']==k for q in d['questions'])for k in sorted(ORIGINS)},'note':'结构计数不证明学术正确；语义核查范围单独记录。'};d['sourceInventory']=inventory
 if errors:d['scope']['completeness']='incomplete'
 expressions=list(math_expressions(d))
 if expressions:
  n=node or os.environ.get('NODE_BINARY')or shutil.which('node')
  if not n:raise ValueError('需Node验证公式；未完成公式核验，停止交付')
  r=subprocess.run([n,str(SKILL/'scripts/check_math.cjs'),str(SKILL/'assets/vendor/katex.min.js')],input=json.dumps(expressions),text=True,capture_output=True)
  if r.returncode:raise ValueError('formula validation failed: '+r.stderr)
 root=Path(asset_root).resolve()
 for b in all_blocks(d):
  if b['type']=='image':
   p=(root/b['path']).resolve()
   if not p.is_relative_to(root):raise ValueError('asset outside approved input root')
   mime=mimetypes.guess_type(str(p))[0]
   if mime not in ('image/png','image/jpeg','image/webp','image/gif'):raise ValueError('image must be local raster; use structured diagram for SVG')
   b['data']='data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()
 css=(SKILL/'assets/vendor/katex.min.css').read_text()
 def font(m):
  name=re.sub(r'\.(woff|ttf)$','.woff2',Path(m.group(1).strip('"\'')).name);p=SKILL/'assets/vendor'/name
  if not p.is_file():raise ValueError('missing font '+name)
  return 'url(data:font/woff2;base64,'+base64.b64encode(p.read_bytes()).decode()+')'
 css=re.sub(r'url\(([^)]+)\)',font,css);css=re.sub(r'format\("(?:woff|truetype)"\)','format("woff2")',css)
 payload=json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
 values={'TITLE':html.escape(d['title']),'CSS':css+'\n'+(SKILL/'assets/style.css').read_text(),'DATA':payload,'JS':'\n'.join((SKILL/'assets'/f).read_text()for f in ['vendor/katex.min.js','storage.js','app.js'])}
 shell=(SKILL/'assets/shell.html').read_text()
 for k,v in values.items():shell=shell.replace('@@'+k+'@@',v)
 dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(shell)
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
 ap=argparse.ArgumentParser(description=__doc__);sp=ap.add_subparsers(dest='cmd',required=True)
 a=sp.add_parser('inventory');a.add_argument('files',nargs='+');a.add_argument('--out',required=True)
 a=sp.add_parser('classify');a.add_argument('input');a.add_argument('--out',required=True)
 for cmd in ('validate','build'):
  a=sp.add_parser(cmd);a.add_argument('course');a.add_argument('--inventory',required=True);a.add_argument('--out',required=True)
  if cmd=='build':a.add_argument('--assets',default='.');a.add_argument('--allow-incomplete',action='store_true');a.add_argument('--node')
 a=sp.add_parser('inspect');a.add_argument('html')
 a=sp.add_parser('checkpoint');a.add_argument('course');a.add_argument('--out',required=True);a.add_argument('--previous')
 args=ap.parse_args()
 try:
  if args.cmd=='inventory':write(args.out,inventory_files(args.files))
  elif args.cmd=='classify':
   d=read(args.input);write(args.out,classify(d['sources'],d.get('evidence',[])))
  elif args.cmd=='validate':
   e=validate(read(args.course),read(args.inventory));write(args.out,{'errors':e,'structuralPass':not e,'semanticMeaning':'脚本只验证审查记录存在，不能判断事实正确'});print(json.dumps({'errors':e},ensure_ascii=False));return bool(e)
  elif args.cmd=='build':print(json.dumps(build(read(args.course),read(args.inventory),args.out,args.assets,args.allow_incomplete,args.node),ensure_ascii=False))
  elif args.cmd=='inspect':
   e=inspect_html(args.html);print(json.dumps(e,ensure_ascii=False));return bool(e)
  elif args.cmd=='checkpoint':
   a=checkpoint(read(args.course));print(json.dumps({'affected':changed(read(args.previous),a)if args.previous else list(a)},ensure_ascii=False));write(args.out,a)
 except (ValueError,KeyError,OSError,json.JSONDecodeError)as e:print(str(e),file=sys.stderr);return 1
 return 0
if __name__=='__main__':sys.exit(main())
