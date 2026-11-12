'use strict';
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={
  availability:{ready:'可学习',partial:'部分待补',pending:'待补'},
  content:{mapped:'已整理',partial:'有待补内容',unknown:'范围待核对',empty:'尚未整理'},
  review:{current:'记录有效',stale:'需重新审校',failed:'发现问题',pending:'待复核',unreviewed:'尚未审校',invalid:'记录需处理','not-reviewed':'尚未审校','legacy-unverified':'旧记录待核对'},
  independent:{'sampled-pass':'样本通过','not-reviewed':'尚未抽检','not-sampled':'未纳入本次样本',pending:'抽检未完成',stale:'需重新抽检',failed:'发现问题',invalid:'记录需处理'},
  verification:{pass:'已检查所列范围',partial:'部分内容已检查','not-verified':'未单独验证',stale:'需重新验证',failed:'检查未通过',pending:'检查未完成',invalid:'记录需处理'}
 };
 const text=(kind,status)=>labels[kind]?.[status]||'尚无有效记录';
 const row=(course,id)=>course.validation?.chapterStatus?.chapters?.find(c=>c.chapterId===id);
 const status=(name,kind,value)=>'<span class="chapter-status-item" data-status="'+esc(value||'unknown')+'"><b>'+esc(name)+'</b>'+esc(text(kind,value))+'</span>';
 const count=value=>Number.isSafeInteger(value)&&value>=0?value:0;
 const names=(course,ids)=>ids.map(id=>course.chapters?.find(c=>c.id===id)?.title||id);
 const rangeName=(course,ids)=>{const titles=names(course,ids);return titles.length===1?titles[0]:titles.length?titles[0]+' — '+titles[titles.length-1]:''};
 function navStatus(course,id){return text('availability',row(course,id)?.availability?.status)}
 function progress(course){
  const r=course.validation?.chapterStatus?.learningRange;
  if(!r||r.status!=='reported')return '<section class="learning-progress" data-learning-progress><h2>本次可学习范围</h2><p>范围尚待核对；请先查看各章说明。</p></section>';
  const total=count(r.chapterCount),ready=Math.min(count(r.readyChapterCount),total),pending=count(r.blockingItemCount),prefix=Array.isArray(r.prefixChapterIds)?r.prefixChapterIds:[],ranges=Array.isArray(r.readyRanges)?r.readyRanges:[];
  return '<section class="learning-progress" data-learning-progress><div class="learning-progress-heading"><h2>本次可学习范围</h2><p><strong>'+ready+' / '+total+'</strong> 章可学习'+(pending?' · '+pending+' 项待处理':'')+'</p></div><progress max="'+Math.max(1,total)+'" value="'+ready+'" aria-label="本次收录章节中已整理并有有效审校记录的章节数"></progress><p class="learning-prefix">'+(prefix.length?'从本次首章起连续可学习：'+esc(rangeName(course,prefix)):'本次首章仍有待处理内容，尚无从首章开始的连续可用段。')+'</p><p class="learning-progress-note">按本次收录章节计算，表示学习内容与答案已整理、审校记录有效；离线功能和视觉验收另列。</p>'+((ranges.length>(prefix.length?1:0))?'<details><summary>查看其他可学习章节</summary><ul>'+ranges.filter(g=>!prefix.length||g.chapterIds?.[0]!==prefix[0]).map(g=>'<li>'+esc(rangeName(course,Array.isArray(g.chapterIds)?g.chapterIds:[]))+'</li>').join('')+'</ul></details>':'')+(count(r.optionalMaterialCount)?'<p class="learning-progress-note">另有 '+count(r.optionalMaterialCount)+' 项明确约定的可选资料待补，不阻断已整理的学习内容。</p>':'')+'</section>';
 }
 function summary(course,id){
  const c=row(course,id);if(!c)return '<div class="chapter-status-summary"><span>本章状态尚未记录</span></div>';
  return '<div class="chapter-status-summary">'+status('学习范围','availability',c.availability?.status)+status('审校','review',c.review.status)+status('抽检','independent',c.independent.status)+'</div>';
 }
 function availability(c){
  const a=c.availability;if(!a)return '<p>本章可学习范围尚未核对。</p>';
  const missing=Array.isArray(a.blockingItems)?a.blockingItems:[],optional=Array.isArray(a.optionalMaterials)?a.optionalMaterials:[];
  return '<section class="chapter-availability"><h3>学习内容 · '+esc(text('availability',a.status))+'</h3>'+((missing.length)?'<ul>'+missing.map(x=>'<li>'+esc(x.message)+(x.targetId||x.sourceItemId?' <small>（'+esc(x.targetId||x.sourceItemId)+'）</small>':'')+'</li>').join('')+'</ul>':'<p>本次学习内容与答案已整理，相关审校记录当前有效。</p>')+(optional.length?'<details><summary>可选待补资料（'+optional.length+'）</summary><ul>'+optional.map(x=>'<li>'+esc(x.description)+'：'+esc(x.reason)+'</li>').join('')+'</ul></details>':'')+(count(a.referencePendingCount)?'<p>仅作对照或存档的资料另有 '+count(a.referencePendingCount)+' 项整理或审校事项待处理，不计作学习主线缺口。</p>':'')+'</section>';
 }
 function evidence(c,kind){
  const v=c.verification[kind],records=v.records||[];
  return '<section class="chapter-verification"><h3>'+esc(kind==='offline'?'离线功能':'视觉检查')+' · '+esc(text('verification',v.status))+'</h3><p>已记录检查 '+esc(v.verifiedCount)+' / '+esc(v.targetCount)+' 项内容。'+(kind==='offline'?'这里展示实际执行的检查，作答测试范围以记录为准。':'截图以实际可见内容为准，不扩大到整章。')+'</p>'+records.map(r=>'<details><summary>'+esc(r.checkedAt)+' · '+esc(r.result==='pass'?'通过':r.result==='fail'?'未通过':'待完成')+'</summary><p>'+esc(r.method)+'</p><p>'+esc(r.evidence)+'</p><p>检查项目：'+esc(r.checks.join('、'))+'</p><p>内容范围：'+esc(r.targetIds.join('、'))+'</p><p>核查者：'+esc(r.reviewer)+'</p><small>文件校验值 '+esc(r.artifactSHA256)+'</small></details>').join('')+(v.staleRecords?'<p>另有 '+esc(v.staleRecords)+' 条旧版验证记录，未计入当前范围。</p>':'')+'</section>';
 }
 function discipline(c){
  const d=c.disciplineChecks;if(!d||d.status==='not-configured')return '<p>学科规则：未配置专门规则；不计作检查通过。</p>';
  const label={pass:'所列规则通过',fail:'发现不一致',invalid:'检查数据或规则需处理'}[d.status]||'待核对';
  const issues=[...new Set([...(d.checks||[]).flatMap(c=>c.issues||[]),...(d.configurationErrors||[])].map(x=>typeof x==='string'?x:x.message||x.detail||JSON.stringify(x)))];
  return '<section class="chapter-discipline"><h3>学科规则 · '+esc(label)+'</h3><p>仅检查声明的借贷、合计或维度关系，不替代内容审校。</p>'+(issues.length?'<ul>'+issues.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':'')+'</section>';
 }
 function chapter(course,id){
  const c=row(course,id);if(!c)return '';
  const i=c.independent;
  return '<details class="chapter-quality" data-chapter-quality="'+esc(id)+'"><summary><span>本章完成情况</span>'+summary(course,id)+'</summary><div class="chapter-quality-body">'+availability(c)+'<p>内容已整理 '+esc(c.content.mappedCount)+' / '+esc(c.content.itemCount)+' 个来源条目；审校记录当前有效 '+esc(c.review.currentCount)+' / '+esc(c.review.targetCount)+' 项内容。整理数量不能代替正确性核查。</p><p>独立抽检：'+esc(text('independent',i.status))+'，已核查 '+esc(i.reviewedCount)+' / '+esc(i.selectedCount)+' 个样本。抽样通过不代表全文已复核。</p>'+discipline(c)+evidence(c,'offline')+evidence(c,'visual')+'</div></details>';
 }
 function overview(course){
  const report=course.validation?.chapterStatus;if(!report)return '<p>此教材尚未记录章级状态。</p>';
  const rows=report.chapters||[];
  return '<section class="chapter-overview" aria-label="章级完成情况"><h2>各章完成情况</h2>'+progress(course)+'<p>内容整理、审校、抽检和功能验证分别记录；教材或显示组件改变后，旧验证需要重新核对。</p><div class="table-scroll"><table><thead><tr><th>章节</th><th>学习范围</th><th>内容</th><th>审校</th><th>独立抽检</th><th>离线功能</th><th>视觉检查</th></tr></thead><tbody>'+rows.map(c=>'<tr><td><a href="#chapter/'+esc(c.chapterId)+'">'+esc(c.title)+'</a></td><td>'+esc(text('availability',c.availability?.status))+'</td><td>'+esc(text('content',c.content.status))+'</td><td>'+esc(text('review',c.review.status))+'</td><td>'+esc(text('independent',c.independent.status))+'<br>'+esc(c.independent.reviewedCount)+' / '+esc(c.independent.selectedCount)+' 样本</td><td>'+esc(text('verification',c.verification.offline.status))+'<br>'+esc(c.verification.offline.verifiedCount)+' / '+esc(c.verification.offline.targetCount)+' 项</td><td>'+esc(text('verification',c.verification.visual.status))+'<br>'+esc(c.verification.visual.verifiedCount)+' / '+esc(c.verification.visual.targetCount)+' 项</td></tr>').join('')+'</tbody></table></div>'+((report.unassignedItems||[]).length?'<p class="warning">有 '+esc(report.unassignedItems.length)+' 个原资料条目尚未确定所属章节，不能确认各章范围完整。</p>':'')+rows.map(c=>chapter(course,c.chapterId)).join('')+'</section>';
 }
 window.DTHQuality={summary,chapter,overview,progress,navStatus};
})();
