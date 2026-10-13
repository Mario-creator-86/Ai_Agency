// Bounded backend-to-scene acceptance: one browser/page, disposable DB, no outbound network.
// The heavy owner_flows game guard remains unchanged. No fixture mutates the engine's state.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync,spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync,rmSync,writeFileSync,readFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'vite';
import {chromium} from 'playwright';

const FRONTEND=fileURLToPath(new URL('../..',import.meta.url)),ROOT=path.resolve(FRONTEND,'..');
const OUT=process.env.E2E_EVIDENCE||path.join(ROOT,'output/playwright/backend-animation-2026-10-09');
const MODES=['WORKING','THINKING','REVIEWING','BLOCKED','ERROR','IDLE'];
const LABELS={WORKING:'în lucru',THINKING:'se gândește',REVIEWING:'verifică',BLOCKED:'blocaj',ERROR:'eroare',IDLE:'în așteptare'};
const ACTORS=JSON.parse(readFileSync(path.join(ROOT,'config/pixel_actors.json'),'utf8'));

test('backend commits update eight employee labels and authorized animated poses through the real page', {timeout:150000},async()=>{
 const scratch=mkdtempSync(path.join(os.tmpdir(),'amn_animation_acceptance_'));
 const dist=path.join(scratch,'dist'),world=path.join(scratch,'world');
 let child,browser;
 const evidence={kind:'isolated real backend/outbox/WebSocket/Owner HTTP/production page; paid vendors replaced',transitions:[],errors:[]};
 try{
  mkdirSync(OUT,{recursive:true});
  await build({root:FRONTEND,logLevel:'warn',build:{outDir:dist,emptyOutDir:true}});
  child=spawn('uv',['run','--locked','python','scripts/e2e_server.py','--dist',dist,'--folder',world,'--scene-identities'],{cwd:ROOT,stdio:['ignore','pipe','pipe'],shell:process.platform==='win32'});
  let stderr='';child.stderr.on('data',c=>{stderr=(stderr+String(c)).slice(-3000);});
  const server=await new Promise((resolve,reject)=>{
   let seen='';const timer=setTimeout(()=>reject(Error('test backend did not start: '+stderr)),45000);
   child.stdout.on('data',c=>{seen+=String(c);const line=seen.split('\n').find(l=>l.trim().startsWith('{'));if(line){clearTimeout(timer);resolve(JSON.parse(line));}});
   child.on('exit',code=>{clearTimeout(timer);reject(Error('test backend exited '+code+': '+stderr));});
  });
  assert.notEqual(new URL(server.url).port,'8000');
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.on('pageerror',e=>evidence.errors.push(e.message));
  let policyReads=0,events=0,layoutReads=0,socketRoute,dropConnections=false;
  await page.routeWebSocket('**/api/v1/ws',route=>{socketRoute=route;if(dropConnections)route.close({code:1012});else route.connectToServer();});
  page.on('response',r=>{if(r.url().endsWith('/office/presentation')&&r.status()===200)policyReads++;});
  page.on('response',r=>{if(r.url().endsWith('/office/layout')&&r.status()===200)layoutReads++;});
  page.on('websocket',ws=>ws.on('framereceived',()=>events++));
  const owner=async (url,body)=>page.evaluate(async ([base,token,value])=>{
   const response=await fetch('/api/v1'+base,{method:value?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(value?{body:JSON.stringify(value)}:{})});
   return {status:response.status,body:await response.json()};
  },[url,server.token,body]);
  await page.goto(server.url);
  await page.fill('#owner-token',server.token);await page.click('#login-form button[type="submit"]');
  await page.waitForSelector('#workspace:not([hidden])');
  await page.waitForFunction(()=>window.__studio?.engine?.visiblePositions().length===8&&window.__studio.engine.visiblePositions().every(p=>window.__studio.engine.motionFor(p.agent).authorized));
  const employees=await page.evaluate(()=>window.__studio.engine.visiblePositions().map(p=>({id:p.id,name:p.agent.display_name,desk:p.deskId,x:p.x,y:p.y})));
  assert.equal(employees.length,8);
  const profiles=await page.evaluate(()=>window.__studio.engine.visiblePositions().map(p=>window.__studio.engine.profileFor(p.agent)));
  for(const profile of profiles){const expected=ACTORS.staff.find(a=>a.employee_id===profile.employeeId);assert.ok(expected);for(const [key,value] of Object.entries(expected.appearance))assert.equal(profile[key],value);}
  evidence.original_ensemble_profiles=profiles.length;
  evidence.front_portraits=[];
  for(const person of employees){
   await page.locator(`#pixel-roster [data-agent="${person.id}"]`).click();await page.waitForSelector('#agent-inspector[open]');
   const portrait=page.locator('#inspector-portrait');
   assert.equal(await portrait.getAttribute('data-orientation'),'front');
   assert.equal(await portrait.getAttribute('data-portrait-source'),'native_atlas');
   const info=await page.evaluate(id=>{const e=window.__studio.engine;return e.renderer.portraitInfo(e.agents.find(a=>a.id===id));},person.id);
   assert.equal(await portrait.getAttribute('data-background-role'),info.background_role);
   const pixels=await portrait.locator('canvas').evaluate(c=>{const a=c.getContext('2d').getImageData(0,0,c.width,c.height).data;const colors=new Set();for(let i=0;i<a.length;i+=4)colors.add(`${a[i]}:${a[i+1]}:${a[i+2]}`);return colors.size;});
   assert.ok(pixels>500,'portrait contains a detailed face and environment');
   await page.locator('#inspector-head').screenshot({path:path.join(OUT,'portrait-'+person.id+'.png')});
   evidence.front_portraits.push({id:person.id,name:person.name,...info,distinct_colors:pixels});
   await page.keyboard.press('Escape');await page.waitForSelector('#agent-inspector[open]',{state:'detached'});
  }
  const cropHashes=()=>page.evaluate(ids=>{const e=window.__studio.engine,v=e.viewport;return ids.map(id=>{
   const p=e.positions.find(p=>p.id===id),s=p.seating;
   const x=Math.ceil((s.ensemble_x-16)*v.zoom+v.panX),y=Math.ceil((s.floor_y-67)*v.zoom+v.panY);
   const pixels=e.ctx.getImageData(x,y,Math.floor(32*v.zoom),Math.floor(48*v.zoom)).data;
   let hash=2166136261;for(const b of pixels)hash=Math.imul(hash^b,16777619);return hash>>>0;
  });},employees.map(a=>a.id));
  const painted=new Map(employees.map(a=>[a.id,new Set()]));
  const read=()=>page.evaluate(ids=>{const e=window.__studio.engine;return ids.map(id=>{
   const a=e.agents.find(a=>a.id===id),p=e.positions.find(p=>p.id===id),m=e.motionFor(a),plan=e.presentation.get(id);
   const roster=document.querySelector(`#pixel-roster [data-agent="${id}"]`);
   return {id,state:a.runtime_state,version:a.version,lifecycle:a.lifecycle,mode:m.mode,action:m.action,animated:m.animate,authorized:m.authorized,planVersion:plan?.version,cycle:plan?.cycle.map(c=>c[0]),label:roster?.textContent,badge:roster?.getAttribute('data-state'),desk:p.deskId,x:p.x,y:p.y};
  });},employees.map(a=>a.id));
  const waitMode=async (state,versions)=>page.waitForFunction(([ids,mode,vs])=>{
   const e=window.__studio.engine;return ids.every((id,i)=>{const a=e.agents.find(a=>a.id===id),m=e.motionFor(a);return a.runtime_state===mode&&a.version===vs[i]&&m.authorized&&m.mode===mode;});
  },[employees.map(a=>a.id),state,versions],{timeout:4000});
  for(const state of MODES){
   const started=performance.now();
   const responses=await Promise.all(employees.map(a=>owner('/e2e/agent-state',{agent_id:a.id,runtime_state:state})));
   responses.forEach(r=>assert.equal(r.status,200));
   try{await waitMode(state,responses.map(r=>r.body.version));}catch(error){
    evidence.failed_transition={state,expected_versions:responses.map(r=>r.body.version),rows:await read(),policy_reads:policyReads,websocket_frames:events,
     engine:await page.evaluate(()=>{const e=window.__studio.engine;return {dirty:e.presentationDirty,pending:e.presentationPending,parked:e.parked,revision:e.presentationRevision,received:e.presentationReceived,connection:e.diagnostics().connection};})};
    throw error;
   }
   const elapsedMs=performance.now()-started,rows=await read();
   for(const [i,row] of rows.entries()){
    assert.equal(row.state,state);assert.equal(row.badge,state);assert.ok(row.animated&&row.authorized);
    assert.equal(row.planVersion,row.version);assert.ok(row.cycle.includes(row.action));
    assert.match(row.label,new RegExp(LABELS[state],'i'));
    assert.deepEqual([row.desk,row.x,row.y],[employees[i].desk,employees[i].x,employees[i].y]);
   }
   evidence.transitions.push({state,elapsed_ms:elapsedMs,employees:rows});
   for(let sample=0;sample<3;sample++){(await cropHashes()).forEach((h,i)=>painted.get(employees[i].id).add(h));await page.waitForTimeout(250);}
   await page.screenshot({path:path.join(OUT,'backend-'+state.toLowerCase()+'.png')});
  }
  evidence.painted_character_regions=[...painted].map(([id,hashes])=>({id,distinct_frames:hashes.size}));
  assert.ok(evidence.painted_character_regions.every(p=>p.distinct_frames>2),'all eight rendered character regions change');

  const person=employees[0],id=person.id;
  await page.locator(`#pixel-roster [data-agent="${id}"]`).click();await page.waitForSelector('#agent-inspector[open]');
  const paused=await owner(`/agents/${id}/pause`,{});assert.equal(paused.status,200);
  await page.waitForFunction(id=>{const e=window.__studio.engine,a=e.agents.find(a=>a.id===id),m=e.motionFor(a);return a.lifecycle==='PAUSED'&&m.authorized&&!m.animate&&m.monitor==='off';},id);
  await page.waitForSelector('#inspector-lifecycle[data-state="PAUSED"]');
  assert.equal(await page.locator('#inspector-head').getAttribute('data-standing'),'PAUSED');
  assert.match(await page.locator(`#pixel-roster [data-agent="${id}"]`).textContent(),/în pauză/);
  await page.waitForTimeout(300);const stopped=(await cropHashes())[0];await page.waitForTimeout(750);
  assert.equal((await cropHashes())[0],stopped,'the paused employee holds their painted body');
  assert.equal((await owner(`/agents/${id}/resume`,{})).status,200);
  await page.waitForFunction(id=>{const e=window.__studio.engine,a=e.agents.find(a=>a.id===id);return a.lifecycle==='ACTIVE'&&e.motionFor(a).authorized&&e.motionFor(a).animate;},id);
  evidence.lifecycle={pause:'visible label/inspector/monitor off/body frozen',resume:'authorized motion restored'};
  let latest;for(const state of ['WORKING','THINKING','REVIEWING'])latest=await owner('/e2e/agent-state',{agent_id:id,runtime_state:state});
  await page.waitForFunction(([id,version])=>{const e=window.__studio.engine,a=e.agents.find(a=>a.id===id);return a.version===version&&a.runtime_state==='REVIEWING'&&e.motionFor(a).authorized;},[id,latest.body.version],{timeout:4000});
  evidence.rapid_transition={state:'REVIEWING',version:latest.body.version};
  await page.waitForSelector('#inspector-state[data-state="REVIEWING"]');
  assert.equal(await page.locator('#inspector-head').getAttribute('data-state'),'REVIEWING');
  assert.equal(await page.locator('#inspector-lifecycle').getAttribute('data-state'),'ACTIVE');
  await page.keyboard.press('Escape');await page.waitForSelector('#agent-inspector[open]',{state:'detached'});

  let delayed=false,release,arrived;
  const captured=new Promise(resolve=>arrived=resolve),gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/v1/office/presentation',async route=>{
   if(delayed)return route.continue();delayed=true;const response=await route.fetch();arrived();await gate;await route.fulfill({response});
  });
  assert.equal((await owner('/e2e/agent-state',{agent_id:id,runtime_state:'WORKING'})).status,200);await captured;
  latest=await owner('/e2e/agent-state',{agent_id:id,runtime_state:'THINKING'});
  await page.waitForSelector(`#pixel-roster [data-agent="${id}"][data-state="THINKING"]`);
  const waiting=(await read()).find(a=>a.id===id);assert.equal(waiting.authorized,false);assert.equal(waiting.animated,false);
  release();
  await page.waitForFunction(([id,version])=>{const e=window.__studio.engine,a=e.agents.find(a=>a.id===id);return a.version===version&&e.motionFor(a).authorized;},[id,latest.body.version],{timeout:4000});
  await page.unroute('**/api/v1/office/presentation');
  evidence.delayed_policy='new label retained, old action refused, latest policy reread';

  const beforeLegacy=layoutReads,started=performance.now();
  const legacy=await Promise.all(employees.map(a=>owner('/e2e/agent-state',{agent_id:a.id,runtime_state:'WORKING',legacy_event:true})));
  legacy.forEach(r=>assert.equal(r.status,200));await waitMode('WORKING',legacy.map(r=>r.body.version));
  assert.ok(layoutReads>beforeLegacy);evidence.legacy_events={repaired_by:'authenticated committed layout read',elapsed_ms:performance.now()-started};

  dropConnections=true;socketRoute.close({code:1012});
  await page.waitForFunction(()=>window.__studio.engine.diagnostics().connection.socket!=='open');
  const disconnected=await owner('/e2e/agent-state',{agent_id:id,runtime_state:'ERROR'});
  await page.waitForFunction(([id,version])=>{const e=window.__studio.engine,a=e.agents.find(a=>a.id===id);return a.version===version&&a.runtime_state==='ERROR'&&e.motionFor(a).authorized;},[id,disconnected.body.version],{timeout:22000});
  const fallback=(await read()).find(a=>a.id===id);assert.ok(fallback.animated&&fallback.authorized);
  dropConnections=false;
  await page.waitForFunction(()=>window.__studio.engine.diagnostics().connection.socket==='open',{},{timeout:22000});
  assert.equal((await read()).find(a=>a.id===id).state,'ERROR');
  evidence.reconnection='missed committed state recovered by HTTP; fresh authorized motion; event socket reopened without state rewind';

  await page.route('**/api/v1/snapshot',route=>route.abort('failed'));
  await page.waitForSelector('#office-status[data-state="stale"]',{timeout:12000});
  assert.ok((await read()).every(a=>!a.animated),'stale main data freezes every employee');
  await page.unroute('**/api/v1/snapshot');
  await page.waitForSelector('#office-status[data-state="live"]',{timeout:12000});
  await page.waitForFunction(()=>window.__studio.engine.visiblePositions().every(p=>window.__studio.engine.motionFor(p.agent).animate));
  evidence.stale_recovery='all employees freeze on failed snapshot, resume after authenticated recovery';
  assert.ok(events>0,'the actual event socket delivered frames');
  evidence.policy_reads=policyReads;evidence.websocket_frames=events;
  assert.deepEqual(evidence.errors,[]);
 }finally{
  writeFileSync(path.join(OUT,'verification.json'),JSON.stringify(evidence,null,2));
  await browser?.close();
  if(child&&child.exitCode===null){if(process.platform==='win32'){
   try{execFileSync('taskkill',['/pid',String(child.pid),'/t','/f'],{stdio:'ignore'});}catch{}
  }else child.kill('SIGINT');}
  // The only deleted path is the verified temporary directory created by this test.
  assert.ok(path.resolve(scratch).startsWith(path.resolve(os.tmpdir())+path.sep));
  rmSync(scratch,{recursive:true,force:true,maxRetries:10,retryDelay:300});
 }
});
