// Read-only UI verification of retained real model output. All POSTs are blocked.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),reportFile=process.argv[2];if(!reportFile)throw Error('Pass report.json');
const report=JSON.parse(fs.readFileSync(reportFile,'utf8')),item=report.cases.find(c=>c.status==='completed');
const env={...process.env,TEMP:'D:/CodexWork/temp',TMP:'D:/CodexWork/temp',PYTHONIOENCODING:'utf-8',PYTHONDONTWRITEBYTECODE:'1'};
const child=spawn(path.join(root,'.venv-research/Scripts/python.exe'),['-B',path.join(root,'tests/serve_live_snapshot.py'),path.dirname(report.database),'--port','18774'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let output='',browser;child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);
(async()=>{
  for(let i=0;i<80;i++){try{if((await fetch('http://127.0.0.1:18774/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const page=await browser.newPage({viewport:{width:1512,height:1060}}),errors=[],posts=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
  await page.addInitScript(sid=>localStorage.setItem('intent-studio-session',sid),item.session_id);
  await page.goto('http://127.0.0.1:18774');await page.waitForSelector('.document-section');await page.waitForFunction(()=>!document.querySelector('#revision-input').disabled);
  assert.equal(await page.locator('.document-section').count(),1);assert((await page.locator('.requirement-notice').innerText()).includes('160–220'));
  await page.screenshot({path:path.join(root,'docs/screenshots/ai-live-short-email-warning.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});const widths=await page.evaluate(()=>[innerWidth,document.documentElement.scrollWidth]);assert(widths[1]<=widths[0]);
  await page.screenshot({path:path.join(root,'docs/screenshots/ai-live-short-email-warning-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(posts,[]);const result={result:'PASS',paidCalls:0,sections:1,explicitLengthWarningVisible:true,errors,posts};fs.writeFileSync(path.join(path.dirname(reportFile),'ui-check.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);console.error(output);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
