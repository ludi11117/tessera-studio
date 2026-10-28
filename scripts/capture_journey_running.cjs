'use strict';
// Read-only production/preview check. Never opens editable intake or submits AI work.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-journey-capture';fs.mkdirSync(temp,{recursive:true});let browser;
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
  const proof={result:'PASS',paidCalls:0,newTrainingCalls:0,services:[]};
  for(const port of [8765,8766]){
    const base='http://127.0.0.1:'+port,request=async(url,data)=>{const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();};
    const health=await request('/api/health');assert(health.capabilities.includes('guided-intent-v1')&&health.capabilities.includes('preserved-fragments-v1'));
    const catalog=await request('/api/guidance');assert.equal(Object.keys(catalog.catalog).length,4);
    const sessions=await request('/api/sessions'),audits={};
    for(const s of sessions.sessions){const a=await request('/api/sessions/'+s.id+'/audit');delete a.exported_at;audits[s.id]=a;const d=await request('/api/sessions/'+s.id+'/decision',{revision:s.revision});assert.equal(d.eligible,d.space.candidates.length);}
    const page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],posts=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
    await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
    await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
    assert.equal(await page.locator('.home-heading [data-journey]').count(),4);assert(await page.locator('.guide-entry [data-guide-open]').isVisible());
    if(port===8765){await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(root,'docs/screenshots/journey-running-home.png'),fullPage:true});}
    await page.locator('#try-choice-demo').click();await page.locator('[data-tab=document]').click();assert.equal(await page.locator('[data-preserve]').count(),2);
    assert((await page.locator('#document-view .journey-steps').innerText()).includes('检查交付'));
    await page.locator('#document-view [data-journey=deliver]').click();assert(await page.locator('[data-journey-export=zip]').isVisible());
    for(const s of sessions.sessions){const a=await request('/api/sessions/'+s.id+'/audit');delete a.exported_at;assert.deepEqual(a,audits[s.id]);}
    assert.deepEqual(await request('/api/sessions'),sessions);assert.deepEqual(errors,[]);assert(posts.every(p=>!/(generate|revise|repair|train|action|draft)$/.test(p)),JSON.stringify(posts));
    proof.services.push({health,originalSessions:sessions.sessions.length,originalAuditsUnchanged:true,journeySteps:4,guidanceCategories:Object.keys(catalog.catalog),preserveButtons:2,mutatingPosts:0});await page.close();
  }
  fs.writeFileSync(path.join(root,'docs/validation/journey-running.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
