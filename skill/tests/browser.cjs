/* Uses real local browser + file://. Set PLAYWRIGHT_MODULE and BROWSER_EXECUTABLE if not on PATH. */
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const file=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]||'browser-report.json');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'dth-test-'));
const options={headless:true,viewport:{width:1440,height:980},...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})};
const report={file,opening:'file://',profile:'isolated temporary test profile',checks:[],errors:[],screenshots:[]};let c;
function ok(name){report.checks.push({name,status:'pass'});console.log('PASS',name)}
async function ready(p){await p.waitForFunction(()=>window.DTH?.ready)}
(async()=>{
 c=await chromium.launchPersistentContext(profile,options);await c.setOffline(true);let p=await c.newPage();report.browser=await c.browser()?.version()||'Chromium persistent';p.on('pageerror',e=>report.errors.push(e.message));const requests=[];p.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url())});
 await p.goto(pathToFileURL(file).href);await ready(p);report.browser=await p.evaluate(()=>navigator.userAgent);assert.match(await p.locator('#storage-state').innerText(),/可用/);ok('file:// offline cold start and real storage probe');
 const qid=await p.evaluate(()=>DTH.course.questions.find(q=>q.parts.length>=2)?.id||DTH.course.questions[0].id);
 await p.evaluate(q=>DTH.go('question/'+q),qid);await p.locator('[data-field]').first().fill('第一次 <script>window.injected=1</script>');
 await p.getByRole('button',{name:'提交本次作答',exact:true}).click();await p.locator('#question-status').filter({hasText:'已提交'}).waitFor();
 for(let i=2;i<=3;i++){await p.getByRole('button',{name:'重新作答',exact:true}).click();await p.locator('[data-field]').first().fill('第'+i+'次');await p.getByRole('button',{name:'提交本次作答',exact:true}).click();await p.locator('#question-status').filter({hasText:'已提交'}).waitFor()}
 assert.equal(await p.evaluate(async q=>(await DTH.db.list('attempts')).filter(a=>a.questionId===q).length,qid),3);ok('three immutable submissions');
 await p.getByRole('button',{name:'重新作答',exact:true}).click();assert.equal(await p.locator('.answer-content').count(),0);await p.locator('[data-field]').first().fill('草稿恢复');await p.waitForFunction(()=>DTH.pending===0);
 const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGxkAAAAASUVORK5CYII=','base64');
 await p.locator('#attachment').setInputFiles({name:'草图.png',mimeType:'image/png',buffer:png});await p.locator('.attachment-image').waitFor();
 await p.getByRole('button',{name:'查看解析',exact:true}).click();assert.match(await p.locator('.answer-content').innerText(),/AI生成参考答案|原资料答案/);ok('hidden answers, provenance and image attachment');
 await p.locator('[data-knowledge]').first().click();await p.getByRole('button',{name:'返回原题',exact:true}).waitFor();assert.equal(await p.locator('[data-field]').count(),0);await p.getByRole('button',{name:'返回原题',exact:true}).click();await p.locator('#answer-form').waitFor();assert.equal(await p.locator('[data-field]').first().inputValue(),'草稿恢复');ok('knowledge roundtrip retains draft');
 await p.reload();await ready(p);assert.equal(await p.locator('[data-field]').first().inputValue(),'草稿恢复');assert.equal(await p.locator('.answer-content').count(),0);ok('reload restores draft; answers remain collapsed');
 const backup=await p.evaluate(()=>DTH.db.exportBackup({id:DTH.course.id,version:DTH.course.version}));assert.equal(backup.tables.attempts.length,3);assert.ok(backup.tables.attempts[0].questionSnapshot);assert.ok(backup.tables.attempts[0].referenceAnswer);ok('backup includes input, version snapshots, attachments');
 await p.evaluate(()=>scrollTo(0,Math.min(400,document.documentElement.scrollHeight-innerHeight)));const savedY=await p.evaluate(()=>scrollY);let posSaved=false;for(let i=0;i<200;i++){posSaved=await p.evaluate(async y=>Math.abs((await DTH.db.get('settings','position'))?.y-y)<1,savedY);if(posSaved)break;await p.waitForTimeout(25)}assert.equal(posSaved,true);
 await c.close();c=await chromium.launchPersistentContext(profile,options);await c.setOffline(true);p=await c.newPage();await p.goto(pathToFileURL(file).href);await ready(p);assert.ok(Math.abs(await p.evaluate(()=>scrollY)-savedY)<2);assert.equal(await p.locator('[data-field]').first().inputValue(),'草稿恢复');assert.equal(await p.locator('.attachment-image').count(),1);ok('browser process close/reopen preserves position, drafts, images and history');
 await p.evaluate(()=>DTH.go('backup'));let dl=p.waitForEvent('download');await p.getByRole('button',{name:'导出完整备份',exact:true}).click();const download=await dl;assert.ok((await download.suggestedFilename()).endsWith('.json'));ok('actual backup download');
 const b2=await chromium.launch(options);try{const other=await b2.newContext();await other.setOffline(true);const r=await other.newPage();await r.goto(pathToFileURL(file).href+'#backup');await ready(r);const input={name:'records.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(backup))};
 for(let i=0;i<2;i++){await r.locator('#import-file').setInputFiles(input);await r.getByRole('button',{name:'确认导入',exact:true}).click();await r.locator('#import-result').filter({hasText:'导入完成'}).waitFor()}
 assert.equal(await r.evaluate(async()=>(await DTH.db.list('attempts')).length),3);ok('independent import and repeated import dedupe');
 const conflicts=await r.evaluate(async b=>{b.tables.attempts[0].userAnswer={altered:'冲突'};try{await DTH.db.importBackup(b);return false}catch(e){return /冲突|不同/.test(e.message)}},backup);assert.ok(conflicts);assert.equal(await r.evaluate(async()=>(await DTH.db.list('attempts')).length),3);ok('conflicting import rejected atomically');
 const foreign=await r.evaluate(async b=>{b.course.id='other-book';try{await DTH.db.importBackup(b);return false}catch{return true}},backup);assert.ok(foreign);ok('foreign book backup rejected');
 await r.evaluate(()=>DTH.go('history'));assert.equal(await r.evaluate(()=>window.injected),undefined);ok('user-input script text never executed');
 }finally{await b2.close()}
 // Simulate real write failure at the IndexedDB API boundary, not a fake UI result.
 await p.evaluate(()=>DTH.go('question/'+DTH.course.questions[0].id));await p.locator('[data-field]').first().fill('before failure');await p.waitForFunction(()=>DTH.pending===0);
 await p.evaluate(()=>{window.originalTransaction=IDBDatabase.prototype.transaction;IDBDatabase.prototype.transaction=function(names,mode,...rest){if(mode==='readwrite')throw new DOMException('quota test','QuotaExceededError');return window.originalTransaction.call(this,names,mode,...rest)}});
 await p.locator('[data-field]').first().fill('无法保存的数据');await p.locator('#question-status').filter({hasText:'保存失败'}).waitFor();assert.doesNotMatch(await p.locator('#question-status').innerText(),/已保存/);ok('quota failure never reports saved');
 await p.evaluate(()=>{IDBDatabase.prototype.transaction=window.originalTransaction});await p.locator('[data-field]').first().fill('恢复保存');await p.waitForFunction(()=>DTH.pending===0);
 await p.evaluate(()=>DTH.go('home'));await p.locator('#search').fill('标签');assert.ok(await p.locator('#search-results a').count()>0);ok('search navigation');
 const desktop=path.join(path.dirname(out),'desktop.png');await p.screenshot({path:desktop,fullPage:false});report.screenshots.push(desktop);
 await p.setViewportSize({width:390,height:844});await p.evaluate(()=>DTH.go('question/'+DTH.course.questions[0].id));const narrow=path.join(path.dirname(out),'narrow.png');await p.screenshot({path:narrow,fullPage:false});report.screenshots.push(narrow);assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));ok('narrow viewport no page overflow');
 assert.equal(await p.locator('.katex-error').count(),0);assert.deepEqual(requests,[]);assert.deepEqual(report.errors,[]);ok('no page errors or network requests');report.status='passed';
})().catch(e=>{report.status='failed';report.failure=e.stack;console.error(e);process.exitCode=1}).finally(async()=>{if(c)await c.close();fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,JSON.stringify(report,null,2))});
