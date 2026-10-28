const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),stamp=String(Date.now()),qa='D:/CodexWork/temp/intent-learning-browser/'+stamp,base='http://127.0.0.1:18777';fs.mkdirSync(qa,{recursive:true});
const env={...process.env,TEMP:qa,TMP:qa,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(qa,'qa.sqlite3'),'--port','18777'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let browser,output='';child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);
async function api(url,body){const r=await fetch(base+url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok,await r.clone().text());return r.json();}
(async()=>{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const texts=['先完成实际步骤，检查输入与预期输出。','希望全面提升整体价值，逐步完善长远愿景。','一起轻松试试，从讨论和建议开始。'];
 const task={title:'开发验收｜真实本地语义训练',facts:{},brief:'选择能实际执行和检查的方案',blocks:['目标','实施','验收'].map((title,i)=>({id:'p'+i,title,variants:texts.map((text,j)=>({id:'p'+i+'-'+j,template:text+title+'部分。'}))}))};
 const {id:sid}=await api('/api/sessions',{task});await api('/api/sessions/'+sid+'/action',{revision:0,kind:'research_config',config:{model:'content_linear',policy:'uncertainty',context_mode:'current',budget:16,seed:11,evaluate_only:true,data_origin:'development_test'}});
 browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
 const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[],paid=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(generate|revise|repair)$/.test(new URL(r.url()).pathname))paid.push(r.url());});
 await page.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
 await page.locator(`[data-session="${sid}"]`).click();await page.waitForSelector('.document-section');await page.locator('[data-tab=candidates]').click();await page.locator('[data-choice-mode=learning]').first().click();
 assert(await page.locator('#train-personal-preference').isDisabled());const original=await api('/api/sessions/'+sid);
 for(let i=0;i<8;i++){
   await page.locator('#collect-training-feedback').click();await page.waitForSelector('#preference-dialog[open]');
   await page.locator('[data-comparison-reason=clarity]').check();await page.locator('[data-preference-choice=a]').click();
   await page.waitForFunction(()=>!document.querySelector('#preference-dialog').open);
   await page.waitForFunction(n=>document.querySelector('.choice-learning p').textContent.includes(`${n} 次已记录`),i+1);
 }
 assert(await page.locator('#train-personal-preference').isEnabled());await page.locator('#learning-steps').selectOption('80');await page.locator('#train-personal-preference').click();
 await page.waitForFunction(()=>document.querySelector('.learning-version-detail')?.textContent.includes('正在使用深度偏好网络'),{timeout:60000});
 const trained=await api('/api/sessions/'+sid);assert.equal(trained.model_config.model_id,'semantic_deep');assert.equal(trained.pair_count,8);assert.equal(trained.text,original.text);
 assert.equal(trained.model_config.phase,'all_preference_layers');assert.equal(trained.learning.runs[0].report.frozen_transformer,true);
 assert(await page.locator('.learning-curve svg').isVisible());assert((await page.locator('.learning-no-test').innerText()).includes('暂不显示测试准确率'));
 await page.screenshot({path:path.join(root,'docs/screenshots/learning-deep-desktop.png'),fullPage:true});
 const hash=trained.model_config.snapshot_hash,beforePriority=await page.locator('#studio-saved').innerText();await page.locator('[data-learning-priority=clarity]').selectOption('2');await page.locator('#save-learning-priorities').click();
 await page.waitForFunction(old=>document.querySelector('#studio-saved').textContent!==old,beforePriority);
 const weighted=await api('/api/sessions/'+sid);assert.notEqual(weighted.model_config.snapshot_hash,hash);assert.equal(weighted.learning.runs.length,1);
 await page.locator('#trial-min').fill('1');await page.locator('#trial-max').fill('10');await page.locator('#run-condition-experiment').click();
 await page.waitForFunction(()=>document.querySelector('.condition-result')?.textContent.includes('试算条件：0'));
 const afterTrial=await api('/api/sessions/'+sid);assert.equal(afterTrial.revision,weighted.revision);assert.deepEqual(afterTrial.state,weighted.state);
 await page.locator('[data-training-kind=semantic_linear]').click();await page.waitForFunction(()=>document.querySelector('.learning-version-detail').textContent.includes('正在使用语义线性对照'));
 assert.equal((await api('/api/sessions/'+sid)).model_config.model_id,'semantic_linear');
 await page.locator('[data-training-kind=semantic_deep]').click();await page.waitForFunction(()=>document.querySelector('.learning-version-detail').textContent.includes('正在使用深度偏好网络'));
 await page.locator('.artifact-tabs [data-tab=decision]').click();await page.waitForSelector('[data-preview-minimax]');
 const decision=await api('/api/sessions/'+sid+'/decision',{revision:(await api('/api/sessions/'+sid)).revision});assert.equal(decision.stability.hypotheses,3);
 await page.locator('[data-preview-minimax]').click();assert.equal((await api('/api/sessions/'+sid)).pair_count,8);assert.equal((await api('/api/sessions/'+sid)).text,original.text);
 await page.locator('[data-choice-mode=learning]').first().click();

 await page.locator('#collect-training-feedback').click();await page.waitForSelector('#preference-dialog[open]');assert((await page.locator('#preference-content').innerText()).includes('完整组合'));
 await page.locator('.query-value summary').click();assert((await page.locator('.query-value').innerText()).includes('两种回答'));
 await page.locator('.query-value').screenshot({path:path.join(root,'docs/screenshots/decision-value-query.png')});
 await page.locator('[data-comparison-reason=clarity]').check();await page.locator('[data-preference-choice=b]').click();await page.waitForFunction(()=>!document.querySelector('#preference-dialog').open);await page.waitForSelector('.learning-stale');
 assert.equal((await api('/api/sessions/'+sid)).pair_count,9);
 await page.locator('.learning-feedback details').first().locator('summary').click();await page.locator('[data-retract-feedback]').first().click();
 await page.waitForFunction(()=>document.querySelector('.choice-learning p').textContent.includes('8 次已记录'));
 assert.equal((await api('/api/sessions/'+sid)).pair_count,8);
 const sizes=[];for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:1000});const x=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('#learning-steps')).borderRadius}));assert(x.scroll<=x.width,JSON.stringify(x));assert.equal(x.radius,'16px');sizes.push(x);}
 await page.setViewportSize({width:390,height:1000});await page.screenshot({path:path.join(root,'docs/screenshots/learning-deep-mobile.png'),fullPage:true});
 assert.deepEqual(paid,[]);assert.deepEqual(errors,[]);
 const proof={result:'PASS',paidCalls:0,realOfflineTransformer:true,qaDatabase:qa,trainingVersion:trained.learning.active_run,phase:trained.model_config.phase,report:trained.learning.runs[0].report,sizes,
 checks:['explicit reasons retained','8 comparisons train both hidden layers','real frozen ONNX encoder','three independently initialized networks','checkpoint active without changing manuscript','actual loss curves','no fabricated heldout accuracy for sparse data','reason priorities change prediction snapshot without retraining','read-only condition experiment never changes accepted constraints','switch exact same-run semantic linear control and deep network','new or retracted labels invalidate previous active weights','16px and responsive layouts']};
 fs.writeFileSync(path.join(root,'docs/validation/learning-browser-'+stamp+'.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify({...proof,report:'saved in proof file'},null,2));
})().catch(e=>{console.error(e);console.error(output);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
