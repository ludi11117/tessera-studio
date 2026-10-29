'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const windows=process.platform==='win32';
const root=path.resolve(__dirname,'..');
const tempRoot=process.env.TESSERA_TEST_TEMP||(windows?'D:/CodexWork/temp':os.tmpdir());
fs.mkdirSync(tempRoot,{recursive:true});
const temp=fs.mkdtempSync(path.join(tempRoot,'tessera-web-'));
let pw;try{pw=require(process.env.PLAYWRIGHT_MODULE||'playwright');}catch(e){if(!windows)throw e;pw=require('D:/CodexWork/cache/branchforge-browser/node_modules/playwright');}
const cached=windows?'D:/CodexWork/cache/ms-playwright/chromium-1243/chrome-win64/chrome.exe':'';
const browserPath=process.env.TESSERA_BROWSER||(fs.existsSync(cached)?cached:undefined);
const py=process.env.INTENT_PYTHON||(windows&&fs.existsSync(path.join(root,'.venv-research/Scripts/python.exe'))?path.join(root,'.venv-research/Scripts/python.exe'):'python');
const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',OPENBLAS_NUM_THREADS:'1'};
if(windows&&!env.PLAYWRIGHT_BROWSERS_PATH)env.PLAYWRIGHT_BROWSERS_PATH='D:/CodexWork/cache/ms-playwright';
module.exports={...pw,root,temp,env,py,browserPath};
