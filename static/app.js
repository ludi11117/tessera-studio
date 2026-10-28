'use strict';
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {created:'创建任务',exposure:'展示三份草稿',select:'挑选段落',lock:'切换锁定',constraint:'设置字数约束',apply:'应用组合',edit:'编辑候选（保留旧版本）',compare:'明确二选一',skip:'跳过比较',undo:'撤回操作',adopt:'最终采用',export:'导出文本',audit_export:'导出会话数据',comparison_exposure:'展示局部比较',recommendation_exposure:'展示推荐组合',research_config:'更新学习与比较设置',query_stop:'停止提问'};
let view, sessionId, sessions = [], samples = [], currentOffer = null, busy = false, showRanks = false;
let toastTimer;
for(const [value,label] of Object.entries({content_linear:'按内容推荐（实验）',content_frozen:'内容与搭配：固定投影（实验）',content_neural:'内容与搭配：可训练投影（实验）'})){
  const option=document.createElement('option');option.value=value;option.textContent=label;$('#pref-model').append(option);
}
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 4500); }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || '请求失败'); error.status = response.status; throw error; }
  return result;
}
function endpoint(suffix = '') { return `/api/sessions/${sessionId}${suffix}`; }
function textVariant(v) { return v.template.replace(/\{\{(.*?)\}\}/g, (_, k) => view.task.facts[k]); }
function variant(b, combo = view.state.combo) { return b.variants.find(v => v.id === combo[b.id]); }
function charCount(s) { return Array.from(s).length; }
function feasibleCombo(combo) {
  if (Object.entries(view.state.locks).some(([k,v]) => combo[k] !== v)) return false;
  const text = view.task.blocks.map(b => textVariant(variant(b, combo))).join('\n\n');
  return view.state.max_chars === null || charCount(text) <= view.state.max_chars;
}
async function exclusive(fn) {
  if (busy) return;
  busy = true; document.body.classList.add('busy');
  try { await fn(); }
  catch (e) { if(e.status === 409 && sessionId) await reload(); if(view) $('#save-state').textContent = `✓ 上次已保存 · v${view.revision}`; toast(e.message); }
  finally { busy = false; document.body.classList.remove('busy'); }
}
async function listSessions() {
  const data = await api('/api/sessions'); sessions = data.sessions; samples = data.samples;
  $('#sessions').innerHTML = sessions.map(s => `<button data-session="${esc(s.id)}" class="${s.id === sessionId ? 'selected' : ''}" ${s.id === sessionId ? 'aria-current="page"' : ''}>${s.source === 'generated' ? '✦' : s.source === 'custom' ? '◇' : '▤'} &nbsp;${esc(s.title)}<small>${s.source === 'generated' ? 'AI生成' : s.source === 'custom' ? '自建内容' : '示例候选'} · ${new Date(s.created).toLocaleDateString('zh-CN')} · v${s.revision}</small></button>`).join('');
}
async function reload() { view = await api(endpoint()); currentOffer = null; showRanks = false; render(); await listSessions(); }
async function openSession(sid) {
  sessionId = sid; try { localStorage.setItem('intent-session', sid); } catch {}
  await reload(); await api(endpoint('/action'), {kind:'exposure',revision:view.revision});
}
async function action(kind, extras = {}) {
  $('#save-state').textContent = '正在保存…';
  const result = await api(endpoint('/action'), {kind, revision:view.revision, ...extras});
  if (!['export','audit_export','exposure','recommend'].includes(kind)) await reload();
  else $('#save-state').textContent = `✓ 已保存到本机 · v${view.revision}`;
  return result;
}
function render() {
  const {task, state} = view;
  $('#task-title').textContent = task.title; $('#crumb-title').textContent = task.title;
  $('#task-brief').textContent = task.brief || '选择喜欢的表达，组合你的完整文本。';
  $('#save-state').textContent = `✓ 已保存到本机 · v${view.revision}`;
  $('#source-badge').textContent = task.source === 'generated' ? 'AI生成' : task.source === 'custom' ? '自建内容' : '示例内容';
  $('#facts').innerHTML = Object.entries(task.facts).map(([k,v]) => `<span>${esc(k)}<b>${esc(v)}</b></span>`).join('') || '此任务未设置固定事实。';
  $('#candidate-heads').innerHTML = ['A','B','C'].map((letter,i) => {
    const combo = Object.fromEntries(task.blocks.map(b => [b.id,state.locks[b.id] || b.variants[i].id]));
    return `<div class="candidate-heading"><span><b>${letter}</b> ${esc(task.ai?.candidate_labels?.[i] || (task.source === 'custom' ? '版本 '+(i+1) : ['简洁直接','温和自然','正式完整'][i]))}</span><button class="lock-button" data-initial="${i}" ${!feasibleCombo(combo)?'disabled title="整份草稿不满足当前约束"':''}>${Object.keys(state.locks).length?'采用可变部分':'整份选用'}</button></div>`;
  }).join('');
  $('#blocks').innerHTML = task.blocks.map((b,index) => `<section class="block-row" data-block="${esc(b.id)}"><div class="block-label"><span><i class="block-index">${String(index+1).padStart(2,'0')}</i> ${esc(b.title)}</span><button class="lock-button ${state.locks[b.id] ? 'locked' : ''}" data-lock="${esc(b.id)}" aria-pressed="${!!state.locks[b.id]}">${state.locks[b.id] ? '▣ 已锁定 · 解锁' : '▢ 锁定当前段落'}</button></div><div class="variant-grid">${b.variants.map((v,i) => {
    const chosen = state.combo[b.id] === v.id, allowed = feasibleCombo({...state.combo,[b.id]:v.id});
    return `<article class="variant ${chosen ? 'chosen' : ''}"><div class="variant-label">版本 ${['A','B','C'][i]}</div><p>${esc(textVariant(v))}</p><div class="variant-bottom"><span>${charCount(textVariant(v))} 字</span><button class="select-button" data-select="${esc(b.id)}" data-variant="${esc(v.id)}" aria-label="${esc(b.title)} 选用版本${i+1}" aria-pressed="${chosen}" ${chosen || !allowed ? 'disabled' : ''}>${chosen ? '✓ 已选用' : '选用 ＋'}</button></div></article>`;
  }).join('')}</div></section>`).join('');
  $('#output').innerHTML = task.blocks.map(b => `<div class="output-paragraph ${state.locks[b.id] ? 'is-locked' : ''}" data-output="${esc(b.id)}" ${state.locks[b.id] ? 'title="该段落已锁定"' : ''}>${esc(textVariant(variant(b)))}</div>`).join('');
  $('#output-meta').textContent = `${task.blocks.length} 个段落 · 随选择实时更新`;
  $('#locked-count').textContent = `${Object.keys(state.locks).length} / ${task.blocks.length} 段已锁定`;
  $('#char-count').textContent = `${charCount(view.text)} 字`;
  $('#max-chars').value = state.max_chars ?? '';
  const valid = feasibleCombo(state.combo);
  $('#constraint-warning').classList.toggle('hidden', valid);
  $('#constraint-warning').textContent = view.feasible_count === 0 ? '当前锁定与字数上限无法同时满足：可行组合为0。已保留你的全部锁定内容；请提高字数上限或解锁部分段落。' : '当前组合超过字数上限。已保留原文；可搜索并应用满足约束的组合。';
  if(view.feasible_count===0 && view.constraint_diagnostics?.minimum_chars_under_locks) $('#constraint-warning').textContent += ` 锁定条件下最短为 ${view.constraint_diagnostics.minimum_chars_under_locks} 字，上限为 ${state.max_chars} 字。`;
  $('#adopt').disabled = !valid; $('#export').disabled = !valid;
  $('#undo').disabled = !view.can_undo;
  $('#final-state').classList.toggle('hidden', !state.final);
  $('#export-path').textContent = view.last_export ? `最近导出：${view.last_export}` : '';
  $('#adopt').textContent = state.final ? '✓ 已最终采用' : '✓ 最终采用';
  $('#comparison').innerHTML = ''; $('#get-compare').textContent = '开始局部比较 ↗';
  $('#recommendations').innerHTML = '';
  $('#pair-count').textContent = `${view.pair_count} 条有效比较`;
  const settings=state.research || {model:'legacy',policy:'uncertainty',context_mode:'current',budget:16,seed:11,evaluate_only:true,data_origin:'unclassified',participant_id:''};
  $('#pref-model').value=settings.model;$('#query-policy').value=settings.policy;$('#context-mode').value=settings.context_mode;
  $('#feedback-budget').value=settings.budget;$('#research-seed').value=settings.seed;$('#evaluate-only').checked=settings.evaluate_only;
  $('#data-origin').value=settings.data_origin;$('#participant-id').value=settings.participant_id||'';
  $('#save-research').disabled=!view.research_available;
  $('#research-status').textContent=view.research_warning || (state.research ? `本会话已启用 · ${view.pair_count} / ${settings.budget} 条有效比较。设置不会把选择或锁定变成标签。` : '默认沿用V1基线。可启用段落搭配模型与诊断比较；每项改动会保存并可撤回。');
  if(!view.research_available) $('#research-status').textContent='当前为无依赖V1环境。启用研究模式请运行 setup-research.ps1，再双击启动研究工作台.cmd。';
  const evaluated=view.last_evaluated;
  $('#evaluation-result').innerHTML=evaluated?`<div class="evaluation-note">最近一次只评价的胜出组合已记录，评价没有改变成稿。<details><summary>查看胜出组合</summary><pre>${esc(evaluated.text)}</pre></details><button id="apply-evaluated" class="secondary" ${evaluated.can_apply?'':'disabled'}>另外采用此完整组合</button></div>`:'';
  renderModel();
  $('#history').innerHTML = view.history.slice().reverse().map(e => `<div class="history-row ${e.retracted ? 'retracted' : ''}"><time>${new Date(e.time).toLocaleTimeString('zh-CN')}</time><span>${esc(labels[e.kind] || e.kind)}${e.retracted ? '（已撤回）' : ''}</span><span>v${e.revision}</span></div>`).join('');
}
function renderModel() {
  if(view.state.research && !view.research_warning) {
    const config=view.model_config;
    const names={legacy:'原始加性基线',additive:'固定先验加性模型',interaction:'单段 + 段落搭配模型',content_linear:'内容加性模型（实验）',content_frozen:'内容搭配模型：固定投影（实验）',content_neural:'内容搭配模型：可训练投影（实验）'};
    if(config.content_conditioned){
      $('#model').innerHTML=`<p>${esc(names[config.model_id])} · ${config.parameter_count} 个参数，${view.pair_count} 条有效比较。内容编码为文字统计与词片段哈希；${config.projection_steps?'已训练小网络 '+config.projection_steps+' 步':'投影保持固定'}。不使用预训练语义编码，不微调大模型，不跨任务训练。</p><p>旧标签仍属于旧文字。新候选通过内容得到预测分数，未经用户比较不能成为标签。条件于投影的头部曲率忽略表示不确定性，未校准。</p><p>观测差分矩阵秩 ${config.coverage?.observed_difference_rank??0}。下表为单段贡献，完整搭配得分见推荐卡。</p><table class="weight-table"><thead><tr><th>部件</th><th>版本</th><th>单段贡献</th></tr></thead><tbody>${view.weights.map(w=>`<tr><td>${esc(w.block)}</td><td>${w.variant}</td><td>${w.weight.toFixed(4)}</td></tr>`).join('')}</tbody></table>`;
      return;
    }
    $('#model').innerHTML=`<p>${esc(names[config.model_id])} · ${config.parameter_count} 个参数，${view.pair_count} 条有效比较。${config.reduction==='sum'?'总和对数损失 + L2正则，固定先验精度':'V1平均对数损失 + L2正则'} ${config.l2}。${config.model_id==='interaction'?'搭配项来自相邻段落和首尾段落的不可变版本组合。':'得分由各段落相加。'}</p><p>新文字使用新版本ID，不继承旧标签。模型仅学习实际比较；无语义编码、跨任务迁移或心理原因解释。近似参数方差未经真实数据校准。</p><p>观测差分矩阵秩 ${config.coverage?.observed_difference_rank ?? 0}；此数只描述反馈覆盖，不等于全部搭配已可识别。推荐卡中展示单段项和搭配项的实际得分贡献。</p><table class="weight-table"><thead><tr><th>部件</th><th>当前版本</th><th>单段权重</th></tr></thead><tbody>${view.weights.map(w=>`<tr><td>${esc(w.block)}</td><td>${w.variant}</td><td>${w.weight.toFixed(4)}</td></tr>`).join('')}</tbody></table>`;
    return;
  }
  $('#model').innerHTML = `<p>本任务独立训练的线性 Bradley–Terry 基线。特征是「部件 × 不可变版本ID」的指示变量，完整组合得分为所含部件权重之和。选择概率 P(A ≻ B) = sigmoid(score(A) − score(B))。</p><p>${view.pair_count ? `已使用 ${view.pair_count} 条未撤回的明确比较；普通选择、编辑、浏览、锁定、跳过、最终采用均不生成训练标签。` : '尚无明确比较，全部权重为0。并列时优先少改动当前组合；这不代表模型已学到偏好。'} 编辑后的文字获得新版本ID，不继承原文字的偏好标签；旧版本及真实比较继续保存在历史中。下表展示当前候选的权重。使用平均成对对数损失与 L2 正则（0.08），从零拟合240步，学习率0.3。未建模部件间交互，也不跨任务复用。</p><table class="weight-table"><thead><tr><th>部件</th><th>版本</th><th>学得权重</th></tr></thead><tbody>${view.weights.map(w => `<tr><td>${esc(w.block)}</td><td>${w.variant}</td><td>${w.weight > 0 ? '+' : ''}${w.weight.toFixed(4)}</td></tr>`).join('')}</tbody></table><p>局部比较只改变一个未锁定段落，选择模型预测概率最接近0.5、且在当前上下文中尚未回答的可行配对。此规则是待验证的基线，没有真实效果证明。</p>`;
}
function renderOffer() {
  if (!currentOffer) { $('#comparison').innerHTML = `<p class="comparison-context">${view.state.research && view.pair_count>=view.state.research.budget ? '已达到本会话有效比较预算。可以直接检查成稿，也可在设置中明确提高预算。' : '当前没有新的可行局部比较。可能所有段落已锁定、约束过严，或合法配对均已比较。可调整组合或解锁后重试。'}</p>`; return; }
  const b = view.task.blocks.find(b => b.id === currentOffer.block);
  const context = view.task.blocks.filter(x => x.id !== b.id).map(x => `${x.title}：版本${x.variants.findIndex(v => v.id === currentOffer.a[x.id])+1}${view.state.locks[x.id] ? '（已锁定）' : ''}`).join(' / ');
  const diagnostic=!!currentOffer.alternative_context, evalOnly=currentOffer.response_mode==='evaluate_only';
  const fullContext=diagnostic?`<div class="shared-context">这次采用以下共同背景，请结合完整顺序判断：${view.task.blocks.map(x=>x.id===b.id?`<p>↓ 这里比较「${esc(x.title)}」的 A / B 表达</p>`:`<b>${esc(x.title)}</b><p>${esc(textVariant(variant(x,currentOffer.a)))}</p>`).join('')}</div>`:'';
  $('#comparison').innerHTML = `<div class="comparison-context">比较「${esc(b.title)}」 · ${diagnostic?'诊断另一种搭配背景，右侧成稿保持不变':'其他段落与右侧组合完全一致'}<br>${esc(context)}</div>${fullContext}<div class="comparison-options">${['a','b'].map(key => `<article class="comparison-option"><h3>表达 ${key.toUpperCase()}</h3><p>${esc(textVariant(variant(b,currentOffer[key])))}</p>${currentOffer.snapshot?`<details><summary>看这一版完整文本</summary><pre>${esc(currentOffer.snapshot.texts[key])}</pre></details>`:''}<button class="secondary" data-choice="${key}">我更喜欢 ${key.toUpperCase()}</button></article>`).join('')}</div><div class="skip-row"><span>${evalOnly?'只记录评价，不改变成稿；采用需另行点击。':'选择会应用这一段，并记录一次真实比较。'}</span><button class="lock-button" id="skip">暂时分不出 · 跳过</button></div>${currentOffer.planning?`<p class="planning-note">策略 ${esc(currentOffer.planning.policy_id)} · 规划 ${currentOffer.planning.planning_ms.toFixed(1)} ms · 成本代理 ${currentOffer.planning.estimated_cost.toFixed(2)}${currentOffer.planning.fallback?' · 规划超时，已回退接近0.5策略':''}</p>`:''}`;
  $('#get-compare').textContent = '当前比较待选择';
}
function renderRanks() {
  $('#recommendations').innerHTML = `<p class="muted">共 ${view.feasible_count} 个可行组合 · 显示前 ${view.ranking.length} 个</p>${view.ranking.map((r,i) => `<article class="recommendation"><div><span>#${i+1} · 得分 ${r.score.toFixed(3)}</span><button class="select-button" data-rank="${i}">${r.changes.length ? '应用组合' : '当前组合'}</button></div><p>${r.changes.length ? '调整：'+esc(r.changes.join('、')) : '保持当前选择'}</p>${r.score_terms?`<p>单段项 ${r.score_terms.unary.toFixed(3)} + 搭配项 ${r.score_terms.interaction.toFixed(3)}<br>相对当前：单段 ${r.score_delta.unary.toFixed(3)} / 搭配 ${r.score_delta.interaction.toFixed(3)}</p>`:''}<details><summary>预览完整文本</summary><pre>${esc(r.text)}</pre></details></article>`).join('')}${!view.pair_count ? '<p class="muted">尚无比较反馈，当前全部得分相同。</p>' : '<p class="muted">得分为相对效用，不是满意度概率。</p>'}`;
}
document.addEventListener('click', e => {
  const target = e.target.closest('button'); if (!target) return;
  if (target.dataset.session) exclusive(() => openSession(target.dataset.session));
  else if (target.dataset.select) exclusive(() => action('select',{block:target.dataset.select,variant:target.dataset.variant}));
  else if (target.dataset.lock) exclusive(() => action('lock',{block:target.dataset.lock}));
  else if (target.dataset.initial !== undefined) exclusive(async () => { const i = Number(target.dataset.initial); await action('apply',{combo:Object.fromEntries(view.task.blocks.map(b => [b.id,view.state.locks[b.id] || b.variants[i].id]))}); });
  else if (target.dataset.choice) exclusive(async () => { await action('compare',{offer:currentOffer.id,choice:target.dataset.choice}); toast('已记录明确比较，偏好模型与组合排序已更新'); });
  else if (target.dataset.rank !== undefined) exclusive(async () => { await action('apply',{combo:view.ranking[Number(target.dataset.rank)].combo}); toast('已应用可行组合，锁定段落保持不变'); });
  else if (target.id === 'skip') exclusive(async () => { await action('skip',{offer:currentOffer.id}); toast('已跳过，不产生训练标签'); });
  else if (target.id === 'apply-evaluated') exclusive(async()=>{await action('apply',{combo:view.last_evaluated.combo});toast('已另外采用评价中的胜出组合');});
});
$('#facts-toggle').onclick = () => { const hidden = $('#facts').classList.toggle('hidden'); $('#facts-toggle').setAttribute('aria-expanded', !hidden); };
$('#undo').onclick = () => exclusive(async () => { await action('undo'); toast('已撤回上一步；撤回的比较已从训练中排除'); });
$('#set-limit').onclick = () => exclusive(async () => { const raw = $('#max-chars').value; await action('constraint',{max_chars:raw === '' ? null : Number(raw)}); });
$('#recommend').onclick = () => exclusive(async () => { await action('recommend'); view = await api(endpoint()); showRanks = true; renderRanks(); });
$('#get-compare').onclick = () => exclusive(async () => { const result = await api(endpoint('/offer'),{revision:view.revision}); currentOffer = result.offer; renderOffer(); });
$('#adopt').onclick = () => exclusive(async () => { await action('adopt'); toast('已保存最终采用的完整文本与组合'); });
$('#export').onclick = () => exclusive(async () => { const result = await action('export'); $('#export-path').textContent = `最近导出：${result.path}`; $('#save-state').textContent = `✓ 已保存到本机 · v${view.revision}`; toast('文本已保存到项目的 data/exports 文件夹（D盘）'); });
$('#audit-export').onclick = () => exclusive(async () => { const result = await action('audit_export'); $('#save-state').textContent = `✓ 已保存到本机 · v${view.revision}`; toast(`会话 JSON 已保存：${result.path}`); });
$('#new-round').onclick = () => exclusive(async () => { const result = await api('/api/sessions', {clone:sessionId}); await openSession(result.id); toast('已创建独立会话，旧记录保留在左侧'); });
$('#save-research').onclick=()=>exclusive(async()=>{await action('research_config',{config:{model:$('#pref-model').value,policy:$('#query-policy').value,context_mode:$('#context-mode').value,budget:Number($('#feedback-budget').value),seed:Number($('#research-seed').value),evaluate_only:$('#evaluate-only').checked,data_origin:$('#data-origin').value,participant_id:$('#participant-id').value.trim()}});toast('已保存学习与比较设置；历史标签保持原始语义');});
const customDefaults = [
  ['项目定位',['{{name}}是一个帮助用户组织内容的工具。','我正在做{{name}}，希望让内容整理更容易。','{{name}}围绕内容组织构建交互流程。']],
  ['当前进展',['目前{{stage}}。','现在还处在{{stage}}的阶段。','项目当前状态为{{stage}}。']],
  ['下一步计划',['下一步先完成核心流程。','接下来想先把最常用的流程做顺手。','近期将优先验证核心功能闭环。']],
  ['收尾',['欢迎试用并提出建议。','如果你也有类似需求，很想听听你的想法。','期待通过真实反馈进一步完善项目。']]
];
let editorMode = 'new', editorBlocks = [], editorRevision = 0;
function editorError(message) { $('#create-error').textContent = message; $('#create-error').classList.remove('hidden'); }
function readFacts() {
  const facts = {};
  for (const line of $('#create-facts').value.split('\n').map(x=>x.trim()).filter(Boolean)) {
    const pos = line.indexOf('='); if (pos < 1) throw new Error('固定事实请使用 key=内容，每行一项');
    const key = line.slice(0,pos).trim(); if (Object.hasOwn(facts,key)) throw new Error('固定事实键重复：'+key); facts[key] = line.slice(pos+1).trim();
  }
  return facts;
}
function collectBlocks() {
  return editorBlocks.map((b,i) => ({...b,title:$(`[data-custom-title="${i}"]`).value,variants:b.variants.map((v,j) => ({...v,template:$(`[data-custom-text="${i}-${j}"]`).value}))}));
}
function renderBuilder() {
  $('#create-blocks').innerHTML = editorBlocks.map((b,i) => `<fieldset><legend>部件 ${i+1}</legend><label>部件名称<input data-custom-title="${i}" value="${esc(b.title)}" required maxlength="100"></label><div class="custom-variants">${b.variants.map((v,j) => {
    const locked = editorMode === 'edit' && (view.state.locks[b.id] === v.id || view.task.blocks.find(x=>x.id===b.id)?.fixed);
    return `<label>版本 ${j+1}${locked ? ' · 已锁定，先解锁再编辑' : ''}<textarea data-custom-text="${i}-${j}" rows="4" required maxlength="3000" ${locked ? 'disabled' : ''}>${esc(v.template)}</textarea></label>`;
  }).join('')}</div></fieldset>`).join('');
  $('#add-block').disabled = editorBlocks.length >= 6; $('#remove-block').disabled = editorBlocks.length <= 2;
}
function populateEditor(task) {
  $('#create-title').value = task.title || '';
  $('#create-brief').value = task.brief || '';
  $('#create-facts').value = Object.entries(task.facts || {}).map(([k,v])=>`${k}=${v}`).join('\n');
  editorBlocks = task.blocks.map(b=>({id:b.id,title:b.title,variants:b.variants.map(v=>({...v}))}));
  renderBuilder();
}
function openEditor(mode) {
  editorMode = mode; editorRevision = view.revision;
  $('.import-panel').open = false;
  $('#create-error').classList.add('hidden'); $('#import-status').textContent = '';
  $('#import-file').value = ''; ['a','b','c'].forEach(k=>$('#draft-'+k).value='');
  $('#dialog-title').textContent = mode === 'edit' ? '编辑本任务的候选' : '新建自己的任务';
  $('#submit-task').textContent = mode === 'edit' ? '保存候选修改 →' : '创建并开始组合 →';
  $('#editor-help').textContent = mode === 'edit' ? '已锁定版本不可编辑。修改会生成新版本，保留旧文字与反馈；新文字不继承旧标签。事实与段落结构保持固定，要更改请新建任务。' : '填写任务与固定事实，手动编写或导入三份草稿。用 {{key}} 引用事实；同一段的三个版本需引用相同事实。默认内容仅供示意，请替换为自己的内容。';
  ['#create-title','#create-brief','#create-facts'].forEach(s=>$(s).disabled=mode==='edit');
  $('#json-import-label').classList.toggle('hidden',mode==='edit'); $('#block-controls').classList.toggle('hidden',mode==='edit');
  populateEditor(mode === 'edit' ? view.task : {title:'我的任务',brief:'描述这次要完成什么',facts:{name:'我的项目',stage:'原型开发中'},blocks:customDefaults.map(([title,texts],i)=>({id:'part'+i,title,variants:texts.map((template,j)=>({id:`part${i}-${j}`,template}))}))});
  $('#create-dialog').showModal();
}
$('#new-task').onclick = () => openEditor('new');
$('#edit-candidates').onclick = () => openEditor('edit');
$('#close-dialog').onclick = () => $('#create-dialog').close();
$('#add-block').onclick = () => {
  editorBlocks = collectBlocks(); let n=editorBlocks.length; while(editorBlocks.some(b=>b.id==='part'+n)) n++;
  const bid='part'+n; editorBlocks.push({id:bid,title:`段落 ${editorBlocks.length+1}`,variants:[0,1,2].map(j=>({id:`${bid}-${j}`,template:''}))}); renderBuilder();
};
$('#remove-block').onclick = () => { if(editorBlocks.length>2){editorBlocks=collectBlocks();editorBlocks.pop();renderBuilder();} };
$('#import-file').onchange = () => exclusive(async () => {
  try {
    const file = $('#import-file').files[0]; if(!file) return; if(file.size>200000) throw new Error('JSON文件请小于200 KB');
    const value=JSON.parse((await file.text()).replace(/^\uFEFF/,'')); const task=value.task || value;
    if(!task || !Array.isArray(task.blocks) || task.blocks.length<2 || task.blocks.length>6 || !task.blocks.every(b=>Array.isArray(b.variants)&&b.variants.length===3)) throw new Error('JSON应包含2–6个部件，每部件3个版本；可直接导入本工具导出的会话JSON');
    populateEditor(task); $('#create-error').classList.add('hidden'); $('#import-status').textContent='已载入事实与候选，可继续编辑。创建后是独立会话，不导入旧反馈。';
  } catch(e) {editorError(e.message);}
});
function referenceFacts(text,facts) {
  const values = [...new Set(Object.values(facts))].filter(Boolean).sort((a,b)=>b.length-a.length);
  if(!values.length) return text;
  const escapeRegex=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const pattern=new RegExp(values.map(escapeRegex).join('|'),'g');
  return text.split(/(\{\{[\s\S]*?\}\})/g).map(piece=>piece.startsWith('{{')?piece:piece.replace(pattern,match=>'{{'+Object.keys(facts).find(k=>facts[k]===match)+'}}')).join('');
}
$('#parse-drafts').onclick = () => {
  try {
    const drafts=['a','b','c'].map(k=>$('#draft-'+k).value.replace(/\r\n/g,'\n').trim().split(/\n\s*\n/).map(s=>s.trim()).filter(Boolean));
    const count=drafts[0].length;
    if(count<2||count>6||drafts.some(d=>d.length!==count)) throw new Error('三份草稿需有相同的2–6个段落；用空行分段');
    if(editorMode==='edit'&&count!==editorBlocks.length) throw new Error('已有任务的段落数量不能改变，请新建任务导入');
    const facts=readFacts(), previous=collectBlocks();
    const next=Array.from({length:count},(_,i)=>({id:previous[i]?.id || 'import'+i,title:previous[i]?.title || '段落 '+(i+1),variants:[0,1,2].map(j=>({...previous[i]?.variants[j],id:previous[i]?.variants[j]?.id || `import${i}-${j}`,template:referenceFacts(drafts[j][i],facts)}))}));
    if(editorMode==='edit') for(const b of next) for(const v of b.variants) if(view.state.locks[b.id]===v.id && view.task.blocks.find(x=>x.id===b.id).variants.find(x=>x.id===v.id).template!==v.template) throw new Error('导入内容改变了已锁定版本，请先解锁该段落');
    editorBlocks=next;renderBuilder();$('#create-error').classList.add('hidden');$('#import-status').textContent=`已解析 ${count} 个段落，可在下方逐段检查和编辑，再保存。`;
  }catch(e){editorError(e.message);}
};
$('#create-form').onsubmit = (event) => { event.preventDefault(); exclusive(async () => {
  try {
    if(editorMode==='edit') {
      await api(endpoint('/action'),{kind:'edit',revision:editorRevision,blocks:collectBlocks()});
      $('#create-dialog').close();await reload();toast('已保存新版本，锁定与历史反馈保留');
    } else {
      const task={title:$('#create-title').value.trim(),brief:$('#create-brief').value.trim(),facts:readFacts(),blocks:collectBlocks()};
      const result=await api('/api/sessions',{task});$('#create-dialog').close();await openSession(result.id);toast('任务已创建，内容仅保存在本机');
    }
  } catch (e) { editorError(e.status===409 ? e.message+' 请关闭编辑器后刷新页面。' : e.message); }
}); };
exclusive(async () => {
  await listSessions(); let saved; try { saved = localStorage.getItem('intent-session'); } catch {}
  const email = sessions.find(s => s.title === '给老师的项目介绍邮件');
  await openSession(sessions.some(s=>s.id===saved) ? saved : (email || sessions[0]).id);
});
