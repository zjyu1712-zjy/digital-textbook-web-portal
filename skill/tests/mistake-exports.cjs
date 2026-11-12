'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const E=require('../assets/mistake_exports.js');
const image='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
function fixture(){
 const course={id:'self-authored',title:'自编错题示例',version:'2',chapters:[{id:'ch1',title:'第一章'}],sources:[{id:'s1',title:'自编资料'}]};
 const answer={version:'a1',provenance:'original',blocks:[{type:'math',tex:'x=-100'},{type:'paragraph',text:'说明 </script><img src=x onerror=alert(1)> ```'}],sourceRefs:[{sourceId:'s1',locator:'第1页'}]};
 const question={id:'q1',version:'1',number:'1',title:'=SUM(1,2)',prompt:[{type:'paragraph',text:'旧题目，不随教材更新。'},{type:'image',data:'data:image/png;base64,'+image,alt:'自编图片'},{type:'table',columns:['项目','值'],rows:[['A',100],['B',-100]]}],parts:[{label:'选择',fields:[{id:'x',kind:'choice',label:'哪个值？',options:[{value:'a',label:'100'},{value:'b',label:'-100'}]}]}],sourceRefs:[{sourceId:'s1',locator:'第1页'}],answer};
 const attempt={id:'try-1',courseId:course.id,questionId:'q1',questionVersion:'1',referenceAnswerVersion:'a1',questionSnapshot:question,referenceAnswer:answer,userAnswer:{x:'a',matrix:[[1,2],[3,4]],notes:'@SUM(A1)'},submittedAt:'2026-01-01T12:00:00Z',judgment:{result:'incorrect'},attachments:['image-1'],viewedAnswerBeforeSubmission:false};
 const backup={format:'digital-textbook-backup',formatVersion:1,course:{id:course.id,title:course.title,version:course.version},exportedAt:'2026-01-02T12:00:00Z',tables:{attempts:[attempt],attachments:[{id:'image-1',name:'手写答案.png',blob:{__studyBlob:true,type:'image/png',data:image}}],events:[{id:'event-1',attemptId:attempt.id,type:'mistake-mark',marked:true}]}};
 const groups=[{groupKey:'a'.repeat(64),questionId:'q1',questionVersion:'1',answerVersion:'a1',questionSnapshot:question,referenceAnswer:answer,chapterIds:['ch1'],state:'review',currentStatus:'missing',currentQuestionId:null,attempts:[attempt],wrongAttempts:[attempt],evidenceIds:['event-1'],aliasPath:[]}];
 return {course,backup,groups};
}
function csvRows(text){
 const rows=[],row=[];let cell='',quoted=false;
 for(let i=1;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++}else quoted=!quoted}else if(!quoted&&c===','){row.push(cell);cell=''}else if(!quoted&&c==='\r'&&text[i+1]==='\n'){row.push(cell);rows.push([...row]);row.length=0;cell='';i++}else cell+=c}
 assert.equal(quoted,false);return rows;
}
let checks=0;const test=(name,fn)=>{fn();checks++;console.log('PASS '+name)};
test('Historical versions, removed questions, attachments and event IDs remain intact without mutation',()=>{
 const f=fixture(),original=JSON.stringify(f),b=E.prepare(f.course,f.backup,f.groups,{chapter:'ch1',state:'all'});
 assert.equal(JSON.stringify(f),original);assert.deepEqual(b.notebook.tables,f.backup.tables);assert.equal(b.items[0].currentStatus,'missing');assert.deepEqual(b.items[0].questionSnapshot,f.groups[0].questionSnapshot);assert.equal(b.notebook.format,'digital-textbook-mistakes');assert.equal(b.notebook.formatVersion,1);assert.equal(b.notebook.filters.chapter,'ch1');
 b.items[0].questionSnapshot.title='mutated';assert.equal(f.groups[0].questionSnapshot.title,'=SUM(1,2)');
});
test('Two historical versions are separate and all corresponding attempts survive',()=>{
 const f=fixture(),a=structuredClone(f.backup.tables.attempts[0]);a.id='try-2';a.questionVersion='2';a.questionSnapshot.version='2';a.questionSnapshot.prompt=[{type:'paragraph',text:'New version'}];
 f.backup.tables.attempts.push(a);f.groups.push({...f.groups[0],groupKey:'b'.repeat(64),questionVersion:'2',questionSnapshot:a.questionSnapshot,attempts:[a],wrongAttempts:[a]});
 const b=E.prepare(f.course,f.backup,f.groups);assert.equal(b.items.length,2);assert.equal(b.notebook.tables.attempts.length,2);assert.notDeepEqual(b.items[0].questionSnapshot,b.items[1].questionSnapshot);
});
test('Missing attachments, mixed versions and wrong book are refused',()=>{
 const f=fixture();assert.throws(()=>E.prepare({...f.course,id:'other'},f.backup,f.groups));f.backup.tables.attachments=[];assert.throws(()=>E.prepare(f.course,f.backup,f.groups),/附件/);
 const g=fixture();g.groups[0].answerVersion='wrong';assert.throws(()=>E.prepare(g.course,g.backup,g.groups),/版本/);
});
test('Empty selection is valid, duplicate groups and unknown attempts are not',()=>{
 const f=fixture();assert.equal(E.prepare(f.course,f.backup,[]).items.length,0);assert.throws(()=>E.prepare(f.course,f.backup,[f.groups[0],f.groups[0]]));f.groups[0].attempts=[{id:'absent'}];assert.throws(()=>E.prepare(f.course,f.backup,f.groups));
});
test('Snapshots differing only in object key order remain one version',()=>{
 const f=fixture(),a=structuredClone(f.backup.tables.attempts[0]);a.id='try-2';a.questionSnapshot=Object.fromEntries(Object.entries(a.questionSnapshot).reverse());f.backup.tables.attempts.push(a);f.groups[0].attempts.push(a);assert.equal(E.prepare(f.course,f.backup,f.groups).items[0].attempts.length,2);
});
test('Markdown escapes untrusted HTML, keeps options and embeds original notebook with attachments',()=>{
 const f=fixture(),b=E.prepare(f.course,f.backup,f.groups),text=E.toMarkdown(b);assert.ok(text.includes('data:image/png;base64,'+image));assert.ok(text.includes('&lt;/script&gt;'));assert.ok(text.includes('哪个值'));assert.ok(text.includes('```tex\nx=-100'));
 const jsonFence=text.match(/(`{4,})json\n([\s\S]*)\n\1\n$/);assert.ok(jsonFence,'Backtick-bearing JSON uses a longer fence');assert.deepEqual(JSON.parse(jsonFence[2]),b.notebook);
});
test('CSV uses BOM, complete escaped fields, structured snapshots and version traceability',()=>{
 const f=fixture();f.groups[0].questionSnapshot.prompt.push({type:'paragraph',text:'逗号, 双引号"\n换行'});const b=E.prepare(f.course,f.backup,f.groups),text=E.toCSV(b),rows=csvRows(text);assert.equal(text.charCodeAt(0),0xfeff);assert.equal(rows.length,2);assert.equal(rows[0].length,rows[1].length);assert.equal(rows[1][7],"'=SUM(1,2)");assert.ok(rows[1][8].includes('双引号"\n换行'));assert.deepEqual(JSON.parse(rows[1][15]),b.items[0].questionSnapshot);assert.deepEqual(JSON.parse(rows[1][17]),b.items[0].attempts);assert.equal(JSON.parse(rows[1][18])[0].blob.data,image);assert.ok(!text.includes('[object Object]'));
});
test('CSV text fields prevent spreadsheet formula injection while numeric strings keep their value',()=>{
 for(const text of['=1+1','+cmd|\' /C calc\'!A0','-2+3','@SUM(A1)',' \t=SUM(1)','\u200b=1','\n=1','\t-100'])assert.ok(E.csvCell(text).startsWith('"\''),text);
 for(const text of['-100','+1.25','-1.0e-3','12','说明 -100'])assert.ok(!E.csvCell(text).startsWith('"\''),text);
 assert.equal(E.csvCell('a,"b"\nc'),'"a,""b""\nc"');
});
test('Standalone export cannot close its data script; scripts and fonts stay self-contained',()=>{
 const f=fixture(),b=E.prepare(f.course,f.backup,f.groups),html=E.toHTML(b);assert.equal((html.match(/<script\b/g)||[]).length,3);assert.equal((html.match(/<\/script>/g)||[]).length,3);assert.ok(!html.includes('<img src=x onerror=alert(1)>'));assert.ok(html.includes("connect-src 'none'"));assert.ok(html.includes('未携带完整公式显示资源'));
 const payload=html.match(/<script id="review-data" type="application\/json">([\s\S]*?)<\/script>/)[1];assert.deepEqual(JSON.parse(payload),b);
 assert.throws(()=>E.toHTML(b,{katexCSS:'@import "https://bad.test/x";'}),/非内嵌/);assert.throws(()=>E.toHTML(b,{katexCSS:'x{src:url(https://bad.test/font)}'}),/非内嵌/);assert.doesNotThrow(()=>E.toHTML(b,{katexCSS:'x{src:url(data:font/woff2;base64,AAAA)}'}));
});
test('Modules are safe to embed in the host script without terminating it',()=>{
 for(const name of['mistake_exports.js','mistake_review.js'])assert.ok(!/<\/script\b/i.test(fs.readFileSync(path.join(__dirname,'../assets',name),'utf8')),name);
});
console.log(JSON.stringify({status:'pass',checks}));
