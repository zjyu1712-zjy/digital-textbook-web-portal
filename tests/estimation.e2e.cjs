/* Isolated real-browser display test. All responses are synthetic; no model/API keys. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.argv[2] || path.join(root, 'evidence', 'estimation-ui'));
fs.mkdirSync(output, {recursive:true});
const report = {status:'running', testDouble:true, realModelCalled:false,
  scope:'Actual browser UI with isolated HTTP fixture; no textbook conversion or real cost baseline',
  checks:[], screenshots:[], pageErrors:[], externalRequests:[]};
const pass = name => report.checks.push({name,status:'pass'});
const unknown = {status:'unknown',low:null,high:null};
const partial = {phase:'资料读取后',testDouble:true,scope:{pageCount:300,chapterCount:null,unitCount:null,sampleCount:null},
  calls:{spentModelCalls:0,maxModelCalls:1200,availableModelCalls:1200,
    successfulResponses:{low:381,high:null},networkAttempts:{low:381,high:null},limitAssessment:'may-stop-before-worst-case'},
  calibrated:false,priceSupplied:false,metrics:{inputTokens:unknown,outputTokens:unknown,elapsedSeconds:unknown,cost:unknown},
  usage:{outcomes:{success:null,failed:null,cacheHits:null},totals:{totalTokens:{knownTotal:null,complete:false}}}};
const sampled = structuredClone(partial);
sampled.phase='抽样计划确定后';sampled.scope={pageCount:10,chapterCount:1,unitCount:2,sampleCount:3};
sampled.calls={spentModelCalls:17,maxModelCalls:20,availableModelCalls:3,successfulResponses:{low:7,high:7},networkAttempts:{low:7,high:21},limitAssessment:'below-minimum'};
sampled.usage={outcomes:{success:15,failed:2,cacheHits:4},unclassifiedAttempts:1,totals:{totalTokens:{knownTotal:850,complete:false}}};
const calibrated = structuredClone(sampled);
calibrated.phase='显式条件估算测试';calibrated.calibrated=true;calibrated.priceSupplied=true;
calibrated.metrics={inputTokens:{status:'conditional',low:1000,high:2000},outputTokens:{status:'conditional',low:100,high:200},
  elapsedSeconds:{status:'conditional',low:12,high:24},cost:{status:'conditional',low:.0024,high:.0048,currency:'EXAMPLE'}};
let estimate=partial;
const job=()=>({id:'estimate-test',title:'自编样本 · 处理量展示测试',status:'needs_attention',stage:'needs_attention',
  message:'测试界面，未调用真实模型；下方数据仅用于验证未知值、限额与显示。',events:[],checks:[],downloadAvailable:false,
  estimate,expiresAt:'2026-11-13T12:00:00Z'});
const server=http.createServer((req,res)=>{
  res.setHeader('Cache-Control','no-store');
  if(req.url==='/api/config') {res.setHeader('Content-Type','application/json');res.end(JSON.stringify({ready:false,reasons:['独立测试服务，不连接模型'],
    limits:{maxFiles:10,maxFileBytes:1048576,maxTotalBytes:1048576},providerId:'openai',provider:'测试模型',retentionHours:24,accessCodeRequired:false,skillVersion:'test-only'}));return;}
  if(req.url==='/api/jobs/estimate-test'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(job()));return;}
  const allowed={'/':['index.html','text/html; charset=utf-8'],'/app.js':['app.js','text/javascript'],'/style.css':['style.css','text/css']};
  const entry=allowed[req.url];
  if(!entry){res.statusCode=404;res.end('Not found');return;}
  res.setHeader('Content-Type',entry[1]);res.end(fs.readFileSync(path.join(root,'static',entry[0])));
});
let browser,context;
(async()=>{
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const base=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 report.browser=browser.version();report.executable=process.env.BROWSER_EXECUTABLE||'Playwright Chromium';
 context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addInitScript(()=>localStorage.setItem('shuye-conversion-tasks-v1',JSON.stringify({tasks:[{id:'estimate-test',token:'test-only-fixed-token'}],selectedId:'estimate-test'})));
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin!==base){report.externalRequests.push(route.request().url());return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',error=>report.pageErrors.push(error.message));
 await page.goto(base);await page.locator('#work-estimate').waitFor();
 assert.match(await page.locator('#estimate-counts').innerText(),/300/);assert.match(await page.locator('#estimate-counts').innerText(),/待确定/);
 assert.match(await page.locator('#estimate-range').innerText(),/上限待确定/);
 assert.match(await page.locator('#estimate-metrics').innerText(),/费用 未知/);assert(!/费用 0/.test(await page.locator('#estimate-metrics').innerText()));
 pass('未规划单元和样本显示待确定；缺少基线时费用与时长为未知');
 await page.locator('#work-estimate').screenshot({path:path.join(output,'desktop-unknown.png')});report.screenshots.push('desktop-unknown.png');
 estimate=sampled;await page.reload();await page.locator('#estimate-phase').getByText('抽样计划确定后',{exact:false}).waitFor();
 assert.match(await page.locator('#estimate-budget').innerText(),/已请求 17 次.*尚余 3 次/);
 assert.match(await page.locator('#estimate-range').innerText(),/剩余成功回复：7/);
 assert.match(await page.locator('#estimate-warning').innerText(),/低于/);
 assert.match(await page.locator('#estimate-history').innerText(),/失败 2 次.*缓存命中 4 次/);
 assert.match(await page.locator('#estimate-history').innerText(),/只含已知部分/);
 pass('已用调用、失败、缓存和已知部分 tokens 分开显示；剩余额度不足可见');
 await page.locator('#work-estimate').screenshot({path:path.join(output,'desktop-budget.png')});report.screenshots.push('desktop-budget.png');
 await page.setViewportSize({width:390,height:844});
 let sizes=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));assert(sizes.width<=sizes.viewport+1);
 await page.locator('#work-estimate').screenshot({path:path.join(output,'mobile-budget.png')});report.screenshots.push('mobile-budget.png');pass('390 像素窄屏不横向溢出');
 await context.setOffline(true);
 assert.match(await page.locator('#estimate-range').innerText(),/剩余成功回复：7/);
 pass('加载后的估算面板在断网后仍可读取（不声称断网可运行服务）');
 await context.setOffline(false);estimate=calibrated;await page.reload();await page.locator('#estimate-phase').getByText('显式条件估算测试',{exact:false}).waitFor();
 assert.match(await page.locator('#estimate-metrics').innerText(),/0.0024–0.0048 EXAMPLE/);
 assert.match(await page.locator('#estimate-metrics').innerText(),/条件估计/);
 pass('仅显式单价及条件样本展示金额，并保留条件说明');
 await page.locator('#work-estimate').screenshot({path:path.join(output,'mobile-conditional.png')});report.screenshots.push('mobile-conditional.png');
 estimate=null;await page.reload();await page.locator('#job-title').getByText('自编样本',{exact:false}).waitFor();assert(await page.locator('#work-estimate').isHidden());pass('旧任务没有估算时正常隐藏面板');
 assert.deepEqual(report.externalRequests,[]);assert.deepEqual(report.pageErrors,[]);pass('无页面错误或外部资源请求');report.status='pass';
})().catch(error=>{report.status='fail';report.error=String(error.stack||error);process.exitCode=1;}).finally(async()=>{
 if(context)await context.close();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
 fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,checks:report.checks.length,report:path.join(output,'report.json')}));
});
