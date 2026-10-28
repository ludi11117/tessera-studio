const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),stamp=String(Date.now()),qa='D:/CodexWork/temp/intent-acceptance-browser/'+stamp;
fs.mkdirSync(qa,{recursive:true});
const env={...process.env,TEMP:qa,TMP:qa,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(process.env.INTENT_PYTHON||path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(qa,'qa.sqlite3'),'--port','18773'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
const base='http://127.0.0.1:18773';let output='',browser;
child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);
async function api(url,data){const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  await page.locator('#goal-input').fill('编写一份本地项目实施方案，必须保留未确认安排，并按资料核对。');
  await page.locator('#generate-goal').click();await page.waitForSelector('.document-section');await page.waitForFunction(()=>!document.querySelector('#send-revision').disabled);
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session'));
  const before=await api('/api/sessions/'+sid);await page.locator('[data-lock=section1]').click();
  await page.waitForFunction(()=>document.querySelector('[data-lock=section1]').getAttribute('aria-pressed')==='true');
  await page.locator('[data-tab=sources]').first().click();await page.locator('#acceptance-required').fill('安排尚未确认');
  await page.locator('#acceptance-form button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.acceptance-panel h3').textContent.includes('本任务'));
  await page.reload();await page.waitForSelector('.document-section');await page.locator('[data-tab=sources]').first().click();
  assert.equal(await page.locator('#acceptance-required').inputValue(),'安排尚未确认');
  await page.locator('[data-tab=candidates]').first().click();assert((await page.locator('.optimization-report').innerText()).includes('当前候选中无解'));
  await page.locator('[data-tab=sources]').first().click();await page.locator('#repair-acceptance').click();
  await page.waitForSelector('.proposal-open',{timeout:15000});
  const frozen=await api('/api/sessions/'+sid);assert.equal(frozen.text,before.text);
  const jobs=(await api('/api/sessions/'+sid+'/ai/history')).jobs,job=jobs.find(j=>j.kind==='repair');
  assert.equal(job.result.attempts.length,3);assert.equal(job.result.can_apply,true);assert.equal(frozen.pair_count,0);
  await page.locator('.proposal-open').click();await page.waitForSelector('#proposal-dialog[open]');
  await page.locator('#proposal-diff .quality-rounds summary').click();assert((await page.locator('#proposal-diff').innerText()).includes('复验'));
  const shotDir=path.join(root,'docs/screenshots');
  await page.screenshot({path:path.join(shotDir,'acceptance-loop-desktop.png'),fullPage:true});
  await page.locator('#apply-proposal-dialog').click();await page.waitForFunction(()=>document.querySelector('#conversation').textContent.includes('查看已采用'));
  const after=await api('/api/sessions/'+sid);assert.equal(after.pair_count,0);assert.deepEqual(after.state.locks,frozen.state.locks);
  assert.equal(after.task.blocks[0].variants[0].template,before.task.blocks[0].variants[0].template);
  await page.locator('[data-tab=sources]').first().click();assert((await page.locator('.acceptance-results').innerText()).includes('通过'));
  const widths=[];
  for(const width of [360,390,740,820,1024,1512]){
    await page.setViewportSize({width,height:1000});await page.evaluate(()=>document.fonts.ready);
    const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('#acceptance-required')).borderRadius}));
    assert(r.scroll<=r.width,JSON.stringify(r));assert.equal(r.radius,'16px');widths.push(r);
  }
  await page.setViewportSize({width:390,height:1000});await page.screenshot({path:path.join(shotDir,'acceptance-loop-mobile.png'),fullPage:true});
  const exported=await api('/api/sessions/'+sid+'/ai/export',{revision:after.revision,format:'zip'});assert(exported.path.startsWith('D:'));
  await page.locator('#undo-studio').click();await page.waitForFunction(()=>document.querySelector('.acceptance-results').textContent.includes('未通过'));
  assert.equal((await api('/api/sessions/'+sid)).text,before.text);
  assert.deepEqual(errors,[]);
  const result={result:'PASS',paidCalls:0,qaDatabase:qa,widths,checks:['confirm and persist contract','empty constrained search reports no solution','review-repair-review is a three-call proposal','protected section unchanged','no implicit preference labels','per-round evidence visible','adoption and undo','ZIP export','16px and 360–1512px layout']};
  fs.writeFileSync(path.join(root,'docs/validation/acceptance-browser-'+stamp+'.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
})().catch(e=>{console.error(e);console.error(output);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
