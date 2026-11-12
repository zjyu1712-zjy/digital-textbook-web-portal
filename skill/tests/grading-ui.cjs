'use strict';
// Synthetic derivatives exercise form behavior, not the supplied book's semantics.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {chromium}=require(require.resolve(process.env.PLAYWRIGHT_MODULE||'playwright',{paths:[process.cwd(),path.resolve(__dirname,'..')]}));
const file=path.resolve(process.argv[2]),reportFile=path.resolve(process.argv[3]),source=fs.readFileSync(file,'utf8');
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'dth-grading-')),profile=path.join(scratch,'profile');
const report={status:'unverified',sha256:crypto.createHash('sha256').update(source).digest('hex'),opening:'file://',offline:true,checks:[],errors:[],remoteRequests:[]};
let context;
const pass=name=>report.checks.push({name,status:'pass'});
const ready=p=>p.waitForFunction(()=>window.DTH?.ready&&DTH.pending===0);
function variant(course,name){const data=JSON.stringify(course).replace(/</g,'\\u003c');const dest=path.join(scratch,name+'.html');fs.writeFileSync(dest,source.replace(/(<script\b[^>]*id=["']course-data["'][^>]*>)[\s\S]*?(<\/script>)/i,(_,a,b)=>a+data+b));return dest}
(async()=>{try{
 context=await chromium.launchPersistentContext(profile,{headless:true,offline:true,viewport:{width:1440,height:980},...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 await context.route(/^https?:\/\//,r=>r.abort());const p=await context.newPage();p.on('pageerror',e=>report.errors.push(e.message));p.on('request',r=>{if(/^https?:/.test(r.url()))report.remoteRequests.push(r.url())});
 await p.goto(pathToFileURL(file).href);await ready(p);const course=await p.evaluate(()=>DTH.course);course.id='grading-check-'+crypto.randomUUID();
 const q=course.questions.find(q=>q.parts.length&&q.parts.every(part=>part.fields.length&&part.fields.every(f=>['text','fill','number'].includes(f.kind))));assert.ok(q,'Need one simple synthetic question.');
 q.parts.forEach(part=>part.fields.forEach(f=>f.kind='number'));const fields=q.parts.flatMap(part=>part.fields);q.answer.status='ready';q.grading={kind:'numeric',rationale:'Synthetic form test with explicit scalar expected values.',rules:fields.map(f=>({fieldId:f.id,expected:1000,tolerance:0}))};
 const valid=variant(course,'numeric');await p.goto(pathToFileURL(valid).href+'#question/'+q.id);await ready(p);
 assert.match(await p.locator('main').innerText(),/不要附带单位或算式/);
 const count=()=>p.evaluate(async()=>(await DTH.db.list('attempts')).length);
 const fill=async value=>{for(const f of fields)await p.locator('[data-field="'+f.id+'"]').fill(value);await ready(p)};
 for(const value of ['1000',' 1000 ','1,000','１０００','1e3']){
  await fill(value);const before=await count();await p.locator('button[type=submit]').click();await p.waitForFunction(()=>document.getElementById('question-status').textContent.startsWith('已提交'));assert.equal(await count(),before+1);
  assert.equal(await p.evaluate(async()=>(await DTH.db.list('attempts')).sort((a,b)=>b.submittedAt.localeCompare(a.submittedAt))[0].judgment.status),'correct');
  await p.locator('#retry').click();await ready(p);
 }pass('normalized-inputs-produce-real-correct-submissions');
 for(const value of ['1000元','10,00','2000/2','9007199254740993','0.100000000000000001']){
  await fill(value);const before=await count();await p.locator('button[type=submit]').click();await p.waitForFunction(()=>document.getElementById('question-status').textContent.includes('输入格式需调整'));assert.equal(await count(),before);assert.equal(await p.locator('[data-field]').first().inputValue(),value);
 }pass('invalid-input-preserves-draft-without-recording-wrong-attempt');
 await fill('999');const before=await count();await p.locator('button[type=submit]').click();await p.waitForFunction(()=>document.getElementById('question-status').textContent.startsWith('已提交'));assert.equal(await count(),before+1);
 assert.equal(await p.evaluate(async()=>(await DTH.db.list('attempts')).sort((a,b)=>b.submittedAt.localeCompare(a.submittedAt))[0].judgment.status),'incorrect');pass('valid-incorrect-answer-remains-a-real-attempt');
 const bad=structuredClone(course);delete bad.questions.find(x=>x.id===q.id).grading.rules[0].expected;
 await p.goto(pathToFileURL(variant(bad,'invalid-rule')).href+'#question/'+q.id);await ready(p);await fill('1000');const beforeBad=await count();await p.locator('button[type=submit]').click();await p.waitForFunction(()=>document.getElementById('question-status').textContent.includes('判分规则待修复'));assert.equal(await count(),beforeBad);pass('malformed-reference-cannot-create-successful-attempt');
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.remoteRequests,[]);pass('offline-no-page-errors-or-network');report.status='pass';
}catch(e){report.status='fail';report.error=e.stack;process.exitCode=1}finally{if(context)await context.close();fs.rmSync(scratch,{recursive:true,force:true});fs.mkdirSync(path.dirname(reportFile),{recursive:true});fs.writeFileSync(reportFile,JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,error:report.error}))}})();
