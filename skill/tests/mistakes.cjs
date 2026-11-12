'use strict';
const assert=require('node:assert/strict');
const notebook=require('../assets/mistakes.js'),grading=require('../assets/grading.js');
function question(id='q1'){return {id,version:'1',number:'1',title:'Exact count',chapterIds:['c1'],prompt:[{type:'paragraph',text:'Enter 10'}],parts:[{id:'p1',fields:[{id:'n',kind:'number',label:'Count'}]}],answer:{version:'1',status:'ready',provenance:'original',blocks:[{type:'paragraph',text:'10'}]},grading:{kind:'numeric',rationale:'Exact reference.',rules:[{fieldId:'n',expected:10}]}}}
function attempt(q,id,answer='9'){return {id,courseId:'course',questionId:q.id,questionVersion:q.version,referenceAnswerVersion:q.answer.version,questionSnapshot:structuredClone(q),referenceAnswer:structuredClone(q.answer),chapterIds:q.chapterIds,userAnswer:{n:answer},attachments:[],submittedAt:'2026-11-12T00:00:'+id.slice(-2)+'.000Z',judgment:grading.grade(q,{n:answer})}}
(async()=>{
const q=question(),a=attempt(q,'a01'),b=attempt(q,'a02','10'),course={id:'course',questions:[q]};let rows=await notebook.collect(course,[a,b],[]);assert.equal(rows.length,1);assert.equal(rows[0].attempts.length,2);assert.equal(rows[0].wrongAttempts.length,1);assert.equal(rows[0].currentStatus,'same');assert.equal(rows[0].state,'review');
const master={id:'e1',type:'mistake-review',at:'2026-11-12T01:00:00Z',groupKey:rows[0].groupKey,state:'mastered',evidenceIds:rows[0].evidenceIds};
rows=await notebook.collect(course,[a,b],[master]);assert.equal(rows[0].state,'mastered');
rows=await notebook.collect(course,[a,b,attempt(q,'a03')],[master]);assert.equal(rows[0].state,'review');assert.equal(rows[0].wrongAttempts.length,2);
const self=question('q2');self.grading={kind:'self'};const s=attempt(self,'a04');assert.equal(notebook.assessment(s).automatic,false);assert.equal((await notebook.collect(course,[s],[])).length,0);
const mark={id:'m1',type:'mistake-mark',at:'2026-11-12T01:00:00Z',attemptId:s.id,marked:true};rows=await notebook.collect(course,[s],[mark]);assert.equal(rows.length,1);assert.equal(rows[0].manualCount,1);assert.equal(rows[0].automaticCount,0);
assert.equal((await notebook.collect(course,[s],[mark,{...mark,id:'m2',at:'2026-11-12T02:00:00Z',marked:false}])).length,0);
const manualAuto={...mark,attemptId:a.id};rows=await notebook.collect(course,[a],[manualAuto,{...manualAuto,id:'m3',at:'2026-11-12T02:00:00Z',marked:false}]);assert.equal(rows.length,1);assert.equal(rows[0].automaticCount,1);assert.equal(rows[0].manualCount,0);
const legacy=structuredClone(a);delete legacy.judgment.status;assert.equal(notebook.assessment(legacy).automatic,true);
legacy.userAnswer.n='10元';assert.equal(notebook.assessment(legacy).automatic,false);assert.equal(notebook.assessment(legacy).reviewNeeded,true);
legacy.userAnswer.n='10';assert.equal(notebook.assessment(legacy).automatic,false);
legacy.userAnswer.n='9';legacy.questionSnapshot.grading.rules=[];assert.equal(notebook.assessment(legacy).automatic,false);
legacy.questionSnapshot.grading=q.grading;legacy.judgment.kind='self';assert.equal(notebook.assessment(legacy).automatic,false);
const precision=question();precision.grading.rules[0].expected=.1;const historic=attempt(precision,'a05','.100000000000000001');historic.judgment={kind:'numeric',result:'与参考规则不一致'};assert.equal(notebook.assessment(historic).automatic,false);
const unchanged=JSON.stringify(a);const changed=structuredClone(q);changed.answer.blocks[0].text='Updated explanation';const newer=attempt(changed,'a06');rows=await notebook.collect({id:'course',questions:[changed]},[a,newer],[]);assert.equal(rows.length,2);assert.deepEqual(new Set(rows.map(x=>x.currentStatus)),new Set(['same','changed']));assert.equal(JSON.stringify(a),unchanged);
const renamed=question('q3'),migrated={id:'course',questions:[renamed],migrations:{questionAliases:{q1:'q2',q2:'q3'}}};rows=await notebook.collect(migrated,[a],[]);assert.equal(rows[0].currentStatus,'renamed');assert.equal(rows[0].currentQuestionId,'q3');assert.deepEqual(rows[0].aliasPath,['q1','q2','q3']);
const cycle={id:'course',questions:[],migrations:{questionAliases:{q1:'q2',q2:'q1'}}};assert.equal(notebook.resolveCurrent(cycle,'q1').question,null);rows=await notebook.collect(cycle,[a],[]);assert.equal(rows[0].currentStatus,'missing');assert.equal(rows[0].currentQuestionId,null);
assert.equal((await notebook.collect(course,[{...a,courseId:'other'}],[])).length,0);assert.equal((await notebook.collect(course,[s],[{...mark,courseId:'other'}])).length,0);
const sameTime=[mark,{...mark,id:'m2',marked:false}];assert.deepEqual(await notebook.collect(course,[s],sameTime),await notebook.collect(course,[s],sameTime.reverse()));
console.log('Mistake notebook grouping, legacy precision, manual marking, mastery and version tests passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
