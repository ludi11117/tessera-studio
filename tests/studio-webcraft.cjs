'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn,spawnSync}=require('node:child_process');
const {chromium,root,temp,env,py,browserPath}=require('./browser-runtime.cjs');
const base='http://127.0.0.1:18791',out=process.env.TESSERA_QA_OUTPUT||path.join(root,'docs/validation/webcraft');fs.mkdirSync(out,{recursive:true});
const child=spawn(py,['-B',path.join(root,'tests/serve_ai_fixture.py'),'--port','18791','--db',path.join(temp,'qa.sqlite3')],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});let logs='',browser;child.stdout.on('data',b=>logs+=b);child.stderr.on('data',b=>logs+=b);
async function get(url,body){const r=await fetch(base+url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok,await r.clone().text());return r.json();}
(async()=>{
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}assert(ready,'Fixture not ready');
  browser=await chromium.launch({headless:true,executablePath:browserPath,env});
  const context=await browser.newContext({viewport:{width:1512,height:1050},reducedMotion:'reduce',recordVideo:process.env.TESSERA_RECORD_VIDEO?{dir:out,size:{width:1512,height:1050}}:undefined});
  const page=await context.newPage(),errors=[],external=[],calls=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/ai'))calls.push(r.url());});
  await page.route('**/*',r=>{const u=new URL(r.request().url());if(!['127.0.0.1',''].includes(u.hostname)){external.push(u.href);return r.abort();}return r.continue();});
  await page.goto(base+'/web-studio');await page.waitForSelector('#page-library');await page.screenshot({path:path.join(out,'intake.png'),fullPage:true});
  await page.locator('#fill-demo').click();await page.locator('#create-page button[type=submit]').click();await page.waitForSelector('#editor:not([hidden])');
  const sid=await page.evaluate(()=>W.view.id),initial=await get('/api/websites/'+sid);
  await page.frameLocator('#page-frame').locator('#hero h1').waitFor();const styled=await page.frameLocator('#page-frame').locator('h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));assert(styled>=30,'Preview CSS must load');
  // Pick directly in the preview and protect only navigation design.
  await page.frameLocator('#page-frame').locator('#nav .brand').click();assert.equal(await page.evaluate(()=>W.selected),'nav');
  await page.locator('[data-protect=layout]').click();await page.waitForFunction(()=>W.view.revision===1&&!W.busy);
  await page.locator('[data-protect=palette]').click();await page.waitForFunction(()=>W.view.revision===2&&!W.busy);
  await page.locator('[data-direction=editorial]').click();await page.waitForSelector('#proposal:not([hidden])');assert.equal((await get('/api/websites/'+sid)).revision,2);
  await page.locator('#apply-page').click();await page.waitForFunction(()=>W.view.revision===3&&!W.busy);
  let current=await get('/api/websites/'+sid);assert.deepEqual(current.document.components.nav,initial.document.components.nav);assert.equal(current.document.components.hero.layout,'editorial');assert(current.history[0].evidence.outside_unchanged);
  await page.locator('[data-component=hero]').click();await page.locator('[data-layout=compact][data-palette=sage]').click();await page.locator('#apply-page').click();await page.waitForFunction(()=>W.view.revision===4&&!W.busy);
  await page.screenshot({path:path.join(out,'component-design.png'),fullPage:true});
  await page.locator('#undo-page').click();await page.waitForFunction(()=>W.view.revision===5&&!W.busy);assert.equal((await get('/api/websites/'+sid)).document.components.hero.layout,'editorial');
  // One synthetic provider request, two proposals, no auto adoption.
  await page.locator('#open-copy').click();await page.locator('#ai-instruction').fill('表达更自然，保留原有项目事实');await page.locator('#request-copy').click();await page.waitForSelector('.ai-option');assert.equal(await page.locator('.ai-option').count(),2);assert.equal((await get('/api/websites/'+sid)).revision,5);
  await page.locator('[data-ai-preview="1"]').click();await page.locator('#apply-page').click();await page.waitForFunction(()=>W.view.revision===6&&!W.busy);
  current=await get('/api/websites/'+sid);assert(current.history[0].evidence.job_id);assert(current.document.components.hero.content.title.endsWith('更自然'));assert.deepEqual(current.document.components.nav,initial.document.components.nav);
  // A stale preview may not replace concurrent updates.
  await page.locator('[data-layout=compact][data-palette=paper]').click();await page.waitForSelector('#proposal:not([hidden])');
  await get('/api/websites/'+sid+'/action',{revision:6,kind:'protect',component:'projects',field:'content',enabled:true});
  await page.locator('#apply-page').click();await page.waitForFunction(()=>document.querySelector('#web-status').textContent.includes('更新'));assert.equal((await get('/api/websites/'+sid)).revision,7);
  await page.reload();await page.waitForFunction(()=>W.view?.revision===7&&!W.busy);if(await page.locator('#ai-dialog').evaluate(e=>e.open))await page.locator('#close-ai').click();
  await page.locator('[data-step=deliver]').click();assert(await page.locator('#export-page').isDisabled());await page.locator('#review-check').check();await page.locator('#confirm-review').click();await page.waitForFunction(()=>W.view.ready&&!W.busy);await page.locator('#export-page').click();await page.waitForSelector('#download-result a');
  const href=await page.locator('#download-result a').getAttribute('href'),zip=path.join(temp,'export.zip');fs.writeFileSync(zip,Buffer.from(await (await fetch(base+href)).arrayBuffer()));
  const extract=path.join(temp,'unpacked');const unzip=spawnSync(py,['-B','-m','zipfile','-e',zip,extract],{env});assert.equal(unzip.status,0,unzip.stderr?.toString());
  const offline=await context.newPage();await offline.goto(require('node:url').pathToFileURL(path.join(extract,'index.html')).href);await offline.locator('#hero h1').waitFor();assert.equal(await offline.locator('script').count(),0);assert.equal(await offline.locator('.component').count(),4);assert((await offline.locator('#hero').innerText()).includes('更自然'));
  await offline.screenshot({path:path.join(out,'export-desktop.png'),fullPage:true});
  const sizes=[];for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:1000});assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=width);await offline.setViewportSize({width,height:900});const check=await offline.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('#hero')).borderRadius}));assert(check.scroll<=width,JSON.stringify(check));assert.equal(check.radius,'16px');sizes.push(check);if(width===390)await offline.screenshot({path:path.join(out,'export-mobile.png'),fullPage:true});}
  assert.equal(calls.length,1);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const proof={result:'PASS',provider:'synthetic fixture; not a real model quality evaluation',paidCalls:0,requests:1,options:2,qaDatabase:path.join(temp,'qa.sqlite3'),export:zip,sizes,checks:['preview CSS actually loaded','click rendered component','property-level preservation across direction changes','two-axis layout/palette customization','preview does not adopt','exact undo','two AI candidates in one call','model adoption provenance','concurrent stale patch rejected','snapshot-bound review and export','offline HTML works without scripts or external assets']};fs.writeFileSync(path.join(out,'proof.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));await context.close();
})().catch(e=>{console.error(e,logs);process.exitCode=1;}).finally(async()=>{await browser?.close();child.kill();});
