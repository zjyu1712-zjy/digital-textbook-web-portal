'use strict';
// Derive the notebook from immutable submissions and explicit user events.
((root)=>{
 const grading=typeof module==='object'&&module.exports?require('./grading.js'):root.DTHGrading;
 const object=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
 const stable=x=>JSON.stringify(x,(_k,v)=>object(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
 const digest=async x=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stable(x)))),x=>x.toString(16).padStart(2,'0')).join('');
 const newest=(a,b)=>String(b.at||'').localeCompare(String(a.at||''))||String(b.id||'').localeCompare(String(a.id||''));
 function snapshotValid(a){return object(a)&&typeof a.id==='string'&&object(a.questionSnapshot)&&object(a.referenceAnswer)&&a.questionSnapshot.id===a.questionId&&a.questionSnapshot.version===a.questionVersion&&a.referenceAnswer.version===a.referenceAnswerVersion&&Array.isArray(a.questionSnapshot.parts)&&Array.isArray(a.questionSnapshot.prompt)&&object(a.userAnswer)}
 async function key(a){return digest({questionId:a.questionId,questionVersion:a.questionVersion,answerVersion:a.referenceAnswerVersion,question:a.questionSnapshot,answer:a.referenceAnswer})}
 function assessment(a){
  const j=a?.judgment||{},negative=j.status==='incorrect'||(!j.status&&['与参考规则不一致','不正确'].includes(j.result));
  if(!negative)return {automatic:false,reviewNeeded:false};
  if(!snapshotValid(a)||!['numeric','choice'].includes(j.kind)||a.questionSnapshot.grading?.kind!==j.kind)return {automatic:false,reviewNeeded:true};
  // Historical labels are not sufficient: repeat only supported exact rules on the saved inputs.
  try{const q={...a.questionSnapshot,answer:a.referenceAnswer},r=grading.grade(q,a.userAnswer);return {automatic:r.status==='incorrect',reviewNeeded:r.status!=='incorrect'}}catch{return {automatic:false,reviewNeeded:true}}
 }
 function resolveCurrent(course,id){
  const questions=new Map((course.questions||[]).map(q=>[q.id,q])),aliases=course.migrations?.questionAliases||{},seen=new Set(),path=[];
  let next=id;
  while(typeof next==='string'&&next&&!seen.has(next)){
   seen.add(next);path.push(next);if(questions.has(next))return {question:questions.get(next),path,migrated:next!==id};
   if(!Object.prototype.hasOwnProperty.call(aliases,next))break;next=aliases[next];
  }
  return {question:null,path,migrated:false};
 }
 async function collect(course,attempts,events){
  const valid=attempts.filter(a=>snapshotValid(a)&&(!a.courseId||a.courseId===course.id));
  const byAttempt=new Map(valid.map(a=>[a.id,a])),marks=new Map(),reviews=new Map();
  for(const e of [...events].filter(e=>object(e)&&(!e.courseId||e.courseId===course.id)).sort(newest)){
   if(e.type==='mistake-mark'&&byAttempt.has(e.attemptId)&&typeof e.marked==='boolean'&&!marks.has(e.attemptId))marks.set(e.attemptId,e);
   if(e.type==='mistake-review'&&typeof e.groupKey==='string'&&['review','mastered'].includes(e.state)&&Array.isArray(e.evidenceIds)&&!reviews.has(e.groupKey))reviews.set(e.groupKey,e);
  }
  const groups=new Map();
  for(const a of valid){
   const groupKey=await key(a);let g=groups.get(groupKey);
   if(!g){g={groupKey,questionId:a.questionId,questionVersion:a.questionVersion,answerVersion:a.referenceAnswerVersion,questionSnapshot:a.questionSnapshot,referenceAnswer:a.referenceAnswer,chapterIds:[...(a.chapterIds||a.questionSnapshot.chapterIds||[])],attempts:[],wrongAttempts:[],evidenceIds:[],automaticCount:0,manualCount:0};groups.set(groupKey,g)}
   const checked=assessment(a),mark=marks.get(a.id);g.attempts.push(a);
   if(checked.automatic){g.evidenceIds.push('auto:'+a.id);g.automaticCount++}
   if(mark?.marked){g.evidenceIds.push('manual:'+mark.id);g.manualCount++}
   if(checked.automatic||mark?.marked)g.wrongAttempts.push(a);
  }
  const result=[];
  for(const g of groups.values()){
   if(!g.wrongAttempts.length)continue;
   g.attempts.sort((a,b)=>b.submittedAt.localeCompare(a.submittedAt)||b.id.localeCompare(a.id));g.wrongAttempts.sort((a,b)=>b.submittedAt.localeCompare(a.submittedAt)||b.id.localeCompare(a.id));g.evidenceIds.sort();
   const review=reviews.get(g.groupKey);g.state=review?.state==='mastered'&&g.evidenceIds.every(id=>review.evidenceIds.includes(id))?'mastered':'review';g.reviewEvent=review||null;
   const resolved=resolveCurrent(course,g.questionId);g.currentQuestionId=resolved.question?.id||null;g.aliasPath=resolved.path;
   if(!resolved.question)g.currentStatus='missing';
   else{const q=resolved.question,currentKey=await key({questionId:q.id,questionVersion:q.version,referenceAnswerVersion:q.answer?.version,questionSnapshot:q,referenceAnswer:q.answer});g.currentStatus=currentKey===g.groupKey?'same':resolved.migrated?'renamed':'changed'}
   g.lastWrongAt=g.wrongAttempts[0].submittedAt;result.push(g);
  }
  result.sort((a,b)=>b.lastWrongAt.localeCompare(a.lastWrongAt)||a.groupKey.localeCompare(b.groupKey));return result;
 }
 const api={collect,key,assessment,resolveCurrent,stable};if(typeof module==='object'&&module.exports)module.exports=api;else root.DTHMistakes=api;
})(typeof window==='object'?window:globalThis);
