// Read-only check of both actual services and original sessions. No model calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-v10-capture';fs.mkdirSync(temp,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
 try{
  const base='http://127.0.0.1:8765',page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[],external=[],paid=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/(generate|revise|repair|train)$/.test(new URL(r.url()).pathname))paid.push(r.url());});
  await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  const request=async(url,data)=>{const r=await page.request[data?'post':'get'](base+url,data?{data}:{});assert(r.ok(),await r.text());return r.json();};
  const health=await request('/api/health');assert.equal(health.version,'product-v10');assert.equal(health.database,path.join(root,'data/workbench.sqlite3'));
  const preview=await (await fetch('http://127.0.0.1:8766/api/health')).json();assert.equal(preview.version,'product-v10');assert.notEqual(preview.database,health.database);
  const before=await request('/api/sessions'),audits={},sessions=[];
  for(const s of before.sessions){
   const audit=await request('/api/sessions/'+s.id+'/audit');delete audit.exported_at;audits[s.id]=audit;
   const d=await request('/api/sessions/'+s.id+'/decision',{revision:s.revision});
   sessions.push({id:s.id,revision:s.revision,source:s.source,eligible:d.eligible,universe:d.universe,model:d.model.model_id||d.model.version,frontierPoints:d.frontier.length,feedback:d.pair_count,readOnly:d.read_only});
  }
  await page.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));await page.goto(base);await page.waitForSelector('#try-learning-demo:not([hidden])');await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-home.png'),fullPage:true});
  const homeSizes=[];for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:1000});const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(r.scroll<=r.width,JSON.stringify(r));homeSizes.push(r);}
  await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-home-mobile.png'),fullPage:false});
  await page.setViewportSize({width:1512,height:1060});await page.locator('#try-decision-demo').click();await page.waitForSelector('.decision-next');
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-decision.png'),fullPage:false});
  await page.locator('#decision-optimizer').screenshot({path:path.join(root,'docs/screenshots/product-v10-change-budget.png')});
  await page.locator('[data-decision-learning]').click();await page.waitForSelector('.learning-panel');
  await page.locator('#new-goal').click();await page.waitForSelector('#try-learning-demo');await page.locator('#try-learning-demo').click();await page.waitForSelector('.learning-version-detail');
  const trainingSid=await page.evaluate(()=>localStorage.getItem('intent-studio-session'));await page.locator('.artifact-tabs [data-tab=decision]').click();await page.waitForSelector('.decision-next');
  assert.equal(await page.locator('.decision-metrics strong').nth(2).innerText(),'8');
  await page.locator('#decision-optimizer').screenshot({path:path.join(root,'docs/screenshots/product-v10-learned-frontier.png')});
  await page.setViewportSize({width:390,height:900});await page.locator('.decision-heading').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-decision-mobile.png'),fullPage:false});
  await page.setViewportSize({width:1512,height:1060});await page.locator('#open-settings').click();await page.evaluate(()=>document.querySelector('.settings-scroll').scrollTop=0);
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-model-settings.png'),fullPage:false});
  await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-model-settings-mobile.png'),fullPage:false});
  for(const s of before.sessions){const after=await request('/api/sessions/'+s.id+'/audit');delete after.exported_at;assert.deepEqual(after,audits[s.id]);}
  assert.deepEqual(await request('/api/sessions'),before);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(paid,[]);
  const proof={result:'PASS',paidCalls:0,trainingCalls:0,externalRequests:0,health,preview,sessions,homeSizes,originalAuditRowsUnchanged:true,trainingDemo:trainingSid};
  fs.writeFileSync(path.join(root,'docs/validation/product-v10-running-proof.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
