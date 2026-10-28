'use strict';
// Inspect existing services and original sessions without submitting edits or AI work.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/tessera-focused-capture';fs.mkdirSync(temp,{recursive:true});let browser;
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
  const proof={result:'PASS',paidCalls:0,newTrainingCalls:0,services:[]};
  for(const port of [8765,8766]){
    const base='http://127.0.0.1:'+port,get=async url=>{const r=await fetch(base+url);assert(r.ok,await r.clone().text());return r.json();};
    const health=await get('/api/health');assert(health.capabilities.includes('local-revision-v1'));
    const sessions=await get('/api/sessions'),audits={};
    for(const s of sessions.sessions){const a=await get('/api/sessions/'+s.id+'/audit');delete a.exported_at;audits[s.id]=a;}
    const page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],posts=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
    await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
    await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
    assert((await page.title()).includes('Tessera'));assert(await page.locator('body').evaluate(e=>e.classList.contains('guided-mode')));
    assert(!(await page.locator('.choice-directions').isVisible()));assert(await page.locator('#workspace-mode-toggle').isVisible());
    await page.evaluate(()=>document.fonts.ready);
    if(port===8765)await page.screenshot({path:path.join(root,'docs/screenshots/focused-running-home.png'),fullPage:true});
    let localButtons=0;
    if(sessions.sessions.length){
      await page.evaluate(id=>openSession(id),sessions.sessions[0].id);await page.waitForFunction(()=>!S.busy&&!!S.view);
      await page.evaluate(()=>activateTab('document'));
      localButtons=await page.locator('[data-local-open]').count();assert(localButtons>0);
      assert(await page.locator('#focused-next').isVisible());
      const radius=await page.locator('#focused-next').evaluate(e=>getComputedStyle(e).borderRadius);assert.equal(radius,'16px');
      await page.setViewportSize({width:390,height:844});assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
      if(port===8765)await page.screenshot({path:path.join(root,'docs/screenshots/focused-running-mobile.png')});
    }
    for(const s of sessions.sessions){const a=await get('/api/sessions/'+s.id+'/audit');delete a.exported_at;assert.deepEqual(a,audits[s.id]);}
    assert.deepEqual(await get('/api/sessions'),sessions);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    const mutating=posts.filter(p=>!p.endsWith('/decision'));assert.deepEqual(mutating,[]);
    proof.services.push({port,health,originalSessions:sessions.sessions.length,originalAuditsUnchanged:true,guidedDefault:true,localButtons,mutatingPosts:0});await page.close();
  }
  fs.writeFileSync(path.join(root,'docs/validation/focused-running.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
