/* Public demo: real offline use, font decoding and clean synthetic screenshots. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const [file,out]=process.argv.slice(2).map(p=>path.resolve(p));fs.mkdirSync(out,{recursive:true});
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'dth-demo-'));
const report={status:'unverified',opening:'file://',offline:true,sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),checks:[],screenshots:[],errors:[],remoteRequests:[],visualReview:{status:'unverified'}};
const pass=name=>report.checks.push({name,status:'pass'});let context;
async function go(page,route){await page.evaluate(r=>DTH.go(r),route);await page.waitForFunction(r=>DTH.ready&&location.hash==='#'+r,route);await page.evaluate(()=>document.fonts.ready)}
async function shot(page,route,label,width){await page.setViewportSize({width,height:980});await go(page,route);await page.locator('#notice').waitFor({state:'hidden',timeout:12000});await page.evaluate(()=>scrollTo(0,0));await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));const target=path.join(out,label+'-'+width+'.png'),height=await page.evaluate(()=>Math.max(980,document.documentElement.scrollHeight));await page.setViewportSize({width,height});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.screenshot({path:target,fullPage:false,animations:'disabled'});await page.setViewportSize({width,height:980});report.screenshots.push(target)}
(async()=>{try{
 context=await chromium.launchPersistentContext(path.join(scratch,'profile'),{headless:true,offline:true,viewport:{width:1440,height:980},...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 await context.route(/^https?:\/\//,r=>r.abort());const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))report.remoteRequests.push(r.url())});
 await page.goto(pathToFileURL(file).href);await page.waitForFunction(()=>DTH?.ready);report.browser=await page.evaluate(()=>navigator.userAgent);
 assert.equal(await page.evaluate(()=>DTH.course.validation.assurance.status),'pass');assert.equal(await page.evaluate(()=>DTH.course.questions.length),6);assert.equal(await page.evaluate(async()=>(await DTH.db.list('attempts')).length),0);pass('demo-starts-without-learner-records');
 const fonts=await page.evaluate(async()=>{const faces=[...document.fonts];await Promise.all(faces.map(f=>f.load()));return faces.map(f=>({family:f.family,status:f.status}))});assert.equal(fonts.length,20);assert.ok(fonts.every(f=>f.status==='loaded'));pass('all-20-fonts-decode-offline');
 await go(page,'question/q-mean');await page.locator('[data-field=mean]').fill('1,000');await page.waitForFunction(()=>DTH.pending===0);await page.locator('button[type=submit]').click();await page.waitForFunction(()=>document.getElementById('question-status').textContent.startsWith('已提交'));assert.match(await page.locator('#question-status').innerText(),/符合参考规则/);pass('numeric-thousands-format-submits-correctly');
 await go(page,'question/q-formula');assert.equal(await page.locator('#answer-slot').innerText(),'');await page.locator('[data-field=formula]').fill('\\frac{800+1000+1200}{3}=1000');await page.waitForFunction(()=>DTH.pending===0);assert.equal(await page.locator('.katex-error').count(),0);assert.ok(await page.locator('.formula-preview .katex').count());pass('formula-preview-and-answer-hidden');
 for(const width of[1440,390]){
  await shot(page,'chapter/ch2','chapter',width);assert.equal(await page.locator('.katex-error').count(),0);
  await shot(page,'question/q-formula','formula',width);
  await shot(page,'history/q-mean','history',width);
  await shot(page,'backup','backup',width);
 }pass('four-views-at-desktop-and-390-width');
 const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();const download=await downloadPromise;const backupFile=path.join(scratch,'demo-backup.json');await download.saveAs(backupFile);const backup=JSON.parse(fs.readFileSync(backupFile,'utf8'));assert.equal(backup.tables.attempts.length,1);assert.equal(backup.tables.attempts[0].userAnswer.mean,'1,000');pass('real-complete-backup-download');
 const imported=await page.evaluate(async data=>DTH.db.importBackup(data),backup);assert.equal(imported.added,0);assert.ok(imported.skipped>0);pass('same-backup-import-does-not-duplicate');
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.remoteRequests,[]);pass('offline-no-page-errors-or-remote-requests');report.status='pass';
}catch(e){report.status='fail';report.error=e.stack;process.exitCode=1}finally{if(context)await context.close();fs.rmSync(scratch,{recursive:true,force:true});fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,error:report.error}))}})();
