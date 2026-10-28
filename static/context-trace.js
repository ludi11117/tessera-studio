'use strict';
let inspirationTimer;
function contextSignature(){
  if(!S.guidance)return '';
  const g=structuredClone(S.guidance);delete g.confirmed;delete g.inspiration;delete g.answers.direction;
  return JSON.stringify({guidance:g,materials:S.materials});
}
function contextualGuideHTML(){return '<section class="context-guide"><h4>围绕这次想法，找具体方向</h4><div id="context-guide-content" role="status">正在整理本次想法与素材…</div></section>';}
async function ensureContextGuide(force=false){
  const signature=contextSignature();
  if(!force&&S.contextGuide?.signature===signature){paintContextGuide();return;}
  const payload={guidance:structuredClone(S.guidance),materials:structuredClone(S.materials)};
  try{
    const preview=await api('/api/guidance/preview',payload);
    if(signature!==contextSignature())return;
    S.contextGuide={signature,preview,payload,job:null};paintContextGuide();
    const {jobs}=await api('/api/ai/jobs');
    if(signature!==contextSignature())return;
    const job=jobs.find(j=>j.kind==='inspire'&&j.context_hash===preview.context_hash);
    if(job){S.contextGuide.job=job;paintContextGuide();if(['queued','running'].includes(job.status))pollInspiration(job.id,signature);}
  }catch(e){const host=$('#context-guide-content');if(host)host.innerHTML=`<p>${esc(e.message)}</p><button type="button" class="button-quiet" data-context-refresh>重新整理本次输入</button>`;}
}
function paintContextGuide(){
  const host=$('#context-guide-content'),state=S.contextGuide;if(!host||!state||state.signature!==contextSignature())return;
  const p=state.preview,j=state.job,pending=j&&['queued','running'].includes(j.status),generated=j?.status==='completed',rows=generated?j.result.directions:p.local_directions;
  host.innerHTML=`<p class="context-idea">${esc(p.brief.original_idea)}</p><details class="context-basis"><summary>本次已知输入 · ${p.basis.length} 条</summary>${p.basis.map(b=>`<div><b>${esc(b.label)}</b><p>${esc(b.text.slice(0,240))}${b.text.length>240?'…':''}</p></div>`).join('')}<p>待确认 ${p.brief.unresolved.length} 项；未知不会当作事实。</p></details><div class="context-directions">${rows.map(d=>`<article><span class="small-kicker">${generated?'本次模型探索':'结合输入的本地起点'}</span><h4>${esc(d.name)}</h4><p>${esc(d.preview)}</p><p class="field-note">${esc(d.tradeoff)}</p><details><summary>查看输入依据</summary>${d.basis_quotes.map(q=>`<blockquote>${esc(q.quote)}<small>${esc(p.basis.find(b=>b.id===q.id)?.label||q.id)}</small></blockquote>`).join('')}</details><button type="button" class="button-quiet" data-context-pick="${esc(d.id)}">按这个方向继续 ↗</button></article>`).join('')}</div><p class="field-note">${generated?'这些是探索建议，引用只核对输入原文；成品内容仍需核查。选择后才纳入需求卡。':'本地起点会带入本次想法和明确回答。也可以让当前模型据此写出更具体的示例。'}</p>${j&&['error','cancelled','interrupted'].includes(j.status)?`<p class="context-error">${esc(j.error||'探索已停止')}。通用示意与本地起点仍可使用。</p>`:''}<div class="guide-actions"><button type="button" class="button-primary" data-context-generate ${pending?'disabled':''}>${pending?'正在探索…':generated?'再探索一组 · 1次模型请求':'结合本次需求生成灵感 · 1次模型请求'}</button>${pending?'<button type="button" class="button-quiet" data-context-cancel>停止探索</button>':''}<button type="button" class="button-quiet" data-context-refresh>更新本次输入</button></div><p class="field-note">点击模型探索会将本次想法、明确回答和相关素材发送至 ${esc(S.config?.base_url||'当前配置接口')}，每次最多1次请求。</p>`;
}
async function pollInspiration(id,signature){
  clearTimeout(inspirationTimer);
  try{
    const job=await api('/api/ai/jobs/'+id);
    if(S.contextGuide?.signature!==signature||signature!==contextSignature())return;
    S.contextGuide.job=job;paintContextGuide();
    if(['queued','running'].includes(job.status)&&$('#guidance-dialog').open)inspirationTimer=setTimeout(()=>pollInspiration(id,signature),700);
  }catch(e){toast(e.message);}
}
function traceHTML(){
  const t=S.delivery?.requirement_trace;if(!t)return '';
  const labels={needs_input:'待补充信息',no_evidence:'暂未定位到文字线索',needs_review:'已定位线索 · 待核对',user_met:'你已确认满足',user_gap:'你已标记缺口',machine_passed:'机器条件通过',machine_failed:'机器条件未通过'};
  const confirmed=t.counts.user_met||0,gaps=t.counts.user_gap||0,unknown=t.counts.needs_input||0;
  return `<section class="source-card requirement-trace"><span class="small-kicker">需求 → 内容 → 逐项核对</span><h3>最初想要的，成果里体现了吗？</h3><p>${confirmed} 项明确需求由你确认满足 · ${gaps} 项已标记缺口 · ${unknown} 项信息待补充</p><p>文字线索用于定位。请查看实际内容，再确认这项要求是否已经满足。</p>${t.rows.map((r,i)=>`<article class="trace-row" data-trace-row="${esc(r.id)}"><div class="trace-row-heading"><div><span>${esc(r.label)}</span><h4>${esc(r.text)}</h4></div><b class="trace-status ${r.status==='user_gap'||r.status==='machine_failed'?'gap':''}">${labels[r.status]}</b></div>${r.stale_review?'<p class="trace-stale">正文、需求或素材已变化，上次确认已过期，请重新核对。</p>':''}${r.kind==='intent'?`<form data-trace-form="${esc(r.id)}"><details ${r.status==='user_gap'||i===0?'open':''}><summary>查看内容并核对这一项</summary><div class="guide-actions"><button type="button" class="button-quiet" data-trace-semantic="${esc(r.id)}">查找语义线索 · 本地</button></div><div data-semantic-result="${esc(r.id)}"></div><div class="trace-evidence">${r.evidence.map(p=>`<blockquote>${esc(p.quote)}<button type="button" class="button-quiet" data-trace-locate="${esc(p.block)}">${esc(p.title)} · 查看章节 ↗</button></blockquote>`).join('')||'<p>当前没有足够的文字匹配线索。可自行选择相关章节核对，或标记缺口。</p>'}</div><fieldset><legend>哪些章节体现了这项要求？</legend>${t.sections.map(s=>`<label><input type="checkbox" name="trace-block" value="${esc(s.block)}" ${r.review?.blocks.includes(s.block)?'checked':''}>${esc(s.title)}</label>`).join('')}</fieldset>${r.selected_sections?.length?`<details><summary>查看你确认时关联的当前章节</summary>${r.selected_sections.map(s=>`<h5>${esc(s.title)}</h5><p>${esc(s.text)}</p>`).join('')}</details>`:''}<label>补充说明（选填）<input name="trace-note" maxlength="500" value="${esc(r.review?.note||'')}" placeholder="例如：已交代操作，但还缺异常情况"></label><div class="guide-actions"><button class="button-quiet" type="submit" data-trace-decision="met">这一项已满足</button><button class="button-quiet" type="submit" data-trace-decision="gap">仍有缺口</button>${r.review?'<button class="button-quiet" type="submit" data-trace-decision="clear">撤销确认</button>':''}<button class="button-quiet" type="button" data-trace-revise="${esc(r.id)}">针对这一项准备修改 ↗</button></div></details></form>`:r.kind==='unknown'?`<p>这项信息仍需你补充；不能仅凭正文出现相似文字宣布已解决。</p><form data-trace-answer="${esc(r.id)}"><label>现在可以补充了<input name="trace-answer" maxlength="500" required placeholder="简单说一句，记录为本项目的明确要求"></label><button type="submit" class="button-quiet">记下这条信息</button><p class="field-note">保存只更新需求；正文需继续核对，不自动生成或标为满足。</p></form>`:`<p>${r.kind==='literal'?'检查指定原文是否仍在同一章节。':'仅表示这一条已实现的机器规则结果。'}</p>${r.evidence.map(p=>`<button type="button" class="button-quiet" data-trace-locate="${esc(p.block)}">${esc(p.title)} · 查看原文 ↗</button>`).join('')}`}</article>`).join('')}<p class="field-note">人工确认绑定当前正文、需求和素材；后续变更需要重新核对。逐项记录会进入交付包。</p></section>`;
}
function mountContextTrace(){
  $('#guidance-dialog').addEventListener('close',()=>clearTimeout(inspirationTimer));
}
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-context-refresh'))ensureContextGuide(true);
  else if(b.hasAttribute('data-context-generate'))run(async()=>{
    if(!(S.config?.ready??S.config?.key_configured)||!S.config?.model){openSettings();toast('先配置模型后再探索；本地起点仍可使用。');return;}
    const c=S.contextGuide;if(!c||c.signature!==contextSignature())throw new Error('输入已变化，请先更新本次输入');
    if(c.job&&['queued','running'].includes(c.job.status))return;
    const job=await jobRequest('/api/ai/inspire',c.payload);c.job=job;paintContextGuide();pollInspiration(job.id,c.signature);
  });
  else if(b.hasAttribute('data-context-cancel'))run(async()=>{const c=S.contextGuide;if(c?.job){c.job=await api('/api/ai/jobs/'+c.job.id+'/cancel',{});paintContextGuide();}});
  else if(b.dataset.contextPick){const c=S.contextGuide;if(!c||c.signature!==contextSignature()){toast('输入已变化，请先更新本次输入');return;}
    const generated=c.job?.status==='completed',rows=generated?c.job.result.directions:c.preview.local_directions,chosen=rows.find(d=>d.id===b.dataset.contextPick);if(!chosen)return;
    delete S.guidance.inspiration;answerGuide(chosen.instruction);
    if(generated)S.guidance.inspiration={job:c.job.id,choice:chosen.id,context_hash:c.preview.context_hash};
    scheduleDraft();
  }
  else if(b.dataset.traceSemantic)run(async()=>{
    b.disabled=true;const id=b.dataset.traceSemantic,t=S.delivery.requirement_trace,sid=S.sid;
    try{const result=await api(endpoint('/requirement-evidence'),{revision:S.view.revision,snapshot_hash:t.snapshot_hash,requirement:id});
      if(S.sid!==sid||S.delivery.requirement_trace.snapshot_hash!==result.snapshot_hash)return;
      const host=document.querySelector('[data-semantic-result="'+id+'"]');if(host)host.innerHTML=`<p class="field-note">${esc(result.note)} · ${result.examined_chunks}/${result.total_chunks} 个本地片段${result.sampled?' · 长文按章节均匀抽取，可能遗漏':''}</p><div class="trace-evidence">${result.evidence.map(p=>`<blockquote>${esc(p.quote)}<button type="button" class="button-quiet" data-trace-locate="${esc(p.block)}">${esc(p.title)} · 查看章节 ↗</button></blockquote>`).join('')}</div><details><summary>本地模型依据</summary><p class="model-fingerprint">${esc(result.model_fingerprint)}</p><p>冻结编码器，只查找线索，没有训练或自动确认。</p></details>`;
    }finally{b.disabled=false;}
  });
  else if(b.dataset.traceLocate){activateTab('document');$('#block-'+b.dataset.traceLocate)?.scrollIntoView({block:'center',behavior:'smooth'});}
  else if(b.dataset.traceRevise){const row=S.delivery.requirement_trace.rows.find(r=>r.id===b.dataset.traceRevise);if(!row)return;
    const form=b.closest('form'),blocks=[...form.querySelectorAll('[name=trace-block]:checked')].map(el=>el.value),note=form.querySelector('[name=trace-note]').value;
    const scope=blocks.length===1?blocks[0]:'all';restoreScope(scope);if($('#revision-scope').selectedOptions[0]?.disabled)restoreScope('all');
    $('#revision-input').value=`请针对这项需求修改：${row.text}\n${note?'发现的缺口：'+note+'\n':''}保留已满意的其他内容与局部原文；先生成可核对的修改草案。`;
    toggleFocus(false);scheduleRevisionDraft();$('#revision-input').focus();toast('修改要求已准备好，可补充后再发送。');
  }
});
document.addEventListener('submit',e=>{const form=e.target;if(form.matches('[data-trace-answer]')){e.preventDefault();const payload={requirement:form.dataset.traceAnswer,snapshot_hash:S.delivery.requirement_trace.snapshot_hash,answer:form.querySelector('[name=trace-answer]').value};run(async()=>{await mutate('requirement_answer',payload);toast('信息已记入当前需求，正文没有改变；请继续核对是否已经体现。');});return;}if(!form.matches('[data-trace-form]'))return;e.preventDefault();
  const decision=e.submitter?.dataset.traceDecision;if(!decision)return;
  const payload={requirement:form.dataset.traceForm,snapshot_hash:S.delivery.requirement_trace.snapshot_hash,decision,
    blocks:[...form.querySelectorAll('[name=trace-block]:checked')].map(el=>el.value),note:form.querySelector('[name=trace-note]').value};
  run(async()=>{await mutate('requirement_review',payload);toast(decision==='met'?'已记录你的确认，绑定当前版本。':decision==='gap'?'已标记这项缺口。':'已撤销这次确认。');});
});
