// Read-only inspection: no creation, comparisons, contract writes, or paid calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
(async()=>{
  const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-v7-preview-capture';fs.mkdirSync(temp,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
  try{
    const page=await browser.newPage({viewport:{width:1512,height:1060},reducedMotion:'reduce'}),base='http://127.0.0.1:8766',errors=[];
    const health=await (await page.request.get(base+'/api/health')).json();assert.equal(health.version,'product-v7');assert(health.database.startsWith('D:'));
    const before=await (await page.request.get(base+'/api/sessions')).json();
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1')return route.abort();return route.continue();});
    await page.goto(base);await page.waitForSelector('#preview-mode-label');await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(root,'docs/screenshots/product-v7-preview-home.png'),fullPage:true});
    await page.locator('.sample-sessions summary').click();await page.locator('[data-session]').first().click();
    await page.waitForSelector('.document-section');await page.locator('[data-tab=sources]').first().click();await page.waitForSelector('#acceptance-form');
    await page.screenshot({path:path.join(root,'docs/screenshots/product-v7-preview-contract.png'),fullPage:true});
    const sizes=[];
    for(const width of [360,390,740,820,1024,1512]){
      await page.setViewportSize({width,height:1000});
      const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,radius:getComputedStyle(document.querySelector('#acceptance-required')).borderRadius}));
      assert(size.scroll<=size.width);assert.equal(size.radius,'16px');sizes.push(size);
    }
    await page.setViewportSize({width:390,height:1000});await page.screenshot({path:path.join(root,'docs/screenshots/product-v7-preview-contract-mobile.png'),fullPage:true});
    const after=await (await page.request.get(base+'/api/sessions')).json();assert.deepEqual(after,before);
    for(const s of after.sessions){const v=await (await page.request.get(base+'/api/sessions/'+s.id)).json();assert.equal(v.pair_count,0);}
    assert.deepEqual(errors,[]);
    const proof={result:'PASS',paidCalls:0,preview:true,health,sizes,sessionRowsUnchanged:true,labels:0};
    fs.writeFileSync(path.join(root,'docs/validation/product-v7-preview-proof.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof,null,2));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
