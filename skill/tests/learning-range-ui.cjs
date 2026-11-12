/* Real offline UI check of a synthetic seven-chapter partial fixture. */
"use strict";
const fs=require("node:fs"),path=require("node:path"),os=require("node:os"),assert=require("node:assert/strict"),crypto=require("node:crypto");
const {pathToFileURL}=require("node:url"),{chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
const [file,out]=process.argv.slice(2).map(x=>path.resolve(x));fs.mkdirSync(out,{recursive:true});
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),"dth-ranges-"));let context;
const report={status:"unverified",opening:"file://",offline:true,sha256:crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex"),checks:[],screenshots:[],errors:[],remoteRequests:[],visualReview:{status:"unverified"},scope:"Synthetic seven chapters with chapters 3–5 missing; no academic-review claim."};
const pass=name=>report.checks.push({name,status:"pass"});
async function go(p,route){await p.evaluate(r=>DTH.go(r),route);await p.waitForFunction(r=>DTH.ready&&location.hash==="#"+r,route);await p.evaluate(()=>document.fonts.ready);await p.evaluate(()=>scrollTo(0,0))}
async function shot(p,label,width){assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));const target=path.join(out,label+"-"+width+".png");await p.screenshot({path:target,fullPage:true,animations:"disabled"});report.screenshots.push(target)}
(async()=>{try{
 context=await chromium.launchPersistentContext(path.join(scratch,"profile"),{headless:true,offline:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 await context.route(/^https?:\/\//,r=>r.abort());const p=await context.newPage();p.on("pageerror",e=>report.errors.push(e.message));p.on("request",r=>{if(/^https?:/.test(r.url()))report.remoteRequests.push(r.url())});
 await p.goto(pathToFileURL(file).href);await p.waitForFunction(()=>DTH?.ready);report.browser=await p.evaluate(()=>navigator.userAgent);
 assert.equal(await p.evaluate(()=>DTH.course.scope.completeness),"incomplete");assert.equal(await p.evaluate(async()=>(await DTH.db.list("attempts")).length),0);pass("partial-scope-and-clean-records");
 for(const width of[1440,390]){
  await p.setViewportSize({width,height:980});await go(p,"home");
  const progress=p.locator("main [data-learning-progress]");assert.match(await progress.innerText(),/4 \/ 7/);assert.match(await progress.locator(".learning-prefix").innerText(),/第1章.*第2章/);assert.equal(await progress.locator("progress").getAttribute("value"),"4");assert.equal(await progress.locator("progress").getAttribute("max"),"7");assert.equal(await p.locator(".chapter-card").count(),7);assert.equal(await p.locator(".chapter-card a").count(),0);
  await progress.locator("summary").click();assert.match(await progress.innerText(),/第6章.*第7章/);await shot(p,"partial-home",width);pass("correct-prefix-and-later-range-"+width);
  await p.locator("#nav a[href=\"#chapter/ch3\"]").click();await p.waitForFunction(()=>DTH.ready&&location.hash==="#chapter/ch3");assert.equal(await p.locator(".lesson").count(),0);assert.match(await p.locator("main").innerText(),/本章原资料尚未提供/);assert.equal(await p.locator(".chapter-quality").getAttribute("open"),null);await shot(p,"pending-chapter",width);pass("pending-placeholder-reason-and-collapsed-state-"+width);
  await go(p,"sources");assert.equal(await p.locator(".chapter-overview tbody tr").count(),7);assert.match(await p.locator(".chapter-overview").innerText(),/未单独验证/);pass("scope-table-does-not-invent-browser-acceptance-"+width);
 }
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.remoteRequests,[]);pass("no-page-errors-or-network");report.status="pass";
}catch(e){report.status="fail";report.error=e.stack;process.exitCode=1}finally{if(context)await context.close();fs.rmSync(scratch,{recursive:true,force:true});fs.writeFileSync(path.join(out,"report.json"),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,error:report.error}))}})();
