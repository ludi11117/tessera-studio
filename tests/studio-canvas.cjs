'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-canvas-browser/'+Date.now(),base='http://127.0.0.1:18783';
fs.mkdirSync(temp,{recursive:true});const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(temp,'qa.sqlite3'),'--port','18783','--choice-demo'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='',browser;child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
async function api(url,data){const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();}
function clean(a){delete a.exported_at;return a;}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],paid=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(generate|revise|repair)$/.test(new URL(r.url()).pathname))paid.push(r.url());});
  await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.goto(base);await page.waitForSelector('#try-choice-demo:not([hidden])');await page.locator('#try-choice-demo').click();
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session')),before=clean(await api('/api/sessions/'+sid+'/audit'));
  await page.locator('[data-choice-mode=canvas]').click();await page.waitForSelector('.canvas-matrix');
  assert((await page.locator('.canvas-status').innerText()).includes('3 / 3'));
  // The whole-plan A/B/C drafts all fail, but mixed chapters meet the same rules.
  const initial=await api('/api/sessions/'+sid);assert(initial.choice_board.initials.every(p=>!p.can_apply));
  await page.locator('[data-canvas-block=intro][data-canvas-variant=intro-1]').click();
  assert((await page.locator('.canvas-status').innerText()).includes('1 / 3'));
  await page.locator('[data-canvas-block=closing][data-canvas-variant=closing-2]').click();
  assert((await page.locator('.canvas-status').innerText()).includes('0 / 3'));assert.equal(await page.locator('[data-canvas-relax]').count(),2);
  await page.screenshot({path:path.join(root,'docs/screenshots/canvas-conflict.png'),fullPage:true});
  await page.locator('[data-canvas-relax]').first().click();assert((await page.locator('.canvas-status').innerText()).includes('1 / 3'));
  assert.equal(await page.locator('[data-canvas-block][aria-pressed=true]').count(),1);
  await page.locator('[data-canvas-reset]').click();
  await page.locator('#canvas-budget').selectOption('0');assert((await page.locator('.canvas-status').innerText()).includes('0 / 3'));
  await page.locator('#canvas-budget').selectOption('2');
  await page.locator('#canvas-max').fill('1');await page.locator('#canvas-max').press('Tab');assert((await page.locator('.canvas-conflict').innerText()).includes('篇幅与改动范围'));
  await page.locator('[data-canvas-reset]').click();
  await page.locator('[data-canvas-block=intro][data-canvas-variant=intro-0]').focus();await page.keyboard.press('Space');
  assert.equal(await page.locator('[data-canvas-block=intro][data-canvas-variant=intro-0]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('.canvas-dot').count(),2);assert.equal(await page.locator('#canvas-plan option').count(),2);
  const sizes=[];
  for(const width of [360,390,740,820,1024,1512]){
    await page.setViewportSize({width,height:1100});
    const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('.configuration-card')).borderRadius}));
    assert(size.scroll<=width,JSON.stringify(size));assert.equal(size.radius,'16px');sizes.push(size);
    if(width===390)await page.screenshot({path:path.join(root,'docs/screenshots/canvas-mobile.png'),fullPage:true});
  }
  await page.locator('#toggle-focus').click();await page.locator('.configuration-card').scrollIntoViewIfNeeded();
  await page.locator('#candidates-view').evaluate(el=>el.scrollTop=0);await page.locator('.artifact-pane').evaluate(el=>el.scrollTop=0);
  await page.locator('.configuration-card').screenshot({path:path.join(root,'docs/screenshots/canvas-card.png')});
  await page.locator('#candidates-view').evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(root,'docs/screenshots/canvas-desktop.png'),fullPage:true});
  assert.deepEqual(clean(await api('/api/sessions/'+sid+'/audit')),before);
  await page.locator('[data-canvas-preview]').click();await page.waitForFunction(()=>!document.querySelector('#adopt-choice-draft').disabled);
  assert.deepEqual(clean(await api('/api/sessions/'+sid+'/audit')),before);
  await page.locator('#adopt-choice-draft').click();await page.waitForSelector('#document-view:not(.hidden)');
  const adopted=await api('/api/sessions/'+sid);assert.equal(adopted.state.locks.intro,'intro-0');assert.equal(adopted.pair_count,0);assert.notEqual(adopted.text,initial.text);
  const zip=await api('/api/sessions/'+sid+'/ai/export',{revision:adopted.revision,format:'zip'});assert(fs.existsSync(zip.path));
  // The previous canvas must reset after adoption, including its old anchors.
  await page.locator('[data-tab=candidates]').click();await page.locator('[data-choice-mode=canvas]').click();await page.waitForSelector('.canvas-matrix');
  assert.equal(await page.locator('[data-canvas-block][aria-pressed=true]').count(),0);assert(await page.locator('[data-canvas-block=intro]').first().isDisabled());
  // Exercise the actual validated six-chapter/729-option UI, not only the pure query.
  const six={title:'729组合浏览器开发样本',brief:'合成内容，仅测交互边界',facts:{},blocks:Array.from({length:6},(_,i)=>({id:'b'+i,title:'章节'+i,variants:[0,1,2].map(j=>({id:'v'+j,template:'甲'.repeat(30+i*3+j*20)}))}))};
  const large=await api('/api/sessions',{task:six});
  await page.evaluate(id=>openSession(id),large.id);await page.locator('[data-tab=candidates]').click();await page.locator('[data-choice-mode=canvas]').click();await page.waitForSelector('.canvas-matrix');
  assert((await page.locator('.canvas-status').innerText()).includes('729 / 729'));assert.equal(await page.locator('#canvas-plan option').count(),729);
  const rendering=await page.evaluate(()=>{const ms=[];for(let i=0;i<12;i++){const t=performance.now();paintCanvas();ms.push(performance.now()-t);}return {paintFunctionMs:ms,canvasSvgGroups:document.querySelectorAll('.canvas-dot').length};});
  // Coincident map points must keep every underlying option accessible in the list.
  assert(rendering.canvasSvgGroups<729);assert.equal(await page.locator('#canvas-plan option').count(),729);
  assert.deepEqual(errors,[]);assert.deepEqual(paid,[]);assert.deepEqual(external,[]);
  const proof={result:'PASS',sizes,rendering,paidCalls:0,externalRequests:0,qaDatabase:path.join(temp,'qa.sqlite3'),zip:zip.path,
    checks:['whole drafts fail; feasible mix found','conditional counts','zero-support conflict','explicit minimal relaxation','filter empty and reset','keyboard selection','coincident options available in list','read-only audit preservation','preview and fresh server check','explicit adoption preserves anchor as lock','revision reset','D-drive ZIP export']};
  fs.writeFileSync(path.join(root,'docs/validation/canvas-browser.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
})().catch(e=>{console.error(e,logs);process.exitCode=1;}).finally(async()=>{await browser?.close();child.kill();});
