'use strict';
// Four connected steps over the existing generation/customization/delivery APIs.
function journeyHTML(home=false,stage='refine'){
  const complete=!!S.sid,items=[['idea','说想法','简单说一句就能开始'],['inspire','找灵感','看具体方向，再做选择'],['refine','保留微调','留下满意的局部'],['deliver','检查交付','核对后拿到成果']];
  return `<nav class="journey-steps" aria-label="定制成果的四步">${items.map(([id,title,desc],i)=>`<button type="button" data-journey="${id}" ${!complete&&i>1?'disabled':''} class="${home&&i===0||!home&&id===stage?'active':''}"><span>0${i+1}</span><b>${title}</b><small>${desc}</small></button>`).join('')}</nav>`;
}
async function openGuide(){
  if(S.sid){await setHome();}
  if(!S.guideCatalog)S.guideCatalog=await api('/api/guidance');
  const goal=$('#goal-input').value;
  if(!S.guidance)S.guidance={version:'guided-intent-v1',category:S.taskType==='auto'?suggestGuideCategory(goal):S.taskType,goal,answers:{},keep:'',change:'',criteria:'',confirmed:false};
  else if(S.guidance.goal!==goal.trim()){S.guidance.goal=goal;guideDirty();}
  renderGuidanceSummary();scheduleDraft();
  S.guideStage='idea';renderGuide();$('#guidance-dialog').showModal();
}
function suggestGuideCategory(goal){
  if(/复习|学习|练习|备考|课程/.test(goal))return 'study';
  if(/邮件|邀请|文章|文案|写作|介绍信|发言/.test(goal))return 'writing';
  if(/对比|比较|分析|决策|选哪个/.test(goal))return 'analysis';
  return 'project';
}
function guideDirty(){S.guidance.confirmed=false;renderGuidanceSummary();scheduleDraft();}
function guideCategory(){return S.guideCatalog.catalog[S.guidance.category];}
function nextGuideQuestion(){return guideCategory().questions.find(q=>!Object.hasOwn(S.guidance.answers,q.id));}
function readGuideIdea(){
  const idea=$('#guide-idea').value.trim();if(idea.length<2){toast('先简单说一句想做什么，两个字也可以。');return false;}
  S.guidance.goal=idea;$('#goal-input').value=idea;guideDirty();return true;
}
function renderGuide(){
  const g=S.guidance,stage=S.guideStage,category=guideCategory(),question=category.questions.find(q=>q.id===S.guideQuestion)||nextGuideQuestion();
  let body='';
  if(stage==='idea')body=`<p>不用组织成完整的提示词。说说想做什么，接下来用具体选择一起补齐。</p><label>我大概想做…<textarea id="guide-idea" rows="3" maxlength="6000" placeholder="例如：写封邀请邮件 / 安排复习 / 梳理一个小项目">${esc(g.goal||$('#goal-input').value)}</textarea></label><fieldset class="guide-category"><legend>这次先做哪类成果？</legend>${Object.entries(S.guideCatalog.catalog).map(([k,v])=>`<button type="button" data-guide-category="${k}" aria-pressed="${g.category===k}">${esc(v.name)}</button>`).join('')}</fieldset><p class="field-note">当前支持文本成果与项目方案；可运行网站与网页组件编辑尚未接入。选择适合这次成果的引导，不需要提供参考设计。</p><button type="button" class="button-primary" data-guide-begin>一起找方向 ↗</button>`;
  else if(stage==='questions'&&question){
    S.guideQuestion=question.id;const answered=Object.values(g.answers).filter(Boolean).length;
    body=`<div class="guide-progress">${esc(category.name)} · 已明确 ${answered} 项 / ${category.questions.length} 项</div><h3>${esc(question.title)}</h3><p>选一个接近的，或者用自己的话说。暂时不知道也能继续。</p>${question.examples?`${contextualGuideHTML()}<details class="guide-common"><summary>也可以看通用示意</summary><div class="guide-examples">${question.examples.map((ex,i)=>`<button type="button" data-guide-example="${i}" aria-pressed="${g.answers[question.id]===ex.value}"><span class="small-kicker">表达 / 过程示意</span><b>${esc(ex.name)}</b><p>${esc(ex.text)}</p><small>按这个方向探索 ↗</small></button>`).join('')}</div><p class="field-note">这些是本地示意，不是模型为本任务生成的成品。选择只表示这次探索方向，不作为训练标签。</p></details>`:''}<div class="guide-options">${(question.options||[]).map((v,i)=>`<button type="button" data-guide-option="${i}" aria-pressed="${g.answers[question.id]===v}">${esc(v)}</button>`).join('')}</div><label>也可以自己说<input id="guide-answer" maxlength="500" value="${esc(g.answers[question.id]||'')}" placeholder="一句话即可"></label><div class="guide-actions"><button class="button-primary" type="button" data-guide-answer>记下并继续</button><button class="button-quiet" type="button" data-guide-skip>还不知道，先往下看</button><button class="button-quiet" type="button" data-guide-summary>先看需求卡</button></div><div class="guide-question-nav">${category.questions.map(q=>`<button type="button" data-guide-question="${q.id}" aria-pressed="${q.id===question.id}">${g.answers[q.id]?'✓ ':Object.hasOwn(g.answers,q.id)?'待确认 · ':''}${esc(q.title)}</button>`).join('')}</div>`;
  }else{
    body=`<h3>先核对，我们有没有理解对。</h3><p>明确的内容会参与生成；不知道的仍标为待确认，不替你作决定。之后可以继续修改这张卡。</p><div class="guide-brief"><b>想做的事</b><p>${esc(g.goal)}</p>${g.inspiration?'<p class="field-note">你选择过一个模型探索方向。后续补充的信息会一起参与生成；确认此卡表示按当前要求继续沿用该方向，也可返回重新探索。</p>':''}${category.questions.map(q=>`<div><b>${esc(q.title)}</b><p>${g.answers[q.id]?esc(g.answers[q.id]):'<span class="guide-unresolved">待确认 · 生成时不能当成已有事实</span>'}</p></div>`).join('')}</div><label>希望保留什么？<textarea id="guide-keep" maxlength="1000" rows="2" placeholder="可以是已有内容、表达方式或喜欢的局部；没有就留空。">${esc(g.keep)}</textarea></label><label>希望调整或避免什么？<textarea id="guide-change" maxlength="1000" rows="2" placeholder="例如：其他部分更简短，不要新增承诺。">${esc(g.change)}</textarea></label><label>什么结果算完成？<textarea id="guide-criteria" maxlength="1000" rows="2" placeholder="例如：有完整正文，事实与素材一致，能直接用于这次沟通。">${esc(g.criteria)}</textarea></label><p class="field-note">这里记录需求；生成后可在成品中把实际满意的原文设为局部保留。保留需求本身不等于结果已通过验收。</p><div class="guide-actions"><button type="button" class="button-primary" data-guide-confirm>确认这张需求卡</button><button type="button" class="button-quiet" data-guide-review>回去调整选择</button></div>`;
  }
  $('#guidance-content').innerHTML=body;
  if(stage==='questions'&&question?.id==='direction')ensureContextGuide();
}
function renderGuidanceSummary(){refreshFocused();
  const host=$('#guidance-summary');if(!host)return;const g=S.guidance;
  if(!g){host.hidden=true;return;}host.hidden=false;
  const stale=g.goal!==$('#goal-input').value.trim()||(S.taskType!=='auto'&&S.taskType!==g.category);
  host.innerHTML=`<div><b>${stale?'想法已变化，需要更新需求卡':g.confirmed?'需求卡已确认':'需求卡整理中'}</b><p>${esc(g.goal)} · ${Object.values(g.answers).filter(Boolean).length} 项已明确，${4-Object.values(g.answers).filter(Boolean).length} 项待确认</p></div><button type="button" class="button-quiet" data-guide-open>继续整理</button><button type="button" class="button-quiet" data-guide-remove>移除需求卡</button>`;
}
function requirementCardHTML(){
  const b=S.view.task.intent_brief;if(!b||typeof b!=='object')return '';
  const answers=Array.isArray(b.explicit_answers)?b.explicit_answers:[],unresolved=Array.isArray(b.unresolved)?b.unresolved:[];
  return `<section class="source-card intent-brief"><span class="small-kicker">从想法到成果</span><h3>当前确认的需求卡</h3><p>${esc(b.original_idea)}</p>${answers.filter(x=>x&&typeof x==='object').map(x=>`<div><b>${esc(x.question)}</b><p>${esc(x.answer)}</p></div>`).join('')}${[['keep','希望保留'],['change','希望调整'],['user_acceptance','完成标准']].map(([key,label])=>b[key]?`<div><b>${label}</b><p>${esc(b[key])}</p></div>`:'').join('')}<details><summary>仍需确认 · ${unresolved.length} 项</summary>${unresolved.map(q=>`<p>${esc(q)}</p>`).join('')||'<p>引导问题已有回答；不代表内容事实已核实。</p>'}</details><p class="field-note">这张卡只记录明确需求；点击示意和填写要求没有形成偏好训练标签。最终成果仍按实际条件与用途验收。</p></section>`;
}
function preservedHTML(block){
  const parts=(S.view.state.preserved_fragments||[]).filter(p=>p.block===block.id);
  return parts.length?`<div class="preserved-parts">${parts.map((p,i)=>`<div><span>保留原文</span><q>${esc(p.text)}</q><button class="button-quiet" data-remove-fragment="${esc(block.id)}" data-fragment-index="${i}">允许修改</button></div>`).join('')}<small>只保护以上原文；本章其他文字仍可调整。</small></div>`:'';
}
function openPreserve(block){
  const b=S.view.task.blocks.find(b=>b.id===block),selection=window.getSelection();
  const raw=selection?.toString().trim()||'',node=$('#block-'+block+' > .markdown');
  const within=selection?.rangeCount&&node?.contains(selection.getRangeAt(0).commonAncestorContainer);
  S.preserveEditing={block,revision:S.view.revision};$('#fragment-text').value=within?raw:'';
  $('#fragment-original').textContent=text(variant(b));$('#fragment-title').textContent='保留「'+b.title+'」里的局部原文';
  $('#fragment-dialog').showModal();
}
function mountJourney(){
  $('.home-heading').insertAdjacentHTML('beforeend',journeyHTML(true));
  $('#goal-input').insertAdjacentHTML('beforebegin','<div class="guide-entry"><span>只有一个模糊想法也可以。</span><button type="button" class="button-quiet" data-guide-open>一起找点灵感 ↗</button></div><div id="guidance-summary" class="guidance-summary" hidden></div>');
  document.body.insertAdjacentHTML('beforeend','<dialog id="guidance-dialog" class="studio-dialog guidance-dialog"><div class="dialog-heading"><div><span class="small-kicker">说想法 · 看例子 · 确认需求</span><h2>让想法，慢慢有形。</h2></div><button type="button" class="button-quiet" data-close="guidance-dialog">稍后继续 ✕</button></div><div id="guidance-content"></div><p class="field-note">整理输入与本地示意不调用模型；点击模型探索才发送相关内容。确认需求卡后，再另行生成成果。</p></dialog><dialog id="fragment-dialog" class="studio-dialog"><form id="fragment-form"><div class="dialog-heading"><h2 id="fragment-title">保留局部原文</h2><button type="button" class="button-quiet" data-close="fragment-dialog">关闭 ✕</button></div><p>只保留喜欢的一小段，这一章的其他内容仍可修改。可先在成品中选中文字，再点“保留局部”。</p><label>要原样保留的连续文字<textarea id="fragment-text" rows="3" maxlength="500" required></textarea></label><details><summary>查看本章原文</summary><pre id="fragment-original" class="draft-content"></pre></details><p class="field-note">逐字检查，不代表事实已核实。保留文字仍可移动到本章其他位置；不能移到别章代替。局部保留不作为训练标签。</p><div class="dialog-actions"><button type="submit" class="button-primary">保留这段，其余可改</button></div></form></dialog>');
}
document.addEventListener('input',e=>{
  if(e.target.id==='goal-input')renderGuidanceSummary();
  if(e.target.id==='guide-idea'){S.guidance.goal=e.target.value;$('#goal-input').value=e.target.value;guideDirty();}
  if(e.target.id==='guide-answer'){if(S.guideQuestion==='direction')delete S.guidance.inspiration;S.guidance.answers[S.guideQuestion]=e.target.value.trim()||null;guideDirty();}
  const key={'guide-keep':'keep','guide-change':'change','guide-criteria':'criteria'}[e.target.id];if(key){S.guidance[key]=e.target.value;guideDirty();}
});
function answerGuide(answer){if(S.guideQuestion==='direction')delete S.guidance.inspiration;S.guidance.answers[S.guideQuestion]=answer;guideDirty();S.guideQuestion=null;if(!nextGuideQuestion())S.guideStage='summary';renderGuide();}
document.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-guide-open'))run(openGuide);
  else if(b.hasAttribute('data-guide-remove')){S.guidance=null;renderGuidanceSummary();scheduleDraft();}
  else if(b.dataset.guideCategory){if(S.guidance.category!==b.dataset.guideCategory){S.guidance.category=b.dataset.guideCategory;S.guidance.answers={};delete S.guidance.inspiration;guideDirty();}renderGuide();}
  else if(b.hasAttribute('data-guide-begin')){if(readGuideIdea()){S.guideStage='questions';S.guideQuestion=null;renderGuide();}}
  else if(b.dataset.guideQuestion){S.guideQuestion=b.dataset.guideQuestion;S.guideStage='questions';renderGuide();}
  else if(b.hasAttribute('data-guide-option'))answerGuide(guideCategory().questions.find(q=>q.id===S.guideQuestion).options[Number(b.dataset.guideOption)]);
  else if(b.hasAttribute('data-guide-example'))answerGuide(guideCategory().questions.find(q=>q.id===S.guideQuestion).examples[Number(b.dataset.guideExample)].value);
  else if(b.hasAttribute('data-guide-answer')){const value=$('#guide-answer').value.trim();if(value)answerGuide(value);else toast('写一句自己的想法，或者选择“还不知道”。');}
  else if(b.hasAttribute('data-guide-skip'))answerGuide(null);
  else if(b.hasAttribute('data-guide-summary')){S.guideStage='summary';renderGuide();}
  else if(b.hasAttribute('data-guide-review')){S.guideStage='questions';S.guideQuestion=guideCategory().questions[0].id;renderGuide();}
  else if(b.hasAttribute('data-guide-confirm'))run(async()=>{
    const g=S.guidance;if(g.goal.trim().length<2)throw new Error('请先简单描述想做什么');
    g.goal=g.goal.trim();$('#goal-input').value=g.goal;
    if(S.taskType!==g.category){changeChoiceTaskType(g.category);document.querySelectorAll('[data-type]').forEach(el=>el.classList.toggle('active',el.dataset.type===g.category));}
    if(g.inspiration){const preview=await api('/api/guidance/preview',{guidance:g,materials:S.materials});g.inspiration.confirmed_context_hash=preview.context_hash;}
    g.confirmed=true;renderGuidanceSummary();await saveDraft();$('#guidance-dialog').close();toast('需求卡已保存。点击开始后，模型会按这些明确选择生成。');
  });
  else if(b.dataset.preserve)openPreserve(b.dataset.preserve);
  else if(b.dataset.removeFragment)run(async()=>{const p=(S.view.state.preserved_fragments||[]).filter(p=>p.block===b.dataset.removeFragment)[Number(b.dataset.fragmentIndex)];if(p)await mutate('preserve_fragment',{...p,remove:true});toast('这处原文已允许修改，正文保持不变。');});
  else if(b.dataset.journey){const step=b.dataset.journey;
    if(!S.sid){if(step==='idea'||step==='inspire')run(openGuide);}
    else if(step==='idea')activateTab('sources');
    else if(step==='inspire'){S.choiceMode=focusedMode()?'compare':'canvas';renderChoiceBoard();activateTab('candidates');}
    else if(step==='refine')activateTab('document');else activateTab('sources');
  }
  else if(b.dataset.journeyExport)run(()=>exportArtifact(b.dataset.journeyExport==='body'?(S.view.task.category==='writing'?'txt':'md'):'zip'));
});
document.addEventListener('submit',e=>{if(e.target.id==='fragment-form'){e.preventDefault();run(async()=>{
  if(S.view.revision!==S.preserveEditing.revision)throw new Error('稿件已更新，请重新选择保留原文');
  await mutate('preserve_fragment',{block:S.preserveEditing.block,text:$('#fragment-text').value});$('#fragment-dialog').close();toast('已保留局部原文；本章其他内容仍可修改。');
});}});
