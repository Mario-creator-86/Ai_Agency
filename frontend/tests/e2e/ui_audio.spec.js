import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {build} from 'vite';
import {chromium} from 'playwright';
const root=fileURLToPath(new URL('../..',import.meta.url));
test('real samples decode and play, OFF silences previews and effects, state persists and bursts are bounded',async()=>{
 const built=await build({root,configFile:false,publicDir:false,logLevel:'silent',build:{write:false,minify:false,lib:{entry:path.join(root,'src/pixel_sound.js'),name:'AudioReview',formats:['iife']}}});
 const code=(Array.isArray(built)?built[0]:built).output.find(x=>x.type==='chunk').code;
 const browser=await chromium.launch({headless:true,args:['--autoplay-policy=user-gesture-required']});const page=await browser.newPage();const errors=[],proof={};page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.route('**/*',r=>{
   const u=new URL(r.request().url());if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:'<button id="toggle">Sunet ON/OFF</button><button id="gesture">Interacțiune</button>'});
   if(u.pathname.startsWith('/sounds/ui/'))return r.fulfill({body:readFileSync(path.join(root,'public',u.pathname)),contentType:u.pathname.endsWith('.ogg')?'audio/ogg':'audio/wav'});
   return r.abort();
  });
  async function mount(){await page.addScriptTag({content:code});await page.evaluate(()=>{window.sound=new AudioReview.StudioAudio();document.getElementById('toggle').onclick=()=>sound.toggle();});}
  await page.goto('http://sound-review.invalid/');await mount();assert.equal(await page.evaluate(()=>sound.context),null);
  await page.locator('#toggle').click();await page.waitForFunction(()=>sound.status().samples===8);assert.deepEqual(await page.evaluate(()=>sound.status().loadErrors),[]);
  proof.on=await page.evaluate(()=>sound.status());assert.equal(proof.on.enabled,true);assert.equal(proof.on.state,'running');
  await page.evaluate(()=>{const video=document.createElement('video');video.id='preview';video.setAttribute('src','/produced-film.mp4');document.body.append(video);});
  assert.equal(await page.locator('#preview').evaluate(e=>e.muted),false);
  const signal=await page.evaluate(async()=>{
   const analyser=sound.context.createAnalyser();sound.master.connect(analyser);const samples=new Float32Array(analyser.fftSize);let rms=0;
   sound.onEvent({event_id:'task-one',event_type:'agent.run_completed',timestamp:new Date().toISOString(),payload:{status:'SUCCEEDED'}},true);
   for(let i=0;i<35;i++){await new Promise(r=>setTimeout(r,16));analyser.getFloatTimeDomainData(samples);rms=Math.max(rms,Math.sqrt(samples.reduce((n,x)=>n+x*x,0)/samples.length));}
   sound.master.disconnect(analyser);return rms;
  });proof.measuredRms=signal;assert.ok(signal>0.00001,'decoded task cue produces an actual audio signal');
  await page.waitForTimeout(1600);const before=await page.evaluate(()=>sound.events);
  await page.evaluate(()=>{for(let i=0;i<30;i++)sound.onEvent({event_id:'burst-'+i,event_type:i===29?'media.render_failed':'agent.run_completed',timestamp:new Date().toISOString(),payload:{status:'SUCCEEDED'}},true);});
  await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>sound.events),before+1);assert.ok(await page.evaluate(()=>sound.last.has('cue:error')));proof.burstEvents=1;
  await page.locator('#toggle').click();await page.waitForFunction(()=>sound.context.state==='suspended');
  proof.off=await page.evaluate(()=>sound.status());assert.equal(proof.off.enabled,false);assert.equal(proof.off.sources,0);assert.equal(await page.evaluate(()=>sound.master.gain.value),0);
  assert.equal(await page.locator('#preview').evaluate(e=>e.muted),true);assert.equal(await page.locator('#preview').getAttribute('src'),'/produced-film.mp4');
  const count=proof.off.events;await page.evaluate(()=>sound.onEvent({event_id:'muted',event_type:'publishing.video_published',timestamp:new Date().toISOString(),payload:{}},true));await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>sound.events),count);
  await page.reload();await mount();assert.equal(await page.evaluate(()=>sound.enabled),false);
  await page.locator('#toggle').click();await page.waitForFunction(()=>sound.unlocked);await page.reload();await mount();assert.equal(await page.evaluate(()=>sound.enabled),true);assert.equal(await page.evaluate(()=>sound.context),null);
  await page.locator('#gesture').click();await page.waitForFunction(()=>sound.context?.state==='running');proof.savedOnRequiresGesture=true;
  await page.evaluate(async()=>{sound.pause();await new Promise(r=>setTimeout(r,30));sound.context.resume=()=>Promise.reject(Error('browser refused'));sound.unlocked=false;});
  await page.locator('#gesture').click();await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>sound.unlocked),false);assert.equal(await page.evaluate(()=>sound.sources.size),0);proof.refusedResumeIsSilent=true;
  await page.locator('#toggle').click();assert.equal(await page.evaluate(()=>sound.enabled),false);assert.deepEqual(errors,[]);
  if(process.env.E2E_EVIDENCE){mkdirSync(process.env.E2E_EVIDENCE,{recursive:true});writeFileSync(path.join(process.env.E2E_EVIDENCE,'sound-verification.json'),JSON.stringify(proof,null,2));}
 }finally{await browser.close();}
});
