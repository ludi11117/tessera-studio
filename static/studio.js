'use strict';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const S={config:null,view:null,sid:null,jobs:[],materials:[],library:[],delivery:null,taskType:'auto',tab:'document',activeJob:null,proposal:null,editing:null,offer:null,busy:false};
let toastTimer,pollTimer;
function toast(text){$('#studio-toast').textContent=text;$('#studio-toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#studio-toast').classList.remove('visible'),5000);}
async function api(path,data){let response;try{response=await fetch(path,data===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}catch{throw new Error('本地服务未连接，请检查启动窗口');}const value=await response.json();if(!response.ok){const error=new Error(value.error||'请求失败');error.status=response.status;throw error;}return value;}
const endpoint=suffix=>`/api/sessions/${S.sid}${suffix||''}`;
async function run(fn){if(S.busy)return;S.busy=true;try{await fn();}catch(e){if(e.status===409&&S.sid&&!e.draftConflict)await refreshDocument();toast(e.message);}finally{S.busy=false;}}
function variant(block,combo){return block.variants.find(v=>v.id===(combo||S.view.state.combo)[block.id]);}
function text(v){return v.template.replace(/\{\{(.*?)\}\}/g,(_,k)=>S.view.task.facts[k]);}
function inline(raw){return esc(raw).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1 ↗</a>').replace(/\[(M\d+#\d+)\]/g,'<button class="source-link" data-source="$1">$1</button>');}
function markdown(raw){
  const lines=String(raw||'').replace(/\r\n/g,'\n').split('\n');let html='',list=null,code=null,table=false;
  function closeList(){if(list){html+=`</${list}>`;list=null;}}
  function closeTable(){if(table){html+='</tbody></table>';table=false;}}
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    if(line.trim().startsWith('```')){closeList();closeTable();if(code!==null){html+=`<pre><code>${esc(code)}</code></pre>`;code=null;}else code='';continue;}
    if(code!==null){code+=line+'\n';continue;}
    if(/^\s*\|.+\|\s*$/.test(line)){
      closeList();if(/^\s*\|[\s:|-]+\|\s*$/.test(line))continue;
      const cells=line.trim().slice(1,-1).split('|');
      if(!table){html+='<table><tbody>';table=true;}
      html+='<tr>'+cells.map(c=>'<td>'+inline(c.trim())+'</td>').join('')+'</tr>';continue;
    }closeTable();
    const bullet=line.match(/^\s*[-*+]\s+(.+)$/),number=line.match(/^\s*\d+[.)、]\s*(.+)$/);
    if(bullet||number){const wanted=bullet?'ul':'ol';if(list!==wanted){closeList();html+=`<${wanted}>`;list=wanted;}html+='<li>'+inline((bullet||number)[1])+'</li>';continue;}
    closeList();const heading=line.match(/^#{1,5}\s+(.+)$/);
    if(heading)html+='<h4>'+inline(heading[1])+'</h4>';else if(line.trim())html+='<p>'+inline(line)+'</p>';
  }
  closeList();closeTable();if(code!==null)html+=`<pre><code>${esc(code)}</code></pre>`;return html;
}
async function setHome(){await flushCurrentDraft();$('#workspace-view').inert=false;S.sid=null;S.view=null;S.jobs=[];S.proposal=null;S.autoOpenJobId=null;$('#home-view').classList.remove('hidden');$('#workspace-view').classList.add('hidden');$('#page-title').textContent='新目标';$('#studio-saved').textContent='目标草稿 · 本地保存';$('#navigation').classList.remove('open');try{localStorage.removeItem('intent-studio-session');}catch{}await loadSessions();}
function activateTab(tab){S.tab=tab;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));['document','candidates','sources','decision'].forEach(k=>$('#'+k+'-view').classList.toggle('hidden',k!==tab));if(tab==='decision')renderDecision().catch(e=>{toast(e.message);$('#decision-view').innerHTML='<p role="status">决策计算未完成，请切换标签后重试。</p>';});}
async function loadSessions(){const {sessions}=await api('/api/sessions');S.sessions=sessions;renderSessions();renderChoiceDemoEntry();}
function renderSessions(){
  const query=$('#session-search').value.trim().toLocaleLowerCase(),all=S.sessions||[];
  const visible=all.filter(s=>!query||s.title.toLocaleLowerCase().includes(query)),real=visible.filter(s=>s.source!=='example'),examples=visible.filter(s=>s.source==='example');
  $('#session-count').textContent=all.filter(s=>s.source!=='example').length;
  const item=s=>`<button data-session="${esc(s.id)}" class="${S.sid===s.id?'active':''}" title="${esc(s.title)}">${s.source==='generated'?'✦':'▤'} &nbsp;${esc(s.title)}<small>${s.source==='generated'?'生成稿件':s.source==='custom'?'导入 / 自建':'示例内容'} · v${s.revision}</small></button>`;
  $('#studio-sessions').innerHTML=(real.map(item).join('')||(query?'':'<p class="empty-sessions">还没有自己的成果。写下目标，开始第一份稿件。</p>'))+(examples.length?`<details class="sample-sessions" ${query?'open':''}><summary>示例与体验 · ${examples.length}</summary>${examples.map(item).join('')}</details>`:'')+(!visible.length&&query?'<p class="empty-sessions">没有找到相符的成果，试试标题中的其他词。</p>':'');
  $('#session-filter-status').textContent=query?`找到 ${visible.length} 份相关稿件`:'';
}

