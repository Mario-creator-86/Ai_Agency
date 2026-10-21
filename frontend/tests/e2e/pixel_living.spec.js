// Explicit fixture states and local test media; no production writes or provider calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'vite';
import {chromium} from 'playwright';
const ROOT=fileURLToPath(new URL('../..',import.meta.url)),OUT=process.env.E2E_EVIDENCE;

test('living studio: backend-only diverse gestures, bounded contacts/props, real video pixels, unlocked original sound and freeze', {timeout:180000},async()=>{
 const result=await build({root:ROOT,configFile:false,publicDir:false,logLevel:'warn',build:{write:false,minify:false,lib:{entry:path.join(ROOT,'tests/fixtures/pixel_living_entry.js'),name:'Living',formats:['iife']}}});
 const code=(Array.isArray(result)?result[0]:result).output.find(o=>o.type==='chunk').code;
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1600,height:1080}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try {
  await page.route('**/*',r=>{const u=new URL(r.request().url());
   if(u.pathname.startsWith('/assets/pixel/'))return r.fulfill({contentType:'image/png',body:readFileSync(path.join(ROOT,'public/assets/pixel',path.basename(u.pathname)))});
   if(u.pathname.startsWith('/sounds/ui/'))return r.fulfill({body:readFileSync(path.join(ROOT,'public',u.pathname))});
   if(u.pathname==='/fixture.mp4'&&process.env.E2E_VIDEO)return r.fulfill({contentType:'video/mp4',body:readFileSync(process.env.E2E_VIDEO)});
   if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><style>body{margin:0;background:#222538;color:#efdfb6;font:18px monospace}canvas{width:1600px;height:1000px;image-rendering:pixelated}.studio-living-controls{position:absolute;top:50px;left:10px}</style><p>AMN-AI · SCENARII DE TEST · gesturi din politica backend</p><button id="media-preview-btn" style="position:fixed;top:8px;right:8px">Filmele studioului</button><div id="scene-viewport"><canvas width="1600" height="1000"></canvas></div>'});
   return r.abort();
  });
  await page.goto('http://living.invalid/');await page.addScriptTag({content:code});await page.evaluate(()=>Living.mountFixture());
  const monitorRepair=await page.evaluate(()=>{
   const e=window.__livingFixture.engine,c=document.createElement('canvas');c.width=960;c.height=640;
   const ctx=c.getContext('2d');ctx.drawImage(e.background,0,0,960,640);
   const before=ctx.getImageData(0,0,960,640).data;e.screens.drawArtwork(ctx);const after=ctx.getImageData(0,0,960,640).data;
   let insideChanged=0,outsideChanged=0;
   for(let y=0;y<640;y++)for(let x=0;x<960;x++){
    const i=(y*960+x)*4,changed=before[i]!==after[i]||before[i+1]!==after[i+1]||before[i+2]!==after[i+2];
    if(changed){if(x<434||x>504||y<448||y>486)outsideChanged++;else insideChanged++;}
   }
   const prior={...e.insets};e.setInsets({...prior,left:45});
   const controlLeft=parseFloat(e.livingControls.style.left);e.setInsets(prior);
   return {artworkReady:e.screens.status().artwork_ready,insideChanged,outsideChanged,controlLeft};
  });
  assert.equal(monitorRepair.artworkReady,1);assert.ok(monitorRepair.insideChanged>500);
  assert.equal(monitorRepair.outsideChanged,0);assert.ok(monitorRepair.controlLeft>45);
  const proof=await page.evaluate(async()=>{
   const f=window.__livingFixture,e=f.engine,seen=new Map(e.agents.map(a=>[a.id,new Set()]));let steps=0,maxPapers=0;
   for(const state of ['IDLE','WORKING','THINKING','REVIEWING','ERROR','BLOCKED']){
    f.setMode(state);
    for(let i=0;i<60;i++){await window.advanceTime(1000);steps++;
     const motions=e.agents.map(a=>e.motionFor(a));motions.forEach((m,i)=>{if(m.authorized)seen.get(e.agents[i].id).add(m.action);});
     if(state==='IDLE'&&i===3&&new Set(motions.map(m=>m.action)).size<2)throw Error('synchronized staff');
     const bodies=f.physics();if(bodies.length!==8||bodies.some(p=>!p.grounded||Math.abs(p.lean)>1||p.weights.some(v=>v<0||v>1)))throw Error('unstable constrained body');
     maxPapers=Math.max(maxPapers,e.roomFrame.papers.length);
     for(const p of e.roomFrame.papers){const seat=e.positions.find(s=>s.id===p.id).seating;if(p.y>seat.floor_y+.001)throw Error('paper through floor');}
    }
   }
   const actions=[...new Set([...seen.values()].flatMap(s=>[...s]))];
   if(!['coffee','hair','type','frustrated','screen_off','screen_on'].every(a=>actions.includes(a)))throw Error('missing backend action');
   const prior=e.motionFor(e.agents[0]);e.presentationReceived=Date.now()-40000;
   if(e.motionFor(e.agents[0]).authorized)throw Error('expired visual intent');f.setMode('IDLE');
   const before=f.physics();e.options.dataLive=()=>false;e.draw();const stopped=f.physics();await window.advanceTime(5000);const after=f.physics();
   if(JSON.stringify(stopped)!==JSON.stringify(after))throw Error('stale bodies moved');
   e.options.dataLive=()=>true;f.setMode('IDLE');
   const sound=[];
   for(const kind of ['key','cup','chair','paper','step','bird']){
    const ctx=new OfflineAudioContext(1,24000,24000);Living.foley(ctx,ctx.destination,kind,0,.08);const buffer=await ctx.startRendering();
    const data=buffer.getChannelData(0);let energy=0,peak=0;for(const v of data){energy+=v*v;peak=Math.max(peak,Math.abs(v));}
    if(energy<=.001||peak>=.5)throw Error('inaudible or clipping '+kind);sound.push({kind,energy,peak});
   }
   return {steps,actions,staff:[...seen].map(([id,s])=>({id,actions:[...s]})),maxPapers,paused:JSON.stringify(stopped)===JSON.stringify(after),sound};
  });
  proof.monitorRepair=monitorRepair;
  assert.equal(proof.steps,360);assert.equal(proof.maxPapers,8);assert.ok(proof.paused);
  await page.getByRole('button',{name:'Sunetul interfeței'}).click();
  assert.equal(await page.evaluate(()=>window.__livingFixture.engine.audio.status().unlocked),true);
  await page.evaluate(()=>window.advanceTime(1000));
  await page.getByRole('button',{name:'Sunetul interfeței'}).click();
  await page.waitForFunction(()=>window.__livingFixture.engine.audio.context.state==='suspended');
  await page.getByRole('button',{name:'Filmele studioului'}).click();
  assert.ok(await page.getByText('Nu există încă un film redabil în biblioteca studioului.',{exact:true}).isVisible());
  await page.getByRole('button',{name:'Închide'}).click();
  if(process.env.E2E_VIDEO){
   await page.evaluate(async()=>{const e=window.__livingFixture.engine;await e.screens.setMedia({local:[{id:'fixture-local-video',stream:'/fixture.mp4',size:500000}],youtube:[]});e.screens.active(true);});
   await page.waitForFunction(()=>window.__livingFixture.engine.screens.video?.currentTime>.3);
   const video=await page.evaluate(async()=>{const e=window.__livingFixture.engine;e.presentationReceived=Date.now();e.draw();const before=e.screens.video.currentTime;
    await new Promise(r=>setTimeout(r,600));e.draw();return {before,after:e.screens.video.currentTime,frames:e.monitorFrames};});
   assert.ok(video.after>video.before);assert.ok(video.frames.some(f=>f.source==='local_video'));proof.video=video;
   await page.evaluate(()=>window.__livingFixture.engine.screens.active(false));
  }
  if(OUT){mkdirSync(OUT,{recursive:true});writeFileSync(path.join(OUT,'living-proof.json'),JSON.stringify(proof,null,2));
   for(const state of ['IDLE','WORKING','THINKING','ERROR']){await page.evaluate(async s=>{window.__livingFixture.setMode(s);await window.advanceTime(3000);},state);await page.screenshot({path:path.join(OUT,'living-'+state.toLowerCase()+'.png'),fullPage:true});}}
  const cleared=await page.evaluate(async()=>{
   const e=window.__livingFixture.engine,s=e.screens;let finish;
   s.clear();s.fetchMedia=()=>new Promise(r=>{finish=r;});
   const pending=s.setMedia({local:[{id:'previous-context',stream:'/fixture.mp4',size:1}]});
   s.clear();finish(new Blob(['fixture']));await pending;
   if(s.asset!==null||s.url!==null||s.video!==null||s.pending)throw Error('private media reappeared after clear');
   let snapshot;s.media=null;e.presentationReceived=0;e.options.fetchPresentation=()=>new Promise(r=>{snapshot=r;});
   const request=e.refreshPresentation(true);e.park();e.parked=false;
   snapshot({schema:1,agents:[{agent_id:'previous-context'}],media:{local:[]}});await request;e.stop();
   if(e.presentation.size||s.media)throw Error('previous owner snapshot reappeared');return true;
  });
  assert.ok(cleared);
  if(OUT){proof.context_cleanup=true;writeFileSync(path.join(OUT,'living-proof.json'),JSON.stringify(proof,null,2));}
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
