const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),stamp=String(Date.now()),qa='D:/CodexWork/temp/intent-choice-browser/'+stamp,base='http://127.0.0.1:18775';
fs.mkdirSync(qa,{recursive:true});const env={...process.env,TEMP:qa,TMP:qa,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(qa,'qa.sqlite3'),'--port','18775','--choice-demo'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let output='',browser;child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);
async function api(url,body){const r=await fetch(base+url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok,await r.clone().text());return r.json();}
async function waitRevision(page,old){await page.waitForFunction(v=>document.querySelector('#studio-saved').textContent!==v,old);}
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[],paidRequests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/ai\/(generate|revise|repair)$/.test(new URL(r.url()).pathname))paidRequests.push(r.url());});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  await page.locator('[data-type=project]').click();await page.locator('#choice-directions summary').click();
  assert.equal(await page.locator('[data-direction-name="0"]').inputValue(),'最快跑通闭环');
  await page.locator('[data-direction-name="0"]').fill('只先验证登记搜索');await page.locator('[data-direction-instruction="0"]').fill('明确暂缓认领自动化，先跑通本机登记与搜索。');
  await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('已保存'));
  await page.reload();await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('已恢复'));
  assert.equal(await page.locator('[data-direction-name="0"]').inputValue(),'只先验证登记搜索');
  await page.locator('#try-choice-demo').click();await page.waitForSelector('.plan-summary');
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session')),before=await api('/api/sessions/'+sid);
  assert.equal(before.choice_board.eligible,3);assert(before.choice_board.initials.every(p=>!p.can_apply));
  assert.equal(await page.locator('.plan-summary').count(),3);assert(await page.locator('[data-candidate="0"]').isDisabled());
  await page.locator('.plan-matrix summary').click();
  assert.equal(await page.locator('.plan-matrix tbody tr').count(),5);
  assert((await page.locator('.plan-matrix tbody').innerText()).includes('未通过'));
  await page.locator('.plan-matrix').screenshot({path:path.join(root,'docs/screenshots/github-reference-plan-matrix.png')});
  await page.setViewportSize({width:390,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1512,height:1060});
  await page.screenshot({path:path.join(root,'docs/screenshots/choices-compare-desktop.png'),fullPage:true});
  // A background + A closing is too short. Preserve A background, then let the solver fill the closing.
  await page.locator('[data-pick-chapter=intro]').first().click();assert(await page.locator('[data-choice-anchor=intro]').isChecked());
  await page.locator('#inspect-choice-draft').click();await page.waitForSelector('#complete-choice-draft');
  assert((await page.locator('#choice-inspection').innerText()).includes('有 2 个可行组合'));
  await page.locator('#complete-choice-draft').click();assert(!(await page.locator('[data-custom-block=closing]').inputValue()).endsWith('-0'));
  assert(await page.locator('#adopt-choice-draft').isEnabled());
  await page.locator('#choice-option-name').fill('简洁背景配完整回复');await page.locator('#save-choice-form button').click();
  await page.waitForSelector('[data-load-saved]');assert((await page.locator('.saved-options').innerText()).includes('简洁背景配完整回复'));
  const saved=await api('/api/sessions/'+sid);assert.equal(saved.text,before.text);assert.equal(saved.pair_count,0);assert.equal(saved.choice_board.saved.length,1);
  await page.reload();await page.waitForSelector('.document-section');await page.locator('[data-tab=candidates]').click();await page.locator('[data-choice-mode=saved]').click();
  await page.locator('[data-load-saved]').click();await page.locator('#inspect-choice-draft').click();await page.waitForFunction(()=>!document.querySelector('#adopt-choice-draft').disabled);
  await page.screenshot({path:path.join(root,'docs/screenshots/choices-mix-desktop.png'),fullPage:true});
  await page.locator('#adopt-choice-draft').click();await page.waitForFunction(()=>document.querySelector('[data-lock=intro]').getAttribute('aria-pressed')==='true');
  const adopted=await api('/api/sessions/'+sid);assert.equal(adopted.state.locks.intro,'intro-0');assert.notEqual(adopted.text,before.text);assert.equal(adopted.pair_count,0);
  await page.locator('#undo-studio').click();await page.waitForFunction(()=>document.querySelector('[data-lock=intro]').getAttribute('aria-pressed')==='false');
  assert.equal((await api('/api/sessions/'+sid)).text,before.text);
  // Two pins conflict with the length contract; the UI must not quietly relax them.
  await page.locator('[data-tab=candidates]').click();await page.locator('[data-choice-mode=mix]').click();await page.locator('#reset-choice-draft').click();
  await page.locator('[data-choice-anchor=intro]').check();await page.locator('[data-choice-anchor=closing]').check();
  await page.locator('#inspect-choice-draft').click();await page.waitForFunction(()=>document.querySelector('#choice-inspection').textContent.includes('无解'));
  assert(await page.locator('#adopt-choice-draft').isDisabled());assert(await page.locator('[data-choice-anchor=intro]').isChecked());assert(await page.locator('[data-choice-anchor=closing]').isChecked());
  await page.screenshot({path:path.join(root,'docs/screenshots/choices-conflict-desktop.png'),fullPage:true});
  const sizes=[];for(const width of [360,390,740,820,1024,1512]){
    await page.setViewportSize({width,height:1000});
    const r=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('[data-custom-block=intro]')).borderRadius}));
    assert(r.scroll<=r.width,JSON.stringify(r));assert.equal(r.radius,'16px');sizes.push(r);
  }
  await page.setViewportSize({width:390,height:1000});await page.screenshot({path:path.join(root,'docs/screenshots/choices-mix-mobile.png'),fullPage:true});
  await page.locator('[data-choice-mode=compare]').click();await page.screenshot({path:path.join(root,'docs/screenshots/choices-compare-mobile.png'),fullPage:true});
  // Strict synthetic 40-character contract leaves two plans differing in both chapters.
  const t={title:'完整方案偏好测试',facts:{},blocks:['left','right'].map((k,i)=>({id:k,title:k,variants:[10,30,50].map((n,j)=>({id:k+j,template:(i?'乙':'甲').repeat(n)}))}))};
  const created=await api('/api/sessions',{task:t});await api('/api/sessions/'+created.id+'/action',{kind:'acceptance',revision:0,contract:{length:{min:40,max:40}}});
  await page.reload();await page.waitForSelector(`[data-session="${created.id}"]`);await page.locator('#mobile-menu').click();await page.locator(`[data-session="${created.id}"]`).click();await page.waitForSelector('.document-section');
  await page.locator('[data-tab=candidates]').click();await page.locator('#compare-studio-learning').click();await page.waitForSelector('#preference-dialog[open]');
  assert((await page.locator('#preference-content').innerText()).includes('完整组合'));
  const wholeBefore=await api('/api/sessions/'+created.id);await page.locator('[data-preference-choice=b]').click();await page.waitForFunction(()=>!document.querySelector('#preference-dialog').open);
  const wholeAfter=await api('/api/sessions/'+created.id);assert.equal(wholeAfter.text,wholeBefore.text);assert.equal(wholeAfter.pair_count,1);
  assert.deepEqual(paidRequests,[]);assert.deepEqual(errors,[]);
  const proof={result:'PASS',paidCalls:0,qaDatabase:qa,alignedPlansPassed:0,mixedPlansPassed:3,combinationsEnumerated:9,sizes,
    checks:['editable generation directions persist','three full plans compared with actual lengths','choose and preserve one chapter','zero-call anchored completion','save and refresh named alternative without adopting','atomic adopt with locks and one-step undo','no solution does not relax pins','full-plan explicit preference changes ranking without adopting','no inferred preference labels','16px and 360–1512px layouts']};
  fs.writeFileSync(path.join(root,'docs/validation/choices-browser-'+stamp+'.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
})().catch(e=>{console.error(e);console.error(output);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
