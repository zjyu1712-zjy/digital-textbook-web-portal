/* Generic product checks: inspect the actual DTH course, never fixture IDs. */
'use strict';
const fs = require('node:fs'), path = require('node:path');
const assert = require('node:assert/strict'), crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const file = path.resolve(process.argv[2]), output = path.resolve(process.argv[3]);
const source = fs.readFileSync(file, 'utf8');
fs.mkdirSync(path.dirname(output),{recursive:true});
// Put temporary derivatives under the job's retention directory, even if killed.
const scratch = fs.mkdtempSync(path.join(path.dirname(output), 'runtime-tmp-'));
const profile = path.join(scratch, 'profile');
const report = {file, sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),
  opening:'file://', profile:'isolated temporary profile, removed after test',
  status:'unverified', checks:[], screenshots:[], errors:[], remoteRequests:[],
  visualReview:{status:'unverified', detail:'截图已提供；像素内容、图文对应与学术语义须由独立审查执行。'},
  scope:{chapters:[], questions:[], exercisedQuestions:[], fieldKinds:[], exams:[]}};
let chromium, context, page, secondary;
const options = {headless:true, viewport:{width:1440,height:980},
  ...(process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {})};
const pass = (name, detail='') => report.checks.push({name,status:'pass',detail});
const skip = (name, detail) => report.checks.push({name,status:'not_applicable',detail});
const ready = p => p.waitForFunction(()=>window.DTH?.ready, null, {timeout:12000});
const settle = async p => {await p.waitForFunction(()=>DTH.pending===0); await p.evaluate(()=>document.fonts.ready)};
const poll = async (p, fn, arg) => {
  // Await each Promise. A Promise object is truthy even when its result is false.
  for(let i=0;i<240;i++){if(await p.evaluate(fn,arg))return;await p.waitForTimeout(25)}
  throw Error('等待异步存储或阅读位置条件超时');
};
async function instrument(c) {
  await c.setOffline(true);
  await c.route(/^https?:\/\//, route=>route.abort());
  c.on('page', p=>{
    p.setDefaultTimeout(8000);
    p.on('pageerror', e=>report.errors.push(e.message));
    p.on('request', r=>{if(/^https?:/.test(r.url()))report.remoteRequests.push(r.url())});
  });
}
async function go(p, route) {await p.evaluate(r=>DTH.go(r),route);await ready(p)}
async function open(p, filename=file, route='') {
  await p.goto(pathToFileURL(filename).href+(route?'#'+route:''));await ready(p);await settle(p);
}
const fieldLocator = (p,id) => p.locator('[data-field='+JSON.stringify(id)+']');
function fields(q) {return q.parts.flatMap(part=>part.fields)}
function expectedCount(f) {
  if(['choice','multiple'].includes(f.kind))return f.options.length;
  if(['matrix','table','journal'].includes(f.kind))
    return f.rows.length*f.columns.filter(c=>typeof c!=='object'||c.editable!==false).length;
  return 1;
}
async function fillQuestion(p,q,seed) {
  for(const f of fields(q)) {
    const els=fieldLocator(p,f.id);
    if(f.kind==='choice'){await els.nth(seed%f.options.length).check();continue}
    if(f.kind==='multiple'){
      for(let i=0;i<f.options.length;i++)await els.nth(i).setChecked(i<Math.min(2,f.options.length));
      continue;
    }
    for(let i=0;i<await els.count();i++) {
      const v=f.kind==='formula'?`\\frac{${seed+1}}{2}`:f.kind==='number'?`${seed+1}.25`:
        `${seed}：输入-${i} <script>window.__dthInjected=1</script>`;
      await els.nth(i).fill(v);
    }
  }
  await settle(p);
  assert.match(await p.locator('#question-status').innerText(),/已保存/);
  return readFields(p);
}
async function readFields(p) {
  return p.locator('[data-field]').evaluateAll(els=>els.map(e=>({id:e.dataset.field,
    row:e.dataset.row,col:e.dataset.col,value:e.value,checked:/^(radio|checkbox)$/.test(e.type)?e.checked:undefined})));
}
async function assertDraft(p,expected){assert.deepEqual(await readFields(p),expected)}
async function savePosition(p) {
  const max=await p.evaluate(()=>Math.max(0,document.documentElement.scrollHeight-innerHeight));
  await p.evaluate(y=>scrollTo(0,y),Math.min(max,500));
  const y=await p.evaluate(()=>scrollY);
  await poll(p,async target=>Math.abs((await DTH.db.get('settings','position'))?.y-target)<1,y);
  return y;
}
async function screenshot(p,name) {
  await p.evaluate(()=>document.fonts.ready);
  await p.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const dest=path.join(path.dirname(output),name+'.png');
  await p.screenshot({path:dest,fullPage:false,animations:'disabled'});
  report.screenshots.push(dest);
}
async function layout(p,label) {
  await p.locator('img').evaluateAll(es=>Promise.all(es.map(e=>e.decode().catch(()=>{}))));
  assert.equal(await p.locator('.katex-error').count(),0,label+': 公式渲染错误');
  assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label+': 页面横向溢出');
  assert.equal(await p.locator('img').evaluateAll(es=>es.filter(e=>!e.complete||e.naturalWidth===0).length),0,label+': 图片未载入');
}
function variant(course,name) {
  const safe=JSON.stringify(course).replace(/</g,'\\u003c').replace(/\u2028/g,'\\u2028').replace(/\u2029/g,'\\u2029');
  const html=source.replace(/(<script\b[^>]*id=["']course-data["'][^>]*>)[\s\S]*?(<\/script>)/i,
    (_,start,end)=>start+safe+end);
  assert.notEqual(html,source,'必须替换实际内嵌课程数据');
  const dest=path.join(scratch,name+'.html');fs.writeFileSync(dest,html);return dest;
}
async function main() {
  try{({chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright'))}
  catch{report.detail='未安装可运行的 Playwright，真实浏览器检查未执行。';return}
  try{context=await chromium.launchPersistentContext(profile,options)}
  catch(e){report.detail='无法启动配置的 Chromium/Edge 浏览器：'+e.message.split('\n')[0];return}
  await instrument(context);page=await context.newPage();await open(page);
  report.browser=await page.evaluate(()=>navigator.userAgent);
  assert.match(await page.locator('#storage-state').innerText(),/^本地存储可用$/);
  pass('file-offline-storage','真实 file:// 冷启动、断网、IndexedDB 写入探测。');
  const course=await page.evaluate(()=>DTH.course);
  assert.ok(course.chapters.length,'实际教材至少需要一章');
  const allKinds=[...new Set(course.questions.flatMap(q=>fields(q).map(f=>f.kind)))].sort();
  report.scope.fieldKinds=allKinds;
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:width===390?844:980});
    for(const ch of course.chapters) {
      await go(page,'chapter/'+ch.id);
      assert.deepEqual(await page.locator('.lesson').evaluateAll(es=>es.map(e=>e.id)),ch.sections.map(s=>s.id));
      await layout(page,`chapter ${ch.id} ${width}`);
      if(width===1440)report.scope.chapters.push(ch.id);
    }
    for(const q of course.questions) {
      await go(page,'question/'+q.id);
      assert.equal(await page.locator('#answer-form fieldset').count(),q.parts.length);
      for(const f of fields(q))assert.equal(await fieldLocator(page,f.id).count(),expectedCount(f),`${q.id}/${f.id}`);
      assert.equal(await page.locator('.answer-content').count(),0,'答案初始必须隐藏');
      await page.getByRole('button',{name:'查看解析',exact:true}).click();await settle(page);
      const badges={ai:'AI生成参考答案，非官方答案，请结合教材与课程要求核对。',original:'原资料答案与解析',teacher:'教师提供答案',unconfirmed:'来源未确认参考答案'};
      assert.equal(await page.locator('.answer-content .badge').innerText(),badges[q.answer.provenance]);
      await layout(page,`question ${q.id} ${width}`);
      if(width===1440)report.scope.questions.push(q.id);
    }
    for(const exam of course.exams||[]) {
      await go(page,'exam/'+exam.id);
      assert.equal(await page.locator('.paper-question').count(),exam.questionIds.length);
      await layout(page,`exam ${exam.id} ${width}`);
      if(width===1440)report.scope.exams.push(exam.id);
    }
  }
  pass('all-routes-layout',`全部 ${course.chapters.length} 章、${course.questions.length} 题、${(course.exams||[]).length} 卷：1440/390 像素独立视图、题型输入数量、答案标记、公式、图片与横向溢出。`);
  if(!(course.exams||[]).length)skip('exam-content','实际资料没有整卷真题，不虚构测试卷。');
  await page.setViewportSize({width:1440,height:980});
  const firstSection=course.chapters.flatMap(ch=>ch.sections.map(s=>({ch:ch.id,...s})))[0];
  if(firstSection) {
    await go(page,'home');await page.locator('#search').fill(firstSection.title);
    const link=page.locator('#search-results a').first();assert.ok(await link.count());
    const target=await link.getAttribute('href');await link.click();
    await page.waitForFunction(h=>location.hash===h&&DTH.ready,target);
    assert.ok((await page.locator('.lesson').count())>0);
    pass('search-navigation','使用实际小节标题搜索并进入独立章节。');
  }else skip('search-navigation','实际教材没有小节标题。');
  const rich=course.chapters.find(ch=>JSON.stringify(ch.sections).match(/"type":"(math|matrix|table|diagram|image)"/))||course.chapters[0];
  await go(page,'chapter/'+rich.id);await screenshot(page,'desktop-chapter');
  if(await page.locator('#main details').count()){
    const d=page.locator('#main details').first();await d.locator('summary').click();assert.equal(await d.getAttribute('open'),'');
    await d.locator('summary').click();pass('collapsible-sections','实际章节折叠区可展开和收起。');
  }else skip('collapsible-sections','当前章节无折叠区。');
  await page.setViewportSize({width:390,height:844});await screenshot(page,'narrow-chapter');
  await page.setViewportSize({width:1440,height:980});
  let selected=null,expected=null,backup,storedY=0;
  if(course.questions.length) {
    // Greedy selection covers every field kind present, and every part in each selected question.
    const representatives=[],seen=new Set();
    for(const q of [...course.questions].sort((a,b)=>fields(b).length-fields(a).length)) {
      if(!representatives.length||fields(q).some(f=>!seen.has(f.kind))) {
        representatives.push(q);fields(q).forEach(f=>seen.add(f.kind));
      }
    }
    const withKnowledge=[...course.questions].sort((a,b)=>fields(b).length-fields(a).length)
      .find(q=>q.knowledgeIds?.length);
    if(withKnowledge&&!representatives.some(q=>q.id===withKnowledge.id))representatives.push(withKnowledge);
    for(const q of representatives) {
      await go(page,'question/'+q.id);const values=await fillQuestion(page,q,1);
      await page.reload();await ready(page);await assertDraft(page,values);
      assert.equal(await page.locator('.answer-content').count(),0);
      report.scope.exercisedQuestions.push(q.id);
    }
    pass('field-kinds-draft-reload',`实际输入并刷新恢复 ${allKinds.join('、')}；代表题 ${representatives.map(q=>q.id).join('、')} 的全部小问。`);
    selected=withKnowledge||representatives[0];await go(page,'question/'+selected.id);
    for(let i=1;i<=3;i++) {
      await page.getByRole('button',{name:'重新作答',exact:true}).click();
      await page.locator('#question-status').filter({hasText:'尚未作答'}).waitFor();
      await fillQuestion(page,selected,i);
      if(i===2){await page.getByRole('button',{name:'查看解析',exact:true}).click();await settle(page)}
      await page.getByRole('button',{name:'提交本次作答',exact:true}).click();
      await page.locator('#question-status').filter({hasText:'已提交'}).waitFor();
    }
    let attempts=await page.evaluate(async id=>(await DTH.db.list('attempts')).filter(a=>a.questionId===id),selected.id);
    assert.equal(attempts.length,3);assert.equal(new Set(attempts.map(a=>a.id)).size,3);
    assert.ok(attempts.every(a=>a.questionSnapshot&&a.referenceAnswer&&a.questionVersion===selected.version&&a.referenceAnswerVersion===selected.answer.version));
    assert.equal(attempts.filter(a=>a.viewedAnswerBeforeSubmission).length,1);
    pass('three-immutable-attempts','同题三次提交、三个独立 ID、题目/答案版本快照和看答案状态。');
    await page.getByRole('button',{name:'重新作答',exact:true}).click();
    await page.locator('#question-status').filter({hasText:'尚未作答'}).waitFor();expected=await fillQuestion(page,selected,4);
    const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGxkAAAAASUVORK5CYII=','base64');
    await page.locator('#attachment').setInputFiles({name:'本地测试草图.png',mimeType:'image/png',buffer:png});
    await page.locator('.attachment-image').waitFor();await settle(page);
    if(selected.knowledgeIds?.length) {
      await page.locator('[data-knowledge]').first().click();await page.locator('#back-question').waitFor();await ready(page);
      assert.equal(await page.locator('[data-field]').count(),0);
      await page.getByRole('button',{name:'返回原题',exact:true}).click();await page.locator('#answer-form').waitFor();await ready(page);await assertDraft(page,expected);
      pass('knowledge-roundtrip','知识点往返保留原题所有小问草稿。');
    }else skip('knowledge-roundtrip','本教材题目没有知识点关联。');
    storedY=await savePosition(page);
    await page.reload();await ready(page);await assertDraft(page,expected);
    await poll(page,y=>Math.abs(scrollY-y)<2,storedY);
    assert.equal(await page.locator('.attachment-image').count(),1);
    await screenshot(page,'desktop-question');await page.setViewportSize({width:390,height:844});
    await screenshot(page,'narrow-question');await layout(page,'narrow input');
    if(await page.locator('.formula-preview').count()){
      await page.locator('.formula-preview').first().scrollIntoViewIfNeeded();await screenshot(page,'narrow-formula-input');
    }
    if(await page.locator('#answer-form .table-scroll').count()){
      await page.locator('#answer-form .table-scroll').first().scrollIntoViewIfNeeded();await screenshot(page,'narrow-table-input');
    }
    await page.setViewportSize({width:1440,height:980});storedY=await savePosition(page);
    pass('image-and-exact-scroll-reload','草图、完整草稿与精确滚动位置刷新恢复。');
  }else {
    for(const name of ['field-kinds-draft-reload','three-immutable-attempts','knowledge-roundtrip','image-and-exact-scroll-reload'])
      skip(name,'实际资料没有题目，未添加虚构题目来宣称通过。');
    await go(page,'chapter/'+rich.id);storedY=await savePosition(page);
  }
  assert.equal(await page.evaluate(async()=>(await DTH.db.list('drafts')).filter(d=>d.forkOf).length),0,
    '没有并发页面时，往返、查看解析与保存不得产生冲突分叉草稿');
  pass('single-page-no-false-conflicts','正常单页导航和作答不得误报另一页面修改或创建 forkOf 草稿。');
  await context.close();context=await chromium.launchPersistentContext(profile,options);await instrument(context);
  page=await context.newPage();await open(page);await poll(page,y=>Math.abs(scrollY-y)<2,storedY);
  if(selected){await assertDraft(page,expected);assert.equal(await page.locator('.attachment-image').count(),1);assert.equal(await page.evaluate(async()=>(await DTH.db.list('attempts')).length),3)}
  pass('browser-process-reopen','关闭真实浏览器进程后，以同一隔离 profile/file:// 入口恢复章节位置和适用的草稿、图片、历史。');
  // A non-curricular note tests backup conflict handling even when the book has no questions.
  await page.evaluate(()=>DTH.db.put('notes',{id:'quality-check-note',text:'仅用于隔离测试 profile 的备份冲突检查'}));
  backup=await page.evaluate(()=>DTH.db.exportBackup({id:DTH.course.id,version:DTH.course.version}));
  if(selected){assert.equal(backup.tables.attempts.length,3);assert.ok(backup.tables.attachments.length);assert.ok(backup.tables.drafts.some(d=>d.attachments.length))}
  await go(page,'backup');const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出完整备份',exact:true}).click();const download=await downloadEvent;
  const exported=path.join(scratch,'export.json');await download.saveAs(exported);
  const actualExport=JSON.parse(fs.readFileSync(exported,'utf8'));assert.equal(actualExport.course.id,course.id);
  assert.deepEqual(actualExport.tables.attempts,backup.tables.attempts);
  pass('actual-backup-download','通过页面下载实际 JSON，并核对历史快照。');
  secondary=await chromium.launch(options);const clean=await secondary.newContext();await instrument(clean);
  const p=await clean.newPage();await open(p,file,'backup');
  for(let i=0;i<2;i++) {
    await p.locator('#import-file').setInputFiles({name:'学习记录.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(backup))});
    await p.getByRole('button',{name:'确认导入',exact:true}).click();
    await p.locator('#import-result').filter({hasText:'导入完成'}).waitFor();
  }
  assert.deepEqual(await p.evaluate(async()=>(await DTH.db.list('attempts')).map(a=>a.id).sort()),backup.tables.attempts.map(a=>a.id).sort());
  const reject=await p.evaluate(async b=>{b.tables.notes[0].text='同 ID 不同内容';try{await DTH.db.importBackup(b);return false}catch(e){return /冲突|不同/.test(e.message)}},backup);
  assert.equal(reject,true);assert.equal(await p.evaluate(async()=>(await DTH.db.list('notes'))[0].text),backup.tables.notes[0].text);
  const foreign=await p.evaluate(async b=>{b.course.id='foreign-book';try{await DTH.db.importBackup(b);return false}catch{return true}},backup);
  assert.equal(foreign,true);pass('backup-import-dedupe-conflict','独立浏览器导入两次不重复；冲突原子拒绝；其他教材备份拒绝。');
  await secondary.close();secondary=null;
  const other=structuredClone(course);other.id='quality-other-'+crypto.randomUUID();
  await open(page,variant(other,'other-book'));
  assert.equal(await page.evaluate(async()=>(await DTH.db.list('attempts')).length),0);
  assert.equal(await page.evaluate(async()=>(await DTH.db.list('notes')).length),0);
  await open(page,file,'history');assert.equal(await page.evaluate(()=>window.__dthInjected),undefined);
  pass('book-isolation-and-input-escape','同 profile 的另一教材 ID 没有原书记录；脚本形用户输入未执行。');
  if(selected) {
    const updated=structuredClone(course);updated.version=course.version+'-quality-update';
    const uq=updated.questions.find(q=>q.id===selected.id);uq.version+='-quality-update';uq.answer.version+='-quality-update';
    await open(page,variant(updated,'updated-book'),'history');
    const old=await page.evaluate(async()=>(await DTH.db.list('attempts')));
    assert.deepEqual(old.map(a=>a.questionSnapshot),backup.tables.attempts.map(a=>a.questionSnapshot));
    assert.deepEqual(old.map(a=>a.referenceAnswer),backup.tables.attempts.map(a=>a.referenceAnswer));
    pass('updated-book-history','仅在临时测试副本提升内容版本，旧题目与参考答案快照保持原样。');
    await open(page,file,'question/'+selected.id);await fillQuestion(page,selected,5);
    await page.evaluate(()=>{window.__originalTransaction=IDBDatabase.prototype.transaction;IDBDatabase.prototype.transaction=function(n,m,...r){if(m==='readwrite')throw new DOMException('quality quota injection','QuotaExceededError');return window.__originalTransaction.call(this,n,m,...r)}});
    // Dispatch a real field event for every input type, including choice-only books.
    await page.locator('[data-field]').first().dispatchEvent('input');
    await page.locator('#question-status').filter({hasText:'保存失败'}).waitFor();
    assert.doesNotMatch(await page.locator('#question-status').innerText(),/已保存/);
    await page.getByRole('button',{name:'提交本次作答',exact:true}).click();
    await page.locator('#question-status').filter({hasText:'提交失败'}).waitFor();
    assert.equal(await page.evaluate(async()=>(await DTH.db.list('attempts')).length),3);
    await page.evaluate(()=>{IDBDatabase.prototype.transaction=window.__originalTransaction});
    await page.locator('[data-field]').first().dispatchEvent('input');await settle(page);
    pass('quota-save-submit-failure','在 IndexedDB 写事务边界注入空间不足；保存和提交均不误报成功，历史不增加。');
  }else {skip('updated-book-history','无题目提交，不伪造旧作答历史。');skip('quota-save-submit-failure','无题目作答输入，保存失败反馈检查不适用。')}
  const unavailable=await context.newPage();await unavailable.addInitScript(()=>Object.defineProperty(window,'indexedDB',{value:undefined}));
  await open(unavailable,file,selected?'question/'+selected.id:'home');
  assert.match(await unavailable.locator('#storage-state').innerText(),/不可用.*未保存/);
  if(selected){await unavailable.locator('[data-field]').first().dispatchEvent('input');await unavailable.locator('#question-status').filter({hasText:'保存失败'}).waitFor()}
  pass('unavailable-storage','缺少 IndexedDB 时明确显示不可用；有题时输入不误报已保存。');
  assert.deepEqual(report.remoteRequests,[]);assert.deepEqual(report.errors,[]);
  pass('offline-no-errors','整个动态范围无 HTTP(S) 请求、无页面异常。');
  report.status='pass';report.detail='自动浏览器检查已通过；范围见 scope。截图内容和教材语义的独立审查不由本脚本宣称通过。';
}
main().catch(e=>{report.status='fail';report.detail=e.message;report.failure=e.stack;
  report.checks.push({name:'runtime-failure',status:'fail',detail:e.message});process.exitCode=1;
}).finally(async()=>{
  try{if(secondary)await secondary.close();if(context)await context.close()}catch{}
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));
  fs.rmSync(scratch,{recursive:true,force:true});
  console.log(JSON.stringify({status:report.status,checks:report.checks.length,detail:report.detail}));
});
