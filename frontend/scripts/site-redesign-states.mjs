import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { chromium } from 'playwright-core';

// Deliberate boundary fixtures: exercise Next's real server/session/proxy code;
// never send email or grant an actual account during a marketing UI check.
let sendStatus = 503;
let logoutStatus = 503;
let receivedEmail;
let receivedNext;
const backend = createServer(async (req, res) => {
  res.setHeader('content-type', 'application/json');
  if (req.url === '/auth/me') {
    if (!req.headers.cookie?.includes('dash_session=site-test')) { res.statusCode=401; res.end('{}'); return; }
    res.end(JSON.stringify({ id: 1, email: 'engineer@factory.example', role: 'member', auth_provider: 'magic_link' }));
  } else if (req.url === '/auth/me/usage') res.end(JSON.stringify({ cap: 15, remaining: 12 }));
  else if (req.url === '/auth/logout-all') { res.statusCode=logoutStatus; res.end('{}'); }
  else if (req.url === '/auth/magic/start') {
    let body=''; for await (const chunk of req) body+=chunk;
    receivedEmail=body;
    receivedNext=(await new Response(body,{headers:{"content-type":req.headers["content-type"]}}).formData()).get("next");
    res.statusCode=sendStatus;
    res.end(sendStatus===200 ? '{"ok":true}' : '{"detail":{"message":"Email delivery is temporarily unavailable."}}');
  } else { res.statusCode=404;res.end('{}'); }
});
backend.listen(0,'127.0.0.1'); await once(backend,'listening');
const port=Number(process.env.E2E_SITE_STATES_PORT || 3219);
const base=`http://localhost:${port}`;
const app=spawn(process.execPath,['node_modules/next/dist/bin/next','start','--port',String(port)],{
  cwd:new URL('..',import.meta.url),
  env:{...process.env,API_BASE:`http://127.0.0.1:${backend.address().port}`,MAGIC_LINK_UI_ENABLED:'1',TURNSTILE_SITE_KEY:'1x00000000000000000000AA',PUBLIC_PASSWORD_SIGNUP_ENABLED:'0',AUTH_PROXY_SECRET:Buffer.from('site-ui-test-secret-not-a-real-secret-0000').toString('base64')},
  stdio:['ignore','pipe','pipe'],
});
let logs='';app.stdout.on('data',chunk=>logs+=chunk);app.stderr.on('data',chunk=>logs+=chunk);
let browser;
try {
  for(let i=0;i<100;i++) {
    if(app.exitCode!==null) throw new Error(logs);
    if(await fetch(base).then(r=>r.ok).catch(()=>false)) break;
    await new Promise(r=>setTimeout(r,200));
    if(i===99) throw new Error(`Site fixture did not start: ${logs}`);
  }
  browser=await chromium.launch({channel:'chrome',headless:true,args:process.env.CI?['--no-sandbox','--disable-dev-shm-usage']:[]});
  const context=await browser.newContext();
  const page=await context.newPage();
  await page.route('https://challenges.cloudflare.com/**',r=>r.fulfill({contentType:'application/javascript',body:`window.turnstile={render(el,opts){window.__token=opts;queueMicrotask(()=>opts.callback('ui-test-token'));return 'test'},reset(){queueMicrotask(()=>window.__token.callback('ui-test-token'))},remove(){}};`}));
  await page.goto(base+'/signup?next=%2Fapp%2Fmany%3Fnew%3D1');
  const email=page.getByRole('textbox',{name:'Work email',exact:true});
  await page.getByText('Work emails get 15 free checks. Personal emails get 3.',{exact:true}).waitFor();
  await email.fill('person@gmail.com');
  await page.getByText('Personal email: 3 free checks.',{exact:true}).waitFor();
  await email.fill('engineer@factory.example');
  await page.getByText('Work email: 15 free checks.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Try ScaleCAD free',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Email delivery is temporarily unavailable.'}).waitFor();
  assert.match(receivedEmail,/engineer@factory\.example/);
  assert.equal(receivedNext, '/app/many?new=1');
  sendStatus=200;
  await page.getByRole('button',{name:'Try ScaleCAD free',exact:true}).click();
  await page.getByRole('heading',{name:'Check your inbox.',exact:true}).waitFor();
  await page.getByRole('button',{name:'Use a different email'}).click();
  assert.equal(await email.inputValue(),'');
  await email.fill('person@gmail.com');
  await page.getByRole('button',{name:'Try ScaleCAD free',exact:true}).click();
  await page.getByRole('status').filter({hasText:'with 3 free checks'}).waitFor();
  await page.goto(base);
  await page.locator('.cv-upload-choice input').setInputFiles({name:'part.txt',mimeType:'text/plain',buffer:Buffer.from('invalid')});
  await page.getByRole('alert').filter({hasText:'STEP, STL and IGES'}).waitFor();
  await page.locator('.cv-upload-choice input').setInputFiles({name:'part.step',mimeType:'application/octet-stream',buffer:Buffer.from('ISO-10303-21;')});
  await page.getByRole('heading',{name:'Your part is ready.'}).waitFor();
  const fileForm = page.locator('.cv-upload-signup');
  await fileForm.getByRole('textbox', {name:'Work email',exact:true}).fill('engineer@factory.example');
  await fileForm.getByRole('button', {name:'Try ScaleCAD free',exact:true}).click();
  await fileForm.getByRole('heading', {name:'Check your inbox.',exact:true}).waitFor();
  assert.deepEqual(await page.evaluate(()=>new Promise((resolve,reject)=>{const r=indexedDB.open('scalecad-pending-part',1);r.onsuccess=()=>{const db=r.result;const q=db.transaction('parts').objectStore('parts').get('pending');q.onsuccess=()=>{resolve({name:q.result.name,email:q.result.email});db.close();};q.onerror=reject;};r.onerror=reject;})), {name:'part.step',email:'engineer@factory.example'});
  await page.getByRole('button',{name:'Use a different file'}).click();
  await page.getByRole('heading',{name:'Your part is ready.'}).waitFor({state:'hidden'});
  // With scripts disabled, the first response must already contain the signed-in navigation.
  const signed=await browser.newContext({javaScriptEnabled:false,viewport:{width:1440,height:1000}});
  await signed.addCookies([{name:'dash_session',value:'site-test',url:base}]);
  const authed=await signed.newPage();
  await authed.goto(base);
  await authed.getByText('12 of 15 checks left',{exact:true}).waitFor();
  assert.equal(await authed.getByRole('link',{name:/Try ScaleCAD free/}).count(),0);
  assert(await authed.getByRole('link',{name:/Open ScaleCAD/}).count()>0);
  await authed.setViewportSize({width:320,height:740});
  assert(await authed.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1), 'Signed-in header fits 320px');
  await signed.close();
  await context.addCookies([{name:'dash_session',value:'site-test',url:base}]);
  await page.goto(base);
  await page.getByLabel('Account', {exact:true}).click();
  await page.getByRole('button', {name:'Log out',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'This browser signed out'}).waitFor();
  assert.equal((await context.cookies()).filter(c=>c.name==='dash_session').length,0);
  logoutStatus=200;
  await context.addCookies([{name:'dash_session',value:'site-test',url:base}]);
  await page.goto(base);
  await page.getByLabel('Account', {exact:true}).click();
  await page.getByRole('button', {name:'Log out',exact:true}).click();
  await page.locator('header[data-signed-in="false"]').waitFor();

  console.log('PASS: email tiers, real proxy errors/retry/success, reset, local CAD handoff, server-rendered signed-in navigation, and logout success/failure');
} finally {
  await browser?.close();
  app.kill('SIGTERM');
  backend.close();
}
