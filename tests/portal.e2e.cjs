/* Actual browser UI tests. Test-only converter accepts one exact authored sample. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.argv[2] || path.join(root, 'evidence', 'ui'));
fs.mkdirSync(output, {recursive:true});
const fixture = path.join(root, 'skill', 'tests', 'fixtures', 'general-source.txt');
const fixtureBytes = fs.readFileSync(fixture);
const fixtureSHA256 = crypto.createHash('sha256').update(fixtureBytes).digest('hex');
assert.equal(fixtureSHA256,'2dc18a77faebcf6d12a873a478c7e9d1ee42359f10370baab3f576403cb6075d');
const report = {status:'running', mode:'test-only injected converter, fixed self-authored source; no real model call', fixtureSHA256, opening:'HTTP localhost UI, downloaded product file:// offline', checks:[], screenshots:[], pageErrors:[], requests:[], realModelCalled:false};
const pass = (name, detail='') => report.checks.push({name, status:'pass', detail});
const servers = [];
const contexts = [];
let browser;
const readyPort = Number(process.env.UI_READY_PORT || 8011), offPort = Number(process.env.UI_OFF_PORT || 8012);
const readyBase = `http://127.0.0.1:${readyPort}`, offBase = `http://127.0.0.1:${offPort}`;
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function serve(port, missing=false) {
  const args = [path.join(root,'tests','serve_ui_fixture.py'),'--port',String(port),...(missing?['--unconfigured']:[])];
  const child = spawn(process.env.PYTHON || 'python3', args, {cwd:root, stdio:['ignore','pipe','pipe'], env:process.env});
  servers.push(child);
  let log='';
  child.stdout.on('data',data=>log+=data.toString());
  child.stderr.on('data',data=>log+=data.toString());
  for(let i=0;i<100;i++) {
    if(child.exitCode!==null) throw Error(`Test server failed to start (${port}): ${log}`);
    try { const response=await fetch(`http://127.0.0.1:${port}/api/config`); if(response.ok) return; } catch(_) {}
    await delay(100);
  }
  throw Error(`Test server readiness timeout (${port}): ${log}`);
}
async function context(options={}) {
  const c=await browser.newContext({viewport:{width:1440,height:1000}, acceptDownloads:true, ...options});
  contexts.push(c);
  c.on('page',p=>{
    p.setDefaultTimeout(15000);
    p.on('pageerror',error=>report.pageErrors.push(error.message));
    p.on('request',request=>{
      const parsed=new URL(request.url());
      if(parsed.protocol==='http:'||parsed.protocol==='https:') {
        assert(!parsed.searchParams.has('token'),'Task token must not appear in URL');
        report.requests.push({method:request.method(),url:request.url()});
      }
    });
  });
  return c;
}
async function noOverflow(page,label) {
  const measurements=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  assert(measurements.width<=measurements.viewport+1,`${label}: horizontal overflow ${JSON.stringify(measurements)}`);
  pass(label,JSON.stringify(measurements));
}
async function screenshot(page,name,fullPage=true) {
  await page.evaluate(()=>document.fonts.ready);
  await page.evaluate(()=>window.scrollTo({top:0,left:0,behavior:'instant'}));
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.screenshot({path:path.join(output,name), fullPage, animations:'disabled'});
  report.screenshots.push(name);
}
async function selectFixture(page,name='自写通用教材小样本.txt') {
  await page.locator('#file-input').setInputFiles({name, mimeType:'text/plain', buffer:fixtureBytes});
}
async function finish(page) {
  await page.waitForFunction(()=>document.querySelector('#job-status').textContent==='可以下载', null, {timeout:60000});
  assert.match(await page.locator('#job-message').innerText(),/测试样本，未调用真实模型/);
  assert(await page.locator('#download-job').isVisible());
}
(async()=>{
  await serve(readyPort);
  await serve(offPort,true);
  browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
  report.browser=browser.version();
  report.executable=process.env.BROWSER_EXECUTABLE||'Playwright bundled browser';
  const missing=await context();
  const noAPI=await missing.newPage();
  await noAPI.goto(offBase);
  await noAPI.getByText('转换服务尚未启用',{exact:true}).waitFor();
  assert.equal(await noAPI.locator('#consent').isChecked(),false);
  await selectFixture(noAPI);
  await noAPI.locator('#book-title').fill('无模型时不可伪造转换');
  await noAPI.locator('#access-code').fill('ui-test-access');
  await noAPI.locator('#consent').check();
  assert(await noAPI.locator('#submit-job').isDisabled());
  assert.match(await noAPI.locator('#file-list').innerText(),/自写通用教材/);
  pass('未配置 API 时允许准备资料，提交禁用且无假进度');
  await screenshot(noAPI,'desktop-unconfigured.png');
  await noOverflow(noAPI,'桌面 1440px 无横向溢出');
  await noAPI.setViewportSize({width:390,height:844});
  await screenshot(noAPI,'narrow-unconfigured.png');
  await noOverflow(noAPI,'窄屏 390px 无横向溢出');
  const c=await context();
  const page=await c.newPage();
  await page.goto(readyBase);
  await page.getByText('转换服务已就绪',{exact:true}).waitFor();
  assert.equal(await page.locator('#consent').isChecked(),false);
  assert(await page.locator('#access-code-field').isVisible());
  assert(await page.locator('#submit-job').isDisabled());
  await selectFixture(page, '<img src=x onerror=window.__portalInjected=1>.txt');
  assert.equal(await page.locator('#file-primary-0').isChecked(),true);
  await page.locator('#file-role-0').selectOption('teacher_slides');
  assert.equal(await page.locator('#file-role-0').inputValue(),'teacher_slides');
  await page.locator('#file-role-0').selectOption('textbook');
  await page.locator('#file-primary-0').uncheck();
  assert.match(await page.locator('#file-error').innerText(),/至少标记一份主资料/);
  await page.locator('#file-primary-0').check();
  await page.locator('#book-title').fill('<img src=x onerror=window.__portalInjected=1> 自写教材');
  await page.locator('#scope').fill('测试范围：只验证对应小样本；未调用真实模型。');
  await page.locator('#material-mode').selectOption('textbook');
  await page.locator('#access-code').fill('incorrect-code');
  assert(await page.locator('#submit-job').isDisabled());
  await page.locator('#consent').check();
  assert(await page.locator('#submit-job').isEnabled());
  await page.locator('#submit-job').click();
  await page.locator('#submit-error').getByText('访问码不正确',{exact:true}).waitFor();
  assert.equal(await page.locator('#file-list img').count(),0);
  assert.equal(await page.evaluate(()=>window.__portalInjected),undefined);
  pass('逐文件角色、主次、范围、同意与访问码校验；用户文件名按文字展示');
  await page.locator('#access-code').fill('ui-test-access');
  const sentPromise=page.waitForRequest(request=>request.url()===`${readyBase}/api/jobs`&&request.method()==='POST');
  await page.locator('#submit-job').click();
  const sent=(await sentPromise).postDataJSON();
  assert.equal(sent.files[0].role,'textbook');
  assert.equal(sent.files[0].primary,true);
  assert.equal(sent.mode,'textbook');
  assert.equal(sent.consent,true);
  await page.locator('#job-panel').waitFor();
  await finish(page);
  assert.equal(await page.evaluate(()=>window.__portalInjected),undefined);
  assert.equal(await page.locator('#job-title img').count(),0);
  pass('真实上传→测试依赖注入构建→检查报告→下载入口；标题 XSS 不执行');
  const tokens=await page.evaluate(()=>JSON.parse(localStorage.getItem('shuye-conversion-tasks-v1')));
  assert.equal(tokens.tasks.length,1);
  assert.deepEqual(Object.keys(tokens.tasks[0]).sort(),['id','token']);
  assert(!JSON.stringify(tokens).includes('自写教材'));
  assert(!page.url().includes(tokens.tasks[0].token));
  await page.reload();
  await finish(page);
  assert.match(await page.locator('#job-title').innerText(),/自写教材/);
  pass('刷新后凭本机任务 ID 与令牌恢复；本地不保存教材正文或书名；令牌不进 URL');
  await screenshot(page,'desktop-ready.png');
  await noOverflow(page,'完成页桌面无横向溢出');
  await page.setViewportSize({width:390,height:844});
  await screenshot(page,'narrow-ready.png');
  await noOverflow(page,'完成页窄屏无横向溢出');
  const downloadPromise=page.waitForEvent('download');
  await page.locator('#download-job').click();
  const download=await downloadPromise;
  const html=path.join(output,'downloaded-test-sample.html');
  await download.saveAs(html);
  assert(fs.statSync(html).size>100000);
  assert(fs.readFileSync(html,'utf8').startsWith('<!doctype html>'));
  report.download={path:'downloaded-test-sample.html',bytes:fs.statSync(html).size,sha256:crypto.createHash('sha256').update(fs.readFileSync(html)).digest('hex')};
  pass('鉴权下载真实单文件 HTML',`${report.download.bytes} bytes`);
  const offline=await context();
  await offline.setOffline(true);
  let remoteRequests=0;
  offline.on('request',request=>{if(/^https?:/.test(request.url()))remoteRequests++;});
  const book=await offline.newPage();
  await book.goto(pathToFileURL(html).href);
  await book.waitForFunction(()=>window.DTH?.ready);
  assert.match(await book.locator('#storage-state').innerText(),/可用/);
  const data=await book.evaluate(()=>({chapters:DTH.course.chapters.length,questions:DTH.course.questions.length}));
  assert(data.chapters>0&&data.questions>0);
  assert.equal(remoteRequests,0);
  await screenshot(book,'downloaded-offline.png',false);
  pass('下载成品实际 file:// 断网打开，章节与原题数据存在，存储探针可用，无远程资源请求',JSON.stringify(data));
  await page.locator('#delete-job').click();
  await page.locator('#confirm-yes').click();
  await page.locator('#prepare-view').waitFor();
  assert.equal(await page.locator('#task-count').innerText(),'0');
  const deleted=await c.request.get(`${readyBase}/api/jobs/${tokens.tasks[0].id}`,{headers:{Authorization:`Bearer ${tokens.tasks[0].token}`}});
  assert.equal(deleted.status(),404);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('shuye-conversion-tasks-v1')).tasks.length),0);
  pass('主动删除服务资料、成品和任务入口；原任务不可再访问');
  // Different input is explicitly rejected by the fixture, not passed as a simulated conversion.
  await page.locator('#file-input').setInputFiles({name:'不同资料.txt',mimeType:'text/plain',buffer:Buffer.from('这不是允许的测试源文件。')});
  await page.locator('#book-title').fill('拒绝非固定测试源');
  await page.locator('#access-code').fill('ui-test-access');
  await page.locator('#consent').check();
  await page.locator('#submit-job').click();
  await page.waitForFunction(()=>document.querySelector('#job-status').textContent==='转换未完成',null,{timeout:30000});
  assert(await page.locator('#download-job').isHidden());
  assert.match(await page.locator('#job-message').innerText(),/指定测试源文件|未完成|失败/);
  pass('测试依赖注入拒绝任何非固定源，失败时无下载入口');
  const retried=page.waitForResponse(response=>response.url().endsWith('/retry')&&response.request().method()==='POST');
  await page.locator('#retry-job').click();
  assert.equal((await retried).status(),202);
  await page.waitForFunction(()=>document.querySelector('#job-status').textContent==='转换未完成',null,{timeout:30000});
  assert(await page.locator('#download-job').isHidden());
  pass('失败任务可发起真实重试，来源仍不符合时继续报告失败、不伪造成功');
  await screenshot(page,'narrow-failed.png');
  await page.locator('#delete-job').click();
  await page.locator('#confirm-yes').click();
  await page.locator('#prepare-view').waitFor();
  assert.deepEqual(report.pageErrors,[]);
  assert(report.requests.every(request=>new URL(request.url).hostname==='127.0.0.1'));
  pass('本次网页端到端无未捕获脚本异常，无外部网络请求');
  report.status='passed';
})().catch(error=>{
  report.status='failed'; report.failure=error.stack; console.error(error); process.exitCode=1;
}).finally(async()=>{
  for(const c of contexts) await c.close().catch(()=>{});
  if(browser) await browser.close();
  for(const child of servers) {
    if(child.exitCode===null) child.kill('SIGTERM');
    await Promise.race([new Promise(resolve=>child.once('exit',resolve)),delay(5000)]);
    if(child.exitCode===null) child.kill('SIGKILL');
  }
  report.testServersStopped=servers.every(child=>child.exitCode!==null||child.signalCode!==null);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({status:report.status,checks:report.checks.length,screenshots:report.screenshots.length,realModelCalled:false,report:path.join(output,'report.json')}));
});
