'use strict';
// Revision-bound local analysis. Viewing, plotting and previewing never adopt.
async function renderDecision(){
  const host=$('#decision-view'),sid=S.sid,revision=S.view.revision;
  if(S.decision?.session===sid&&S.decision.revision===revision){paintDecision();return;}
  host.innerHTML='<div class="decision-loading" role="status">正在计算当前候选、约束和改动边界…</div>';
  const report=await api(endpoint('/decision'),{revision});
  if(S.sid!==sid||S.view.revision!==revision)return;
  S.decision=report;S.decisionBudget=report.budget_curve.length-1;paintDecision();
}
function decisionNext(d){
  const a=d.delivery.acceptance;
  if(!a.contract.confirmed)return {title:'先确认，怎样才算完成。',text:'核对从目标提取的篇幅、原文和其他验收条件，再开始受约束的取舍。',action:'确认验收条件',tab:'sources'};
  if(!d.eligible)return {title:'先解开条件之间的冲突。',text:'当前文字中没有可行搭配。下面列出不可再删的冲突条件，以及有候选佐证的调整方向。',action:'查看冲突依据',target:'decision-conflicts'};
  if(!d.current_eligible)return {title:'用尽量少的改动，先满足条件。',text:'当前正文尚未通过机器条件。先调整下方的改动上限，预览搜索得到的可行方案。',action:'选择改动上限',target:'decision-optimizer'};
  if(!['read_through','facts_checked','usable'].every(k=>d.delivery.review[k]))return {title:'最后一步，把内容核对到位。',text:'机器只检查已实现的条件。通读、事实核对和使用要求仍由你确认，结果会绑定当前稿件版本。',action:'核对并确认',tab:'sources'};
  return {title:'人工确认已记录，可以准备交付。',text:d.delivery.warnings.length?'仍有结构或来源提示。导出前请再查看提示，确认它们不会影响本次使用。':'导出时会保留正文、来源、训练版本和本次决策证据。',action:'查看交付检查',tab:'sources'};
}
function frontierSVG(d){
  const points=d.frontier;if(!points.length)return '';
  const lo=Math.min(...points.map(p=>p.score)),hi=Math.max(...points.map(p=>p.score)),span=hi-lo;
  const x=p=>52+p.change_count/Math.max(1,d.budget_curve.length-1)*490;
  const y=p=>span?155-(p.score-lo)/span*110:100;
  return `<figure class="decision-plot"><svg viewBox="0 0 600 212" role="img" aria-label="帕累托前沿：横轴为改动章节数，纵轴为当前模型相对偏好分"><path class="plot-axis" d="M52 28V172H552"/>${points.length>1?`<polyline class="plot-frontier" points="${points.map(p=>x(p)+','+y(p)).join(' ')}"/>`:''}${points.map(p=>`<circle class="plot-point" cx="${x(p)}" cy="${y(p)}" r="5"/><text x="${x(p)}" y="193" text-anchor="middle">${p.change_count}章</text>`).join('')}<text x="52" y="18">${d.pair_count?'模型相对偏好分 ↑':'尚无明确比较 · 不能解释为偏好收益'}</text><text x="552" y="210" text-anchor="end">改动章节数 →</text></svg><figcaption>只保留无法同时提高偏好分、减少改动量的代表点。${span?'纵轴在本任务内缩放，不能跨模型比较。':'当前前沿只有一个得分层级。'}等价方案按确定规则取一份；不表示语义最优。</figcaption></figure>`;
}
function decisionChoiceHTML(){
  const d=S.decision,budget=Number(S.decisionBudget),entry=d.budget_curve[budget],p=d.frontier.find(p=>p.id===entry.best_id);
  return `<div class="decision-budget-result" role="status">${p?`<div><span class="small-kicker">此改动上限内的推荐</span><h4>${esc(p.mix)}</h4><p>实际改动 ${p.change_count} 章 · 正文 ${p.body_characters} 字 · ${entry.eligible} 个可行搭配</p><p>${p.changes.length?'将调整：'+esc(p.changes.join('、')):'保留当前章节搭配。'}</p></div><button id="preview-decision-plan" class="button-primary" data-decision-plan="${esc(p.id)}">预览这个搭配 ↗</button>`:`<div><h4>只改 ${budget} 章还无法满足条件。</h4><p>提高改动上限，或查看条件是否需要重新核对。系统不会自动改动锁定章节。</p></div>`}</div>`;
}
function paintDecision(){
  const d=S.decision;if(!d)return;const a=d.delivery.acceptance,next=decisionNext(d),human=['read_through','facts_checked','usable'].filter(k=>d.delivery.review[k]).length;
  const effects=d.sensitivity.filter(s=>s.newly_eligible>0).sort((a,b)=>b.newly_eligible-a.newly_eligible);
  $('#decision-view').innerHTML=`<div class="decision-heading"><div><span class="small-kicker">DECISION / DELIVERY</span><h2>让每个选择，都有来由。</h2><p>从你的条件出发，在已有方案中做取舍，再核对与交付。</p></div><span class="snapshot-badge"><i data-lucide="git-commit-horizontal" aria-hidden="true"></i>稿件 v${d.revision}</span></div>
  ${S.view.task.source==='example'?'<p class="decision-example"><i data-lucide="flask-conical" aria-hidden="true"></i>当前是开发示例；文字与模拟反馈不能证明真实使用收益。</p>':''}
  ${d.warning?`<p role="status" class="decision-example">${esc(d.warning)}</p>`:''}
  <section class="decision-next"><div class="decision-next-icon"><i data-lucide="arrow-up-right" aria-hidden="true"></i></div><div><span class="small-kicker">建议下一步</span><h3>${next.title}</h3><p>${next.text}</p><button class="button-primary" ${next.tab?`data-decision-tab="${next.tab}"`:`data-decision-jump="${next.target}"`}>${next.action} ↗</button></div></section>
  <ol class="delivery-path" aria-label="交付路径"><li><span>01</span><div><b>明确目标</b><small>${S.view.task.blocks.filter(b=>!b.fixed).length} 个内容章节</small></div></li><li><span>02</span><div><b>确认边界</b><small>${a.contract.confirmed?d.constraints.length+' 项机器条件':'条件待确认'}</small></div></li><li><span>03</span><div><b>做出取舍</b><small>${d.eligible} 个可行搭配</small></div></li><li><span>04</span><div><b>核对交付</b><small>${human}/3 项人工确认</small></div></li></ol>
  <div class="decision-metrics"><div><span>候选搜索空间</span><strong>${d.universe}</strong><small>当前已有文字组合</small></div><div><span>满足机器条件</span><strong>${d.eligible}</strong><small>${d.universe-d.eligible} 个被条件排除</small></div><div><span>明确偏好比较</span><strong>${d.pair_count}</strong><small>${d.pair_count?'仅本任务反馈':'尚无个人偏好证据'}</small></div><div><span>本次付费请求</span><strong>0</strong><small>全部在本地计算</small></div></div>
  <section id="decision-optimizer" class="decision-card"><div class="decision-section-title"><span class="feature-icon"><i data-lucide="sliders-horizontal" aria-hidden="true"></i></span><div><span class="small-kicker">取舍，而不只是重写</span><h3>你愿意改动多少？</h3></div></div><p>先保证锁定与已确认条件，再在改动范围内寻找当前模型偏好分最高的搭配。${d.pair_count?'分数只反映当前模型估计，不代表交付质量。':'还没有明确比较，得分只来自基线或实验先验，优先保留原文。'}</p>${d.eligible?`${frontierSVG(d)}<label class="budget-label" for="decision-budget">最多改动 <output id="decision-budget-value">${S.decisionBudget}</output> 章<input id="decision-budget" type="range" min="0" max="${d.budget_curve.length-1}" step="1" value="${S.decisionBudget}"></label><div id="decision-budget-choice">${decisionChoiceHTML()}</div>`:'<p class="decision-empty">当前候选中无解。先查看下方冲突，再决定修改文字或调整条件。</p>'}</section>
  <section id="decision-conflicts" class="decision-card"><div class="decision-section-title"><span class="feature-icon"><i data-lucide="scan-line" aria-hidden="true"></i></span><div><span class="small-kicker">可解释的约束</span><h3>${d.conflict_core.length?'这些条件放在一起，当前无解。':'哪些条件，影响了选择空间？'}</h3></div></div>${d.conflict_core.length?`<ul class="conflict-list">${d.conflict_core.map(c=>`<li><i data-lucide="link-2" aria-hidden="true"></i>${esc(c.label)}</li>`).join('')}</ul><p>这组条件不可再删：拿掉其中任意一项，这组本身就有解。它不一定是条件数最少的冲突组，也不代表只有这一处冲突。</p><h4>有候选作为依据的调整方向</h4><div class="correction-list">${d.corrections.map(c=>`<article><b>重新核对 ${c.relax.length} 项条件</b><p>${c.relax.map(x=>esc(x.label)).join('；')}</p><small>存在只违反上述条件的候选组合；当前仍不可采用。</small><button class="button-quiet" data-decision-tab="sources">核对原条件 ↗</button></article>`).join('')}</div><p class="field-note">共 ${d.correction_count} 种包含关系最小的调整集合，最多展示6种。条件由你决定；也可以保留条件、改写候选。</p>`:''}<div class="sensitivity-list">${effects.map(s=>`<div><span>${esc(s.label)}</span><span>单独移除后 <b>+${s.newly_eligible}</b> 个搭配</span></div>`).join('')||'<p>单独移除任一条件均没有新增搭配；多项条件可能互相遮蔽。这不代表条件没有作用。</p>'}</div><p class="field-note">这是逐项移除条件的只读分析。各项新增数量可能重叠，不能相加；没有自动放宽条件。</p></section>
  ${stabilityHTML(d.stability)}<section class="decision-card decision-lineage"><div class="decision-section-title"><span class="feature-icon"><i data-lucide="workflow" aria-hidden="true"></i></span><div><span class="small-kicker">从输入到交付的记录</span><h3>这次结论，从哪里来？</h3></div></div><div class="lineage-rows"><div><span>输入</span><p>${esc(S.view.task.brief||S.view.task.title)}</p></div><div><span>排序模型</span><p>${esc(d.model.model_id||d.model.version||'版本偏好基线')} · ${d.pair_count} 次明确比较</p></div><div><span>决策器</span><p>穷举候选 → 硬条件过滤 → 偏好 / 改动量前沿 → 指定改动预算内推荐</p></div><div><span>验收</span><p>${a.contract.confirmed?a.machine_check_count+' 项机器检查，'+a.failures.length+' 项未通过':'机器条件尚未确认'} · ${human}/3 项人工确认 · ${d.delivery.warnings.length} 项结构或来源提示</p></div></div><details><summary>查看当前快照与算法边界</summary><p class="model-fingerprint">决策指纹 ${esc(d.hash)}<br>正文指纹 ${esc(d.snapshot.document_hash)}</p><ul>${d.limits.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><p>交付包包含“决策与约束证据.json”。训练、更换模型、改稿或更改条件后需要重新计算。</p></details><button class="button-quiet" data-decision-learning>查看训练与对照 ↗</button><button class="button-quiet" data-decision-tab="sources">核对来源与验收 ↗</button></section>`;
}
document.addEventListener('input',event=>{if(event.target.id==='decision-budget'){
  S.decisionBudget=Number(event.target.value);$('#decision-budget-value').textContent=S.decisionBudget;$('#decision-budget-choice').innerHTML=decisionChoiceHTML();
}});
document.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;
  if(b.dataset.decisionTab)activateTab(b.dataset.decisionTab);
  else if(b.hasAttribute('data-open-decision'))activateTab('decision');
  else if(b.dataset.decisionJump)$('#'+b.dataset.decisionJump)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
  else if(b.dataset.decisionPlan){const p=S.decision?.frontier.find(p=>p.id===b.dataset.decisionPlan);if(p){loadChoiceCombo(p.combo);activateTab('candidates');toast('已载入预览。采用前，当前正文保持原样。');}}
  else if(b.hasAttribute('data-decision-learning')){S.choiceMode='learning';renderChoiceBoard();activateTab('candidates');}
  else if(b.id==='try-decision-demo')run(async()=>{const demo=S.sessions.find(s=>s.source==='example'&&s.title==='组合定制示例｜邀请邮件');await openSession(demo.id);activateTab('decision');});
});

function stabilityHTML(r){if(!r)return '';
 return `<section class="decision-card"><div class="small-kicker">模型分歧与选择风险</div><h3>推荐，在不同假设下稳不稳？</h3><p>${r.hypotheses} 个模型假设，${r.supported_winners} 种各自首选。均值推荐的预期后悔值 ${r.expected_regret.toFixed(4)}，最不利成员下 ${r.worst_member_regret.toFixed(4)}；最小最大后悔值方案为 ${r.minimax_worst_regret.toFixed(4)}。</p><p>后悔值是相对于同一成员自己最优方案的分数差，不是实际损失或正确率。${esc(r.note)}</p><button class="button-quiet" data-preview-minimax>预览对分歧更保守的搭配 ↗</button></section>`;
}
document.addEventListener('click',event=>{if(event.target.closest('[data-preview-minimax]')&&S.decision?.stability){loadChoiceCombo(S.decision.stability.minimax_combo);activateTab('candidates');toast('已载入预览；正文和偏好标签未改变。');}});
