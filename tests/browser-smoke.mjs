// No npm dependency. Requires Node >=22 and a local Chromium executable.
// BROWSER_EXECUTABLE=... node tests/browser-smoke.mjs
import {spawn} from 'node:child_process';
import {mkdir, readdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const base = process.env.APP_URL || 'http://127.0.0.1:8000';
const initialStatus = await (await fetch(base + '/status')).json();
assert.equal(initialStatus.status, 'success', 'App status must be available before browser checks.');
const expectedPages = String(initialStatus.data.total_pages);
const expectedDocuments = initialStatus.data.total_documents;
const artifacts = path.resolve('scratch/browser');
await mkdir(artifacts, {recursive:true});
let executable = process.env.BROWSER_EXECUTABLE;
if (!executable && process.platform === 'win32') {
  const cache = path.join(process.env.LOCALAPPDATA, 'ms-playwright');
  const versions = (await readdir(cache)).filter(name => /^chromium-\d+$/.test(name)).sort().reverse();
  if (versions.length) executable = path.join(cache, versions[0], 'chrome-win64/chrome.exe');
}
assert(executable, 'Set BROWSER_EXECUTABLE to a Chromium/Chrome executable.');
const port = Number(process.env.CDP_PORT || 9337);
const browser = spawn(executable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(artifacts,'profile')}`, 'about:blank'],
  {windowsHide:true, stdio:'ignore'});
let browserError;
browser.on('error', error => { browserError = error; });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(fn, timeout=15000) {
  const end = Date.now()+timeout;
  while(Date.now()<end) {
    if(browserError) throw browserError;
    try { const value=await fn(); if(value) return value; } catch(error) { if(error instanceof assert.AssertionError) throw error; }
    await pause(150);
  }
  throw new Error('Browser check timed out.');
}
let ws;
try {
  await waitFor(async () => (await fetch(`http://127.0.0.1:${port}/json/version`)).ok);
  const tab = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(base)}`, {method:'PUT'})).json();
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject) => { ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true}); });
  const pending = new Map(); let id=0; const errors=[];
  ws.addEventListener('message', event => {
    const message=JSON.parse(event.data);
    if(message.id) {
      const task=pending.get(message.id);
      pending.delete(message.id);
      if(message.error) task?.reject(new Error(message.error.message)); else task?.resolve(message.result);
    }
    if(message.method==='Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
    if(message.method==='Log.entryAdded' && message.params.entry.level==='error' && !message.params.entry.text.includes('favicon')) errors.push(message.params.entry.text);
  });
  const send=(method,params={}) => new Promise((resolve,reject) => { const messageId=++id; pending.set(messageId,{resolve,reject}); ws.send(JSON.stringify({id:messageId,method,params})); });
  const evaluate=async expression => {
    const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1080,deviceScaleFactor:1,mobile:false});
  await waitFor(() => evaluate(`document.querySelector('#stat-pages')?.textContent===${JSON.stringify(expectedPages)}`));
  assert.equal(await evaluate(`document.querySelectorAll('.document').length`),expectedDocuments);
  await writeFile(path.join(artifacts,'desktop.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
  await evaluate(`document.querySelector('#question').value='Siapa penanggung jawab pembicara pada rapat ke-4?'; document.querySelector('#ask-form').requestSubmit();`);
  await waitFor(() => evaluate(`!document.querySelector('#answer-section').hidden && document.querySelector('#answer-text').textContent.includes('Meydina')`),125000);
  assert(await evaluate(`document.querySelector('#sources a').getAttribute('href').includes('/pdf#page=1')`));
  await evaluate(`document.querySelector('#sources details').open=true`);
  assert(await evaluate(`document.querySelector('#sources pre').textContent.includes('Meydina')`));
  const answerMode=await evaluate(`document.querySelector('#answer-meta').textContent`);
  await writeFile(path.join(artifacts,'answer.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
  await evaluate(`document.querySelector('#reset-chat').click(); document.querySelector('#question').value='Berapa harga bitcoin hari ini?'; document.querySelector('#ask-form').requestSubmit();`);
  await waitFor(() => evaluate(`document.querySelector('#answer-meta').textContent.includes('Bukti belum ditemukan')`));
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate(`document.querySelector('#reset-chat').click(); window.scrollTo(0,0)`);
  await pause(200);
  assert(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth`),'Mobile page has horizontal overflow.');
  await writeFile(path.join(artifacts,'mobile.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
  assert.deepEqual(errors,[],'Browser errors detected.');
  console.log(JSON.stringify({passed:true,checks:['documents','statistics','ask','source links','source quotes','no evidence','mobile overflow','browser errors'],answerMode,artifacts},null,2));
} finally { ws?.close(); browser.kill(); }
