/* Actual offline chapter-state UI; no injected pass records or learner data. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const [file,out]=process.argv.slice(2).map(x=>path.resolve(x));fs.mkdirSync(out,{recursive:true});
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'dth-quality-'));
const report={status:'unverified',opening:'file://',offline:true,sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),checks:[],screenshots:[],errors:[],remoteRequests:[],visualReview:{status:'unverified'}};
let context;const pass=name=>report.checks.push({name,status:'pass'});
async function go(page,route){await page.evaluate(r=>DTH.go(r),route);await page.waitForFunction(r=>DTH.ready&&location.hash==='#'+r,route);await page.evaluate(()=>document.fonts.ready);await page.locator('#notice').waitFor({state:'hidden',timeout:12000})}
async function layout(page){assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.equal(await page.locator('.katex-error').count(),0)}
async function shot(page,name,width){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));const namePath=path.join(out,name+'-'+width+'.png');await page.screenshot({path:namePath,animations:'disabled'});report.screenshots.push(namePath)}
async function completeChapterShot(page,id,width){await go(page,'chapter/'+id);await page.evaluate(()=>scrollTo(0,0));const height=await page.evaluate(()=>Math.max(980,document.documentElement.scrollHeight));await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));await shot(page,'complete-'+id,width);await page.setViewportSize({width,height:980})}
(async()=>{try{
 context=await chromium.launchPersistentContext(path.join(scratch,'profile'),{headless:true,offline:true,viewport:{width:1440,height:980},...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 await context.route(/^https?:\/\//,r=>r.abort());const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))report.remoteRequests.push(r.url())});
 await page.goto(pathToFileURL(file).href);await page.waitForFunction(()=>DTH?.ready);report.browser=await page.evaluate(()=>navigator.userAgent);
 const chapters=await page.evaluate(()=>DTH.course.chapters.map(c=>({id:c.id,sectionIds:c.sections.map(s=>s.id)})));
 assert.ok(chapters.length);report.scope={chapters:chapters.map(c=>c.id),checks:['state-display','collapsed-details','scope-counts','navigation','wide-and-narrow-layout']};
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:980});await go(page,'home');await page.locator('h1').scrollIntoViewIfNeeded();await layout(page);
  assert.equal(await page.locator('.chapter-card .chapter-status-summary').count(),chapters.length);assert.equal(await page.locator('.chapter-card a').count(),0);assert.equal(await page.locator('main .chapter-overview').count(),0);await shot(page,'home',width);pass('compact-home-no-nested-links-'+width);
  for(const chapter of chapters){
   await go(page,'chapter/'+chapter.id);const panel=page.locator('[data-chapter-quality="'+chapter.id+'"]');assert.equal(await panel.getAttribute('open'),null);assert.equal(await page.locator('.lesson').count(),chapter.sectionIds.length);await page.locator('h1').scrollIntoViewIfNeeded();await layout(page);await shot(page,'chapter-'+chapter.id,width);
   await panel.locator(':scope > summary').click();await panel.locator(':scope > summary').scrollIntoViewIfNeeded();assert.notEqual(await panel.getAttribute('open'),null);assert.match(await panel.innerText(),/抽样通过不代表全文已复核/);assert.match(await panel.innerText(),/离线功能/);assert.match(await panel.innerText(),/视觉检查/);await layout(page);await shot(page,'status-'+chapter.id,width);await completeChapterShot(page,chapter.id,width);
  }pass('chapter-states-default-collapsed-and-expand-'+width);
  await go(page,'sources');const table=page.locator('.chapter-overview');assert.equal(await table.locator('tbody tr').count(),chapters.length);assert.match(await table.innerText(),/已核查|样本/);assert.doesNotMatch(await table.innerText(),/\[object Object\]|undefined|NaN/);await layout(page);pass('source-page-chapter-scope-table-'+width);
  await table.locator('tbody tr a').first().click();await page.waitForFunction(()=>DTH.ready&&location.hash.startsWith('#chapter/'));assert.equal(await page.locator('.lesson').count(),chapters[0].sectionIds.length);pass('chapter-status-links-open-actual-content-'+width);
 }
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.remoteRequests,[]);pass('no-page-errors-or-network');report.status='pass';
}catch(e){report.status='fail';report.error=e.stack;process.exitCode=1}finally{if(context)await context.close();fs.rmSync(scratch,{recursive:true,force:true});fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,error:report.error}))}})();
