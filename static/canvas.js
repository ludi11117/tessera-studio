'use strict';
function canvasState(report){
  if(!S.canvas||S.canvas.sid!==S.sid||S.canvas.revision!==report.revision||S.canvas.hash!==report.space.hash){
    const cs=report.space.candidates;
    S.canvas={sid:S.sid,revision:report.revision,hash:report.space.hash,index:Configuration.index(cs,S.view.task.blocks.filter(b=>!b.fixed)),
      anchors:{},min:0,max:Math.max(0,...cs.map(c=>c.body_characters)),budget:S.view.task.blocks.filter(b=>!b.fixed).length,selected:null};
  }
  return S.canvas;
}
async function renderCanvas(){
  const host=$('#configuration-canvas');if(!host||S.choiceMode!=='canvas')return;
  const sid=S.sid,revision=S.view.revision;
  host.innerHTML='<p role="status">正在载入本版本的可行方案…</p>';
  try{
    const d=S.decision?.session===sid&&S.decision.revision===revision?S.decision:await api(endpoint('/decision'),{revision});
    if(S.sid!==sid||S.view.revision!==revision||!host.isConnected||S.choiceMode!=='canvas')return;
    S.decision=d;
    if(!d.space){host.innerHTML='<p role="status">服务尚未载入定制画布，请重新启动工作室。</p>';return;}
    canvasState(d);paintCanvas();
  }catch(e){if(host.isConnected)host.innerHTML=`<p role="status">${esc(e.message)}</p><button class="button-quiet" data-canvas-retry>重新载入</button>`;}
}
function canvasPlot(c,r){
  const rows=r.rows,all=c.index.candidates;
  if(!rows.length)return '<p class="canvas-empty">当前范围里没有组合。下方保留了冲突依据，可先调整本次筛选。</p>';
  const lo=Math.min(...all.map(p=>p.body_characters)),hi=Math.max(...all.map(p=>p.body_characters)),groups=new Map();
  for(const p of rows){const key=p.body_characters+':'+p.change_count;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);}
  const x=p=>54+(p.body_characters-lo)/Math.max(1,hi-lo)*470,y=p=>180-p.change_count/Math.max(1,c.index.blocks.length)*140;
  return `<svg viewBox="0 0 580 240" role="img" aria-label="方案地图：横轴正文字符数，纵轴与当前稿不同的章节数。可用下方列表选择每份方案。"><path class="plot-axis" d="M54 24V188H540"/>${Array.from({length:c.index.blocks.length+1},(_,n)=>`<text x="42" y="${y({change_count:n})+4}" text-anchor="end">${n}</text>`).join('')}<text x="54" y="215">${lo}字</text><text x="524" y="215" text-anchor="end">${hi}字</text><text x="54" y="16">改动章节 ↑</text><text x="524" y="238" text-anchor="end">正文篇幅 →</text>${[...groups.values()].map(group=>{const p=group[0],picked=group.some(p=>p.id===c.selected),front=group.some(p=>r.frontier.includes(p.id));return `<g class="canvas-dot ${picked?'selected':''} ${front?'frontier':''}" data-canvas-cell="${esc(p.id)}"><circle cx="${x(p)}" cy="${y(p)}" r="${picked?9:7}"/><title>${p.body_characters}字 · 改动${p.change_count}章 · ${group.length}个搭配</title>${group.length>1?`<text x="${x(p)}" y="${y(p)-12}" text-anchor="middle">${group.length}</text>`:''}</g>`;}).join('')}</svg><figcaption>点选查看；重叠点上方标出方案数，列表保留全部搭配。实心点含偏好 / 改动量前沿方案；篇幅本身不判定好坏。</figcaption>`;
}
function paintCanvas(){
  const host=$('#configuration-canvas');if(!host||!S.canvas)return;
  const c=S.canvas,d=S.decision,task=S.view.task,blocks=c.index.blocks,r=Configuration.query(c.index,c);
  if(!r.rows.some(p=>p.id===c.selected))c.selected=r.best?.id||null;
  const chosen=r.rows.find(p=>p.id===c.selected),labels=ks=>ks.map(k=>blocks.find(b=>b.id===k)?.title||k).join('、');
  const mix=p=>blocks.map(b=>'ABC'[b.variants.findIndex(v=>v.id===p.combo[b.id])]).join(' / ');
  const locked=S.view.state.locks;
  host.innerHTML=`<section class="configuration-card"><div class="canvas-heading"><div><span class="small-kicker">按章节选择 · 即时看见可行性</span><h3>你的选择，在同一张画布里。</h3><p>横向挑版本，纵向搭章节。选中即保留，再点一次取消；每个版本下方的数字是其余选择不变时，仍可组成的方案数。</p></div><button class="button-quiet" data-canvas-reset>重置本次筛选</button></div>
  ${task.source==='example'?'<p class="field-note">开发示例，不是模型成功交付或真实用户效果。</p>':''}
  <div class="canvas-filters"><label>正文至少<input id="canvas-min" type="number" min="0" step="1" value="${c.min}" aria-label="正文字符数下限"></label><label>正文至多<input id="canvas-max" type="number" min="0" step="1" value="${c.max}" aria-label="正文字符数上限"></label><label>最多改动<select id="canvas-budget">${Array.from({length:blocks.length+1},(_,n)=>`<option value="${n}" ${n===c.budget?'selected':''}>${n}章</option>`).join('')}</select></label></div><p class="field-note">以上只筛选这次预览，不修改验收条件。篇幅按去空白与引用编号的字符计；改动量相对当前成稿。</p>
  <div class="canvas-status" role="status" aria-live="polite"><strong>${r.rows.length}</strong> / ${r.total} 个满足机器条件的搭配，符合本次筛选 · 已保留 ${Object.keys(c.anchors).length} 章 · 本地计算</div>
  <div class="canvas-matrix" role="group" aria-label="章节与版本定制矩阵"><div class="canvas-matrix-head"><span>章节</span><b>A</b><b>B</b><b>C</b></div>${blocks.map(b=>`<div class="canvas-matrix-row"><div class="canvas-row-title">${esc(b.title)}${locked[b.id]?'<small>正文已锁定</small>':''}</div>${b.variants.map((v,j)=>{const n=r.support[b.id][v.id],on=c.anchors[b.id]===v.id;return `<button class="canvas-version ${on?'active':''} ${n?'':'unsupported'}" data-canvas-block="${esc(b.id)}" data-canvas-variant="${esc(v.id)}" aria-pressed="${on}" ${locked[b.id]?'disabled':''} aria-label="${esc(b.title)}，版本${'ABC'[j]}，${n}个可行搭配${on?'，已保留':''}"><span>${esc(text(v).replace(/\s+/g,' ').slice(0,62))}</span><small>${on?'已保留 · ':''}${n} 个搭配</small></button>`;}).join('')}</div>`).join('')}</div>
  ${!r.rows.length?`<div class="canvas-conflict" role="status"><h4>${!r.total?'已有候选无法满足当前机器条件':!r.window_count?'篇幅与改动范围里暂时没有搭配':'这些保留项，在当前范围内互相冲突'}</h4>${r.core.length?`<p>不可再删的一组保留项：${esc(labels(r.core))}。拿掉其中任意一项，这组本身即有解；其他保留项可能仍冲突。</p>`:''}${r.repairs.map((s,i)=>`<button class="button-quiet" data-canvas-relax="${i}">允许调整 ${esc(labels(s.relax))} · 预览 ${mix(s.witness)} ↗</button>`).join('')}<p>${r.repairs.length?`共 ${r.repair_count} 组最小调整集合，展示前 ${r.repairs.length} 组。只取消明确点击的本次保留项，正文锁定与机器条件继续生效。`:!r.total?'请在交付总览查看机器条件冲突，或编辑现有候选。':'可以调整篇幅、增加改动上限或重置本次筛选。'}</p></div>`:''}
  <div class="canvas-result-grid"><figure class="canvas-plot">${canvasPlot(c,r)}</figure><div class="canvas-selection">${chosen?`<label for="canvas-plan">当前范围内的全部搭配<select id="canvas-plan">${r.rows.map(p=>`<option value="${esc(p.id)}" ${c.selected===p.id?'selected':''}>${mix(p)} · ${p.body_characters}字 · 改${p.change_count}章</option>`).join('')}</select></label><h4>${mix(chosen)}</h4><p>${chosen.body_characters}字 · 改动${chosen.change_count}章</p><p>${d.pair_count?`与本次筛选内最高偏好分相差 ${(r.best.score-chosen.score).toFixed(4)}。得分只是当前模型估计。`:'尚无明确比较；按基线得分与少改动排序，不能解释为个人偏好收益。'}</p><button class="button-primary" data-canvas-preview>完整预览与检查 ↗</button><p class="field-note">先看具体差异，再明确采用；本次筛选不会形成偏好标签。</p>`:'<p>找到合格搭配后，可在这里查看完整内容。</p>'}</div></div>
  ${chosen?`<details class="canvas-diff" open><summary>对当前稿件，将改哪里？</summary>${blocks.filter(b=>chosen.combo[b.id]!==S.view.state.combo[b.id]).map(b=>`<article><h4>${esc(b.title)}</h4><div class="canvas-diff-columns"><div><span class="small-kicker">当前正文</span><div class="markdown">${markdown(draftSection(b,S.view.state.combo))}</div></div><div><span class="small-kicker">所选搭配</span><div class="markdown">${markdown(draftSection(b,chosen.combo))}</div></div></div></article>`).join('')||'<p>与当前搭配相同，没有需要替换的章节。</p>'}</details>`:''}<details class="canvas-method"><summary>本次计算的依据</summary><p>对已通过锁定和机器条件的候选建立位集索引，精确计算每个版本的条件补齐数。零搭配也可以点选查看冲突。无解时枚举有候选佐证的最小保留项调整集合。推荐只使用当前固定分数，不推测新文字或训练后的效果。</p><p class="model-fingerprint">稿件 v${d.revision} · ${esc(d.model.model_id||d.model.version||'版本偏好基线')}<br>候选表 ${esc(d.space.hash)}</p><p>当前有限候选之外可能有更好的文字；机器条件通过仍需核对连贯、事实与实际用途。</p></details></section>`;
  c.result=r;
}
document.addEventListener('change',e=>{
  if(!['canvas-min','canvas-max','canvas-budget','canvas-plan'].includes(e.target.id))return;
  const c=S.canvas;if(!c)return;
  if(e.target.id==='canvas-plan'){c.selected=e.target.value;paintCanvas();$('#canvas-plan')?.focus();return;}
  const min=Number($('#canvas-min').value),max=Number($('#canvas-max').value),budget=Number($('#canvas-budget').value);
  if(!Number.isInteger(min)||!Number.isInteger(max)||min<0||max<min){toast('请填写有效的篇幅区间，下限不能大于上限。');paintCanvas();return;}
  const id=e.target.id;Object.assign(c,{min,max,budget});paintCanvas();$('#'+id)?.focus();
});
document.addEventListener('click',e=>{
  const version=e.target.closest('[data-canvas-block]'),cell=e.target.closest('[data-canvas-cell]'),b=e.target.closest('button'),c=S.canvas;
  if(b?.hasAttribute('data-canvas-retry')){renderCanvas();return;}
  if(!c||S.choiceMode!=='canvas')return;
  if(version){const k=version.dataset.canvasBlock,v=version.dataset.canvasVariant;if(c.anchors[k]===v)delete c.anchors[k];else c.anchors[k]=v;paintCanvas();document.querySelectorAll('[data-canvas-block]').forEach(el=>{if(el.dataset.canvasBlock===k&&el.dataset.canvasVariant===v)el.focus();});}
  else if(cell){c.selected=cell.dataset.canvasCell;paintCanvas();}
  else if(b?.hasAttribute('data-canvas-reset')){S.canvas=null;canvasState(S.decision);paintCanvas();$('[data-canvas-reset]')?.focus();}
  else if(b?.hasAttribute('data-canvas-relax')){const repair=c.result.repairs[Number(b.dataset.canvasRelax)];if(repair){for(const k of repair.relax)delete c.anchors[k];c.selected=repair.witness.id;paintCanvas();$('#canvas-plan')?.focus();}}
  else if(b?.hasAttribute('data-canvas-preview'))run(async()=>{
    if(c.revision!==S.view.revision)throw new Error('稿件已变化，请重新打开画布');
    const plan=c.result.rows.find(p=>p.id===c.selected);if(!plan)return;
    loadChoiceCombo(plan.combo,c.anchors);await inspectChoiceDraft();toast('已载入完整预览并重新检查。确认后可另行采用。');
  });
});
