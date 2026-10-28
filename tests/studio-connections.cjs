/* Settings UX against synthetic transport only; does not contact any provider. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),stamp=String(Date.now()),temp='D:/CodexWork/temp/intent-connections-browser/'+stamp,base='http://127.0.0.1:18781';fs.mkdirSync(temp,{recursive:true});
const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),[path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(temp,'qa.sqlite3'),'--port','18781'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let browser,logs='';child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
(async()=>{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[],connects=[],paid=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/api/ai/connect'))connects.push(r.url());if(r.method()==='POST'&&/\/ai\/(generate|revise|repair)$/.test(new URL(r.url()).pathname))paid.push(r.url());});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));await page.locator('#open-settings').click();
  await page.locator('#connection-preset').selectOption('custom');await page.locator('#base-url-input').fill('https://model-a.example.test/v1');
  await page.locator('#api-key-input').fill('dummy-endpoint-a-browser-credential');await page.locator('#model-input').fill('manual/unknown-model');
  await page.locator('.connection-advanced summary').click();await page.locator('#provider-stream').uncheck();await page.locator('#provider-json').uncheck();await page.locator('#provider-temperature').uncheck();await page.locator('#provider-token-parameter').selectOption('max_completion_tokens');
  await page.locator('#save-connection-only').click();await page.waitForFunction(()=>document.querySelector('#settings-feedback').textContent.includes('没有发送模型请求'));
  assert.equal(connects.length,0);assert.equal(await page.locator('#api-key-input').inputValue(),'');assert((await page.locator('.provider-notice').innerText()).includes('model-a.example.test'));
  const configA=await (await fetch(base+'/api/ai/config')).json();assert(configA.key_configured);assert.equal(configA.model,'manual/unknown-model');assert(!JSON.stringify(configA).includes('dummy-endpoint-a-browser-credential'));
  await page.locator('#save-ai-settings').click();await page.waitForFunction(()=>document.querySelector('#settings-feedback').textContent.includes('连接正常'));
  // The synthetic /models omits the manual model; it must not be silently replaced.
  assert.equal(await page.locator('#model-input').inputValue(),'manual/unknown-model');assert.equal(connects.length,1);
  await page.locator('.model-catalog summary').click();await page.locator('#model-catalog-search').fill('missing-model');assert.equal(await page.locator('[data-catalog-model]').count(),0);
  await page.locator('#model-catalog-search').fill('FIXTURE');assert.equal(await page.locator('[data-catalog-model]').count(),1);
  await page.locator('[data-catalog-model]').click();assert.equal(await page.locator('#model-input').inputValue(),'test/fixture-model');
  assert.equal((await (await fetch(base+'/api/ai/config')).json()).model,'manual/unknown-model');assert.equal(connects.length,1);
  await page.locator('.model-catalog').screenshot({path:path.join(root,'docs/screenshots/github-reference-model-search.png')});
  await page.locator('#model-input').fill('manual/unknown-model');
  await page.locator('#connection-preset').selectOption('custom');await page.locator('#base-url-input').fill('https://model-b.example.test/v1');await page.locator('#model-input').fill('model-b');
  await page.locator('#save-connection-only').click();await page.waitForFunction(()=>document.querySelector('#connection-label').textContent==='连接你的 AI');
  const configB=await (await fetch(base+'/api/ai/config')).json();assert.equal(configB.key_configured,false);assert.equal(configB.ready,false);
  await page.locator('#connection-preset').selectOption('https://model-a.example.test/v1');assert.equal(await page.locator('#model-input').inputValue(),'manual/unknown-model');assert.equal(await page.locator('#provider-token-parameter').inputValue(),'max_completion_tokens');
  assert((await page.locator('#endpoint-key-note').innerText()).includes('已有独立保存的Key'));
  await page.locator('#connection-preset').selectOption('local');await page.locator('#model-input').fill('local/my-model');await page.locator('#save-connection-only').click();
  await page.waitForFunction(()=>document.querySelector('#connection-label').textContent.includes('本机模型'));
  const local=await (await fetch(base+'/api/ai/config')).json();assert.equal(local.key_configured,false);assert.equal(local.ready,true);
  await page.evaluate(()=>{document.querySelector('.connection-advanced').open=false;document.querySelector('.settings-scroll').scrollTop=0;});
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-model-settings.png'),fullPage:false});
  await page.setViewportSize({width:390,height:900});const dimensions=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,dialog:document.querySelector('#settings-dialog').getBoundingClientRect().width,radius:getComputedStyle(document.querySelector('#base-url-input')).borderRadius}));
  assert(dimensions.scroll<=dimensions.width);assert(dimensions.dialog<=390);assert.equal(dimensions.radius,'16px');
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v10-model-settings-mobile.png'),fullPage:false});
  assert.deepEqual(errors,[]);assert.deepEqual(paid,[]);
  const proof={result:'PASS',paidCalls:0,provider:'synthetic transport; not a real external compatibility claim',qaDatabase:temp,dimensions,checks:['manual model and endpoint','save without request','explicit models-list request only','manual unknown model retained','endpoint-scoped key not borrowed','profiles restore model and compatibility flags','local endpoint without key','destination shown to user','credential absent from public config and input after save']};
  fs.writeFileSync(path.join(root,'docs/validation/product-v10-connections-'+stamp+'.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
})().catch(e=>{console.error(e);console.error(logs);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
