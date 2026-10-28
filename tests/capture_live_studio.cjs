const fs=require('node:fs');const path=require('node:path');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const folder=process.argv[2];if(!folder)throw new Error('Pass an isolated live-check directory');
const result=JSON.parse(fs.readFileSync(path.join(folder,'result.json'),'utf8'));
const sid=result.result.session_id;
const temp=path.join('D:/CodexWork/temp/intent-live-browser',String(Date.now()));fs.mkdirSync(temp,{recursive:true});
const env={...process.env,TEMP:temp,TMP:temp};
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});try{
const context=await browser.newContext({viewport:{width:1512,height:1120}});const page=await context.newPage();
await page.addInitScript(id=>localStorage.setItem('intent-studio-session',id),sid);
await page.goto('http://127.0.0.1:18768');await page.waitForSelector('#workspace-view:not(.hidden) .document-section');
await page.screenshot({path:path.join(root,'docs/screenshots/ai-live-workspace.png'),animations:'disabled'});
await page.locator('[data-proposal]').first().click();await page.waitForSelector('#proposal-dialog[open]');
await page.screenshot({path:path.join(root,'docs/screenshots/ai-live-proposal.png'),animations:'disabled'});
await page.locator('[data-close=proposal-dialog]').click();await page.setViewportSize({width:390,height:844});
await page.screenshot({path:path.join(root,'docs/screenshots/ai-live-mobile.png'),animations:'disabled'});
console.log('Actual-provider artifact screenshots saved; no model request was made.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
