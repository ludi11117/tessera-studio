'use strict';
const DEFAULT_ENDPOINT='https://api.siliconflow.cn/v1';
function connectionBody(){return {base_url:$('#base-url-input').value.trim(),api_key:$('#api-key-input').value,model:$('#model-input').value.trim(),preferences:$('#personal-preferences').value,stream:$('#provider-stream').checked,json_mode:$('#provider-json').checked,send_temperature:$('#provider-temperature').checked,token_parameter:$('#provider-token-parameter').value};}
function applyConnectionFields(config){
  $('#base-url-input').value=config.base_url||DEFAULT_ENDPOINT;$('#model-input').value=config.model||'';$('#api-key-input').value='';
  $('#provider-stream').checked=config.stream??true;$('#provider-json').checked=config.json_mode??false;$('#provider-temperature').checked=config.send_temperature??true;$('#provider-token-parameter').value=config.token_parameter||'max_tokens';
  $('#credential-status').textContent=config.key_configured?'此接口已配置Key':isLocalConnection(config.base_url)?'本机接口 · Key可选':'此接口未配置Key';
  $('#available-models').replaceChildren();S.modelCatalog=null;renderModelCatalog();updateConnectionDestination();
}
function isLocalConnection(value){try{return ['localhost','127.0.0.1','[::1]'].includes(new URL(value).hostname);}catch{return false;}}
function updateConnectionDestination(){
  const value=$('#base-url-input').value.trim(),profile=(S.config?.profiles||[]).find(p=>p.base_url===value.replace(/\/$/,''));
  $('#connection-destination').textContent='生成与AI修正时，目标和相关素材将发送至：'+(value||'请填写的接口地址')+'。本地偏好训练不使用这个接口。';
  $('#endpoint-key-note').textContent=profile?.key_configured?'此地址已有独立保存的Key；留空可保留。':'为此地址单独填写Key；不会复用其他服务的Key。'+(isLocalConnection(value)?'本机无鉴权服务可留空。':'');
}
function populateConnectionProfiles(){
  const profiles=S.config?.profiles||[];
  $('#connection-preset').innerHTML='<option value="siliconflow">硅基流动</option><option value="local">本机兼容服务</option><option value="custom">自定义兼容接口</option>'+profiles.filter(p=>p.base_url!==DEFAULT_ENDPOINT).map(p=>`<option value="${esc(p.base_url)}">已保存 · ${esc(p.base_url)}</option>`).join('');
  $('#connection-preset').value=S.config.base_url===DEFAULT_ENDPOINT?'siliconflow':profiles.some(p=>p.base_url===S.config.base_url)?S.config.base_url:'custom';
}
async function saveConnection(test){
  const button=test?$('#save-ai-settings'):$('#save-connection-only');button.disabled=true;
  try{
    const body=connectionBody();S.config=await api('/api/ai/config',body);$('#api-key-input').value='';await loadConfig();
    if(test){
      const connected=await api('/api/ai/connect',{});S.config=connected.config;
      $('#available-models').innerHTML=connected.models.map(m=>`<option value="${esc(m)}"></option>`).join('');
      S.modelCatalog={endpoint:S.config.base_url,models:connected.models};$('#model-catalog-search').value='';renderModelCatalog();
      $('#model-input').value=S.config.model;await loadConfig();
      settingsFeedback(`连接正常 · 接口可达，读取到 ${connected.models.length} 个模型。当前：${S.config.model||'请手动选择模型'}。尚未调用生成，不代表模型已通过成品验收。`);
    }else settingsFeedback('连接配置已保存。没有发送模型请求；生成前请确认接口和模型名。');
    $('#credential-status').textContent=S.config.key_configured?'此接口已配置Key':S.config.local_endpoint?'本机接口 · Key可选':'此接口未配置Key';populateConnectionProfiles();updateConnectionDestination();
  }catch(e){$('#api-key-input').value='';await loadConfig();settingsFeedback(e.message+(S.config.preview_mode?'':'。模型名可手动填写；不会自动尝试其他服务。'),true);}
  finally{button.disabled=false;}
}
document.addEventListener('change',event=>{if(event.target.id==='connection-preset'){
  const selection=event.target.value,url=selection==='siliconflow'?DEFAULT_ENDPOINT:selection==='local'?'http://127.0.0.1:11434/v1':selection==='custom'?'':selection;
  const saved=(S.config.profiles||[]).find(p=>p.base_url===url);
  applyConnectionFields(saved||{base_url:url,stream:true,json_mode:selection==='siliconflow'});
  if(selection==='custom'){$('#base-url-input').value='';$('#base-url-input').focus();updateConnectionDestination();}
}});
document.addEventListener('input',event=>{if(event.target.id==='base-url-input'){
  $('#api-key-input').value='';$('#credential-status').textContent='以保存后的接口配置为准';$('#available-models').replaceChildren();S.modelCatalog=null;renderModelCatalog();updateConnectionDestination();
}});
document.addEventListener('click',event=>{const b=event.target.closest('button');if(b?.id==='save-connection-only')run(()=>saveConnection(false));});

function renderModelCatalog(){
  const host=$('#model-catalog-results');if(!host)return;
  const catalog=S.modelCatalog,query=$('#model-catalog-search').value.trim().toLocaleLowerCase();
  const matches=(catalog?.models||[]).filter(m=>m.toLocaleLowerCase().includes(query));
  $('#model-catalog-count').textContent=catalog?`${matches.length} / ${catalog.models.length} 个匹配 · 仅筛选已读取的列表`:'先点击“保存并读取模型”，也可以直接手动填写模型名。';
  host.innerHTML=matches.slice(0,60).map(m=>`<button type="button" data-catalog-model="${esc(m)}" aria-pressed="${$('#model-input').value===m}"><span>${esc(m)}</span><i data-lucide="plus" aria-hidden="true"></i></button>`).join('')+(matches.length>60?'<p>先显示60项，请输入更多关键词缩小范围。</p>':catalog&&!matches.length?'<p>列表里没有匹配项，仍可手动填写；这不代表模型不可用。</p>':'');
}
document.addEventListener('input',event=>{if(['model-catalog-search','model-input'].includes(event.target.id))renderModelCatalog();});
document.addEventListener('click',event=>{const b=event.target.closest('[data-catalog-model]');if(!b)return;$('#model-input').value=b.dataset.catalogModel;renderModelCatalog();$('#model-catalog-count').textContent='已填入模型名，点击保存才生效；没有发送生成请求。';});
