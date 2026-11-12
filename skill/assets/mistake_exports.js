'use strict';
// Read-only exports from selected historical groups and one complete backup.
((root) => {
 const object=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
 const clone=x=>JSON.parse(JSON.stringify(x));
 const stable=x=>Array.isArray(x)?x.map(stable):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,stable(x[k])])):x;
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const json=x=>JSON.stringify(x,null,2);
 const plain=x=>typeof x==='string'?x:x==null?'':object(x)||Array.isArray(x)?json(x):String(x);
 const imageURI=a=>a?.blob?.__studyBlob===true&&/^image\/(png|jpeg|webp|gif)$/.test(a.blob.type)&&/^[A-Za-z0-9+/]+={0,2}$/.test(a.blob.data||'')?'data:'+a.blob.type+';base64,'+a.blob.data:null;
 const knownImage=value=>/^data:image\/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$/.test(value||'');
 function prepare(course,backup,groups,filters={}){
  if(!object(course)||typeof course.id!=='string'||!object(backup)||backup.format!=='digital-textbook-backup'||backup.formatVersion!==1||backup.course?.id!==course.id||!Array.isArray(groups))throw Error('错题导出需要同一本教材的完整备份和筛选结果。');
  for(const table of ['attempts','attachments','events'])if(!Array.isArray(backup.tables?.[table]))throw Error('完整备份缺少'+table+'。');
  const attemptsById=new Map(backup.tables.attempts.map(a=>[a.id,a])),seen=new Set(),ids=new Set(),keys=new Set();
  const items=groups.map(g=>{
   if(!object(g)||!/^([a-f0-9]{64})$/.test(g.groupKey)||seen.has(g.groupKey)||!Array.isArray(g.attempts)||!g.attempts.length||!object(g.questionSnapshot)||!object(g.referenceAnswer))throw Error('错题归集结果缺少有效的历史快照。');
   seen.add(g.groupKey);keys.add(g.groupKey);
   const attempts=g.attempts.map(a=>{const original=attemptsById.get(a.id);if(!original||original.courseId&&original.courseId!==course.id)throw Error('错题记录与完整备份不一致，请重新导出。');ids.add(original.id);return original});
   const first=attempts[0];
   if(attempts.some(a=>a.questionId!==g.questionId||a.questionVersion!==g.questionVersion||a.referenceAnswerVersion!==g.answerVersion||JSON.stringify(stable(a.questionSnapshot))!==JSON.stringify(stable(first.questionSnapshot))||JSON.stringify(stable(a.referenceAnswer))!==JSON.stringify(stable(first.referenceAnswer))))throw Error('同一错题组混入了不同题目或答案版本。');
   const wrongIds=(g.wrongAttempts||[]).map(a=>a.id);if(wrongIds.some(id=>!attempts.some(a=>a.id===id)))throw Error('错题来源不属于当前导出组。');
   return {groupKey:g.groupKey,questionId:g.questionId,questionVersion:g.questionVersion,answerVersion:g.answerVersion,chapterIds:[...(g.chapterIds||[])],state:g.state,currentStatus:g.currentStatus,currentQuestionId:g.currentQuestionId||null,wrongAttemptIds:wrongIds,questionSnapshot:first.questionSnapshot,referenceAnswer:first.referenceAnswer,attempts};
  });
  const attempts=backup.tables.attempts.filter(a=>ids.has(a.id)),attachmentIds=new Set(attempts.flatMap(a=>a.attachments||[])),attachments=backup.tables.attachments.filter(a=>attachmentIds.has(a.id));
  if([...attachmentIds].some(id=>!attachments.some(a=>a.id===id)))throw Error('错题附件缺失，不能导出为完整错题记录。');
  const notebook={format:'digital-textbook-mistakes',formatVersion:1,exportedAt:backup.exportedAt,course:backup.course,filters:{...filters},note:'这是当前筛选的错题与相关记录，不是完整学习备份；不能作为完整备份导入。',entries:groups.map(({groupKey,questionId,questionVersion,answerVersion,chapterIds,state,evidenceIds,currentQuestionId,currentStatus,aliasPath})=>({groupKey,questionId,questionVersion,answerVersion,chapterIds,state,evidenceIds,currentQuestionId,currentStatus,aliasPath})),tables:{attempts,attachments,events:backup.tables.events.filter(e=>ids.has(e.attemptId)||keys.has(e.groupKey))}};
  return clone({format:'digital-textbook-mistake-export',formatVersion:1,exportId:crypto.randomUUID(),notebook,items,chapters:(course.chapters||[]).map(c=>({id:c.id,title:c.title})),sources:(course.sources||[]).map(s=>({id:s.id,title:s.title,locator:s.locator,identity:s.identity,sha256:s.sha256}))});
 }
 function blockText(blocks){return(blocks||[]).map(b=>{
  if(!object(b))return plain(b);
  switch(b.type){
   case 'paragraph':return Array.isArray(b.runs)?b.runs.map(r=>r.type==='math'?'[公式] '+plain(r.tex):plain(r.text)).join(''):plain(b.text);
   case 'heading':return plain(b.text);
   case 'list':return(b.items||[]).map(x=>'• '+plain(x)).join('\n');
   case 'math':return '[公式] '+plain(b.tex);
   case 'matrix':return '[矩阵]\n'+json(b.rows||[]);
   case 'table':return '[表格]\n'+json({columns:b.columns||[],rows:b.rows||[]});
   case 'image':return '[图片] '+plain(b.caption||b.alt)+' ('+plain(b.path)+')';
   case 'details':return plain(b.title)+'\n'+blockText(b.blocks);
   case 'diagram':return '[结构化图] '+plain(b.caption||b.alt)+'\n'+json({lines:b.lines||[],labels:b.labels||[]});
   default:return json(b);
  }
 }).join('\n\n')}
 function references(bundle,refs){return(refs||[]).map(r=>(bundle.sources.find(s=>s.id===r.sourceId)?.title||r.sourceId)+' · '+plain(r.locator)).join('\n')}
 const provenance={original:'原资料答案与解析',teacher:'教师提供答案',unconfirmed:'来源未确认参考答案',ai:'AI生成参考答案，非官方答案'};
 const mdText=x=>esc(plain(x)).replace(/([\\`*_{}\[\]()#+.!|~-])/g,'\\$1');
 function fence(text,language=''){
  const value=plain(text),matches=value.match(/`+/g)||[],marker='`'.repeat(Math.max(3,...matches.map(m=>m.length+1)));
  return marker+language+'\n'+value+'\n'+marker;
 }
 function markdownBlocks(blocks){return(blocks||[]).map(b=>{
  if(b?.type==='math')return fence(b.tex,'tex');
  if(b?.type==='matrix'||b?.type==='table'||b?.type==='diagram')return fence(blockText([b]));
  if(b?.type==='image')return knownImage(b.data)?'!['+mdText(b.caption||b.alt||'原题图片')+']('+b.data+')':'图片未内嵌：'+mdText(b?.alt||b?.path||'待核对');
  if(b?.type==='details')return '**'+mdText(b.title)+'**\n\n'+markdownBlocks(b.blocks);
  return mdText(blockText([b]));
 }).join('\n\n')}
 function markdownParts(parts){return(parts||[]).map(p=>'**'+mdText(p.label)+'**\n\n'+(p.fields||[]).map(f=>mdText(f.label||f.id)+(f.options?'\n\n'+f.options.map((o,i)=>'- '+mdText(object(o)?o.value+' · '+o.label:i+' · '+plain(o))).join('\n'):'')+(f.rows?'\n\n'+fence(json({columns:f.columns||[],rows:f.rows}),'json'):'')+(f.placeholder?'\n\n'+mdText(f.placeholder):'')).join('\n\n')).join('\n\n')}
 function toMarkdown(bundle){
  const n=bundle.notebook,lines=['# 错题本 · '+mdText(n.course.title||n.course.id),'教材：'+mdText(n.course.id)+'；版本：'+mdText(n.course.version)+'；导出时间：'+mdText(n.exportedAt),'此文件保存当时题目、答案与历次记录。Markdown查看器对data URI图片支持不同；完整附件与快照同时保留在文末JSON中。本文件不能作为完整学习备份导入。'];
  for(const item of bundle.items){
   const q=item.questionSnapshot,a=item.referenceAnswer;
   lines.push('## '+mdText(q.number||item.questionId)+' · '+mdText(q.title||''),'章节：'+mdText(item.chapterIds.map(id=>bundle.chapters.find(c=>c.id===id)?.title||id).join('、')),'题目版本：'+mdText(item.questionVersion)+'；答案版本：'+mdText(item.answerVersion)+'；导出时状态：'+mdText(item.state==='mastered'?'已掌握':'待复习'),'### 当时题设',markdownBlocks(q.prompt),'### 作答要求与选项',markdownParts(q.parts),'来源：\n'+mdText(references(bundle,q.sourceRefs)),'### 当时参考解析',mdText(provenance[a.provenance]||a.provenance),markdownBlocks(a.blocks),'来源：\n'+mdText(references(bundle,a.sourceRefs)),'### 历次作答');
   for(const attempt of item.attempts){
    lines.push('#### '+mdText(attempt.submittedAt)+' · '+(item.wrongAttemptIds.includes(attempt.id)?'错题来源':'同版本其他作答'),fence(json(attempt.userAnswer),'json'),'当时判定：'+mdText(attempt.judgment?.result||'未记录')+'；提交前'+(attempt.viewedAnswerBeforeSubmission?'已看解析':'未看解析'));
    for(const id of attempt.attachments||[]){const image=n.tables.attachments.find(x=>x.id===id),uri=imageURI(image);lines.push(uri?'!['+mdText(image.name||id)+']('+uri+')':'附件 '+mdText(image?.name||id)+' 保留在文末JSON中。')}
   }
  }
  lines.push('## 完整错题数据','以下JSON保留历史快照、图片字节和相关事件；属于错题导出格式，不是完整学习备份。',fence(json(n),'json'));
  return lines.join('\n\n')+'\n';
 }
 function csvCell(value){
  let text=plain(value);const first=text.replace(/^[\s\u0000-\u0020\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]+/u,'');
  const numeric=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text.trim());
  if((/^[=+\-@]/.test(first)&&!numeric)||/^[\t\r\n]/.test(text))text="'"+text;
  return '"'+text.replace(/"/g,'""')+'"';
 }
 function toCSV(bundle){
  const columns=['bookId','bookVersion','questionId','questionVersion','answerVersion','chapterIds','chapterNames','title','prompt','answerProvenance','referenceExplanation','wrongCount','lastWrongAt','reviewState','currentVersionStatus','questionSnapshotJSON','referenceAnswerJSON','attemptsJSON','attachmentsJSON','eventsJSON'];
  const rows=bundle.items.map(item=>{
   const ids=new Set(item.attempts.map(a=>a.id)),attachmentIds=new Set(item.attempts.flatMap(a=>a.attachments||[]));
   return [bundle.notebook.course.id,bundle.notebook.course.version,item.questionId,item.questionVersion,item.answerVersion,item.chapterIds,item.chapterIds.map(id=>bundle.chapters.find(c=>c.id===id)?.title||id),item.questionSnapshot.title,blockText(item.questionSnapshot.prompt),item.referenceAnswer.provenance,blockText(item.referenceAnswer.blocks),item.wrongAttemptIds.length,item.attempts.find(a=>item.wrongAttemptIds.includes(a.id))?.submittedAt||'',item.state,item.currentStatus,item.questionSnapshot,item.referenceAnswer,item.attempts,bundle.notebook.tables.attachments.filter(a=>attachmentIds.has(a.id)),bundle.notebook.tables.events.filter(e=>ids.has(e.attemptId)||e.groupKey===item.groupKey)];
  });
  return '\ufeff'+[columns,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n')+'\r\n';
 }
 const CSS=':root{color-scheme:light;--ink:#173e36;--line:#d8e1da;--muted:#617169}*{box-sizing:border-box}body{margin:0;background:#f6f5ee;color:var(--ink);font:17px/1.75 system-ui,-apple-system,"Microsoft YaHei",sans-serif}header,main{max-width:1080px;margin:auto;padding:28px}header{border-bottom:1px solid var(--line)}h1{font-size:clamp(28px,4vw,42px);line-height:1.3;margin:.3em 0}h2{font-size:24px;line-height:1.4}h3{font-size:19px}h1,h2,h3,summary,p{overflow-wrap:anywhere}article{background:#fffef9;border:1px solid var(--line);border-radius:14px;padding:28px;margin:24px 0}details{border:1px solid var(--line);border-radius:9px;padding:12px 16px;margin:16px 0}summary{cursor:pointer;font-weight:600}button,select,textarea{font:inherit;color:inherit}button{background:#24695c;color:white;border:0;border-radius:6px;padding:11px 16px;cursor:pointer}button.secondary{background:transparent;color:var(--ink);border:1px solid var(--ink)}textarea{width:100%;min-height:120px;background:white;border:1px solid #a6bcb2;border-radius:6px;padding:12px}select{padding:8px;max-width:100%;background:white;border:1px solid #a6bcb2;border-radius:5px}label{display:block;margin:12px 0}.actions{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.note,small{color:var(--muted);font-size:14px}.notice{background:#fff1d8;padding:12px;border-radius:8px}.status{background:#e8f0e8;padding:7px 11px;border-radius:6px;display:inline-block}pre{background:#f2f3ed;padding:12px;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:6px}img,svg{max-width:100%;height:auto}.table-scroll,.math{max-width:100%;overflow-x:auto}table{width:100%;border-collapse:collapse}td,th{padding:8px;border:1px solid var(--line);text-align:left}figure{margin:16px 0}figcaption{font-size:14px;color:var(--muted)}.katex{font-size:1.1em}.katex-display{margin:1em 0}.history-item{border-top:1px solid var(--line);padding-top:12px;margin-top:14px}.formula-source{font-family:monospace;white-space:pre-wrap}.empty{padding:24px}a{color:#24695c}@media(max-width:600px){header,main{padding:18px}article{padding:18px}h2{font-size:21px}.actions button{flex-grow:1}}';
 function toHTML(bundle,assets={}){
  let reviewSource=assets.reviewSource;
  if(!reviewSource){const bootstrap=typeof module==='object'&&module.exports?require('./mistake_review.js'):root.DTHMistakeReview;if(typeof bootstrap!=='function')throw Error('缺少本地复习页组件，不能导出空壳HTML。');reviewSource=bootstrap.toString()}
  const katexSource=assets.katexSource||'',katexCSS=assets.katexCSS||'';
  if(typeof reviewSource!=='string'||typeof katexSource!=='string'||typeof katexCSS!=='string')throw Error('离线显示资源必须是本地文本。');
  if(/<\/style\b|@import\b/i.test(katexCSS)||[...katexCSS.matchAll(/url\(([^)]+)\)/g)].some(m=>!/^['"]?data:font\//.test(m[1].trim())))throw Error('公式样式包含非内嵌资源，不能导出离线文件。');
  const data=JSON.stringify(bundle).replace(/[<>&\u2028\u2029]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  const endScript='<'+ '/script>';
  const safeScript=source=>source.replace(/<\/script/gi,'<\\/script');
  return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; font-src data:; connect-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>错题复习 · '+esc(bundle.notebook.course.title||bundle.notebook.course.id)+'</title><style>'+CSS+'\n'+katexCSS+'</style></head><body><header><div class="note">离线错题复习</div><h1>错题复习 · '+esc(bundle.notebook.course.title||bundle.notebook.course.id)+'</h1><p>按导出时的题目与答案版本复习。这里的练习和状态单独保存，不会自动回写原教材。</p><div class="actions"><button id="export-original" class="secondary">导出原错题JSON</button><button id="export-review">导出本页复习结果</button></div><p id="storage-status" role="status"></p>'+(katexSource&&katexCSS?'':'<p class="notice">未携带完整公式显示资源；公式保留LaTeX文本，请与原教材核对。</p>')+'</header><main id="review-main"></main><script id="review-data" type="application/json">'+data+endScript+'<script>'+safeScript(katexSource)+endScript+'<script>('+safeScript(reviewSource)+')();'+endScript+'</body></html>';
 }
 function download(text,filename,mime){const link=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:mime||'text/plain;charset=utf-8'}));link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}
 const api={prepare,toMarkdown,toCSV,toHTML,download,blockText,csvCell,imageURI};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.DTHMistakeExports=api;
})(typeof window==='object'?window:globalThis);
