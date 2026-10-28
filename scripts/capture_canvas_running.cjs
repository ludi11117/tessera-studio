'use strict';
// Read-only verification of existing production and preview tasks; no generation.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{performance}=require('node:perf_hooks');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-canvas-capture';fs.mkdirSync(temp,{recursive:true});
let browser;
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
  const proof={result:'PASS',paidCalls:0,trainingCalls:0,services:[],dataUnchanged:true};
  for(const port of [8765,8766]){
    const base='http://127.0.0.1:'+port,page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],posts=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
    await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
    const api=async(url,data)=>{const res=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(res.ok,await res.clone().text());return res.json();};
    const health=await api('/api/health');assert(health.capabilities.includes('configuration-space-v1'));
    const sessions=await api('/api/sessions'),audits={},timings=[];
    for(const s of sessions.sessions){
      const audit=await api('/api/sessions/'+s.id+'/audit');delete audit.exported_at;audits[s.id]=audit;
      const t=performance.now(),d=await api('/api/sessions/'+s.id+'/decision',{revision:s.revision});
      timings.push({id:s.id,revision:s.revision,source:s.source,eligible:d.eligible,candidates:d.space.candidates.length,http_decision_ms:performance.now()-t,pairs:d.pair_count,model:d.model.model_id||d.model.version});
      assert.equal(d.space.candidates.length,d.eligible);assert(d.space.candidates.every(p=>p.combo));
    }
    const trained=timings.find(s=>s.pairs>0),warm=[];
    if(trained)for(let i=0;i<3;i++){const t=performance.now();await api('/api/sessions/'+trained.id+'/decision',{revision:trained.revision});warm.push(performance.now()-t);}
    await page.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));await page.goto(base);await page.waitForSelector('#try-choice-demo:not([hidden])');await page.locator('#try-choice-demo').click();
    await page.locator('[data-choice-mode=canvas]').click();await page.waitForSelector('.canvas-matrix');
    const before=posts.length;
    await page.locator('[data-canvas-block=intro][data-canvas-variant=intro-0]').click();
    await page.locator('#canvas-budget').selectOption('1');
    await page.locator('#canvas-plan').selectOption({index:0});
    assert.equal(posts.length,before,'Filtering must not POST');
    if(port===8765){
      await page.locator('#toggle-focus').click();await page.evaluate(()=>document.fonts.ready);
      await page.setViewportSize({width:1512,height:2600});await page.locator('.artifact-pane').evaluate(el=>el.scrollTop=0);
      await page.locator('.configuration-card').screenshot({path:path.join(root,'docs/screenshots/canvas-running-card.png')});
      await page.setViewportSize({width:1512,height:1100});
      await page.locator('[data-choice-mode=canvas]').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'docs/screenshots/canvas-running-desktop.png'),fullPage:false});
      await page.setViewportSize({width:390,height:1000});await page.locator('[data-choice-mode=canvas]').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'docs/screenshots/canvas-running-mobile.png'),fullPage:false});
      await page.setViewportSize({width:1512,height:1100});await page.locator('#new-goal').click();await page.locator('#try-learning-demo').click();
      await page.locator('[data-choice-mode=canvas]').click();await page.waitForSelector('.canvas-matrix');
      assert((await page.locator('.canvas-selection').innerText()).includes('偏好分相差'));
      await page.setViewportSize({width:1512,height:2600});await page.locator('.artifact-pane').evaluate(el=>el.scrollTop=0);
      await page.locator('.configuration-card').screenshot({path:path.join(root,'docs/screenshots/canvas-running-trained.png')});
    }
    for(const s of sessions.sessions){const after=await api('/api/sessions/'+s.id+'/audit');delete after.exported_at;assert.deepEqual(after,audits[s.id]);}
    assert.deepEqual(await api('/api/sessions'),sessions);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    assert(posts.every(p=>!/(generate|revise|repair|train|action|options)$/.test(p)),JSON.stringify(posts));
    proof.services.push({health,timings,trainedRepeatHttpMs:warm,canvasFilterPosts:0,originalSessionsUnchanged:true});await page.close();
  }
  fs.writeFileSync(path.join(root,'docs/validation/canvas-running.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
