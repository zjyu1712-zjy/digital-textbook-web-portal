/* v1 -> v2 record compatibility and source-contract/review UI, using synthetic data. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {chromium}=require(require.resolve(process.env.PLAYWRIGHT_MODULE||'playwright',{paths:[process.cwd(),path.resolve(__dirname,'..')]}));
const [oldFile,newFile,staleFile,legacyFile,reportFile]=process.argv.slice(2).map(x=>path.resolve(x));
const output=path.dirname(reportFile);fs.mkdirSync(output,{recursive:true});
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'textbook-assurance-')),profile=path.join(scratch,'profile'),entry=path.join(scratch,'learning.html');
const hash=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const report={status:'unverified',opening:'file://',offline:true,sha256:hash(newFile),inputHashes:{old:hash(oldFile),reviewed:hash(newFile),stale:hash(staleFile),legacy:hash(legacyFile)},checks:[],screenshots:[],errors:[],remoteRequests:[],visualReview:{status:'unverified'}};
const pass=name=>report.checks.push({name,status:'pass'});let context;
async function start(){
 context=await chromium.launchPersistentContext(profile,{headless:true,offline:true,viewport:{width:1440,height:980},...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 await context.route(/^https?:\/\//,r=>r.abort());
 const p=await context.newPage();p.on('pageerror',e=>report.errors.push(e.message));p.on('request',r=>{if(/^https?:/.test(r.url()))report.remoteRequests.push(r.url())});
 await p.goto(pathToFileURL(entry).href);await p.waitForFunction(()=>window.DTH?.ready);report.browser=await p.evaluate(()=>navigator.userAgent);return p;
}
async function go(p,r){await p.evaluate(r=>DTH.go(r),r);await p.waitForFunction(r=>DTH.ready&&location.hash==='#'+r,r);await p.evaluate(()=>document.fonts.ready)}
async function input(p,id,answers){await go(p,'question/'+id);for(const [field,value]of Object.entries(answers))await p.locator('[data-field="'+field+'"]').fill(value);await p.waitForFunction(()=>DTH.pending===0)}
async function layout(p){assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.equal(await p.locator('.katex-error').count(),0)}
async function screenshot(p,name){const file=path.join(output,name+'.png');await p.screenshot({path:file,animations:'disabled'});report.screenshots.push(file)}
(async()=>{try{
 fs.copyFileSync(oldFile,entry);let p=await start();
 const identity=await p.evaluate(()=>DTH.course.id);
 await input(p,'q1',{fields:'样本代号、采集日期、观察者',reason:'缺失日期须标注并核查，不能猜测。'});
 await p.locator('button[type=submit]').click();await p.waitForFunction(()=>document.getElementById('question-status').textContent.startsWith('已提交'));
 await input(p,'ex1',{response:'旧版草稿：保留S01与S10并回查原记录。'});
 const before=await p.evaluate(async()=>({attempts:await DTH.db.list('attempts'),drafts:await DTH.db.list('drafts'),questions:DTH.course.questions}));
 assert.equal(before.attempts.length,1);await context.close();context=null;
 fs.copyFileSync(newFile,entry);p=await start();
 assert.equal(await p.evaluate(()=>DTH.course.id),identity);
 assert.equal(await p.evaluate(()=>DTH.course.schemaVersion),2);
 const after=await p.evaluate(async()=>({attempts:await DTH.db.list('attempts'),drafts:await DTH.db.list('drafts'),questions:DTH.course.questions}));
 assert.deepEqual(after.attempts,before.attempts);assert.deepEqual(after.drafts,before.drafts);assert.deepEqual(after.questions,before.questions);pass('v1-to-v2-keeps-questions-attempts-drafts-and-book-id');
 await go(p,'question/ex1');assert.equal(await p.locator('[data-field=response]').inputValue(),'旧版草稿：保留S01与S10并回查原记录。');pass('old-draft-restores-in-v2-ui');
 await go(p,'history/q1');assert.ok((await p.locator('main').innerText()).includes('样本代号、采集日期、观察者'));pass('old-submission-snapshot-readable');
 for(const width of[1440,390]){
  await p.setViewportSize({width,height:980});await go(p,'sources');await p.evaluate(()=>scrollTo(0,0));
  const text=await p.locator('main').innerText();assert.match(text,/本次资料安排/);assert.match(text,/课堂案例/);assert.match(text,/仅作对照或存档/);assert.match(text,/审校记录与当前内容一致/);assert.match(text,/资料如何融入学习/);assert.doesNotMatch(text,/\[object Object\]/);await layout(p);await screenshot(p,'contract-'+width);pass('contract-roles-and-fresh-status-'+width);
  await p.locator('[aria-label="当前审校状态"]').scrollIntoViewIfNeeded();await screenshot(p,'review-'+width);
  const link=p.locator('main a[href="#chapter/ch1/k1"]').first();await link.click();await p.waitForFunction(()=>DTH.ready&&location.hash==='#chapter/ch1/k1');await p.locator('#k1').waitFor();assert.match(await p.locator('#k1').innerText(),/3月1日和4月1日/);pass('fusion-evidence-link-opens-real-explanation-'+width);
 }
 await p.goto(pathToFileURL(staleFile).href+'#sources');await p.waitForFunction(()=>DTH.ready);assert.notEqual(await p.evaluate(()=>DTH.course.validation.assurance.status),'pass');assert.match(await p.locator('[aria-label="当前审校状态"]').innerText(),/重新核对|需要重做|尚待复核/);pass('stale-review-is-visible');
 await p.goto(pathToFileURL(legacyFile).href+'#sources');await p.waitForFunction(()=>DTH.ready);assert.match(await p.locator('[aria-label="当前审校状态"]').innerText(),/旧版记录尚未与当前内容绑定/);pass('legacy-build-does-not-claim-bound-review');
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.remoteRequests,[]);pass('offline-no-remote-requests-or-page-errors');report.status='pass';
}catch(e){report.status='fail';report.error=e.stack;process.exitCode=1}finally{if(context)await context.close();fs.rmSync(scratch,{recursive:true,force:true});fs.writeFileSync(reportFile,JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,error:report.error}))}})();
