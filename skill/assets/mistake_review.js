'use strict';
// Exported without execution. toHTML embeds this self-contained function once.
((root) => {
 function bootstrapMistakeReview(){
  const bundle=JSON.parse(document.getElementById('review-data').textContent),notebook=bundle.notebook;
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const plain=x=>typeof x==='string'?x:x==null?'':typeof x==='object'?JSON.stringify(x,null,2):String(x);
  const object=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
  const imageURI=x=>/^data:image\/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$/.test(x||'')?x:null;
  const labels={original:'原资料答案与解析',teacher:'教师提供答案',unconfirmed:'来源未确认参考答案',ai:'AI生成参考答案，非官方答案'};
  const storageKey='digital-textbook-mistake-review:'+bundle.exportId,state=Object.create(null);
  let persistent=true,storageReason='';
  function math(tex,display=true){
   try{if(!window.katex)throw Error('missing');return window.katex.renderToString(String(tex),{displayMode:display,throwOnError:true,trust:false,strict:'error',maxExpand:1000})}
   catch(e){return '<span class="formula-source">'+esc(tex)+'</span>'}
  }
  function table(columns,rows){return '<div class="table-scroll"><table><thead><tr>'+(columns||[]).map(c=>'<th>'+esc(object(c)?c.label:plain(c))+'</th>').join('')+'</tr></thead><tbody>'+(rows||[]).map(row=>'<tr>'+(Array.isArray(row)?row:[row]).map(c=>'<td>'+esc(plain(c))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'}
  function diagram(b){const num=x=>Number.isFinite(Number(x))?Number(x):0;return '<figure><svg viewBox="0 0 640 360" role="img" aria-label="'+esc(b.alt||'模型示意图')+'"><path d="M65 25V310H610" stroke="currentColor" fill="none"/>'+(b.lines||[]).map((l,i)=>'<polyline fill="none" stroke="'+['#23665d','#ac573b','#5f6d9c'][i%3]+'" stroke-width="3" points="'+(l.points||[]).map(p=>num(p[0])+','+num(p[1])).join(' ')+'"/>').join('')+(b.labels||[]).map(t=>'<text x="'+num(t.x)+'" y="'+num(t.y)+'" font-size="16">'+esc(t.text)+'</text>').join('')+'</svg><figcaption>'+esc(b.caption||b.alt)+'</figcaption></figure>'}
  function blocks(list){return(list||[]).map(b=>{
   if(!object(b))return '<pre>'+esc(plain(b))+'</pre>';
   switch(b.type){
    case 'paragraph':return '<p>'+(Array.isArray(b.runs)?b.runs.map(r=>r.type==='math'?math(r.tex,false):esc(r.text)).join(''):esc(b.text))+'</p>';
    case 'heading':return '<h3>'+esc(b.text)+'</h3>';
    case 'list':return '<ul>'+(b.items||[]).map(v=>'<li>'+esc(plain(v))+'</li>').join('')+'</ul>';
    case 'math':return '<div class="math">'+math(b.tex,b.display!==false)+'</div>';
    case 'matrix':return '<div class="math">'+math('\\begin{pmatrix}'+(b.rows||[]).map(r=>r.join('&')).join('\\\\')+'\\end{pmatrix}')+'</div>';
    case 'table':return table(b.columns,b.rows);
    case 'image':return imageURI(b.data)?'<figure><img src="'+b.data+'" alt="'+esc(b.alt)+'"><figcaption>'+esc(b.caption||b.alt)+'</figcaption></figure>':'<p class="notice">原题图片未内嵌，保留的来源：'+esc(b.path||b.alt)+'</p>';
    case 'details':return '<details><summary>'+esc(b.title)+'</summary>'+blocks(b.blocks)+'</details>';
    case 'diagram':return diagram(b);
    default:return '<pre>'+esc(plain(b))+'</pre>';
   }
  }).join('')}
  function sources(refs){return '<p class="note">来源：'+(refs||[]).map(r=>esc(bundle.sources.find(s=>s.id===r.sourceId)?.title||r.sourceId)+' · '+esc(plain(r.locator))).join('；')+'</p>'}
  function parts(q){return(q.parts||[]).map(p=>'<section><h3>'+esc(p.label)+'</h3>'+(p.fields||[]).map(f=>'<p>'+esc(f.label)+'</p>'+(f.options?'<ul>'+f.options.map((o,i)=>'<li>'+esc(object(o)?o.value+' · '+o.label:i+' · '+plain(o))+'</li>').join('')+'</ul>':'')+(f.rows?table(f.columns,f.rows):'')+(f.placeholder?'<p class="note">'+esc(f.placeholder)+'</p>':'')).join('')+'</section>').join('')}
  function userAnswer(q,answer){
   const fields=(q.parts||[]).flatMap(p=>p.fields||[]),known=new Set(fields.map(f=>f.id));
   return fields.map(f=>{let value=answer?.[f.id];if(['choice','multiple'].includes(f.kind)){const label=v=>{const i=(f.options||[]).findIndex((o,i)=>String(object(o)?o.value:i)===String(v));return i<0?plain(v):plain(v)+' · '+plain(object(f.options[i])?f.options[i].label:f.options[i])};value=Array.isArray(value)?value.map(label):value==null?'':label(value)}return '<div><b>'+esc(f.label||f.id)+'</b>'+(f.kind==='formula'?'<div class="math">'+math(plain(value))+'</div>':Array.isArray(value)&&Array.isArray(value[0])?table(f.columns,value):'<pre>'+esc(plain(value)||'未填写')+'</pre>')+'</div>'}).join('')+Object.keys(answer||{}).filter(id=>!known.has(id)).map(id=>'<p>'+esc(id)+'</p><pre>'+esc(plain(answer[id]))+'</pre>').join('');
  }
  function attachments(ids){return(ids||[]).map(id=>{const a=notebook.tables.attachments.find(x=>x.id===id),uri=a?.blob?.__studyBlob?imageURI('data:'+a.blob.type+';base64,'+a.blob.data):null;return uri?'<figure><img src="'+uri+'" alt="'+esc(a.name||id)+'"><figcaption>'+esc(a.name||id)+'</figcaption></figure>':'<p class="note">附件 '+esc(a?.name||id)+' 可从原错题JSON中取出。</p>'}).join('')}
  function failStorage(reason){persistent=false;storageReason=reason;storageStatus()}
  function storageStatus(){const status=document.getElementById('storage-status');status.className=persistent?'note':'notice';status.textContent=persistent?'本页记录已单独保存在此浏览器。换浏览器或移动文件前，请导出本页复习结果。':'本页记录尚未可靠保存（'+storageReason+'），仅保留在当前页面内存。请保持页面并导出本页复习结果。'}
  for(const item of bundle.items)state[item.groupKey]={state:item.state==='mastered'?'mastered':'review',draft:'',viewedAnswer:false,practices:[]};
  try{
   const raw=localStorage.getItem(storageKey);
   if(raw){const saved=JSON.parse(raw);if(!object(saved)||saved.format!=='digital-textbook-review-state'||saved.formatVersion!==1||saved.exportId!==bundle.exportId||!object(saved.entries))throw Error('已有复习记录无法确认');
    for(const key of Object.keys(state)){const entry=saved.entries[key];if(!entry)continue;
     if(!object(entry)||!['review','mastered'].includes(entry.state)||typeof entry.draft!=='string'||typeof entry.viewedAnswer!=='boolean'||!Array.isArray(entry.practices)||entry.practices.some(p=>!object(p)||typeof p.id!=='string'||typeof p.at!=='string'||typeof p.answer!=='string'||typeof p.viewedAnswerBeforeSave!=='boolean'))throw Error('已有复习记录格式不完整');
     state[key]={state:entry.state,draft:entry.draft,viewedAnswer:entry.viewedAnswer,practices:entry.practices.map(p=>({id:p.id,at:p.at,answer:p.answer,viewedAnswerBeforeSave:p.viewedAnswerBeforeSave}))};
    }
   }
   const probe=storageKey+':probe';localStorage.setItem(probe,'1');if(localStorage.getItem(probe)!=='1')throw Error('浏览器未保存探测记录');localStorage.removeItem(probe);
  }catch(e){failStorage(e.message||'浏览器存储不可用')}
  function save(){if(!persistent)return;try{const data=JSON.stringify({format:'digital-textbook-review-state',formatVersion:1,exportId:bundle.exportId,entries:state});localStorage.setItem(storageKey,data);if(localStorage.getItem(storageKey)!==data)throw Error('浏览器未保留新记录')}catch(e){failStorage(e.message||'浏览器拒绝保存')}}
  function practiceHistory(card,entry){card.querySelector('[data-practice-history]').innerHTML=entry.practices.length?entry.practices.map(p=>'<div class="history-item"><p>'+esc(p.at)+' · 保存前'+(p.viewedAnswerBeforeSave?'已看':'未看')+'参考解析</p><pre>'+esc(p.answer)+'</pre></div>').join(''):'<p class="note">本页尚无练习记录。</p>'}
  const main=document.getElementById('review-main');
  main.innerHTML=bundle.items.map(item=>{
   const q=item.questionSnapshot,a=item.referenceAnswer,key=item.groupKey;
   return '<article data-review-group="'+esc(key)+'"><h2>'+esc(q.number||item.questionId)+' · '+esc(q.title)+'</h2><p class="note">'+esc(item.chapterIds.map(id=>bundle.chapters.find(c=>c.id===id)?.title||id).join('、'))+' · 题目 '+esc(item.questionVersion)+' / 答案 '+esc(item.answerVersion)+'</p><p class="note">'+({same:'当前教材仍有同版本题目。',changed:'当前教材题目已更新；本页保留当时版本。',renamed:'当前教材题目已改名；本页保留原记录。',missing:'当前教材已移除此题；本页仍可阅读原题与记录。'}[item.currentStatus]||'本页保留导出时的历史版本。')+'</p><h3>当时题设</h3>'+blocks(q.prompt)+parts(q)+sources(q.sourceRefs)+'<label>本页练习<textarea data-review-draft aria-label="本页练习" placeholder="记录你的重做过程；复杂表格或公式可用文本描述。"></textarea></label><div class="actions"><button data-save-practice>保存本次练习</button><button class="secondary" data-new-practice>开始新一次练习</button></div><p data-practice-status role="status" class="note">本页练习由你对照解析自评，不自动判分。</p><details data-answer><summary>展开当时参考解析</summary><p class="note">'+esc(labels[a.provenance]||a.provenance)+'</p>'+blocks(a.blocks)+sources(a.sourceRefs)+'</details><label>本页复习状态<select data-review-state><option value="review">待复习</option><option value="mastered">已掌握</option></select></label><details><summary>本页练习记录</summary><div data-practice-history></div></details><details data-old-history><summary>教材中的历次作答（'+item.attempts.length+'）</summary>'+item.attempts.map(attempt=>'<section class="history-item"><h3>'+esc(attempt.submittedAt)+'</h3><p class="note">'+(item.wrongAttemptIds.includes(attempt.id)?'错题来源':'同版本其他作答')+' · 当时判定：'+esc(attempt.judgment?.result||'未记录')+' · 提交前'+(attempt.viewedAnswerBeforeSubmission?'已看':'未看')+'解析</p>'+userAnswer(q,attempt.userAnswer)+attachments(attempt.attachments)+'</section>').join('')+'</details></article>';
  }).join('')||'<p class="empty">当前筛选没有错题。</p>';
  for(const card of main.querySelectorAll('[data-review-group]')){
   const key=card.dataset.reviewGroup,entry=state[key],input=card.querySelector('[data-review-draft]'),select=card.querySelector('[data-review-state]'),answer=card.querySelector('[data-answer]'),status=card.querySelector('[data-practice-status]');
   input.value=entry.draft;select.value=entry.state;practiceHistory(card,entry);
   input.oninput=()=>{entry.draft=input.value;save()};select.onchange=()=>{entry.state=select.value;save()};
   answer.ontoggle=()=>{if(answer.open){entry.viewedAnswer=true;save()}};
   card.querySelector('[data-save-practice]').onclick=()=>{if(!entry.draft.trim()){status.textContent='请先写下本次练习。';return}entry.practices.push({id:crypto.randomUUID(),at:new Date().toISOString(),answer:entry.draft,viewedAnswerBeforeSave:entry.viewedAnswer});save();practiceHistory(card,entry);status.textContent=persistent?'已保存本次练习，原教材记录未改变。':'本次练习已留在本页内存，请导出复习结果。'};
   card.querySelector('[data-new-practice]').onclick=()=>{entry.draft='';input.value='';answer.open=false;entry.viewedAnswer=false;save();status.textContent='已开始新一次练习，过去记录仍保留。';input.focus()};
  }
  function download(data,name){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}
  document.getElementById('export-original').onclick=()=>download(notebook,'原错题记录.json');
  document.getElementById('export-review').onclick=()=>download({format:'digital-textbook-review-results',formatVersion:1,exportId:bundle.exportId,exportedAt:new Date().toISOString(),sourceCourse:notebook.course,sourceExportedAt:notebook.exportedAt,note:'本页独立复习结果，不会自动回写原教材；此文件不是完整学习备份。',entries:bundle.items.map(item=>({groupKey:item.groupKey,questionId:item.questionId,questionVersion:item.questionVersion,answerVersion:item.answerVersion,...state[item.groupKey]})),originalNotebook:notebook},'错题复习结果.json');
  storageStatus();window.DTHMistakeReviewPage={ready:true,storageKey};
 }
 if(typeof module==='object'&&module.exports)module.exports=bootstrapMistakeReview;else root.DTHMistakeReview=bootstrapMistakeReview;
})(typeof window==='object'?window:globalThis);
