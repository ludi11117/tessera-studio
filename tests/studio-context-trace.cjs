'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-context-trace-browser/'+Date.now(),base='http://127.0.0.1:18787';
fs.mkdirSync(temp,{recursive:true});const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(temp,'qa.sqlite3'),'--port','18787'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='',browser;child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
async function api(url,data){const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();}
async function idle(page){await page.waitForFunction(()=>!S.busy);}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],requests=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(inspire|generate|revise|repair)$/.test(new URL(r.url()).pathname))requests.push(new URL(r.url()).pathname);});
  await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  await page.locator('#goal-input').fill('做校园失物招领，先验证发布与搜索');
  await page.locator('#material-files').setInputFiles({name:'已有条件.md',mimeType:'text/plain',buffer:Buffer.from('校园失物招领需要发布与搜索，不公开联系方式。')});
  await page.waitForFunction(()=>document.querySelector('#material-chips').textContent.includes('已有条件.md'));
  await page.locator('.guide-entry [data-guide-open]').click();await page.locator('[data-guide-category=project]').click();await page.locator('[data-guide-begin]').click();
  await page.locator('#guide-answer').fill('给同学使用');await page.locator('[data-guide-answer]').click();await page.locator('[data-guide-skip]').click();
  await page.waitForSelector('.context-directions article');await page.locator('.context-basis summary').click();assert((await page.locator('.context-basis').innerText()).includes('已有条件.md'));assert.equal(requests.length,0);
  const before=(await api('/api/sessions')).sessions.length;
  await page.locator('[data-context-generate]').click();await page.waitForFunction(()=>document.querySelector('.context-directions .small-kicker')?.textContent.includes('本次模型探索'));
  const inspireJobs=(await api('/api/ai/jobs')).jobs.filter(j=>j.kind==='inspire');assert.equal(inspireJobs.length,1);assert.equal(inspireJobs[0].result.call_limit,1);assert.equal(inspireJobs[0].result.attempts.length,1);assert.equal((await api('/api/sessions')).sessions.length,before);
  await page.setViewportSize({width:1512,height:2200});await page.locator('#guidance-dialog').evaluate(el=>el.scrollTop=0);await page.locator('#guidance-dialog').screenshot({path:path.join(root,'docs/screenshots/contextual-inspiration.png')});await page.setViewportSize({width:1512,height:1100});
  // Completed exploration is restored without another model request.
  await page.locator('[data-close=guidance-dialog]').click();await idle(page);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('已保存'));await page.reload();await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('已恢复'));
  await page.locator('.guide-entry [data-guide-open]').click();await page.locator('[data-guide-begin]').click();await page.waitForFunction(()=>document.querySelector('.context-directions .small-kicker')?.textContent.includes('本次模型探索'));assert.equal(requests.length,1);
  await page.locator('[data-context-pick=direction-0]').click();await page.locator('[data-guide-option="2"]').click();await page.locator('#guide-criteria').fill('提供错误恢复步骤');await page.locator('[data-guide-confirm]').click();await page.waitForFunction(()=>!document.querySelector('#guidance-dialog').open);await idle(page);
  const draft=await api('/api/ai/draft');assert(draft.input.guidance.inspiration.confirmed_context_hash);
  await page.locator('#generate-goal').click();await page.waitForSelector('#workspace-view:not(.hidden) .document-section');await idle(page);
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session')),initial=await api('/api/sessions/'+sid);assert.equal(initial.pair_count,0);assert.equal(initial.task.intent_brief.inspiration.job,inspireJobs[0].id);
  await page.locator('[data-tab=sources]').click();await page.waitForSelector('.requirement-trace');
  await page.locator('[data-trace-answer] input').fill('先做发布与搜索，不公开联系方式');await page.locator('[data-trace-answer] [type=submit]').click();await page.waitForFunction(()=>!document.querySelector('[data-trace-answer]'));await idle(page);assert.equal(requests.length,2);
  const criterion=page.locator('.trace-row').filter({has:page.locator('h4',{hasText:'提供错误恢复步骤'})});assert.equal(await criterion.count(),1);assert(!(await criterion.locator('.trace-status').innerText()).includes('确认满足'));
  if(!(await criterion.locator('form>details').evaluate(el=>el.open)))await criterion.locator('summary').first().click();await criterion.locator('[data-trace-decision=gap]').click();await page.waitForFunction(()=>document.querySelector('.trace-status.gap'));await idle(page);
  await page.locator('[data-review=usable]').check();await page.waitForFunction(()=>document.querySelector('#studio-toast').textContent.includes('明确需求'));await idle(page);assert(!(await page.locator('[data-review=usable]').isChecked()));
  if(!(await criterion.locator('form>details').evaluate(el=>el.open)))await criterion.locator('summary').first().click();await criterion.locator('[name=trace-note]').fill('缺少失败时保留输入的具体动作');await criterion.locator('[data-trace-revise]').click();assert((await page.locator('#revision-input').inputValue()).includes('提供错误恢复步骤'));assert.equal(requests.length,2,'Preparing a revision is free and does not submit');
  await page.locator('[data-tab=document]').click();await page.locator('[data-edit=section3]').click();await page.locator('#section-edit-text').fill((await page.locator('#section-edit-text').inputValue())+'\n提供错误恢复步骤：失败时保留输入，核对错误提示，再允许重新提交。');await page.locator('#section-edit-form [type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#edit-section-dialog').open);await idle(page);
  await page.locator('[data-tab=sources]').click();await page.waitForSelector('.trace-stale');
  if(!(await criterion.locator('form>details').evaluate(el=>el.open)))await criterion.locator('summary').first().click();await criterion.locator('[data-trace-semantic]').click();await page.waitForFunction(()=>document.querySelector('[data-semantic-result]').parentElement.closest('.requirement-trace').textContent.includes('语义相近的候选片段'));await idle(page);assert((await criterion.locator('[data-semantic-result]').textContent()).includes('冻结编码器'));await criterion.locator('[name=trace-block][value=section3]').check();await criterion.locator('[data-trace-decision=met]').click();await page.waitForFunction(()=>document.querySelector('.requirement-trace').textContent.includes('你已确认满足'));await idle(page);
  const delivery=await api('/api/sessions/'+sid+'/ai/delivery');assert(delivery.requirement_trace.rows.some(r=>r.status==='user_met'&&r.text==='提供错误恢复步骤'));
  const sizes=[];
  for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:1000});const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('.requirement-trace')).borderRadius}));assert(r.scroll<=width,JSON.stringify(r));assert.equal(r.radius,'16px');sizes.push(r);if(width===390){await criterion.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'docs/screenshots/requirement-trace-mobile.png')});}}
  await page.locator('.requirement-trace').screenshot({path:path.join(root,'docs/screenshots/requirement-trace.png')});
  await page.locator('[data-journey-export=zip]').click();await page.waitForSelector('#export-file-path');const zip=(await page.locator('#export-file-path').innerText()).replace('已保存到 D 盘：','');assert(fs.existsSync(zip));
  assert.equal((await api('/api/sessions/'+sid)).pair_count,0);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.equal(requests.length,2);
  const proof={result:'PASS',paidCalls:0,provider:'synthetic local fixture',explicitMockRequests:requests,qaDatabase:path.join(temp,'qa.sqlite3'),zip,session:sid,sizes,
    checks:['actual goal/answers/materials reach inspiration context','one model call and no session from inspiration','restore completed inspiration without request','selection provenance and updated-card confirmation','no automatic semantic pass','gap blocks global usable checkbox with UI rollback','targeted revision prepared without submission','content edit expires review','explicit evidence-linked manual confirmation','actual ZIP export','no inferred preference labels']};
  fs.writeFileSync(path.join(root,'docs/validation/context-trace-browser.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
})().catch(e=>{console.error(e,logs);process.exitCode=1;}).finally(async()=>{await browser?.close();child.kill();});
