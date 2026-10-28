'use strict';
const LOCAL_ACTIONS={concise:'更简洁',detail:'补细节',tone:'换个感觉',alternatives:'给我两个版本'};
function focusedMode(){return document.body.classList.contains('guided-mode');}
function setWorkspaceMode(full){
  document.body.classList.toggle('guided-mode',!full);$('#workspace-mode-toggle').textContent=full?'精简工作区':'完整工作台';
  $('#workspace-mode-toggle').setAttribute('aria-pressed',String(full));
  try{localStorage.setItem('tessera-workspace-mode',full?'full':'guided');}catch{}
  refreshFocused();
}
function refreshFocused(){
  const valid=!!S.guidance?.confirmed&&S.guidance.goal===$('#goal-input').value.trim();
  document.body.classList.toggle('guided-has-brief',valid);
  const form=$('#acceptance-form');
  if(form&&focusedMode()&&!form.closest('.focused-advanced')){
    const wrapper=document.createElement('details');wrapper.className='focused-advanced';const summary=document.createElement('summary');summary.textContent='调整与确认验收条件';wrapper.append(summary);form.before(wrapper);wrapper.append(form);
  }else if(form&&!focusedMode()&&form.closest('.focused-advanced')){const wrapper=form.closest('.focused-advanced');wrapper.before(form);wrapper.remove();}
  const next=$('#focused-next');if(next)next.remove();
  if(S.view&&$('#document-view')){
    const blocked=S.delivery?.acceptance?.contract.confirmed&&S.delivery.acceptance.failures.length;
    $('#document-view').insertAdjacentHTML('afterbegin',`<section id="focused-next" class="focused-next"><div><span class="small-kicker">接下来</span><p>${blocked?'先找一个满足条件的起点，再打磨细节。':'选中一句或一段就能局部调整，满意后核对整份作品。'}</p></div><button type="button" class="button-primary" data-focused-next="${blocked?'candidates':'sources'}">${blocked?'挑一个合格起点':'核对这份作品'} ↗</button></section>`);
  }
  if(S.localDraft&&(S.localDraft.sid!==S.sid||S.localDraft.revision!==S.view?.revision))$('#selection-toolbar')?.classList.add('hidden');
}
function chapterSurface(block){const b=S.view.task.blocks.find(b=>b.id===block);return text(variant(b));}
function selectionAt(block,full,start,end){return {sid:S.sid,revision:S.view.revision,original:full,block,variant:S.view.state.combo[block],start:[...full.slice(0,start)].length,end:[...full.slice(0,end)].length,text:full.slice(start,end)};}
function captureLocalSelection(){
  if(!S.view||S.tab!=='document'||$('#local-dialog')?.open)return;
  const selection=window.getSelection();if(!selection?.rangeCount||selection.isCollapsed){$('#selection-toolbar')?.classList.add('hidden');return;}
  const range=selection.getRangeAt(0),node=range.commonAncestorContainer.nodeType===1?range.commonAncestorContainer:range.commonAncestorContainer.parentElement;
  const markdownNode=node.closest?.('#document-view .document-section > .markdown');if(!markdownNode){$('#selection-toolbar')?.classList.add('hidden');S.localDraft=null;return;}
  const section=markdownNode.closest('.document-section'),block=section.id.slice('block-'.length),chosen=selection.toString(),full=chapterSurface(block),start=full.indexOf(chosen);
  if(!chosen.trim()||[...chosen].length>1500){$('#selection-toolbar')?.classList.add('hidden');S.localDraft=null;return;}
  if(S.view.state.locks[block]){$('#selection-toolbar')?.classList.add('hidden');return;}
  const unique=start>=0&&full.indexOf(chosen,start+1)<0;
  S.localDraft=unique?selectionAt(block,full,start,start+chosen.length):{sid:S.sid,revision:S.view.revision,block,original:full,variant:S.view.state.combo[block],text:''};
  $('#selection-toolbar').innerHTML=unique?`${Object.entries(LOCAL_ACTIONS).map(([k,label])=>`<button type="button" data-local-action="${k}">${label}</button>`).join('')}<small>生成草案 · 1次请求 · 采用后才替换</small>`:'<button type="button" data-local-open="'+esc(block)+'">选区有重复或排版，精确选取原文 ↗</button>';
  $('#selection-toolbar').classList.remove('hidden');
}
function openLocalEditor(block){
  const full=chapterSurface(block),old=S.localDraft;
  if(S.view.state.locks[block]){toast('这一章已锁定，请先解锁');return;}
  const valid=old?.block===block&&old.sid===S.sid&&old.revision===S.view.revision&&old.text;
  S.localDraft=valid?old:{sid:S.sid,revision:S.view.revision,block,variant:S.view.state.combo[block],original:full,text:''};
  $('#local-content').innerHTML=`<h3>只调整这一处。</h3><p>在下面的原文里选取一句或一段，再选择调整方式。</p><label>当前章节原文<textarea id="local-source" rows="7" readonly>${esc(full)}</textarea></label><div id="local-selection-status" role="status">${valid?esc(old.text):'还没有选中文字。'}</div><label>补充一句（选填）<input id="local-note" maxlength="500" placeholder="例如：保留语气，少一点铺垫"></label><div class="local-actions">${Object.entries(LOCAL_ACTIONS).map(([key,label])=>`<button type="button" class="button-quiet" data-local-action="${key}" ${valid?'':'disabled'}>${label}</button>`).join('')}</div><p class="field-note">每次最多1次模型请求。其他原文由程序保留；固定事实、锁定、局部保留与验收继续检查。</p>`;
  $('#selection-toolbar').classList.add('hidden');if(!$('#local-dialog').open)$('#local-dialog').showModal();
}
async function submitLocal(action){
  const d=S.localDraft;if(!d?.text)throw new Error('先选中一段连续原文');
  if(d.sid!==S.sid||d.revision!==S.view.revision)throw new Error('正文已变化，请重新选取');
  if(S.activeJob)throw new Error('已有AI任务进行中，请等待或取消');
  if(!(S.config?.ready??S.config?.key_configured)||!S.config.model){openSettings();return;}
  const job=await jobRequest(endpoint('/ai/local_revise'),{revision:d.revision,selection:{block:d.block,variant:d.variant,start:d.start,end:d.end,text:d.text},action,note:$('#local-note')?.value||''});
  $('#selection-toolbar').classList.add('hidden');$('#local-content').innerHTML='<p role="status">正在为选中文字起草替换。当前原文保持不变…</p>';
  if(!$('#local-dialog').open)$('#local-dialog').showModal();watch(job.id);
}
async function showLocalJob(jobOrId){
  const job=typeof jobOrId==='string'?await api('/api/ai/jobs/'+jobOrId):jobOrId;
  if(job.session!==S.sid)throw new Error('请先打开这份局部草案所属的作品');
  const r=job.result;if(job.status!=='completed'||!r?.options){$('#local-content').innerHTML=`<p role="status">${esc(job.error||job.progress||'草案尚未完成')}</p><button type="button" class="button-quiet" data-local-open="${esc(r?.target?.block||S.localDraft?.block||S.view.task.blocks.find(b=>!b.fixed).id)}">重新选取原文</button>`;}
  else{
    const stale=r.base_revision!==S.view.revision;
    $('#local-content').innerHTML=`<h3>只替换选中的文字。</h3><p class="field-note">${r.applied?'这次替换已采用。':stale?'正文已更新，这份草案只能查看。':'其他原文由程序保留，采用前仍可查看。'} 共 ${r.attempts?.length||1} 次模型请求。</p><section class="local-before"><span class="small-kicker">选中的原文</span><p>${esc(r.target.text)}</p></section><div class="local-options">${r.options.map(o=>`<article><span class="small-kicker">${esc(o.label)}</span><div class="local-replacement">${esc(o.replacement)}</div><p class="field-note">${esc(o.validation_message||'当前机器条件通过，语义与事实仍需核对。')}</p><button type="button" class="button-primary" data-local-apply="${esc(job.id)}" data-local-option="${esc(o.id)}" ${stale||r.applied||!o.can_apply?'disabled':''}>采用这一处</button></article>`).join('')}</div><details><summary>查看整章替换后的预览</summary>${r.options.map(o=>`<h4>${esc(o.label)}</h4><pre class="local-whole">${esc(o.after)}</pre>`).join('')}</details>`;
  }
  if(!$('#local-dialog').open)$('#local-dialog').showModal();
}
function mountFocused(){
  $('#open-settings').insertAdjacentHTML('beforebegin','<button id="workspace-mode-toggle" type="button" class="button-quiet">完整工作台</button>');
  document.body.insertAdjacentHTML('beforeend','<div id="selection-toolbar" class="selection-toolbar hidden" role="group" aria-label="选中文字的局部调整"></div><dialog id="local-dialog" class="studio-dialog local-dialog"><div class="dialog-heading"><div><span class="small-kicker">保留整体 · 微调局部</span><h2>打磨这一处</h2></div><button type="button" class="button-quiet" data-close="local-dialog">关闭 ✕</button></div><div id="local-content"></div></dialog>');
  let full=false;try{full=localStorage.getItem('tessera-workspace-mode')==='full';}catch{}setWorkspaceMode(full);
  $('#selection-toolbar').addEventListener('pointerdown',e=>e.preventDefault());
}
document.addEventListener('pointerup',e=>{if(e.target.closest?.('#selection-toolbar,#local-dialog'))return;captureLocalSelection();});
document.addEventListener('keyup',e=>{if(e.shiftKey)captureLocalSelection();});
document.addEventListener('selectionchange',()=>{if(!window.getSelection()?.toString())$('#selection-toolbar')?.classList.add('hidden');});
function readLocalRange(){const el=$('#local-source');if(!el||el.selectionStart===el.selectionEnd)return;const d=S.localDraft;S.localDraft=selectionAt(d.block,el.value,el.selectionStart,el.selectionEnd);$('#local-selection-status').textContent=S.localDraft.text;document.querySelectorAll('#local-dialog [data-local-action]').forEach(b=>b.disabled=[...S.localDraft.text].length>1500);}
document.addEventListener('select',e=>{if(e.target.id==='local-source')readLocalRange();});
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  if(b.id==='workspace-mode-toggle')setWorkspaceMode(focusedMode());
  else if(b.dataset.focusedNext){if(b.dataset.focusedNext==='candidates'){S.choiceMode='compare';renderChoiceBoard();}activateTab(b.dataset.focusedNext);}
  else if(b.dataset.localOpen)openLocalEditor(b.dataset.localOpen);
  else if(b.dataset.localAction)run(()=>submitLocal(b.dataset.localAction));
  else if(b.dataset.openLocal)run(()=>showLocalJob(b.dataset.openLocal));
  else if(b.dataset.localApply)run(async()=>{await api('/api/ai/jobs/'+b.dataset.localApply+'/apply',{revision:S.view.revision,option:b.dataset.localOption});$('#local-dialog').close();await refreshDocument();await loadHistory();toast('已替换这一处；其余原文保持，可以撤回。');});
});
