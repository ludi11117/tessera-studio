const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-decision-value-capture';fs.mkdirSync(temp,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
 try{
  const base='http://127.0.0.1:8765',page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),paid=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/(generate|revise|repair|train)$/.test(new URL(r.url()).pathname))paid.push(r.url());});
  await page.addInitScript(()=>localStorage.setItem('tessera-workspace-mode','full'));await page.goto(base);await page.waitForSelector('#try-learning-demo:not([hidden])');await page.locator('#try-learning-demo').click();await page.waitForSelector('.learning-version-detail');
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session'));
  const before=await (await fetch(base+'/api/sessions/'+sid)).json();
  await page.locator('.artifact-tabs [data-tab=decision]').click();await page.waitForSelector('[data-preview-minimax]');
  const r=await (await page.request.post(base+'/api/sessions/'+sid+'/decision',{data:{revision:before.revision}})).json();assert.equal(r.stability.hypotheses,3);
  await page.locator('.decision-card').filter({has:page.locator('[data-preview-minimax]')}).screenshot({path:path.join(root,'docs/screenshots/decision-value-stability.png')});
  await page.setViewportSize({width:390,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('[data-preview-minimax]').click();const after=await (await fetch(base+'/api/sessions/'+sid)).json();assert.deepEqual(after.state,before.state);assert.equal(after.revision,before.revision);assert.deepEqual(errors,[]);assert.deepEqual(paid,[]);
  const proof={result:'PASS',paidCalls:0,session:sid,stability:r.stability,originalStateUnchanged:true,mobileNoOverflow:true};
  fs.writeFileSync(path.join(root,'docs/validation/decision-value-running-proof.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
