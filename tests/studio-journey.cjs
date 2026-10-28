'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-journey-browser/'+Date.now(),base='http://127.0.0.1:18785';
fs.mkdirSync(temp,{recursive:true});const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(temp,'qa.sqlite3'),'--port','18785'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='',browser;child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
async function api(url,data){const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();}
async function changed(page,old){await page.waitForFunction(v=>document.querySelector('#studio-saved').textContent!==v,old);}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],modelPosts=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(generate|revise|repair)$/.test(new URL(r.url()).pathname))modelPosts.push(r.url());});
  await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  assert.equal(await page.locator('.home-heading .journey-steps button').count(),4);
  await page.locator('.guide-entry [data-guide-open]').click();await page.waitForSelector('#guide-idea');
  await page.locator('#guide-idea').fill('做项目');await page.locator('[data-guide-category=project]').click();await page.locator('[data-guide-begin]').click();
  await page.locator('#guide-answer').fill('给同学使用，方便查找丢失的物品');await page.locator('[data-guide-answer]').click();
  await page.locator('[data-guide-skip]').click();await page.locator('.guide-common summary').click();assert.equal(await page.locator('.guide-examples button').count(),2);
  await page.screenshot({path:path.join(root,'docs/screenshots/journey-inspiration.png')});
  await page.locator('[data-guide-example="0"]').click();await page.locator('[data-guide-option="2"]').click();
  await page.locator('#guide-keep').fill('保留不公开联系方式这个边界');await page.locator('#guide-change').fill('先做小范围验证，不堆功能');await page.locator('#guide-criteria').fill('明确输入、操作、输出与验收步骤');
  await page.screenshot({path:path.join(root,'docs/screenshots/journey-brief.png')});
  assert.equal(modelPosts.length,0);
  await page.locator('[data-guide-confirm]').click();await page.waitForFunction(()=>!document.querySelector('#guidance-dialog').open);
  assert((await page.locator('#guidance-summary').innerText()).includes('需求卡已确认'));
  await page.reload();await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('已恢复'));
  assert((await page.locator('#guidance-summary').innerText()).includes('3 项已明确，1 项待确认'));
  const draft=await api('/api/ai/draft');assert.equal(draft.input.guidance.confirmed,true);assert.equal(draft.input.guidance.answers.boundary,null);assert.equal(draft.input.task_type,'project');
  await page.locator('#generate-goal').click();await page.waitForSelector('#workspace-view:not(.hidden) .document-section');
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session')),first=await api('/api/sessions/'+sid);
  assert.equal(first.task.intent_brief.unresolved.length,1);assert.equal(first.pair_count,0);
  await page.locator('[data-preserve=section2]').click();await page.locator('#fragment-text').fill('使用Python与SQLite');
  await page.locator('#fragment-form [type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#fragment-dialog').open);
  const preserved=await api('/api/sessions/'+sid);assert.equal(preserved.text,first.text);assert.equal(preserved.state.preserved_fragments.length,1);assert.equal(preserved.state.locks.section2,undefined);assert.equal(preserved.pair_count,0);
  assert(await page.locator('[data-edit=section2]').isEnabled());
  // Rewriting unrelated text succeeds; deleting the protected phrase is atomic and refused.
  await page.locator('[data-edit=section2]').click();await page.locator('#section-edit-text').fill('这次修改把需要保留的原文删掉了。');await page.locator('#section-edit-form [type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#studio-toast').textContent.includes('局部原文'));assert.equal((await api('/api/sessions/'+sid)).text,first.text);
  await page.locator('#section-edit-text').fill('使用Python与SQLite。其他部分改成更容易理解的说明。');await page.locator('#section-edit-form [type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#edit-section-dialog').open);
  assert((await page.locator('#block-section2 > .markdown').innerText()).includes('更容易理解'));
  await page.locator('#revision-scope').selectOption('section2');await page.locator('#revision-input').fill('保留已经喜欢的原文，补充其他部分的验收方式');await page.locator('#send-revision').click();
  await page.waitForSelector('#proposal-banner .proposal-strip:not(.stale)');await page.locator('#proposal-banner [data-proposal]').click();assert(await page.locator('#apply-proposal-dialog').isEnabled());await page.locator('#apply-proposal-dialog').click();await page.waitForFunction(()=>!document.querySelector('#proposal-dialog').open);
  await page.waitForFunction(()=>document.querySelector('#block-section2 > .markdown').textContent.includes('新增验收')&&!S.busy);
  assert((await page.locator('#block-section2 > .markdown').innerText()).includes('使用Python与SQLite'));
  await page.locator('#toggle-focus').click();await page.setViewportSize({width:1512,height:2000});await page.locator('.artifact-pane').evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(root,'docs/screenshots/journey-preservation.png')});
  const sizes=[];
  for(const width of [360,390,740,820,1024,1512]){
    await page.setViewportSize({width,height:1000});const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('.preserved-parts')).borderRadius}));assert(r.scroll<=width,JSON.stringify(r));assert.equal(r.radius,'16px');sizes.push(r);
    if(width===390){await page.locator('#block-section2').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'docs/screenshots/journey-mobile.png')});}
  }
  await page.locator('#document-view [data-journey=deliver]').click();await page.waitForSelector('#sources-view:not(.hidden) .intent-brief');
  assert((await page.locator('.intent-brief').innerText()).includes('明确输入、操作、输出'));
  for(const key of ['read_through','facts_checked','usable']){const old=await page.locator('#studio-saved').innerText();await page.locator('[data-review='+key+']').check();await changed(page,old);}
  await page.locator('[data-journey-export=zip]').click();await page.waitForSelector('#export-file-path');const zip=(await page.locator('#export-file-path').innerText()).replace('已保存到 D 盘：','');assert(fs.existsSync(zip));
  const final=await api('/api/sessions/'+sid);assert.equal(final.pair_count,0);assert.equal(final.state.preserved_fragments.length,1);assert(final.state.review.usable);
  await page.locator('#new-goal').click();await page.locator('.guide-entry [data-guide-open]').click();await page.waitForSelector('#guide-idea');
  await page.locator('[data-guide-begin]').click();await page.locator('[data-guide-review]').click();await page.locator('[data-guide-question=direction]').click();
  const guideSizes=[];
  for(const width of [360,390,740,820,1024,1512]){
    await page.setViewportSize({width,height:1000});const size=await page.evaluate(()=>{const el=document.querySelector('#guidance-dialog');return {width:innerWidth,scroll:document.documentElement.scrollWidth,dialogClient:el.clientWidth,dialogScroll:el.scrollWidth,radius:getComputedStyle(el).borderRadius};});
    assert(size.scroll<=width&&size.dialogScroll<=size.dialogClient,JSON.stringify(size));assert.equal(size.radius,'16px');guideSizes.push(size);
    if(width===390)await page.screenshot({path:path.join(root,'docs/screenshots/journey-guide-mobile.png')});
  }
  assert.equal(modelPosts.length,2,'Only explicit generation and revision use the fixture provider');assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
  const proof={result:'PASS',paidCalls:0,provider:'synthetic local fixture',explicitMockRequests:2,qaDatabase:path.join(temp,'qa.sqlite3'),zip,session:sid,sizes,guideSizes,checks:['four connected steps','domain-specific questions and concrete examples','unknown remains unknown','zero model calls during guidance','confirmed brief survives reload','brief reaches generated task','chapter-local preservation without whole chapter lock','manual violation rejected atomically','AI rewrites remainder preserving literal','six responsive sizes and 16px including guidance dialog','manual-review checkbox persistence (automated fixture)','real D-drive ZIP with trace','zero inferred preference labels']};
  fs.writeFileSync(path.join(root,'docs/validation/journey-browser.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
})().catch(e=>{console.error(e,logs);process.exitCode=1;}).finally(async()=>{await browser?.close();child.kill();});
