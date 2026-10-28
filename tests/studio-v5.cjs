/* Isolated product acceptance: local evidence, lazy fonts, navigation and reading. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');
const root=path.resolve(__dirname,'..'),qa=path.join('D:/CodexWork/temp/intent-v5-browser',String(Date.now()));fs.mkdirSync(qa,{recursive:true});
const env={...process.env,TEMP:qa,TMP:qa,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8'};
const child=spawn(process.env.INTENT_PYTHON||'python',['-B',path.join(root,'tests/serve_ai_fixture.py'),'--db',path.join(qa,'qa.sqlite3'),'--port','18771'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
let output='',browser;child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);
const base='http://127.0.0.1:18771',shots=path.join(root,'docs/screenshots');
async function api(url,data){const r=await fetch(base+url,data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{});assert(r.ok,await r.clone().text());return r.json();}
async function ready(){for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error(output);}
async function fits(page){const widths=await page.evaluate(()=>[innerWidth,document.documentElement.scrollWidth]);assert(widths[1]<=widths[0],JSON.stringify(widths));}
(async()=>{
  await ready();browser=await chromium.launch({headless:true,executablePath:'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe',env});
  const context=await browser.newContext({viewport:{width:1512,height:1060}}),page=await context.newPage(),errors=[],external=[],fontLoads=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(/\.(woff2|ttf)$/.test(r.url()))fontLoads.push({file:new URL(r.url()).pathname,bytes:Number(r.headers()['content-length'])});});
  await page.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){external.push(route.request().url());return route.abort();}return route.continue();});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#draft-status').textContent.includes('D 盘'));await page.evaluate(()=>document.fonts.ready);
  const initialFonts=[...fontLoads],initialFontBytes=initialFonts.reduce((n,f)=>n+f.bytes,0);
  assert(initialFontBytes>0&&initialFontBytes<2500000,JSON.stringify(initialFonts));assert(!initialFonts.some(f=>f.file.includes('SourceHan')));
  await page.screenshot({path:path.join(shots,'ai-product-v5-home.png'),fullPage:true});
  const partitions=JSON.parse(fs.readFileSync(path.join(root,'static/assets/font-partitions.json'),'utf8'));
  assert.equal(partitions.original_unicode_count,partitions.partitioned_unicode_count);
  const samples=['IntentSans-9000.woff2','IntentSans-20000.woff2'].map(name=>partitions.partitions.find(p=>p.file===name));
  await page.evaluate(chars=>{const el=document.createElement('span');el.id='font-coverage-probe';el.textContent=String.fromCodePoint(...chars);el.className='sr-only';document.body.append(el);},samples.map(s=>s.sample_unicode));await page.evaluate(()=>document.fonts.ready);
  const cdp=await context.newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');const dom=await cdp.send('DOM.getDocument');const node=await cdp.send('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#font-coverage-probe'});
  const rareFonts=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId:node.nodeId})).fonts;
  assert(rareFonts.every(f=>f.isCustomFont&&f.familyName.includes('Intent Sans SC')),JSON.stringify(rareFonts));assert.equal(rareFonts.reduce((n,f)=>n+f.glyphCount,0),2);
  for(const sample of samples)assert(fontLoads.some(f=>f.file.endsWith(sample.file)),'Rare partition not requested: '+sample.file);
  await page.evaluate(()=>document.querySelector('#font-coverage-probe').remove());

  await page.locator('#goal-input').fill('为现场演示编写一份操作说明，只使用附上的实际按钮和预算资料。');
  await page.locator('#material-files').setInputFiles({name:'实际操作.md',mimeType:'text/plain',buffer:Buffer.from('实际按钮为“导出 MD”，预算为30元。生成修改后需要预览草案，再由使用者采用。')});
  await page.waitForFunction(()=>document.querySelector('#material-chips').textContent.includes('实际操作.md'));
  await page.locator('#generate-goal').click();await page.waitForSelector('.document-section');await page.waitForFunction(()=>!document.querySelector('#revision-input').disabled);
  await page.locator('[data-edit=section2]').click();await page.locator('#section-edit-text').fill('点击“导出 PDF”，预算50元。[M1#1]\n点击“导出 MD”，预算30元。[M1#1]');
  await page.locator('#section-edit-form button[type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#edit-section-dialog').open);
  await page.locator('[data-evidence=section2]').first().click();await page.waitForSelector('#evidence-dialog[open]');
  assert((await page.locator('#evidence-content').innerText()).includes('引用原文未找到'));
  assert((await page.locator('#evidence-content').innerText()).includes('有相同文字'));
  await page.locator('#evidence-filter').selectOption('review');assert.equal(await page.locator('.evidence-paragraph').count(),1);
  await page.locator('.evidence-source summary').click();assert((await page.locator('.evidence-source p').innerText()).includes('30元'));
  await page.screenshot({path:path.join(shots,'ai-product-v5-evidence.png')});
  await page.setViewportSize({width:390,height:844});await fits(page);await page.screenshot({path:path.join(shots,'ai-product-v5-evidence-mobile.png'),fullPage:true});
  await page.locator('[data-close=evidence-dialog]').click();await page.setViewportSize({width:1512,height:1060});
  await page.locator('#toggle-focus').click();assert(await page.locator('.conversation-pane').isHidden());assert.equal(await page.locator('#toggle-focus').getAttribute('aria-pressed'),'true');
  await page.reload();await page.waitForSelector('.document-section');assert(await page.locator('.conversation-pane').isHidden());
  await page.screenshot({path:path.join(shots,'ai-product-v5-focus.png')});await page.keyboard.press('Escape');assert(await page.locator('.conversation-pane').isVisible());
  await page.keyboard.press('Control+k');assert(await page.locator('#session-search').evaluate(e=>e===document.activeElement));
  await page.locator('#session-search').fill('绝对不存在的任务名');assert((await page.locator('#studio-sessions').innerText()).includes('没有找到'));
  await page.locator('#session-search').fill('校园失物');assert.equal(await page.locator('#studio-sessions [data-session]').count(),1);await page.locator('#session-search').fill('');
  const sid=await page.evaluate(()=>localStorage.getItem('intent-studio-session'));
  const before=await api('/api/sessions/'+sid+'/audit'),delivery=await api('/api/sessions/'+sid+'/ai/delivery');
  assert.equal(delivery.evidence.sections.find(s=>s.block==='section2').review_items,2);
  const after=await api('/api/sessions/'+sid+'/audit');delete before.exported_at;delete after.exported_at;assert.deepEqual(before,after);assert.equal((await api('/api/sessions/'+sid)).pair_count,0);
  const library=await api('/api/sessions/'+sid+'/ai/materials');await api('/api/sessions/'+sid+'/ai/materials',{revision:library.revision,materials:[{name:'替换资料.md',text:'新的按钮名为导出 TXT。'}]});
  await page.reload();await page.waitForSelector('.document-section');await page.locator('[data-evidence=section2]').first().click();
  assert((await page.locator('#evidence-content').innerText()).includes('素材已移除'));await page.locator('[data-close=evidence-dialog]').click();
  await page.locator('[data-tab=sources]').click();assert.equal(await page.locator('.evidence-section-list button').count(),3);
  await page.locator('[data-tab=document]').click();await page.screenshot({path:path.join(shots,'ai-product-v5-workspace.png')});
  for(const width of [360,390,740,820,1024,1512]){await page.setViewportSize({width,height:900});await fits(page);}
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(shots,'ai-product-v5-workspace-mobile.png'),fullPage:true});
  const effects=await page.evaluate(()=>[...document.querySelectorAll('*')].filter(e=>{const s=getComputedStyle(e);return s.backdropFilter!=='none'||s.boxShadow!=='none'||s.backgroundImage.includes('gradient(');}).length);assert.equal(effects,0);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const result={result:'PASS',paidCalls:0,qaDatabase:path.join(qa,'qa.sqlite3'),initialFonts,initialFontBytes,rareFonts,unicodeCoverage:partitions.original_unicode_count,previousFullChineseFontBytes:28660328,checks:['literal evidence mismatches and source excerpts','review-only filter','removed source remains traceable','read-only audit has no event/label changes','mobile evidence dialog','focus mode persists and Escape restores editing','Ctrl+K and task search','local lazy fonts below 2.5MB','full original Unicode repertoire retained; rare BMP and supplementary glyphs load on demand','360–1512px layout','no gradients/shadows/blur','no external browser requests']};
  fs.writeFileSync(path.join(root,'docs/validation/product-v5-local-proof.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
})().catch(e=>{console.error(e);console.error(output);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill();});
