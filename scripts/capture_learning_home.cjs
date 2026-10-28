// Read-only checks of the actual running v9 service; never starts training or AI.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-v9-capture';fs.mkdirSync(temp,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
 try{
  const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),errors=[],external=[],base='http://127.0.0.1:8765';
  page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>{if(new URL(r.request().url()).hostname!=='127.0.0.1'){external.push(r.request().url());return r.abort();}return r.continue();});
  const health=await (await page.request.get(base+'/api/health')).json();assert.equal(health.version,'product-v9');assert.equal(health.database,path.join(root,'data/workbench.sqlite3'));
  const before=await (await page.request.get(base+'/api/sessions')).json();await page.goto(base);await page.waitForSelector('#try-learning-demo:not([hidden])');await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v9-home.png'),fullPage:true});await page.locator('#try-learning-demo').click();
  await page.waitForSelector('.learning-version-detail');assert((await page.locator('.learning-panel').innerText()).includes('模拟规则'));
  await page.screenshot({path:path.join(root,'docs/screenshots/product-v9-learning.png'),fullPage:true});
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session')),v=await (await page.request.get(base+'/api/sessions/'+sid)).json();
  assert.equal(v.model_config.model_id,'semantic_deep');assert.equal(v.learning.runs[0].report.data_origin,'simulation');assert.equal(v.pair_count,8);
  const sizes=[];for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:1000});const item=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('#learning-steps')).borderRadius}));assert(item.scroll<=item.width,JSON.stringify(item));assert.equal(item.radius,'16px');sizes.push(item);}
  await page.setViewportSize({width:390,height:1000});await page.screenshot({path:path.join(root,'docs/screenshots/product-v9-learning-mobile.png'),fullPage:true});
  assert.deepEqual((await (await page.request.get(base+'/api/sessions')).json()),before);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const proof={result:'PASS',paidCalls:0,health,demo:{session:sid,training_run:v.learning.active_run,pairs:v.pair_count,origin:'simulation',phase:v.model_config.phase,parameter_count:v.model_config.parameter_count},sizes,sessionRowsUnchanged:true,externalRequests:0};
  fs.writeFileSync(path.join(root,'docs/validation/product-v9-running-proof.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