async function loadConfig(){S.config=await api('/api/ai/config');const health=await api('/api/health');S.serverVersion=health.version;S.choiceCapable=health.capabilities?.includes('choice-board-v1');if($('#choice-directions'))$('#choice-directions').hidden=!S.choiceCapable;if(S.config.preview_mode&&!$('#preview-mode-label')){const label=document.createElement('p');label.id='preview-mode-label';label.textContent='新版隔离预览 · 数据不写入正式库';$('.nav-bottom').prepend(label);}const connected=S.config.ready??S.config.key_configured;const providerName=S.config.provider==='siliconflow'?'硅基流动':S.config.local_endpoint?'本机模型':'自定义模型';$('#connection-label').textContent=connected?providerName+' · 已配置':'连接你的 AI';$('#connection-label').title=S.config.model||'';$('#provider-display-name').textContent=providerName;$('#provider-display-url').textContent=S.config.base_url;$('.provider-notice').textContent='生成与AI修正会将目标及相关素材发送至 '+S.config.base_url+'；本地偏好训练不使用此接口。';return S.config;}
async function openSession(sid){await flushCurrentDraft();S.sid=sid;S.view=null;revisionChannel=null;$('#revision-input').value='';$('#workspace-view').inert=true;$('#document-view').textContent='正在读取这份稿件…';$('#candidates-view').replaceChildren();$('#sources-view').replaceChildren();$('#revision-input').disabled=true;$('#revision-scope').disabled=true;$('#send-revision').disabled=true;$('#revision-draft-status').textContent='正在读取这个任务的修改草稿…';$('#home-view').classList.add('hidden');$('#workspace-view').classList.remove('hidden');$('#navigation').classList.remove('open');try{localStorage.setItem('intent-studio-session',sid);}catch{}try{await refreshDocument();await loadRevisionDraft(sid);await loadHistory();await loadSessions();activateTab('document');}catch(error){$('#revision-draft-status').textContent='草稿读取失败，请从任务列表重新打开；输入暂不可用。';throw error;}finally{const ready=!!revisionChannel?.ready;$('#workspace-view').inert=!ready;$('#revision-input').disabled=!ready;$('#revision-scope').disabled=!ready;$('#send-revision').disabled=!ready||!!S.activeJob;}}
async function refreshDocument(){if(!S.sid)return;const previousScope=$('#revision-scope').value;S.view=await api(endpoint());const [library,delivery]=await Promise.all([api(endpoint('/ai/materials')),api(endpoint('/ai/delivery'))]);if(library.revision!==S.view.revision||delivery.revision!==S.view.revision){const error=new Error('稿件正在另一窗口更新，请稍后重新打开');error.status=409;throw error;}S.library=library.materials;S.delivery=delivery;S.decision=null;renderDocument();renderCandidates();renderSources();renderProposalBanner();if(S.tab==='decision')renderDecision().catch(e=>toast(e.message));$('#studio-saved').textContent=`✓ 已保存 · v${S.view.revision}`;$('#page-title').textContent=S.view.task.title;$('#export-md').textContent=S.view.task.category==='writing'?'导出 TXT ↓':'导出 MD ↓';$('#undo-studio').disabled=!S.view.can_undo;$('#revision-scope').innerHTML='<option value="all">全部未锁定部分</option>'+S.view.task.blocks.filter(b=>!b.fixed).map(b=>`<option value="${esc(b.id)}" ${S.view.state.locks[b.id]?'disabled':''}>${esc(b.title)}${S.view.state.locks[b.id]?'（已锁定）':''}</option>`).join('');restoreScope(previousScope);}
function renderDocument(){
  const {task,state}=S.view;
  const origin=task.source==='generated'?`由 ${task.ai?.model||'硅基流动'} 生成，按你的选择继续定制`:task.source==='example'||!task.source?'演示内容，可直接修改与体验':'你导入或编写的内容';
  const sections=task.blocks.filter(b=>!b.fixed).map(b=>`<section class="document-section ${state.locks[b.id]?'is-locked':''}" id="block-${esc(b.id)}"><div class="section-title-row"><h3>${esc(b.title)}</h3><div class="section-actions"><button data-rewrite="${esc(b.id)}" ${state.locks[b.id]?'disabled':''}>✦ 改进</button><button data-preserve="${esc(b.id)}">保留局部</button><button data-edit="${esc(b.id)}" ${state.locks[b.id]?'disabled':''}>编辑</button><button data-lock="${esc(b.id)}" class="${state.locks[b.id]?'locked':''}" aria-pressed="${!!state.locks[b.id]}">${state.locks[b.id]?'▣ 已锁定':'▢ 锁定'}</button></div></div><div class="markdown">${markdown(text(variant(b)))}</div>${preservedHTML(b)}<div class="variant-switch"><span>其他版本</span>${b.variants.map((v,j)=>`<button data-variant="${esc(v.id)}" data-block="${esc(b.id)}" class="${v.id===state.combo[b.id]?'selected':''}" ${state.locks[b.id]||v.id===state.combo[b.id]?'disabled':''}>${['A','B','C'][j]}</button>`).join('')}<button class="evidence-entry" data-evidence="${esc(b.id)}"><i data-lucide="scan-text" aria-hidden="true"></i>核对来源</button></div></section>`).join('');
  const constraints=task.blocks.some(b=>b.fixed)?`<div class="task-conditions"><span>▣ ${Object.keys(task.facts).length} 项固定条件在任务记录中保留，不混入导出正文。</span><button id="view-conditions" class="button-quiet">查看条件</button></div>`:'';
  const lockCount=task.blocks.filter(b=>!b.fixed&&state.locks[b.id]).length;
  const requirements=[...(S.delivery?.requirements?.warnings||[]),...(S.delivery?.acceptance?.contract.confirmed?(S.delivery.acceptance.failures.map(f=>'已确认条件未通过：'+f.label)):[])];const requirementNotice=requirements.length?`<div class="requirement-notice"><i data-lucide="circle-alert" aria-hidden="true"></i><div>${requirements.map(w=>`<p>${esc(w)}</p>`).join('')}<button data-tab="sources">查看交付检查</button></div></div>`:'';
  $('#document-view').innerHTML=`${journeyHTML()}<button class="document-overview-link" data-open-decision><i data-lucide="workflow" aria-hidden="true"></i><span>查看本次交付的条件、取舍与证据</span><i data-lucide="chevron-right" aria-hidden="true"></i></button>${constraints}${requirementNotice}<article class="document-paper"><div class="document-heading"><span class="small-kicker">当前文稿</span><h2>${esc(task.title)}</h2><p>${esc(origin)} · ${lockCount} 处锁定</p><button id="ask-preference" class="button-quiet preference-entry">帮我挑一版 ↗</button></div>${sections}</article><p class="artifact-note">满意的部分可以锁定。导出前，请通读一次完整成品。</p>`;
}
function comboForCandidate(index){return Object.fromEntries(S.view.task.blocks.map(b=>[b.id,S.view.state.locks[b.id]||b.variants[index].id]));}
function optimizationHTML(){
  const o=S.view.optimization,best=S.view.ranking[0];
  if(!o)return '<p>先在“目标与素材”确认验收条件，让组合搜索按你的要求筛选。</p>';
  return `<div class="optimization-report"><h3>在约束下搜索整份方案</h3><p>已遍历 ${o.searched} 个满足锁定与长度上限的组合，${o.eligible} 个满足已确认机器条件。</p>${Object.keys(o.rejected_by_requirement).length?`<details><summary>查看排除依据</summary><ul>${Object.entries(o.rejected_by_requirement).map(([k,v])=>`<li>${esc(k)}：排除 ${v} 个组合</li>`).join('')}</ul><p>同一组合可能违反多项条件，计数不能相加。</p></details>`:''}<p>${o.pair_count?`按 ${o.pair_count} 次明确比较的偏好得分排序，再优先保留原文。`:'尚无明确比较，优先选择改动最少的合格组合。'}只保证已实现的机器条件，搭配连贯与事实仍需核对。</p>${best?`<button id="apply-verified-combo" class="button-primary" ${!best.changes.length?'disabled':''}>采用合格组合${best.changes.length?` · 调整${best.changes.length}章`:''}</button>`:'<p role="status">当前候选中无解。可修正失败章节、解锁必要部分，或核对验收条件。</p>'}</div>`;
}
function acceptanceHTML(){
  if(!['product-v7','product-v8','product-v9','product-v10'].includes(S.serverVersion))return '<p class="field-note">新版验收后端尚未启用。请关闭旧服务窗口后，通过原启动入口重新打开工程。</p>';
  const a=S.delivery?.acceptance;if(!a)return '';const c=a.contract;
  const fields=[['required','必须保留的原文短语'],['forbidden','禁止出现的原文短语'],['manual','需要模型与人工判断的要求']];
  const review=a.latest_review,rounds=review?.rounds||[];
  return `<article class="source-card acceptance-panel"><div class="small-kicker">验收与修正</div><h3>${c.confirmed?'本任务的验收条件':'先把合格条件定下来'}</h3><p>${c.confirmed?'已确认的机器条件用于组合搜索、采用与导出；手动编辑可保留未通过的中间稿。':'从目标中保守提取的建议，确认前不作为硬约束。没有识别的要求请自行补充。'}</p><form id="acceptance-form"><label><span><input id="acceptance-source-numbers" type="checkbox" ${c.source_numbers?'checked':''}> 数字措辞必须在目标、条件或素材中有相同原文</span></label><div class="contract-fields"><label>正文最少字符<input id="acceptance-min" type="number" min="1" max="20000" value="${c.length?.min||''}" placeholder="不限"></label><label>正文最多字符<input id="acceptance-max" type="number" min="1" max="20000" value="${c.length?.max||''}" placeholder="不限"></label><label>逐日覆盖天数<input id="acceptance-days" type="number" min="1" max="31" value="${c.days||''}" placeholder="不限"></label></div>${fields.map(([key,label])=>`<label>${label}<textarea id="acceptance-${key}" rows="2" placeholder="每行一项">${esc(c[key].join('\n'))}</textarea></label>`).join('')}<p class="field-note">字数不含标题、固定条件、空白与引用编号。数字只核对原文出现，不验证归属、单位换算或代码；可能排除合理的新建议，可按任务关闭。短语逐字检查，日序只核对“第几天”标记；每天时长、语义、事实和其他目标需单独判断。</p><button type="submit" class="button-quiet">${c.confirmed?'保存验收条件':'确认验收条件'}</button></form><ul class="acceptance-results">${a.checks.map(x=>`<li>${x.passed?'通过':'未通过'} · ${esc(x.label)}${x.id==='length'?`（当前 ${x.actual} 字）`:''}</li>`).join('')||'<li>尚未设置机器检查项；这不代表已满足目标。</li>'}</ul><p>${a.machine_check_count?`${a.machine_check_count-a.failures.length}/${a.machine_check_count} 项机器条件通过。`:''}人工判断尚待确认。</p><button id="repair-acceptance" class="button-primary" ${!c.confirmed||S.activeJob?'disabled':''}>检查并修正未通过部分 ↗</button><p class="field-note">主动点击才调用 API；最多3次请求，包含独立模型检查、必要修正和复验。只处理未通过且未锁定章节，先保存草案，采用前不改动正文。模型检查可能漏检，不能替代人工判断。</p>${rounds.length?`${review.current?'':'<p>以下为旧版本检查记录，正文、条件或素材已变化，需要重新检查。</p>'}${qualityHTML(rounds)}`:''}</article>`;
}
function qualityHTML(rounds){return `<details class="quality-rounds"><summary>查看逐轮验收依据 · ${rounds.length} 轮</summary>${rounds.map(r=>`<div><h4>${r.phase==='before'?'修正前':'复验'}</h4><p>机器条件：${!r.machine.machine_check_count?'未设置检查项':r.machine.machine_passed?'通过':'未通过'} · 独立模型：${({no_issue_found:'未发现问题',issues_found:'发现问题',uncertain:'仍有不确定项'})[r.review.status]||'未完成'}</p><ul>${r.machine.failures.map(f=>`<li>${esc(f.label)}</li>`).join('')}${r.review.findings.map(f=>`<li>${esc(f.block)} · ${esc(f.reason)}${f.quote?`<blockquote>${esc(f.quote)}</blockquote>`:''}</li>`).join('')}${r.review.uncertain.map(s=>`<li>待核实：${esc(s)}</li>`).join('')}</ul></div>`).join('')}</details>`;}
async function confirmAcceptance(){
  const lo=$('#acceptance-min').value,hi=$('#acceptance-max').value,days=$('#acceptance-days').value;
  if(!!lo!==!!hi)throw new Error('请同时填写最少与最多字符，或同时留空');
  const contract={length:lo?{min:Number(lo),max:Number(hi)}:null,days:days?Number(days):null,source_numbers:$('#acceptance-source-numbers').checked};
  for(const key of ['required','forbidden','manual'])contract[key]=$('#acceptance-'+key).value.split('\n').map(s=>s.trim()).filter(Boolean);
  await mutate('acceptance',{contract});toast('验收条件已保存；推荐、采用与导出将检查机器条件。');
}
async function repairAcceptance(){
  if(S.activeJob)throw new Error('请等待当前任务完成');
  const job=await jobRequest(endpoint('/ai/repair'),{revision:S.view.revision});
  $('#repair-acceptance').disabled=true;renderProgress(job);watch(job.id);
}
function renderCandidates(){
  if(S.view.choice_board&&typeof renderChoiceBoard==='function'){renderChoiceBoard();return;}
  const task=S.view.task,labels=task.ai?.candidate_labels||['简洁直接','温和自然','正式完整'],best=S.view.ranking[0];
  const models={legacy:'记住具体版本',additive:'记住具体版本（固定先验）',interaction:'学习版本搭配',content_linear:'按内容推荐（实验）',content_frozen:'按内容与搭配推荐（固定特征，实验）',content_neural:'按内容与搭配推荐（可训练，实验）'};
  const selected=S.view.state.research?.model||'legacy';
  const learning=`<article class="source-card"><h3>让推荐跟上你的修改</h3><p>你明确选出的更好版本，用来改进本任务的推荐。按内容推荐可为新改写估分，仍需你确认。</p><label>本任务的推荐方式<select id="studio-learning-model" ${!S.view.research_available?'disabled':''}>${Object.entries(models).map(([key,label])=>`<option value="${key}" ${key===selected?'selected':''}>${label}</option>`).join('')}</select></label><button id="save-studio-learning" class="button-quiet" ${!S.view.research_available?'disabled':''}>保存推荐方式</button><button id="compare-studio-learning" class="button-quiet">比较两个版本 ↗</button><p>${S.view.research_warning?esc(S.view.research_warning):S.view.research_available?`已记录 ${S.view.pair_count} 次明确比较；选择、编辑和锁定不会变成偏好标签。`:'使用“启动研究工作台.cmd”可启用内容推荐；普通 AI 生成不受影响。'}</p>${selected.startsWith('content_')?'<details><summary>实验能力说明</summary><p>使用文字统计与词片段特征，不等于理解语义；模型在本任务内拟合，不训练或微调硅基流动大模型。少于4条比较时冻结小网络。搭配得分与预测未经真实用户效果验证，可随时切回基线。</p></details>':''}</article>`;
  $('#candidates-view').innerHTML=`<div class="source-card"><h3>先选一个起点，再按你的目标调整</h3><p>三种方案按相同章节组织。切换会保留已锁定内容，你也可以在成品里只替换一个章节。</p>${S.view.pair_count&&best?.changes.length?`<p>根据本任务中 ${S.view.pair_count} 次明确比较，模型推荐调整：${esc(best.changes.join('、'))}。得分是相对效用估计。</p><button id="apply-preference-rank" class="button-quiet">采用偏好推荐组合</button>`:''}</div>${optimizationHTML()}${learning}${[0,1,2].map(j=>`<article class="candidate-card"><div class="candidate-number">${['A','B','C'][j]}</div><h3>${esc(labels[j])}</h3><div class="markdown">${markdown(text(task.blocks.find(b=>!b.fixed).variants[j]).slice(0,200))}</div><details><summary>查看完整方案</summary><div class="markdown">${task.blocks.filter(b=>!b.fixed).map(b=>`<h3>${esc(b.title)}</h3>${markdown(text(b.variants[j]))}`).join('')}</div></details><button data-candidate="${j}" class="button-primary">以这个方案继续 ↗</button></article>`).join('')}`;
}
function renderSources(){
  const t=S.view.task,blue=t.ai?.blueprint||{};
  const warnings=[...(t.ai?.checks?.unsupported_citations_removed||[]),...(t.ai?.revisions||[]).flatMap(r=>r.checks?.unsupported_citations_removed||[])];
  const cards=[`<article class="source-card"><h3>这次要完成什么</h3><p>${esc(t.brief)}</p>${blue.objective?`<p><b>交付目标：</b>${esc(blue.objective)}</p>`:''}${blue.audience?`<p><b>面向：</b>${esc(blue.audience)}</p>`:''}</article>`];
  cards.unshift(journeyHTML(false,'deliver'),requirementCardHTML(),traceHTML());
  cards.push(acceptanceHTML());
  cards.push(`<article class="source-card"><h3>任务素材 · ${S.library.length} 份</h3><p>补充新信息后，可让 AI 基于最新资料继续修改。</p>${S.library.map(m=>`<p><b>${esc(m.id)} · ${esc(m.name)}</b> · ${m.text.length.toLocaleString()} 字</p>`).join('')}<button id="manage-materials" class="button-primary">补充 / 修改素材</button></article>`);
  if(S.delivery){const d=S.delivery;cards.push(`<article class="source-card evidence-overview"><div class="small-kicker">正文与原文对照</div><h3>交付前，把依据看清楚。</h3><p>逐段查看数字、引号措辞与引用原文的文字对应。缺少对应不代表事实错误，相同文字也不代表语义已核实。</p><div class="evidence-section-list">${(d.evidence?.sections||[]).map(s=>`<button data-evidence="${esc(s.block)}"><span>${esc(s.title)}</span><span>${s.review_items?`${s.review_items} 项待核对`:'查看文字对应'} <i data-lucide="chevron-right" aria-hidden="true"></i></span></button>`).join('')}</div></article>`);cards.push(`<article class="source-card"><span class="small-kicker">04 · 检查交付</span><h3>这份成果，可以交付了吗？</h3><p>${d.sections} 个章节 · ${d.characters.toLocaleString()} 字 · ${d.citation_count} 处不同引用</p>${d.preservation?.length?`<p>${d.preservation.filter(c=>c.passed).length}/${d.preservation.length} 处局部原文保留通过</p>`:''}${d.warnings.length?'<ul>'+d.warnings.map(w=>`<li>${esc(w)}</li>`).join('')+'</ul>':'<p>未发现已实现检查中的结构提示。</p>'}<div class="delivery-review">${Object.entries({read_through:'我已通读成品，内容完整',facts_checked:'我已核对事实、假设与素材',usable:'这份成果满足本次使用要求'}).map(([key,label])=>`<label><input type="checkbox" data-review="${key}" ${d.review[key]?'checked':''}>${label}</label>`).join('')}</div><p>勾选由你确认；正文、章节标题或素材改变后需重新确认。自动检查不判断事实真伪。</p><div class="guide-actions"><button class="button-quiet" data-journey-export="body">导出正文 ↓</button><button class="button-primary" data-journey-export="zip">导出成果与记录 ↗</button></div></article>`);}
  cards.push(`<article class="source-card"><h3>固定事实与限制</h3>${Object.keys(t.facts).length?'<ul>'+Object.entries(t.facts).map(([k,v])=>`<li><b>${esc(k)}</b>：${esc(v)}</li>`).join('')+'</ul>':'<p>本任务没有单独设置固定事实。</p>'}<button id="fork-goal" class="button-quiet">更改目标或条件，创建新任务 ↗</button><p>旧成果和反馈保留，新任务的素材需重新附加。</p></article>`);
  if(blue.assumptions?.length)cards.push(`<article class="source-card"><h3>初版使用的假设</h3><ul>${blue.assumptions.map(v=>`<li>${esc(v)}</li>`).join('')}</ul><p>可在对话中补充和纠正；后续修改会结合当前成稿与明确要求。</p></article>`);
  if(blue.questions?.length)cards.push(`<article class="source-card"><h3>值得补充的信息</h3><ul>${blue.questions.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></article>`);
  if(warnings.length)cards.push(`<article class="source-card"><h3>生成检查提示</h3><p>模型曾返回不存在的素材引用，已移除：${esc([...new Set(warnings)].join('、'))}。这不等于其余事实经过外部验证，使用前仍需核查。</p></article>`);
  cards.push('<h3 class="small-kicker">实际使用的素材片段</h3>');
  cards.push((t.ai?.sources||[]).map(source=>`<article class="source-card" data-source-card="${esc(source.id)}"><div class="source-id">${esc(source.id)} · ${esc(source.name)}</div><p>${esc(source.text)}</p></article>`).join('')||'<p class="empty-note">没有附加素材。当前内容来自你的目标与模型生成，请核实事实和方案可行性。</p>');
  $('#sources-view').innerHTML=cards.join('');
}
async function loadHistory(){if(!S.sid)return;const data=await api(endpoint('/ai/history'));S.jobs=data.jobs;const latest=S.jobs.find(j=>['revise','repair'].includes(j.kind)&&j.status==='completed');S.proposal=latest&&!latest.result?.applied&&latest.result?.diffs?.length?latest:null;renderMessages();renderProposalBanner();const recent=S.jobs.find(j=>['revise','repair'].includes(j.kind));if(!S.activeJob){if(recent&&['error','interrupted','cancelled'].includes(recent.status))renderProgress(recent);else $('#workspace-progress').innerHTML='';}}
function renderMessages(){if(!S.view)return;const task=S.view.task;let html=`<article class="message user"><div class="message-label">你 · 这次的目标</div><div class="message-body">${esc(task.brief)}</div></article>`;const ordered=[...S.jobs].reverse();let hasGeneration=false;for(const job of ordered){if(job.kind==='generate'){hasGeneration=true;if(job.status==='completed')html+=message('assistant','拾构',job.result.summary,job);}else{html+=message('user','你',job.user_message);if(job.status==='completed')html+=message('assistant','拾构',job.result.summary,job);else if(['error','interrupted','cancelled'].includes(job.status))html+=message('error','这次未改动成稿',job.error||'已取消',job);}}if(!hasGeneration)html+=message('assistant','拾构',task.source==='generated'?'这份成果已保存。可以继续告诉我哪里需要调整。':'这是一份已有内容。你可以直接编辑，也可以连接AI后用自然语言定向修改。');$('#conversation').innerHTML=html;$('#conversation').scrollTop=$('#conversation').scrollHeight;}
function message(kind,label,body,job){const tokens=(job?.result?.calls||[]).reduce((n,c)=>n+(c.usage?.total_tokens||0),0);return `<article class="message ${kind}"><div class="message-label">${esc(label)}</div><div class="message-body">${esc(body)}</div>${['revise','repair'].includes(job?.kind)&&(job.result?.diffs?.length||job.result?.quality_rounds?.length||job.result?.attempts?.length)?`<button class="proposal-open" data-proposal="${esc(job.id)}">${job.status!=='completed'?'查看检查记录':job.result.applied?'查看已采用的修改':'预览修改'} · ${job.result.diffs?.length||0} 处 ↗</button>`:''}${tokens?`<div class="message-meta">${esc(job.result.calls[0].model)} · ${tokens.toLocaleString()} tokens</div>`:''}</article>`;}
function renderProposalBanner(){const p=S.proposal;if(!p||!S.view){$('#proposal-banner').innerHTML='';return;}const stale=p.result.base_revision!==S.view.revision;$('#proposal-banner').innerHTML=`<div class="proposal-strip ${stale?'stale':''}"><span>${stale?'成稿已有更新；此草案仅供查看，请基于新版本重新生成。':`新的修改草案 · ${p.result.diffs.length} 处改动，当前成稿尚未变化。`}</span><div><button class="button-quiet" data-proposal="${esc(p.id)}">预览</button><button class="button-primary" data-apply-proposal="${esc(p.id)}" ${stale||!p.result.can_apply?'disabled':''}>采用修改</button></div></div>`;}
function showProposal(jid){const job=S.jobs.find(j=>j.id===jid);if(!job?.result)return;S.proposal=job;const r=job.result;$('#proposal-diff').innerHTML=`<p class="field-note">${esc(r.summary||'本次任务未完成，检查记录已保留。')}</p><p class="field-note">已记录 ${r.attempts?.length||r.calls?.length||0} 次请求；只有人工采用才会修改成稿。</p>${r.quality_rounds?qualityHTML(r.quality_rounds):''}${(r.diffs||[]).map(d=>`<article class="diff-block"><h3>${esc(d.title)}</h3><div class="diff-columns"><div class="diff-column"><div class="diff-label">当前成稿</div><div class="markdown">${markdown(d.before)}</div></div><div class="diff-column after"><div class="diff-label">AI 草案</div><div class="markdown">${markdown(d.after)}</div></div></div></article>`).join('')}`;const stale=r.base_revision!==S.view.revision;$('#proposal-validation').textContent=r.applied?'这次修改已采用':stale?'成稿已更新，此草案不能直接覆盖新版本':r.validation_message||(job.status==='completed'?'锁定与固定事实已通过结构检查，请确认内容是否符合你的要求。':'本次任务未完成，不能采用。');$('#apply-proposal-dialog').disabled=r.applied||stale||!r.can_apply;$('#proposal-dialog').showModal();}
async function applyProposal(jid){await api(`/api/ai/jobs/${jid}/apply`,{revision:S.view.revision});if($('#proposal-dialog').open)$('#proposal-dialog').close();await refreshDocument();await loadHistory();toast('已采用修改，锁定内容保持不变；需要时可撤回。');}
async function mutate(kind,extra={}){await api(endpoint('/action'),{kind,revision:S.view.revision,...extra});await refreshDocument();await loadSessions();}
function progressHTML(job){const failed=['error','interrupted','cancelled'].includes(job.status);return `<div class="progress-card ${failed?'error':''}">${failed?'':`<span class="spinner"></span>`}<span>${esc(job.error||job.progress)}<br><small>长任务可切换页面，完成记录会保存在本机。</small></span>${['queued','running'].includes(job.status)?`<button data-cancel-job="${esc(job.id)}">取消</button>`:failed?`<button data-retry-job="${esc(job.id)}">重试</button>`:''}</div>`;}
function renderProgress(job){const target=job.kind==='generate'?'#home-progress':'#workspace-progress';$(target).innerHTML=progressHTML(job);}
function watch(jid){
  clearTimeout(pollTimer);S.activeJob=jid;
  async function poll(){
    try{
      const job=await api('/api/ai/jobs/'+jid);renderProgress(job);
      if(['queued','running'].includes(job.status)){pollTimer=setTimeout(poll,1000);return;}
      S.activeJob=null;$('#generate-goal').disabled=false;$('#send-revision').disabled=false;
      if(job.status==='completed'){
        if(job.kind==='generate'){
          if(!S.sid&&S.autoOpenJobId===jid)await openSession(job.result.session_id);
          else{await loadSessions();toast('新的定制成果已生成，可从左侧打开。');}
          $('#home-progress').innerHTML='';
        }else if(S.sid===job.session){$('#workspace-progress').innerHTML='';await loadHistory();if(!job.result.diffs?.length)toast(job.result.summary);renderSources();}
      }else{toast(job.error||'任务已取消，现有成稿未改动');if(S.sid===job.session){await loadHistory();renderSources();}}
    }catch(e){toast(e.message);S.activeJob=null;$('#generate-goal').disabled=false;$('#send-revision').disabled=false;}
  }
  poll();
}
async function generateGoal(){if(!(S.config?.ready??S.config?.key_configured)||!S.config.model){openSettings();toast('先配置你的模型接口，目标内容会保留。');return;}if(S.activeJob){toast('已有AI任务进行中，请等待或取消');return;}$('#generate-goal').disabled=true;try{await saveDraft();const job=await jobRequest('/api/ai/generate',{goal:$('#goal-input').value,task_type:S.taskType,facts:$('#goal-facts').value,materials:S.materials,detail_level:$('#detail-level').value,...(S.choiceCapable?{approaches:readDirections()}:{}),...(S.guidance?{guidance:S.guidance}:{})});S.autoOpenJobId=job.id;renderProgress(job);watch(job.id);}catch(e){$('#generate-goal').disabled=false;throw e;}}
async function submitRevision(){
  if(!revisionChannel?.ready||revisionChannel.path!==endpoint('/ai/draft')){toast('请先重新打开任务，读取已保存的修改要求');return;}
  if(!(S.config?.ready??S.config?.key_configured)||!S.config.model){openSettings();return;}
  if(S.activeJob){toast('已有AI任务进行中，请等待或取消');return;}
  const instruction=$('#revision-input').value.trim(),scope=$('#revision-scope').value;
  if(instruction.length<2){toast('告诉我这次要怎样修改');return;}
  if($('#revision-scope').selectedOptions[0]?.disabled){toast('这个章节已锁定，请选择其他范围或先解锁');return;}
  const submitted=JSON.stringify(revisionDraft());await saveChannel(revisionChannel);
  const job=await jobRequest(endpoint('/ai/revise'),{revision:S.view.revision,instruction,scope:scope==='all'?null:[scope]});
  $('#send-revision').disabled=true;renderProgress(job);watch(job.id);
  if(JSON.stringify(revisionDraft())===submitted){$('#revision-input').value='';saveChannel(revisionChannel).catch(error=>toast(error.message));}
  await loadHistory();
}
function openSettings(){const config=S.config||{};applyConnectionFields(config);populateConnectionProfiles();$('#personal-preferences').value=config.preferences||'';$('#settings-feedback').classList.add('hidden');$('#settings-dialog').showModal();}
function settingsFeedback(text,error=false){$('#settings-feedback').textContent=text;$('#settings-feedback').classList.remove('hidden');$('#settings-feedback').classList.toggle('error',error);}
function materialChips(){ $('#material-chips').innerHTML=S.materials.map((m,i)=>`<span class="material-chip">▤ ${esc(m.name)} · ${m.text.length.toLocaleString()} 字<button type="button" data-remove-material="${i}" aria-label="移除素材">×</button></span>`).join('');}
async function showPreference(){const {offer}=await api(endpoint('/offer'),{revision:S.view.revision});S.offer=offer;if(!offer){toast('当前约束下没有可比较的未锁定版本。可先采用合格组合，或核对条件与锁定范围。');return;}if(offer.comparison_kind==='whole_plan'){showWholePreference(offer);return;}const block=S.view.task.blocks.find(b=>b.id===offer.block);const evaluationOnly=offer.response_mode==='evaluate_only';const background=offer.alternative_context?`<article class="source-card"><h3>这次诊断采用以下共同背景</h3>${S.view.task.blocks.filter(b=>b.id!==block.id).map(b=>`<h4>${esc(b.title)}</h4><div class="markdown">${markdown(text(variant(b,offer.a)))}</div>`).join('')}</article>`:'';$('#preference-content').innerHTML=`<p class="field-note">比较「${esc(block.title)}」。${evaluationOnly?'只记录此次评价，成稿保持不变。':'其他内容保持相同，选择后采用这一段。'}只有这次明确比较形成偏好标签。</p>${background}<div class="diff-columns">${['a','b'].map(k=>`<article class="diff-column ${k==='b'?'after':''}"><div class="diff-label">${k.toUpperCase()}</div><div class="markdown">${markdown(text(variant(block,offer[k])))}</div><button class="button-primary" data-preference-choice="${k}">这版更适合我</button></article>`).join('')}</div>`;$('#preference-content').insertAdjacentHTML('afterbegin',preferenceReasonsHTML());$('#preference-dialog').showModal();}
let evidenceBlock=null;
function toggleFocus(value){const active=value??!document.body.classList.contains('focus-mode');document.body.classList.toggle('focus-mode',active);$('#toggle-focus').setAttribute('aria-pressed',String(active));$('#toggle-focus').innerHTML=`<i data-lucide="${active?'panel-left-open':'panel-left-close'}" aria-hidden="true"></i><span>${active?'继续编辑':'专注阅读'}</span>`;try{localStorage.setItem('intent-studio-focus',String(active));}catch{}}
function showEvidence(block){evidenceBlock=block;$('#evidence-filter').value='all';renderEvidence();$('#evidence-dialog').showModal();}
function renderEvidence(){
  const report=S.delivery?.evidence,section=report?.sections.find(s=>s.block===evidenceBlock);if(!section){$('#evidence-content').textContent='当前服务尚未加载来源对照，请刷新后重新打开任务。';return;}
  $('#evidence-context').textContent=section.title+' · 稿件 v'+report.revision;
  $('#evidence-summary').textContent=section.review_items?`${section.review_items} 项需要你核对`:'未发现本规则内的待核对项';
  const sourceNames={goal:'目标说明'},byId=Object.fromEntries(section.sources.map(s=>[s.id,s]));
  const statusName={current:'当前素材',unknown:'未记录的引用',removed:'素材已移除',changed:'原文与当前素材不一致'};
  const filtered=section.paragraphs.filter(p=>$('#evidence-filter').value!=='review'||p.literals.some(c=>c.status!=='literal_present')||p.source_ids.some(id=>byId[id]?.status!=='current'));
  $('#evidence-content').innerHTML=filtered.map(p=>`<article class="evidence-paragraph"><div class="evidence-line">第 ${p.line} 行</div><div class="evidence-prose">${esc(p.text)}</div>${p.literals.length?`<div class="literal-list">${p.literals.map(c=>`<div><span>${esc(c.text)}</span><span>${c.status==='literal_present'?'有相同文字':c.status==='not_found'?'引用原文未找到':'没有可对照的引用'}</span><span>${c.matches.map(id=>esc(sourceNames[id]||(id.startsWith('fact:')?'固定条件':id))).join('、')||'待人工核对'}</span></div>`).join('')}</div>`:''}${p.source_ids.map(id=>{const s=byId[id];return `<details class="evidence-source"><summary>${esc(id)} · ${esc(s.name)}<span>${statusName[s.status]}</span></summary><p>${esc(s.text||'没有记录这份原文，无法还原依据。')}</p></details>`;}).join('')}</article>`).join('')||'<p class="empty-note">本次筛选下没有可展示的数字、引号措辞或引用。仍需通读和核对其他内容。</p>';
}
document.addEventListener('click',e=>{const button=e.target.closest('button');if(!button)return;
  if(button.dataset.evidence){showEvidence(button.dataset.evidence);return;}
  if(button.dataset.close){$('#'+button.dataset.close).close();return;}
  if(button.dataset.session)run(()=>openSession(button.dataset.session));
  else if(button.dataset.type){changeChoiceTaskType(button.dataset.type);document.querySelectorAll('[data-type]').forEach(b=>b.classList.toggle('active',b.dataset.type===S.taskType));scheduleDraft();}
  else if(button.dataset.tab)activateTab(button.dataset.tab);
  else if(button.dataset.lock)run(()=>mutate('lock',{block:button.dataset.lock}));
  else if(button.dataset.variant)run(()=>mutate('select',{block:button.dataset.block,variant:button.dataset.variant}));
  else if(button.dataset.candidate!==undefined)run(async()=>{await mutate('apply',{combo:comboForCandidate(Number(button.dataset.candidate))});activateTab('document');toast('已切换方案，锁定部分保留');});
  else if(button.dataset.edit){const b=S.view.task.blocks.find(b=>b.id===button.dataset.edit);S.editing=b.id;$('#edit-section-title').textContent='编辑章节';$('#section-edit-name').value=b.title;$('#section-edit-text').value=variant(b).template;$('#edit-section-dialog').showModal();}
  else if(button.dataset.rewrite){$('#revision-scope').value=button.dataset.rewrite;$('#revision-input').value='请在保留固定事实的前提下，把这一部分写得更具体、更可执行。';scheduleRevisionDraft();$('#revision-input').focus();if(innerWidth<741)$('#revision-form').scrollIntoView({behavior:'smooth'});}
  else if(button.dataset.prompt){$('#revision-input').value=button.dataset.prompt;scheduleRevisionDraft();$('#revision-input').focus();}
  else if(button.dataset.proposal)showProposal(button.dataset.proposal);
  else if(button.dataset.applyProposal)run(()=>applyProposal(button.dataset.applyProposal));
  else if(button.dataset.cancelJob)run(async()=>{await api('/api/ai/jobs/'+button.dataset.cancelJob+'/cancel',{});toast('已请求取消；正在执行的上游请求可能仍会计费。');});
  else if(button.dataset.removeMaterial!==undefined){S.materials.splice(Number(button.dataset.removeMaterial),1);materialChips();scheduleDraft();}
  else if(button.id==='manage-materials')run(openMaterials);
  else if(button.id==='reload-materials')run(openMaterials);
  else if(button.id==='save-materials')run(async()=>{await api(endpoint('/ai/materials'),{revision:S.libraryRevision,materials:collectMaterials()});$('#materials-dialog').close();await refreshDocument();toast('素材已保存。告诉 AI 如何使用新资料，现有正文保持原样。');});
  else if(button.dataset.removeLibrary!==undefined){S.materialDraft=collectMaterials();S.materialDraft.splice(Number(button.dataset.removeLibrary),1);renderMaterialEditors();}
  else if(button.dataset.retryJob)run(async()=>{if(S.activeJob)throw new Error('请等待当前AI任务结束');const job=await jobRequest('/api/ai/jobs/'+button.dataset.retryJob+'/retry',{revision:S.view?.revision});if(job.kind==='generate')S.autoOpenJobId=job.id;renderProgress(job);watch(job.id);});
  else if(button.dataset.source){activateTab('sources');const card=Array.from(document.querySelectorAll('[data-source-card]')).find(c=>c.dataset.sourceCard===button.dataset.source);if(card){card.classList.add('highlight');card.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>card.classList.remove('highlight'),3000);}}
  else if(button.id==='ask-preference')run(showPreference);
  else if(button.id==='compare-studio-learning')run(showPreference);
  else if(button.id==='save-studio-learning')run(async()=>{if(['semantic_deep','semantic_linear'].includes($('#studio-learning-model').value)){const r=S.view.learning.runs.find(r=>r.compatible);if(!r)throw new Error('请先训练与当前反馈一致的本地模型');await mutate('learning_activate',{run:r.id,model_kind:$('#studio-learning-model').value});toast('已启用本地训练版本中的推荐模型');return;}const old=S.view.state.research||{};await mutate('research_config',{config:{model:$('#studio-learning-model').value,policy:old.policy||'uncertainty',context_mode:old.context_mode||'current',budget:old.budget??16,seed:old.seed??11,evaluate_only:old.evaluate_only??true,data_origin:old.data_origin||'unclassified',participant_id:old.participant_id||''}});toast('已保存；历史反馈仍对应原文字，新文字仅获得预测');});
  else if(button.id==='view-conditions')activateTab('sources');
  else if(button.id==='fork-goal')run(async()=>{const task=S.view.task;await setHome();$('#goal-input').value=task.brief;$('#goal-facts').value=Object.entries(task.facts).map(([k,v])=>`${k}=${v}`).join('\n');$('.goal-constraints').open=true;$('#goal-input').focus();scheduleDraft();});
  else if(button.id==='apply-preference-rank')run(async()=>{await mutate('apply',{combo:S.view.ranking[0].combo});activateTab('document');toast('已采用符合约束的偏好推荐');});
  else if(button.id==='apply-verified-combo')run(async()=>{await mutate('apply',{combo:S.view.ranking[0].combo});activateTab('document');toast('已采用满足机器条件的组合，请继续核对内容。');});
  else if(button.id==='repair-acceptance')run(repairAcceptance);
  else if(button.dataset.preferenceChoice)run(async()=>{const mode=S.offer.response_mode;await mutate('compare',{offer:S.offer.id,choice:button.dataset.preferenceChoice,...explicitPreferenceReasons()});$('#preference-dialog').close();toast(mode==='evaluate_only'?'已记录偏好，成稿没有改变。':'已记录这次真实比较并应用选择。');activateTab('candidates');});
  else if(button.dataset.example){const examples={project:'我会一点Python，想在四周内做出能展示的校园失物招领项目。请帮我明确真实用户、最小功能、技术路线、每周实施任务与验收方式，避免功能堆砌。',study:'我想用自己的课程资料制定两周复习计划。请按知识点、每天练习和自测标准组织，标明需要补充的信息。',writing:'我要向一个潜在合作伙伴介绍自己的项目。请从已有素材提炼核心价值、当前进展和合作诉求，给出能直接使用的完整表达。'};$('#goal-input').value=examples[button.dataset.example];$('#goal-input').focus();scheduleDraft();}
});
$('#session-search').oninput=renderSessions;
$('#toggle-focus').onclick=()=>toggleFocus();
$('#evidence-filter').onchange=renderEvidence;
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){if(document.querySelector('dialog[open]'))return;event.preventDefault();$('#navigation').classList.add('open');$('#session-search').focus();$('#session-search').select();}if(event.key==='Escape'&&!document.querySelector('dialog[open]')){$('#navigation').classList.remove('open');if(document.body.classList.contains('focus-mode'))toggleFocus(false);}});
$('#new-goal').onclick=()=>run(setHome);$('#open-settings').onclick=openSettings;$('#nav-settings').onclick=openSettings;
$('#mobile-menu').onclick=()=>$('#navigation').classList.toggle('open');
$('#goal-form').onsubmit=e=>{e.preventDefault();run(generateGoal);};
$('#revision-form').onsubmit=e=>{e.preventDefault();run(submitRevision);};
$('#revision-input').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();run(submitRevision);}};
$('#show-brief').onclick=()=>activateTab('sources');
$('#undo-studio').onclick=()=>run(async()=>{await mutate('undo');await loadHistory();toast('已撤回上一步');});
$('#apply-proposal-dialog').onclick=()=>run(()=>applyProposal(S.proposal.id));
$('#settings-form').onsubmit=e=>{e.preventDefault();run(()=>saveConnection(true));};
$('#clear-api-key').onclick=()=>run(async()=>{await api('/api/ai/config',{base_url:$('#base-url-input').value.trim(),clear_key:true});await loadConfig();applyConnectionFields(S.config);populateConnectionProfiles();settingsFeedback(S.config.key_configured?'此接口环境变量仍提供Key；本地保存的Key已移除。':'已移除此接口本地保存的加密Key。');});
async function readMaterials(files,previous){
  const materials=structuredClone(previous);
  for(const file of files){
    if(materials.length>=10)throw new Error('最多附加10份文本素材');
    if(!/\.(txt|md|json)$/i.test(file.name))throw new Error('请添加 TXT、MD 或 JSON 文本文件');
    if(file.size>160000)throw new Error('单份文件请小于160KB');
    const buffer=await file.arrayBuffer(),bytes=new Uint8Array(buffer);let contents;
    if(bytes[0]===255&&bytes[1]===254)contents=new TextDecoder('utf-16le').decode(buffer);
    else if(bytes[0]===254&&bytes[1]===255)contents=new TextDecoder('utf-16be').decode(buffer);
    else{try{contents=new TextDecoder('utf-8',{fatal:true}).decode(buffer);}catch{contents=new TextDecoder('gb18030').decode(buffer);}}
    contents=contents.replace(/^\uFEFF/,'');
    if(contents.length>40000)throw new Error('单份素材最多4万字');
    if(materials.reduce((n,m)=>n+m.text.length,0)+contents.length>100000)throw new Error('素材总计最多10万字');
    materials.push({name:file.name,text:contents});
  }
  return materials;
}
$('#material-files').onchange=()=>run(async()=>{S.materials=await readMaterials($('#material-files').files,S.materials);$('#material-files').value='';materialChips();scheduleDraft();});
$('#workspace-material-files').onchange=()=>run(async()=>{S.materialDraft=await readMaterials($('#workspace-material-files').files,collectMaterials());$('#workspace-material-files').value='';renderMaterialEditors();});
$('#section-edit-form').onsubmit=e=>{e.preventDefault();run(async()=>{const blocks=structuredClone(S.view.task.blocks);const block=blocks.find(b=>b.id===S.editing);block.title=$('#section-edit-name').value.trim();block.variants.find(v=>v.id===S.view.state.combo[block.id]).template=$('#section-edit-text').value;await mutate('edit',{blocks});$('#edit-section-dialog').close();toast('已保存新版本，旧内容保留在历史中');});};
async function exportArtifact(format){const result=await api(endpoint('/ai/export'),{revision:S.view.revision,format});$('#export-result').innerHTML=`<a href="${esc(result.url)}" download="${esc(result.filename)}">下载${format==='zip'?'交付包':'成品'} ↓</a><span id="export-file-path">已保存到 D 盘：${esc(result.path)}</span>`;$('#export-result').classList.remove('hidden');toast('已导出；交付包包含正文、素材原文与检查记录');}
$('#export-md').onclick=()=>run(()=>exportArtifact(S.view.task.category==='writing'?'txt':'md'));$('#export-bundle').onclick=()=>run(()=>exportArtifact('zip'));
const requestIds=new Map();
async function jobRequest(path,data){const key=JSON.stringify({path,data});if(!requestIds.has(key))requestIds.set(key,crypto.randomUUID());try{const result=await api(path,{...data,request_id:requestIds.get(key)});requestIds.delete(key);return result;}catch(error){if(error.status)requestIds.delete(key);throw error;}}
function homeDraft(){return {...(S.guidance?{guidance:S.guidance}:{}),goal:$('#goal-input').value,facts:$('#goal-facts').value,materials:S.materials,task_type:S.taskType,detail_level:$('#detail-level').value,approaches:readDirections()};}
function revisionDraft(){return {instruction:$('#revision-input').value,scope:$('#revision-scope').value};}
function restoreScope(scope){if(Array.from($('#revision-scope').options).some(o=>o.value===scope))$('#revision-scope').value=scope;}
function applyHomeDraft(value){S.guidance=value.guidance||null;$('#goal-input').value=value.goal||'';$('#goal-facts').value=value.facts||'';S.materials=value.materials||[];S.taskType=value.task_type||'auto';$('#detail-level').value=value.detail_level||'complete';renderDirections(value.approaches||defaultDirections(S.taskType));document.querySelectorAll('[data-type]').forEach(b=>b.classList.toggle('active',b.dataset.type===S.taskType));materialChips();renderGuidanceSummary();}
function applyRevisionDraft(value){$('#revision-input').value=value.instruction||'';restoreScope(value.scope||'all');}
function makeChannel(path,status,read,apply){return {path,status,read,apply,revision:0,last:'',ready:false,conflict:false,queue:Promise.resolve(),timer:null};}
const homeChannel=makeChannel('/api/ai/draft','#draft-status',homeDraft,applyHomeDraft);
let revisionChannel=null,conflictChannel=null,conflictRemote=null;
function draftStatus(channel,message,action){const el=$(channel.status);el.replaceChildren(document.createTextNode(message));if(action){const button=document.createElement('button');button.type='button';button.className='draft-recovery';button.textContent=action;button.onclick=()=>run(()=>channel.conflict?showDraftConflict(channel):saveChannel(channel));el.append(button);}}
function conflictError(){const error=new Error('草稿在另一窗口有更新，请先比较两份草稿');error.draftConflict=true;return error;}
function scheduleChannel(channel){if(!channel?.ready)return;clearTimeout(channel.timer);if(channel.conflict)return;draftStatus(channel,'草稿保存中…');channel.timer=setTimeout(()=>saveChannel(channel).catch(error=>toast(error.message)),500);}
function scheduleDraft(){scheduleChannel(homeChannel);}
function scheduleRevisionDraft(){scheduleChannel(revisionChannel);}
function saveDraft(){return saveChannel(homeChannel);}
function saveChannel(channel){
  if(!channel?.ready)return Promise.resolve();clearTimeout(channel.timer);
  channel.queue=channel.queue.catch(()=>{}).then(async()=>{
    if(channel.conflict)throw conflictError();
    const value=structuredClone(channel.read()),serialized=JSON.stringify(value);
    if(serialized!==channel.last){try{const result=await api(channel.path,{revision:channel.revision,input:value});channel.revision=result.revision;channel.last=serialized;}catch(error){if(error.status===409){channel.conflict=true;error.draftConflict=true;draftStatus(channel,'另一窗口已更新，当前输入保留。','比较两份草稿');}else draftStatus(channel,'草稿未保存，请保持页面打开。','重新保存草稿');throw error;}}
    if(JSON.stringify(channel.read())===channel.last)draftStatus(channel,'已保存到 D 盘'+(channel===homeChannel?' · 目标与素材':' · 未提交的修改要求'));
    else scheduleChannel(channel);
  });return channel.queue;
}
async function loadChannel(channel){const draft=await api(channel.path);channel.revision=draft.revision;channel.apply(draft.input);channel.last=JSON.stringify(channel.read());channel.ready=true;draftStatus(channel,draft.revision?'已恢复保存在 D 盘的'+(channel===homeChannel?'目标草稿':'修改草稿'):'输入后自动保存到 D 盘');}
async function loadDraft(){await loadChannel(homeChannel);}
async function loadRevisionDraft(sid){revisionChannel=makeChannel('/api/sessions/'+sid+'/ai/draft','#revision-draft-status',revisionDraft,applyRevisionDraft);await loadChannel(revisionChannel);}
async function flushCurrentDraft(){await saveChannel(S.sid?revisionChannel:homeChannel);}
function describeDraft(value,revision){
  if(revision)return '修改范围：'+(Array.from($('#revision-scope').options).find(o=>o.value===(value.scope||'all'))?.textContent||'原章节')+'\n\n'+(value.instruction||'（没有修改要求）');
  return '需求卡：'+(value.guidance?JSON.stringify(value.guidance,null,2):'（未使用）')+'\n\n目标：'+(value.goal||'（空）')+'\n\n固定条件：'+(value.facts||'（无）')+'\n\n任务类型：'+({auto:'按目标定制',project:'项目方案',study:'学习规划',writing:'写作沟通',analysis:'分析决策'}[value.task_type]||'按目标定制')+'\n初稿：'+(value.detail_level==='quick'?'快速起点':'完整初稿')+'\n方案方向：'+(value.approaches||[]).map(d=>d.name+'：'+d.instruction).join('；')+'\n\n素材：\n'+(value.materials||[]).map(m=>m.name+'\n'+m.text).join('\n\n');
}
async function showDraftConflict(channel){clearTimeout(channel.timer);conflictChannel=channel;conflictRemote=await api(channel.path);$('#draft-conflict-local').textContent=describeDraft(channel.read(),channel!==homeChannel);$('#draft-conflict-remote').textContent=describeDraft(conflictRemote.input,channel!==homeChannel);$('#draft-conflict-version').textContent='另一窗口草稿 v'+conflictRemote.revision+'。选择后只改变草稿，不生成任务。';if(!$('#draft-conflict-dialog').open)$('#draft-conflict-dialog').showModal();}
$('#use-remote-draft').onclick=()=>run(async()=>{const c=conflictChannel;const latest=await api(c.path);if(latest.revision!==conflictRemote.revision){await showDraftConflict(c);toast('另一窗口又有更新，请重新核对');return;}c.apply(latest.input);c.revision=latest.revision;c.last=JSON.stringify(c.read());c.conflict=false;$('#draft-conflict-dialog').close();draftStatus(c,'已载入另一窗口的草稿');});
$('#use-local-draft').onclick=()=>run(async()=>{const c=conflictChannel;try{const value=structuredClone(c.read());const saved=await api(c.path,{revision:conflictRemote.revision,input:value});c.revision=saved.revision;c.last=JSON.stringify(value);c.conflict=false;$('#draft-conflict-dialog').close();draftStatus(c,'当前窗口的草稿已保存到 D 盘');}catch(error){if(error.status===409){error.draftConflict=true;await showDraftConflict(c);}throw error;}});
async function openMaterials(){const library=await api(endpoint('/ai/materials'));S.libraryRevision=library.revision;S.materialDraft=library.materials;renderMaterialEditors();if(!$('#materials-dialog').open)$('#materials-dialog').showModal();}
function collectMaterials(){return Array.from(document.querySelectorAll('.material-editor')).map((element,index)=>({...S.materialDraft[index],name:element.querySelector('input').value,text:element.querySelector('textarea').value}));}
function renderMaterialEditors(){$('#material-editors').innerHTML=S.materialDraft.map((m,index)=>`<article class="material-editor"><div><b>${esc(m.id||'新素材')}</b><button class="button-quiet" data-remove-library="${index}">移除</button></div><label>素材名称<input maxlength="150" value="${esc(m.name)}"></label><label>素材原文<textarea rows="5" maxlength="40000">${esc(m.text)}</textarea></label></article>`).join('')||'<p class="field-note">尚无素材。添加资料后，再让 AI 按要求更新成品。</p>';$('#materials-summary').textContent=`${S.materialDraft.length} / 10 份素材`;} 
$('#goal-input').insertAdjacentHTML('afterend','<div class="draft-options"><label>初稿完整度<select id="detail-level"><option value="complete">完整初稿 · 含实施细节与验收</option><option value="quick">快速起点 · 先确定方向</option></select></label></div>');
mountChoiceDirections();
mountJourney();
mountContextTrace();
$('#home-progress').insertAdjacentHTML('beforebegin','<p id="draft-status" class="field-note" role="status">正在读取目标草稿…</p>');
for(const selector of ['#goal-input','#goal-facts'])$(selector).addEventListener('input',scheduleDraft);
$('#detail-level').onchange=scheduleDraft;
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')flushCurrentDraft().catch(()=>{});});
$('#revision-input').addEventListener('input',scheduleRevisionDraft);
$('#revision-scope').addEventListener('change',scheduleRevisionDraft);
window.addEventListener('beforeunload',event=>{const c=S.sid?revisionChannel:homeChannel;if(c?.ready&&JSON.stringify(c.read())!==c.last){event.preventDefault();event.returnValue='';}});
document.addEventListener('change',event=>{if(event.target.dataset.review)run(async()=>{const checks=Object.fromEntries(Array.from(document.querySelectorAll('[data-review]')).map(input=>[input.dataset.review,input.checked]));try{await mutate('review',{checks});}catch(error){renderSources();throw error;}});});
try{if(localStorage.getItem('intent-studio-focus')==='true')toggleFocus(true);}catch{}
run(async()=>{await loadConfig();await loadDraft();await loadSessions();let saved;try{saved=localStorage.getItem('intent-studio-session');}catch{}if(saved){try{await openSession(saved);}catch(error){if(error.draftConflict)throw error;await setHome();await loadDraft();}}const {jobs}=await api('/api/ai/jobs');const pending=jobs.find(j=>['generate','revise','repair'].includes(j.kind)&&['queued','running'].includes(j.status));if(pending){if(!S.sid&&pending.kind==='generate')S.autoOpenJobId=pending.id;renderProgress(pending);watch(pending.id);}else if(!S.sid){const recent=jobs.find(j=>j.kind==='generate');if(recent&&['error','interrupted','cancelled'].includes(recent.status))renderProgress(recent);}});

document.addEventListener('submit',event=>{if(event.target.id==='acceptance-form'){event.preventDefault();run(confirmAcceptance);}});
