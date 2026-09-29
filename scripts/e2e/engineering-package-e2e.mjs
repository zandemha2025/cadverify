// Run against an isolated local stack with a valid session fixture produced by
// its test-data setup. No production credentials or synthetic customer claims.
import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {chromium}=require('playwright-core');
const base=process.env.APP_URL || 'http://localhost:3047';
const fixture=JSON.parse(await readFile(process.env.E2E_SESSION_FILE || '/tmp/cadverify-engineering-browser.json','utf8'));
const out=process.env.E2E_ARTIFACT_DIR || 'outputs/product-discovery-2026-09-29/evidence/implementation-browser';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
await context.addCookies([{name:'dash_session',value:fixture.cookie,url:base,httpOnly:true,sameSite:'Lax'}]);
await context.addInitScript(()=>localStorage.setItem('proofshape_welcome_v2','1'));
const page=await context.newPage();const errors=[];const steps=[];
page.setDefaultTimeout(15000);
page.on('pageerror',e=>errors.push(e.message));
const mutation=()=>page.waitForResponse(r=>r.url().endsWith('/api/proxy/engineering-packages') && r.request().method()==='POST');
try {
 await page.goto(base+'/verify');
 await page.getByRole('button',{name:'Parts',exact:true}).click();
 await page.getByText('BR214-browser.stl',{exact:true}).first().click();
 await page.getByRole('button',{name:'Open standing →'}).click();
 const panel=page.getByRole('region',{name:'Engineering package',exact:true});
 await panel.getByRole('heading',{name:'Engineering package',exact:true}).waitFor();
 await panel.getByRole('button',{name:'New order package',exact:true}).click();
 const invalidWait=mutation();await panel.getByRole('button',{name:'Save and assess package',exact:true}).click();
 assert.equal((await invalidWait).status(),422);
 await panel.getByRole('alert').filter({hasText:/revision/}).waitFor();steps.push('Invalid input remains editable with a specific server validation message');
 async function section(n){const s=panel.locator('fieldset > details').nth(n-1);if(await s.getAttribute('open')===null) await s.locator(':scope > summary').click();return s;}
 const order=await section(1);
 for(const [label,value] of Object.entries({'Part number':'BR214','Authorized revision':'C','Order / configuration':'Browser-'+Date.now(),'Order quantity':'40','Process':'cnc_3axis','Exact material':'Mild Steel','Machine':'M07','Setup / fixture':'S1','Inspection method':'CMM'})) await order.getByLabel(label,{exact:true}).fill(value);
 const sources=await section(2);
 async function addSource(id,name,kind,authority){
  const form=sources.locator('form');await form.getByLabel('Source identifier',{exact:true}).fill(id);await form.getByLabel('Document name',{exact:true}).fill(name);await form.getByLabel('Document type',{exact:true}).selectOption(kind);await form.getByLabel('Document revision',{exact:true}).fill('C');await form.getByLabel('Controlled reference / document-system link',{exact:true}).fill('DMS/'+id+'/C');await form.getByLabel('Source authority',{exact:true}).selectOption(authority);await form.getByLabel('Characteristic coverage',{exact:true}).selectOption('complete');
  if(kind==='evidence') await form.getByLabel('Original file',{exact:true}).setInputFiles({name:'study.txt',mimeType:'text/plain',buffer:Buffer.from('Illustrative measured capability / inspection study for browser QA only.')});
  await form.getByRole('button',{name:'Add source',exact:true}).click();await sources.getByText(name,{exact:true}).waitFor();
 }
 await addSource('drawing','BR214 drawing','drawing','controlling');await addSource('study','Measured study','evidence','supporting');
 const reqs=await section(3); const reqForm=reqs.locator('form');
 for(const [label,value] of Object.entries({'Characteristic identifier':'bore','Characteristic name':'Bore diameter','Feature / datum identifier':'B1','Original value / requirement text':'20','Units':'mm','Lower limit':'19.95','Upper limit':'20.05','Sheet / zone / clause / PMI identifier':'Sheet 1 B4'})) await reqForm.getByLabel(label,{exact:true}).fill(value);
 await reqForm.getByLabel('Source document',{exact:true}).selectOption('drawing');await reqForm.getByRole('button',{name:'Add requirement',exact:true}).click();
 const evidence=await section(4);
 for(const kind of ['manufacturing','inspection']){
  const form=evidence.locator('form');await form.getByLabel('Evidence identifier',{exact:true}).fill(kind);await form.getByLabel('Evidence type',{exact:true}).selectOption(kind);await form.getByLabel('Evidence source',{exact:true}).selectOption('study');await form.getByLabel('Page / section / result identifier',{exact:true}).fill('Section 2');await form.getByLabel('What does it establish?',{exact:true}).selectOption('supports');await form.getByLabel('Engineering rationale / limitations',{exact:true}).fill('Reviewed test-fixture study; scoped to B1 and setup S1.');await form.getByRole('checkbox',{name:'bore: Bore diameter',exact:true}).check();await form.getByRole('button',{name:'Add evidence',exact:true}).click();await evidence.getByText(kind+' · '+kind,{exact:true}).waitFor();
 }
 async function saveWith(button){const wait=mutation();await button.click();const res=await wait;assert.equal(res.status(),201,await res.text());return res.json();}
 let saved=await saveWith(panel.getByRole('button',{name:'Save and assess package',exact:true}));assert.equal(saved.qualification,'evidence_needed');steps.push('Unreviewed package remains blocked');
 for(const container of [sources,reqs,evidence]){
  while(await container.getByRole('button',{name:'Confirm reviewed',exact:true}).count()) saved=await saveWith(container.getByRole('button',{name:'Confirm reviewed',exact:true}).first());
 }
 assert.equal(saved.evaluation.screening,'passed');assert.equal(saved.qualification,'reviewed_evidence');assert.equal(saved.evaluation.authorization,'not_recorded');steps.push('Explicit source, requirement and evidence review closes scoped evidence gaps');
 await panel.getByLabel('Reviewer note / decision rationale',{exact:true}).fill('Browser QA: review packet only, no manufacturing authorization.');
 const issued=await saveWith(panel.getByRole('button',{name:'Issue decision packet',exact:true}));assert.equal(issued.state,'issued');
 const pdf=await context.request.get(base+`/api/proxy/engineering-packages/${issued.id}/export.pdf`);assert.equal(pdf.status(),200);assert((await pdf.body()).subarray(0,4).equals(Buffer.from('%PDF')));steps.push('Immutable issued packet exports as PDF');
 await order.getByLabel('Authorized revision',{exact:true}).fill('D');await reqs.getByRole('button',{name:'Edit requirement',exact:true}).first().click();await reqs.locator('form').getByLabel('Lower limit',{exact:true}).fill('19.99');await reqs.locator('form').getByLabel('Upper limit',{exact:true}).fill('20.01');await reqs.getByRole('button',{name:'Update requirement',exact:true}).click();
 let changed=await saveWith(panel.getByRole('button',{name:'Save and assess package',exact:true}));assert.equal(changed.evaluation.screening,'passed');assert.equal(changed.qualification,'evidence_needed');assert.deepEqual(changed.evaluation.changes.changed_requirements,['bore']);assert(changed.evaluation.blockers.some(b=>b.kind==='manufacturing'));assert(changed.evaluation.blockers.some(b=>b.kind==='inspection'));
 const historic=await (await context.request.get(base+`/api/proxy/engineering-packages/${issued.id}`)).json();assert.equal(historic.document.revision,'C');assert.equal(historic.qualification,'reviewed_evidence');steps.push('Unchanged geometry / tighter drawing invalidates dependent evidence and preserves revision C');
 await panel.locator('fieldset > details').nth(4).locator(':scope > summary').scrollIntoViewIfNeeded();
 await page.screenshot({path:out+'/revision-consequences.png'});
 const actions=await section(5);
 await actions.getByText('Bore diameter: applicable manufacturing evidence is needed.',{exact:true}).locator('..').getByRole('button',{name:'Assign / plan closure',exact:true}).click();
 await actions.locator('form').getByLabel('Responsible person / team',{exact:true}).fill('Manufacturing engineering');
 await actions.getByRole('button',{name:'Save action to draft',exact:true}).click();
 changed=await saveWith(panel.getByRole('button',{name:'Save and assess package',exact:true}));
 assert.equal(changed.evaluation.blockers.find(b=>b.kind==='manufacturing').owner,'Manufacturing engineering');
 const outcomes=await section(7);const outcomeForm=outcomes.locator('form');
 await outcomeForm.getByLabel('Measurement / production record',{exact:true}).selectOption('study');
 await outcomeForm.getByLabel('Record location',{exact:true}).fill('QA run 1');
 await outcomeForm.getByLabel('Sample count',{exact:true}).fill('20');await outcomeForm.getByLabel('Failure count',{exact:true}).fill('3');
 await outcomeForm.getByRole('checkbox',{name:'bore: Bore diameter',exact:true}).check();
 await outcomeForm.getByLabel('Outcome / limitations',{exact:true}).fill('Synthetic QA: three bores exceeded the new upper limit.');
 await outcomeForm.getByLabel('Actual cycle minutes per part',{exact:true}).fill('8');
 await outcomes.getByRole('button',{name:'Save outcome to draft',exact:true}).click();
 changed=await saveWith(panel.getByRole('button',{name:'Save and assess package',exact:true}));
 assert(changed.evaluation.blockers.some(b=>b.kind==='outcome'));assert.equal(changed.document.outcomes[0].failures,3);steps.push('Actions retain accountable owners and failed actual outcomes create disposition blockers');
 await page.getByRole('button',{name:'Parts',exact:true}).click();await page.getByText('Engineering evidence queue',{exact:true}).click();
 await page.getByRole('button',{name:/manufacturing · Manufacturing engineering/}).click();
 await page.getByRole('button',{name:`BR214 · ${changed.order} · rev D`,exact:true}).click();
 await panel.getByRole('button',{name:'New order package',exact:true}).click();
 for(const [label,value] of Object.entries({'Part number':'BR214-reuse','Authorized revision':'E','Order / configuration':'Reuse-'+Date.now(),'Setup / fixture':'S2','Inspection method':'CMM'})) await (await section(1)).getByLabel(label,{exact:true}).fill(value);
 const reuse=await section(4);await reuse.getByRole('button',{name:'Find prior package evidence',exact:true}).click();
 await reuse.getByLabel('Prior package',{exact:false}).selectOption(changed.id);
 await reuse.getByRole('button',{name:'Import for applicability review',exact:true}).first().click();
 const candidate=await saveWith(panel.getByRole('button',{name:'Save and assess package',exact:true}));
 assert.equal(candidate.qualification,'evidence_needed');assert.deepEqual(candidate.document.evidence[0].requirement_ids,[]);assert.equal(candidate.evaluation.evidence_status[0].reason,'review_required');
 steps.push('Portfolio drilldown opens the exact order; prior evidence enters another setup as an unreviewed candidate');
 assert.deepEqual(errors,[]);await writeFile(out+'/result.json',JSON.stringify({status:'PASS',steps,consoleErrors:errors,issued:issued.id,revised:changed.id},null,2));console.log(JSON.stringify({status:'PASS',steps}));
} catch(error) {
 await page.screenshot({path:out+'/failure.png',fullPage:true});await writeFile(out+'/failure.txt',String(error)+'\n'+await page.locator('body').innerText());throw error;
} finally {await browser.close();}
