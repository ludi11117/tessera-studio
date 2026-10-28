/* Product recovery verification. Isolated D: database; synthetic provider only. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),qa=path.join('D:/CodexWork/temp/intent-draft-browser',String(Date.now()));fs.mkdirSync(qa,{recursive:true});
const env={...process.env,TEMP:qa,TMP:qa,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8'};
const child=spawn(process.env.INTENT_PYTHON||'python',['-B',path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(qa,'qa.sqlite3'),'--port','18769'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let output='',browser;child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);
const base='http://127.0.0.1:18769',shots=path.join(root,'docs/screenshots');
async function api(url,data){const r=await fetch(base+url,data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{});assert(r.ok,await r.clone().text());return r.json();}
async function ready(){for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error(output);}
async function loaded(page){await page.waitForFunction(()=>document.querySelector('#revision-draft-status').textContent.includes('D 盘'));}
async function open(page,sid){await page.locator('[data-session="'+sid+'"]').click();await page.waitForSelector('[data-session="'+sid+'"].active');await loaded(page);}
async function saved(page,id){await page.waitForFunction(id=>document.querySelector(id).textContent.includes('已保存到 D 盘'),id);}
async function resolve(page,channel,choice){await page.locator(channel+' .draft-recovery').click();await page.waitForSelector('#draft-conflict-dialog[open]');await page.locator(choice).click();await page.waitForFunction(()=>!document.querySelector('#draft-conflict-dialog').open);}
(async()=>{
  await ready();browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const context=await browser.newContext({viewport:{width:1512,height:1060}}),a=await context.newPage(),b=await context.newPage(),errors=[];
  await context.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));
  for(const p of [a,b])p.on('pageerror',e=>errors.push(e.message));
  await a.goto(base);await a.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  await b.goto(base);await b.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
  await a.locator('#goal-input').fill('窗口甲：整理课程资料并制定两周复习计划。');await saved(a,'#draft-status');
  await b.locator('#goal-input').fill('窗口乙：给项目伙伴写一份交接说明。');await b.waitForSelector('#draft-status .draft-recovery');
  assert((await api('/api/ai/draft')).input.goal.includes('窗口甲'));
  await b.locator('#draft-status .draft-recovery').click();await b.waitForSelector('#draft-conflict-dialog[open]');
  assert((await b.locator('#draft-conflict-local').innerText()).includes('窗口乙'));
  assert((await b.locator('#draft-conflict-remote').innerText()).includes('窗口甲'));
  await b.screenshot({path:path.join(shots,'ai-draft-conflict.png')});
  // A third write during review must be shown again, never silently replaced.
  await a.locator('#goal-input').fill('窗口甲：最新版本，先清点讲义。');await saved(a,'#draft-status');
  await b.locator('#use-local-draft').click();await b.waitForFunction(()=>document.querySelector('#draft-conflict-remote').textContent.includes('最新版本'));
  assert(await b.locator('#draft-conflict-dialog').isVisible());
  await b.locator('#use-local-draft').click();await b.waitForFunction(()=>!document.querySelector('#draft-conflict-dialog').open);
  assert((await api('/api/ai/draft')).input.goal.includes('窗口乙'));
  await a.locator('#goal-input').fill('窗口甲：未保存的修改。');await a.waitForSelector('#draft-status .draft-recovery');
  await resolve(a,'#draft-status','#use-remote-draft');assert((await a.locator('#goal-input').inputValue()).includes('窗口乙'));
  const email=await api('/api/sessions',{sample:'email'}),message=await api('/api/sessions',{sample:'message'});
  const first=await api('/api/sessions',{task:(await api('/api/sessions/'+email.id)).task}),second=await api('/api/sessions',{task:(await api('/api/sessions/'+message.id)).task});
  // Open sessions by the normal navigation after fetching the fixture list.
  await a.reload();await a.waitForSelector('[data-session="'+first.id+'"]');await open(a,first.id);
  await a.locator('#revision-scope').selectOption('closing');
  const instruction='先保留当前范围，补充错误恢复步骤；这条要求尚未提交。';await a.locator('#revision-input').fill(instruction);await saved(a,'#revision-draft-status');
  await a.reload();await loaded(a);assert.equal(await a.locator('#revision-input').inputValue(),instruction);assert.equal(await a.locator('#revision-scope').inputValue(),'closing');
  // Content refresh caused by locks must preserve the intended scope.
  await a.locator('[data-lock=opening]').click();await a.waitForFunction(()=>document.querySelector('[data-lock=opening]').getAttribute('aria-pressed')==='true');
  assert.equal(await a.locator('#revision-scope').inputValue(),'closing');
  await open(a,second.id);assert.equal(await a.locator('#revision-input').inputValue(),'');
  await open(a,first.id);assert.equal(await a.locator('#revision-input').inputValue(),instruction);
  await b.reload();await b.waitForSelector('[data-session="'+first.id+'"]');await open(b,first.id);
  await a.locator('#revision-input').fill('窗口甲：修改任务范围与验收。');await saved(a,'#revision-draft-status');
  await b.locator('#revision-input').fill('窗口乙：保留另一份未提交要求。');await b.waitForSelector('#revision-draft-status .draft-recovery');
  await resolve(b,'#revision-draft-status','#use-remote-draft');assert.equal(await b.locator('#revision-input').inputValue(),'窗口甲：修改任务范围与验收。');
  await b.locator('#revision-input').fill('离开任务时立刻保存的文字。');await open(b,second.id);
  assert.equal((await api('/api/sessions/'+first.id+'/ai/draft')).input.instruction,'离开任务时立刻保存的文字。');
  assert.equal((await api('/api/ai/jobs')).jobs.length,0);assert.equal((await api('/api/sessions/'+first.id)).pair_count,0);
  await a.route('**/api/sessions/'+first.id+'/ai/draft',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'测试用草稿读取中断'})}));
  await a.locator('[data-session="'+first.id+'"]').click();
  await a.waitForFunction(()=>document.querySelector('#revision-draft-status').textContent.includes('读取失败'));
  assert(await a.locator('#revision-input').isDisabled());assert(await a.locator('#send-revision').isDisabled());assert.equal(await a.locator('#revision-input').inputValue(),'');
  await a.unroute('**/api/sessions/'+first.id+'/ai/draft');await open(a,first.id);
  assert.equal(await a.locator('#revision-input').inputValue(),'离开任务时立刻保存的文字。');

  // D: assets, deliberate fonts and restrained visual rules are part of delivery.
  await a.reload();await loaded(a);await open(a,first.id);
  await a.locator('#revision-input').fill('补充这份稿件的下一步行动。');await saved(a,'#revision-draft-status');
  await a.locator('#send-revision').click();await a.waitForSelector('#proposal-banner .proposal-strip');await saved(a,'#revision-draft-status');
  assert.equal((await api('/api/sessions/'+first.id+'/ai/draft')).input.instruction,'');
  assert.equal(await a.locator('#revision-input').inputValue(),'');
  await a.reload();await loaded(a);assert.equal(await a.locator('#revision-input').inputValue(),'');
  assert.equal((await api('/api/ai/jobs')).jobs.length,1);
  await a.evaluate(()=>document.fonts.ready);
  const visuals=await a.evaluate(()=>({sans:document.fonts.check('14px "Intent Sans SC"'),space:document.fonts.check('14px "Space Grotesk"'),icons:document.querySelectorAll('svg.lucide').length,accent:getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),effects:[...document.querySelectorAll('*')].filter(e=>{const s=getComputedStyle(e);return s.backdropFilter!=='none'||s.boxShadow!=='none'||s.backgroundImage.includes('gradient(');}).length}));
  assert(visuals.sans&&visuals.space);assert(visuals.icons>10);assert.equal(visuals.accent,'#30343B');assert.equal(visuals.effects,0);
  await a.screenshot({path:path.join(shots,'ai-drafts-v5-workspace.png')});
  for(const width of [360,390,740,820,1024,1512]){await a.setViewportSize({width,height:900});const sizes=await a.evaluate(()=>[innerWidth,document.documentElement.scrollWidth]);assert(sizes[1]<=sizes[0],JSON.stringify(sizes));}
  await a.setViewportSize({width:390,height:844});await a.screenshot({path:path.join(shots,'ai-drafts-v5-workspace-mobile.png'),fullPage:true});
  await a.setViewportSize({width:1512,height:1060});await a.locator('#new-goal').click();await a.waitForSelector('#home-view:not(.hidden)');await a.evaluate(()=>document.fonts.ready);await a.screenshot({path:path.join(shots,'ai-drafts-v5-home.png'),fullPage:true});
  await a.setViewportSize({width:390,height:844});await a.screenshot({path:path.join(shots,'ai-drafts-v5-home-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);const result={result:'PASS',paidCalls:0,qaDatabase:path.join(qa,'qa.sqlite3'),visuals,checks:['home draft conflict: both choices','concurrent update during conflict review','revision draft and scope refresh','session isolation and immediate navigation flush','failed draft load disables submission and reopening restores input','revision draft conflict','scope survives document refresh','accepted submission clears saved draft without resubmitting on refresh','no jobs or labels from drafts','local fonts and Lucide','no blur/shadow/gradient','360–1512px overflow']};fs.writeFileSync(path.join(root,'docs/validation/product-v5-draft-proof.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
})().catch(e=>{console.error(e);console.error(output);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
