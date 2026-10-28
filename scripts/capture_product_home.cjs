// Read-only UI check of the running local product. Browser artifacts stay on D:.
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
(async()=>{
  const root=path.resolve(__dirname,'..'),temp='D:/CodexWork/temp/intent-product-home';fs.mkdirSync(temp,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env:{...process.env,TEMP:temp,TMP:temp}});
  try{
    const fontResources=[];
    const page=await browser.newPage({viewport:{width:1512,height:1060}}),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>{const url=new URL(route.request().url());if(url.hostname!=='127.0.0.1'){external.push(url.origin);return route.abort();}return route.continue();});
    page.on('response',response=>{if(/\.(woff2|ttf)$/.test(response.url()))fontResources.push({file:new URL(response.url()).pathname,bytes:Number(response.headers()['content-length'])});if(response.status()>=400)errors.push(response.status()+' '+new URL(response.url()).pathname);});
    const health=await (await page.request.get('http://127.0.0.1:8765/api/health')).json();
    if(health.version!=='product-v7'||!health.database.startsWith('D:'))throw Error('Wrong running service');
    await page.goto('http://127.0.0.1:8765/');await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));
    await page.evaluate(()=>document.fonts.ready);
    const initialFontBytes=fontResources.reduce((n,f)=>n+f.bytes,0);
    const cdp=await page.context().newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
    const doc=await cdp.send('DOM.getDocument');
    const actualFonts={};
    for(const [name,selector] of [['title','h1'],['body','.home-lead']]){const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:doc.root.nodeId,selector});actualFonts[name]=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId})).fonts.map(f=>({family:f.familyName,custom:f.isCustomFont,glyphs:f.glyphCount}));if(!actualFonts[name].some(f=>f.custom))throw Error('Custom font did not render: '+name);}
    await page.screenshot({path:path.join(root,'docs/screenshots/ai-product-home.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    const widths=await page.evaluate(()=>[document.documentElement.clientWidth,document.documentElement.scrollWidth]);
    if(widths[1]>widths[0]||errors.length||external.length)throw new Error(JSON.stringify({widths,errors,external}));
    await page.screenshot({path:path.join(root,'docs/screenshots/ai-product-home-mobile.png'),fullPage:true,animations:'disabled'});
    const result={result:'PASS',url:page.url(),health,ownArtifacts:await page.locator('#session-count').innerText(),actualFonts,initialFontBytes,fontResources,externalRequests:external,paidCalls:0,errors};
    fs.writeFileSync(path.join(root,'docs/validation/product-v6-running-proof.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
