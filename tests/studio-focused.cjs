'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/tessera-focused-browser/'+Date.now(),base='http://127.0.0.1:18789';
fs.mkdirSync(temp,{recursive:true});const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(temp,'qa.sqlite3'),'--port','18789'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='',browser;child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
async function api(url,data){const r=await fetch(base+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert(r.ok,await r.clone().text());return r.json();}
async function idle(page){await page.waitForFunction(()=>!S.busy);}
async function select(page,block,quote){
  await page.locator('#block-'+block+' > .markdown').evaluate((el,quote)=>{const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode()){const i=node.textContent.indexOf(quote);if(i>=0){const r=document.createRange();r.setStart(node,i);r.setEnd(node,i+quote.length);const s=getSelection();s.removeAllRanges();s.addRange(r);break;}}},quote);
  await page.keyboard.press('Shift');await page.keyboard.up('Shift');
  await page.evaluate(()=>captureLocalSelection());await page.waitForSelector('#selection-toolbar:not(.hidden)');
}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1100},reducedMotion:'reduce'}),errors=[],requests=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(local_revise|generate|revise|repair)$/.test(new URL(r.url()).pathname))requests.push(new URL(r.url()).pathname);});
  await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  assert(await page.locator('body').evaluate(el=>el.classList.contains('guided-mode')));assert(!(await page.locator('.choice-directions').isVisible()));assert(await page.locator('#workspace-mode-toggle').isVisible());
  await page.screenshot({path:path.join(root,'docs/screenshots/focused-home.png'),fullPage:true});
  await page.locator('#workspace-mode-toggle').click();assert(await page.locator('.choice-directions').isVisible());await page.locator('#workspace-mode-toggle').click();
  const text='前文🙂。我喜欢这句话。需要修改的内容。后文。',task={title:'局部打磨开发样本',brief:'检验只改选区，保留其他文字',facts:{},blocks:[{id:'intro',title:'内容',variants:[0,1,2].map(i=>({id:'v'+i,template:text+i}))},{id:'end',title:'结尾',variants:[0,1,2].map(i=>({id:'v'+i,template:'其他章节保持不变。'+i}))}]};
  const {id:sid}=await api('/api/sessions',{task});await page.evaluate(id=>openSession(id),sid);await idle(page);const before=await api('/api/sessions/'+sid);
  assert(await page.locator('#focused-next').isVisible());assert(!(await page.locator('[data-edit=intro]').isVisible()));assert(await page.locator('[data-local-open=intro]').isVisible());
  await select(page,'intro','需要修改的内容。');await page.locator('#selection-toolbar [data-local-action=alternatives]').click();
  await page.waitForSelector('.local-options article');assert.equal(await page.locator('.local-options article').count(),2);assert.equal((await api('/api/sessions/'+sid)).text,before.text);
  await page.screenshot({path:path.join(root,'docs/screenshots/focused-two-options.png')});
  await page.locator('[data-local-option=option-1]').click();await page.waitForFunction(()=>!document.querySelector('#local-dialog').open&&!S.busy);
  const after=await api('/api/sessions/'+sid);assert.equal(after.pair_count,0);assert.equal(after.text,before.text.replace('需要修改的内容。','需要修改的内容。（换一种表达）'));
  await page.locator('#undo-studio').click();await page.waitForFunction(()=>S.view.text.includes('后文。')&&!S.busy&&!S.view.text.includes('换一种表达'));assert.equal((await api('/api/sessions/'+sid)).text,before.text);
  // Accessible exact-range selection in the original source, including emoji offsets.
  await page.locator('[data-local-open=intro]').click();await page.locator('#local-source').evaluate(el=>{const start=el.value.indexOf('我喜欢');el.setSelectionRange(start,start+'我喜欢这句话。'.length);el.dispatchEvent(new Event('select',{bubbles:true}));});
  await page.locator('#local-dialog [data-local-action=concise]').click();await page.waitForSelector('.local-options article');assert.equal(await page.locator('.local-options article').count(),1);
  // A concurrent version change makes the earlier proposal read-only.
  const current=await api('/api/sessions/'+sid);await api('/api/sessions/'+sid+'/action',{kind:'lock',revision:current.revision,block:'end'});
  await page.evaluate(()=>refreshDocument());const local=(await api('/api/sessions/'+sid+'/ai/history')).jobs.find(j=>j.kind==='local_revise');await page.evaluate(id=>showLocalJob(id),local.id);assert(await page.locator('[data-local-apply]').isDisabled());
  await page.locator('[data-close=local-dialog]').click();
  const sizes=[];for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:1000});const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('#focused-next')).borderRadius}));assert(r.scroll<=width,JSON.stringify(r));assert.equal(r.radius,'16px');sizes.push(r);if(width===390)await page.screenshot({path:path.join(root,'docs/screenshots/focused-mobile.png'),fullPage:false});}
  await page.locator('#workspace-mode-toggle').click();assert(await page.locator('[data-edit=intro]').isVisible());await page.reload();await page.waitForSelector('.document-section');assert(!(await page.locator('body').evaluate(el=>el.classList.contains('guided-mode'))));
  assert.equal(requests.length,2);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const proof={result:'PASS',paidCalls:0,provider:'local synthetic fixture',mockLocalRequests:2,qaDatabase:path.join(temp,'qa.sqlite3'),sizes,checks:['guided default and full mode persistence','expert controls remain accessible','DOM text selection with emoji prefix','two replacements from one request','preview does not adopt','exact selected range patch','undo restores body','precise source selection','stale local proposal blocked','zero inferred labels','16px and responsive layout']};
  fs.writeFileSync(path.join(root,'docs/validation/focused-browser.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
})().catch(e=>{console.error(e,logs);process.exitCode=1;}).finally(async()=>{await browser?.close();child.kill();});
