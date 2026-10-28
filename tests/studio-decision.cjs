/* Local functional and visual QA; no paid generation calls. All state is on D:. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),stamp=String(Date.now()),temp='D:/CodexWork/temp/intent-decision-browser/'+stamp,base='http://127.0.0.1:18779';
fs.mkdirSync(temp,{recursive:true});const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(temp,'qa.sqlite3'),'--port','18779','--choice-demo'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='',browser;child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
async function api(url,data){const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();}
async function tab(page,name){await page.locator('.artifact-tabs [data-tab='+name+']').click();}
async function fits(page,width){await page.setViewportSize({width,height:1000});const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('.decision-next')).borderRadius}));assert(r.scroll<=width,JSON.stringify(r));assert.equal(r.radius,'16px');return r;}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[],paid=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(generate|revise|repair)$/.test(new URL(r.url()).pathname))paid.push(r.url());});
  await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-home.png'),fullPage:true});
  await page.locator('#try-decision-demo').click();await page.waitForSelector('.decision-next');
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session')),before=await api('/api/sessions/'+sid+'/audit'),view=await api('/api/sessions/'+sid);
  assert.equal(await page.locator('.decision-metrics strong').nth(0).innerText(),'9');assert.equal(await page.locator('.decision-metrics strong').nth(1).innerText(),'3');
  assert((await page.locator('.decision-example').innerText()).includes('开发示例'));
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-decision.png'),fullPage:true});
  await page.locator('#decision-budget').fill('0');assert((await page.locator('#decision-budget-choice').innerText()).includes('还无法满足条件'));
  await page.locator('#decision-budget').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#decision-budget-value').innerText(),'1');
  await page.waitForSelector('#preview-decision-plan');assert((await page.locator('#decision-budget-choice').innerText()).includes('实际改动 1 章'));
  await page.locator('#preview-decision-plan').click();assert(await page.locator('#choice-mix').isVisible());
  const afterPreview=await api('/api/sessions/'+sid+'/audit');delete before.exported_at;delete afterPreview.exported_at;assert.deepEqual(afterPreview,before);
  // All real actions continue through existing revision checks. Preview did not adopt.
  await tab(page,'document');await page.locator('[data-lock=intro]').click();await page.waitForFunction(()=>document.querySelector('[data-lock=intro]').getAttribute('aria-pressed')==='true');
  await page.locator('[data-lock=closing]').click();await page.waitForFunction(()=>document.querySelector('[data-lock=closing]').getAttribute('aria-pressed')==='true');
  await tab(page,'decision');await page.waitForSelector('.conflict-list');assert.equal(await page.locator('.conflict-list li').count(),3);
  assert.equal(await page.locator('.correction-list article').count(),3);assert.equal(await page.locator('#decision-budget').count(),0);
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-conflict.png'),fullPage:true});
  const sizes=[];for(const width of [360,390,740,820,1024,1512])sizes.push(await fits(page,width));
  await page.setViewportSize({width:390,height:1000});await page.locator('.artifact-pane').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-decision-mobile.png'),fullPage:true});
  // Constraint adjustment requires explicit navigation and confirmation; no auto-relaxation.
  await page.locator('.correction-list button').first().click();assert(await page.locator('#sources-view').isVisible());
  const current=await api('/api/sessions/'+sid),stale=await fetch(base+'/api/sessions/'+sid+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:view.revision})});assert.equal(stale.status,409);
  assert.deepEqual(current.state.acceptance,view.state.acceptance);assert.equal(current.pair_count,0);
  // Restore the two QA locks and exercise the newly bundled decision evidence.
  await page.setViewportSize({width:1512,height:1060});await tab(page,'document');
  for(const bid of ['closing','intro']){await page.locator('[data-lock='+bid+']').click();await page.waitForFunction(b=>document.querySelector('[data-lock='+b+']').getAttribute('aria-pressed')==='false',bid);}
  const ready=await api('/api/sessions/'+sid),plan=(await api('/api/sessions/'+sid+'/decision',{revision:ready.revision})).frontier[0];
  await api('/api/sessions/'+sid+'/action',{kind:'apply',revision:ready.revision,combo:plan.combo});
  const exportView=await api('/api/sessions/'+sid),zip=await api('/api/sessions/'+sid+'/ai/export',{revision:exportView.revision,format:'zip'});assert(fs.existsSync(zip.path));
  fs.writeFileSync(path.join(temp,'export-proof.json'),JSON.stringify({zip:zip.path,session:sid,revision:exportView.revision}));
  assert.deepEqual(paid,[]);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const proof={result:'PASS',paidCalls:0,externalRequests:0,sizes,qaDatabase:path.join(temp,'qa.sqlite3'),export:zip.path,checks:['read-only revision-bound analysis','keyboard-operable change budget','minimum change feasible preview without adoption','irreducible conflict with 3 witnessed correction sets','no automatic relaxation or preference labels','stale snapshot rejected','16px and responsive layouts','real ZIP export includes decision calculation']};
  fs.writeFileSync(path.join(root,'docs/validation/product-v10-browser-'+stamp+'.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
})().catch(e=>{console.error(e);console.error(logs);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
