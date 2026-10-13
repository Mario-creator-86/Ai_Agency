// Real Canvas, explicit fixture crossings; no production/model/backend calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'vite';
import {chromium} from 'playwright';
const FRONTEND=fileURLToPath(new URL('../..',import.meta.url)),EVIDENCE=process.env.E2E_EVIDENCE;

test('foreground plants, road gaps, clock/traffic, pets and all indoor floors have coherent depth', {timeout:120000},async()=>{
 const result=await build({root:FRONTEND,configFile:false,publicDir:false,logLevel:'warn',build:{write:false,minify:false,lib:{entry:path.join(FRONTEND,'tests/fixtures/pixel_depth_entry.js'),name:'Depth',formats:['iife']}}});
 const code=(Array.isArray(result)?result[0]:result).output.find(o=>o.type==='chunk').code;
 const bible=JSON.parse(readFileSync(path.join(FRONTEND,'tests/fixtures/pixel_actors_bible.json'),'utf8'));
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.route('**/*',r=>{const u=new URL(r.request().url());
   if(u.pathname.startsWith('/assets/pixel/'))return r.fulfill({contentType:'image/png',body:readFileSync(path.join(FRONTEND,'public/assets/pixel',path.basename(u.pathname)))});
   if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><style>body{margin:0;background:#222538}canvas{display:block;image-rendering:pixelated}</style><canvas width="1600" height="1050"></canvas>'});return r.abort();});
  await page.goto('http://depth.invalid/');await page.addScriptTag({content:code});
  const proof=await page.evaluate(async bible=>{
   await Depth.loadActorAtlases();const bg=new Image();await new Promise(resolve=>{bg.onload=resolve;bg.src=Depth.PIXEL_LAYOUT.background;});
   const weather=Depth.normalizeWeather({available:true,condition:'clear'});
   const make=()=>{const c=document.createElement('canvas');c.width=960;c.height=640;return c;};
   const snapshots=[];
   for(const [label,moment] of [['day',{daylight:1,dusk:0}],['night',{daylight:0,dusk:0}]])for(const [region,x] of [['left',65],['centre',210],['right',900]]){
    const reference=make(),r=reference.getContext('2d');r.imageSmoothingEnabled=false;r.drawImage(bg,0,0,960,640);Depth.drawOutdoorLight(r,moment,weather);
    const scene=make(),s=scene.getContext('2d');s.drawImage(reference,0,0);Depth.drawCar(s,{x,y:590,direction:-1,variant:1,elapsed:0,lights:false,ambientFilter:Depth.streetLighting(moment)},false);
    const before=s.getImageData(x-50,550,110,42).data;Depth.drawSceneForeground(s,bg,moment,weather);
    const after=s.getImageData(x-50,550,110,42).data,base=r.getImageData(x-50,550,110,42).data;
    let restored=0,visibleCar=0,incorrect=0;
    for(let i=0;i<after.length;i+=4){const changed=[0,1,2].some(k=>Math.abs(after[i+k]-before[i+k])>6);
     if(changed){restored++;if([0,1,2].some(k=>Math.abs(after[i+k]-base[i+k])>3))incorrect++;}
     else if([0,1,2].some(k=>Math.abs(before[i+k]-base[i+k])>8))visibleCar++;
    }
    if(restored<50||visibleCar<50||incorrect>10)throw Error('foreground/road gaps are incorrect: '+JSON.stringify({label,region,restored,visibleCar,incorrect}));
    snapshots.push({label,region,restored,visibleCar,incorrect});
   }
   // Two complete vehicle variant loops and both walking directions, including every edge.
   const mask=make(),m=mask.getContext('2d');Depth.drawSceneForeground(m,bg,{daylight:1,dusk:0},weather);
   const pixels=m.getImageData(0,0,960,640).data,indices=[];
   for(let i=0;i<pixels.length;i+=4)if(pixels[i+3]===255)indices.push(i);
   const route=make(),t=route.getContext('2d'),routeRestored={left:0,centre:0,right:0},variants=new Set();t.imageSmoothingEnabled=false;
   let routeFrames=0,clockInBack=0;
   for(let elapsed=0;elapsed<=64000;elapsed+=250){
    t.clearRect(0,0,960,640);t.drawImage(bg,0,0,960,640);
    Depth.drawOutdoorLight(t,{daylight:1,dusk:0},weather);
    const f=Depth.drawOutdoorLife(t,weather,elapsed,{daylight:1,dusk:0},{clock:()=>Depth.drawOutdoorClock(t,new Date('2026-10-09T09:00:00Z'),'Europe/Bucharest')});
    const before=t.getImageData(0,0,960,640).data;
    Depth.drawSceneForeground(t,bg,{daylight:1,dusk:0},weather);
    const after=t.getImageData(0,0,960,640).data;
    for(const i of indices){
     if([0,1,2].some(k=>Math.abs(after[i+k]-pixels[i+k])>1))throw Error('Foreground is behind an actor at '+elapsed+' ms / pixel '+i);
     if([0,1,2].some(k=>Math.abs(before[i+k]-after[i+k])>6)){
      const x=(i/4)%960;routeRestored[x<150?'left':x<300?'centre':'right']++;
     }
    }
    const gap=(580*960+450)*4;
    if([0,1,2,3].some(k=>before[gap+k]!==after[gap+k]))throw Error('Clear road was incorrectly masked');
    variants.add(f.car.variant);routeFrames++;
    clockInBack+=f.depthOrder.findIndex(a=>a.id==='street-clock')<f.depthOrder.findIndex(a=>a.id==='car');
   }
   if(Object.values(routeRestored).some(n=>n<100)||variants.size!==4||clockInBack!==routeFrames)throw Error('Incomplete route/depth coverage');
   // Rain, snow and fog cover the outside depth layers, while office interiors stay intact.
   const weatherProof=[];
   for(const condition of ['rain','snow','fog']){
    const canvas=make(),ctx=canvas.getContext('2d');ctx.drawImage(bg,0,0,960,640);
    Depth.drawSceneForeground(ctx,bg,{daylight:1,dusk:0},weather);
    const officeBefore=ctx.getImageData(160,145,120,70).data,streetBefore=ctx.getImageData(0,518,960,84).data;
    Depth.drawOutdoorWeather(ctx,Depth.normalizeWeather({available:true,condition}),4567);
    const officeAfter=ctx.getImageData(160,145,120,70).data,streetAfter=ctx.getImageData(0,518,960,84).data;
    if(officeBefore.some((v,i)=>v!==officeAfter[i]))throw Error(condition+' crosses the interior wall');
    if(!streetBefore.some((v,i)=>v!==streetAfter[i]))throw Error(condition+' missing from foreground street');
    weatherProof.push({condition,interiorProtected:true,outsideChanged:true});
   }
   // Clock stem behind traffic, but ahead of the sidewalk's pedestrians and bicycle.
   const world=make(),w=world.getContext('2d'),elapsed=(1040-902)/.14,frame=Depth.drawOutdoorLife(w,weather,elapsed,{daylight:1,dusk:0},{background:bg,clock:()=>Depth.drawOutdoorClock(w,new Date('2026-10-09T09:00:00Z'),'Europe/Bucharest')});
   if(frame.depthOrder.findIndex(a=>a.id==='street-clock')>=frame.depthOrder.findIndex(a=>a.id==='car'))throw Error('clock is incorrectly in front of nearer traffic');
   if(frame.depthOrder.findIndex(a=>a.id==='dog')<=frame.depthOrder.findIndex(a=>a.id==='person-2'))throw Error('pet behind its farther owner');
   const expected=make();Depth.drawOutdoorClock(expected.getContext('2d'),new Date('2026-10-09T09:00:00Z'),'Europe/Bucharest');Depth.drawCar(expected.getContext('2d'),frame.car,false);
   const a=w.getImageData(900,560,4,12).data,b=expected.getContext('2d').getImageData(900,560,4,12).data;
   if(a.some((v,i)=>v!==b[i]))throw Error('clock/traffic overlap differs from correct back-to-front composition');
   const engineCanvas=make(),engine=new Depth.OfficeEngine(engineCanvas,{parked:true,dataLive:()=>true,reducedMotion:()=>false});await engine.ready;
   engine.characters=new Map(bible.map(b=>[b.employee_id,b]));
   engine.setAgents(Depth.ACTORS.staff.map((p,i)=>({id:p.employee_id,pixel_slot:i,lifecycle:'ACTIVE',runtime_state:'IDLE'})).reverse());engine.draw();
   if(engine.depth.indoors.some((a,i,list)=>i&&a.depth<list[i-1].depth))throw Error('indoor painter order follows roster instead of floor');
   const contacts=engine.visiblePositions().map(p=>({id:p.id,floor:p.seating.floor_y,x:p.seating.ensemble_x}));
   if(contacts.length!==8)throw Error('missing personal seats');
   const indoorOrder=engine.depth.indoors,expectedHits=indoorOrder.map(p=>p.id).reverse();
   if(engine.renderer.hits.some((h,i)=>h.agent.id!==expectedHits[i]))throw Error('Pointer order disagrees with painted depth');
   // Explicit overlapping fixture: the nearer employee must receive a pointer hit.
   const personalPositions=engine.positions,far=personalPositions[0],near=personalPositions[1];
   engine.positions=[{...far,x:300,y:375,seating:{...far.seating,floor_y:374}},
     {...near,x:300,y:375,seating:{...near.seating,floor_y:375}}];engine.syncHits();
   const hit=engine.renderer.hits.find(h=>300>=h.x&&300<=h.x+h.w&&350>=h.y&&350<=h.y+h.h);
   if(hit.agent.id!==near.id)throw Error('Covered rear person steals the front person pointer target');
   engine.positions=personalPositions;engine.syncHits();engine.park();
   const c=document.querySelector('canvas').getContext('2d');
   window.paintDepthReview=()=>{
    c.fillStyle='#222538';c.fillRect(0,0,1600,1050);c.fillStyle='#efdfb6';c.font='20px monospace';c.fillText('AMN-AI · Verificare front / back · scenarii de test',24,30);
    for(let index=0;index<4;index++){
     const night=index>=2,source=make(),s=source.getContext('2d'),moment={daylight:night?0:1,dusk:0};s.imageSmoothingEnabled=false;s.drawImage(bg,0,0,960,640);Depth.drawOutdoorLight(s,moment,weather);
     const elapsed=(1040-(index%2?902:65))/.14+8000;
     Depth.drawOutdoorLife(s,weather,elapsed,moment,{background:bg,clock:()=>Depth.drawOutdoorClock(s,new Date('2026-10-09T09:00:00Z'),'Europe/Bucharest')});
     const left=index%2?805:0,x=index%2*800,y=Math.floor(index/2)*500+60;
     c.drawImage(source,left,510,155,110,x,y,775,550);
     c.fillStyle='#efdfb6';c.fillText((night?'Noapte':'Zi')+' · '+(index%2?'ceas în spate, trafic în față':'vegetație în față, trafic în spate'),x+12,y-10);
    }
   };window.paintDepthReview();
   return {snapshots,foreground:Depth.foregroundStatus(bg),routeFrames,routeRestored,carVariants:[...variants],weatherProof,streetOrder:frame.depthOrder,contacts,indoorOrder,pointerFrontmost:true};
  },bible);
  if(EVIDENCE){mkdirSync(EVIDENCE,{recursive:true});writeFileSync(path.join(EVIDENCE,'depth-cycle-proof.json'),JSON.stringify(proof,null,2));await page.screenshot({path:path.join(EVIDENCE,'depth-crossings.png'),fullPage:true});}
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
