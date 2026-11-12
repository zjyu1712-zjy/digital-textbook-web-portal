'use strict';
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={
  content:{mapped:'已整理',partial:'有待补内容',unknown:'范围待核对',empty:'尚未整理'},
  review:{current:'记录有效',stale:'需重新审校',failed:'发现问题',pending:'待复核',unreviewed:'尚未审校',invalid:'记录需处理','not-reviewed':'尚未审校','legacy-unverified':'旧记录待核对'},
  independent:{'sampled-pass':'样本通过','not-reviewed':'尚未抽检','not-sampled':'未纳入本次样本',pending:'抽检未完成',stale:'需重新抽检',failed:'发现问题',invalid:'记录需处理'},
  verification:{pass:'已检查所列范围',partial:'部分内容已检查','not-verified':'未单独验证',stale:'需重新验证',failed:'检查未通过',pending:'检查未完成',invalid:'记录需处理'}
 };
 const text=(kind,status)=>labels[kind]?.[status]||'尚无有效记录';
 const row=(course,id)=>course.validation?.chapterStatus?.chapters?.find(c=>c.chapterId===id);
 const status=(name,kind,value)=>'<span class="chapter-status-item" data-status="'+esc(value||'unknown')+'"><b>'+esc(name)+'</b>'+esc(text(kind,value))+'</span>';
 function summary(course,id){
  const c=row(course,id);if(!c)return '<div class="chapter-status-summary"><span>本章状态尚未记录</span></div>';
  return '<div class="chapter-status-summary">'+status('内容','content',c.content.status)+status('审校','review',c.review.status)+status('抽检','independent',c.independent.status)+'</div>';
 }
 function evidence(c,kind){
  const v=c.verification[kind],records=v.records||[];
  return '<section class="chapter-verification"><h3>'+esc(kind==='offline'?'离线功能':'视觉检查')+' · '+esc(text('verification',v.status))+'</h3><p>已记录检查 '+esc(v.verifiedCount)+' / '+esc(v.targetCount)+' 项内容。'+(kind==='offline'?'这里展示实际执行的检查，作答测试范围以记录为准。':'截图以实际可见内容为准，不扩大到整章。')+'</p>'+records.map(r=>'<details><summary>'+esc(r.checkedAt)+' · '+esc(r.result==='pass'?'通过':r.result==='fail'?'未通过':'待完成')+'</summary><p>'+esc(r.method)+'</p><p>'+esc(r.evidence)+'</p><p>检查项目：'+esc(r.checks.join('、'))+'</p><p>内容范围：'+esc(r.targetIds.join('、'))+'</p><p>核查者：'+esc(r.reviewer)+'</p><small>文件校验值 '+esc(r.artifactSHA256)+'</small></details>').join('')+(v.staleRecords?'<p>另有 '+esc(v.staleRecords)+' 条旧版验证记录，未计入当前范围。</p>':'')+'</section>';
 }
 function chapter(course,id){
  const c=row(course,id);if(!c)return '';
  const i=c.independent;
  return '<details class="chapter-quality" data-chapter-quality="'+esc(id)+'"><summary><span>本章完成情况</span>'+summary(course,id)+'</summary><div class="chapter-quality-body"><p>内容已整理 '+esc(c.content.mappedCount)+' / '+esc(c.content.itemCount)+' 个来源条目；审校记录当前有效 '+esc(c.review.currentCount)+' / '+esc(c.review.targetCount)+' 项内容。整理数量不能代替正确性核查。</p><p>独立抽检：'+esc(text('independent',i.status))+'，已核查 '+esc(i.reviewedCount)+' / '+esc(i.selectedCount)+' 个样本。抽样通过不代表全文已复核。</p>'+evidence(c,'offline')+evidence(c,'visual')+'</div></details>';
 }
 function overview(course){
  const report=course.validation?.chapterStatus;if(!report)return '<p>此教材尚未记录章级状态。</p>';
  const rows=report.chapters||[];
  return '<section class="chapter-overview" aria-label="章级完成情况"><h2>各章完成情况</h2><p>内容整理、审校、抽检和功能验证分别记录；教材或显示组件改变后，旧验证需要重新核对。</p><div class="table-scroll"><table><thead><tr><th>章节</th><th>内容</th><th>审校</th><th>独立抽检</th><th>离线功能</th><th>视觉检查</th></tr></thead><tbody>'+rows.map(c=>'<tr><td><a href="#chapter/'+esc(c.chapterId)+'">'+esc(c.title)+'</a></td><td>'+esc(text('content',c.content.status))+'</td><td>'+esc(text('review',c.review.status))+'</td><td>'+esc(text('independent',c.independent.status))+'<br>'+esc(c.independent.reviewedCount)+' / '+esc(c.independent.selectedCount)+' 样本</td><td>'+esc(text('verification',c.verification.offline.status))+'<br>'+esc(c.verification.offline.verifiedCount)+' / '+esc(c.verification.offline.targetCount)+' 项</td><td>'+esc(text('verification',c.verification.visual.status))+'<br>'+esc(c.verification.visual.verifiedCount)+' / '+esc(c.verification.visual.targetCount)+' 项</td></tr>').join('')+'</tbody></table></div>'+((report.unassignedItems||[]).length?'<p class="warning">有 '+esc(report.unassignedItems.length)+' 个原资料条目尚未确定所属章节，不能确认各章范围完整。</p>':'')+rows.map(c=>chapter(course,c.chapterId)).join('')+'</section>';
 }
 window.DTHQuality={summary,chapter,overview};
})();
