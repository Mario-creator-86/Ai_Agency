// Original assets in real Playwright Canvas; fixture time is separate from live verification.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync,mkdirSync,writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { chromium } from 'playwright';
const FRONTEND=fileURLToPath(new URL('../..',import.meta.url)),EVIDENCE=process.env.E2E_EVIDENCE;
test('whole street loops, left edge, transparent car profiles and rotating hubs render correctly', {timeout:120000},async()=>{
 const result=await build({root:FRONTEND,configFile:false,publicDir:false,logLevel:'warn',build:{write:false,minify:false,lib:{entry:path.join(FRONTEND,'tests/fixtures/pixel_street_entry.js'),name:'Street',formats:['iife']}}});
 const code=(Array.isArray(result)?result[0]:result).output.find(o=>o.type==='chunk').code;
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1600,height:860}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.route('**/*',r=>{const u=new URL(r.request().url());
   if(u.pathname.startsWith('/assets/pixel/'))return r.fulfill({contentType:'image/png',body:readFileSync(path.join(FRONTEND,'public/assets/pixel',path.basename(u.pathname)))});
   if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><style>body{margin:0;background:#222538}canvas{display:block;image-rendering:pixelated}</style><canvas width="1600" height="860"></canvas>'});return r.abort();});
  await page.goto('http://street.invalid/');await page.addScriptTag({content:code});
  const proof=await page.evaluate(async()=>{
   await Street.loadActorAtlases();if(Street.actorAtlasStatus().loaded!==Street.actorAtlasStatus().total)throw Error('missing atlas');
   const weather=Street.normalizeWeather({available:true,condition:'clear'}),world=document.createElement('canvas');world.width=960;world.height=640;
   const ctx=world.getContext('2d'),hash=(c,x,y,w,h)=>{let n=2166136261;for(const b of c.getImageData(x,y,w,h).data)n=Math.imul(n^b,16777619);return n>>>0;};
   const opaque=(c,x,y,w,h)=>{const b=c.getImageData(x,y,w,h).data;let n=0;for(let i=3;i<b.length;i+=4)if(b[i]>128)n++;return n;};
   // This walker is at x=63.8; the preceding x=147 mask would erase it completely.
   Street.drawOutdoorLife(ctx,weather,1500,{daylight:1});const left=opaque(ctx,50,523,29,48);if(left<150)throw Error('left walker still clipped');
   const cats=[new Set(),new Set()],road=new Set();let steps=0;
   for(let t=0;t<=80000;t+=125){ctx.clearRect(0,0,960,640);const f=Street.drawOutdoorLife(ctx,weather,t,{daylight:1});
    road.add(hash(ctx,0,547,960,55));f.cats.forEach((a,i)=>cats[i].add(hash(ctx,Math.max(0,Math.floor(a.x)-25),a.y-19,50,20)));steps++;
   }
   const models=[];
   for(let variant=0;variant<4;variant++){
    const r=Street.ACTORS.atlases.cars.rows[variant],f=r.frames[0],h=Street.ACTORS.sizes.car,w=f.width*h/r.height;
    ctx.clearRect(0,0,960,640);Street.drawCar(ctx,{x:500,y:590,direction:1,variant,elapsed:0,lights:false},false);
    const base=hash(ctx,440,548,120,50),body=hash(ctx,480,560,40,10),blank=opaque(ctx,440,545,120,9);
    ctx.clearRect(0,0,960,640);Street.drawCar(ctx,{x:500,y:590,direction:1,variant,elapsed:33,lights:false},false);
    const changed=hash(ctx,440,548,120,50);if(base===changed)throw Error('wheel hub is static');if(body!==hash(ctx,480,560,40,10))throw Error('car body moves with wheels');if(blank!==0)throw Error('opaque sprite background');
    ctx.clearRect(0,0,960,640);Street.drawCar(ctx,{x:500,y:590,direction:-1,variant,elapsed:33,lights:true},true);
    if(ctx.getImageData(500,592,1,1).data[3]===0)throw Error('wet car has no reflection');
    if(ctx.getImageData(426,578,1,1).data[3]===0||ctx.getImageData(574,578,1,1).data[3]!==0)throw Error('headlights must lead left-bound traffic');
    const xs=[];for(let t=0;t<8000;t+=125){const car=Street.streetFrame(t,weather,false).car;ctx.clearRect(0,0,960,640);Street.drawCar(ctx,{...car,variant},false);xs.push(opaque(ctx,0,547,146,55));}
    if(!xs.some(n=>n>100))throw Error('car still excluded from left edge');
    // Compare the composed roof to a direct full sprite; the old road mask cut all roofs.
    let t,centre;
    for(let candidate=100;candidate<860;candidate+=20){
     const time=(1040-candidate)/.14+variant*8000,f=Street.streetFrame(time,weather,false);
     if([...f.people,...f.cats,f.bicycle,f.dog].every(a=>!a||Math.abs(a.x-candidate)>60)){t=time;centre=candidate;break;}
    }
    if(t===undefined)throw Error('fixture roof has an overlapping sidewalk actor');
    const rx=Math.round(centre)-20;ctx.clearRect(0,0,960,640);Street.drawOutdoorLife(ctx,weather,t,{daylight:1});const roof=hash(ctx,rx,555,40,10);
    const direct=document.createElement('canvas');direct.width=960;direct.height=640;Street.drawCar(direct.getContext('2d'),Street.streetFrame(t,weather,false).car,false);
    const roofWhole=roof===hash(direct.getContext('2d'),rx,555,40,10);
    models.push({variant,width:w,height:h,bodyFixed:true,hubRotates:true,backgroundClear:true,roofWhole,leftPass:true});
   }
   const bg=new Image();await new Promise(resolve=>{bg.onload=resolve;bg.src=Street.PIXEL_LAYOUT.background;});
   window.paintStreetReview=()=>{
    const c=document.querySelector('canvas').getContext('2d');c.fillStyle='#222538';c.fillRect(0,0,1600,860);c.fillStyle='#efdfb6';c.font='20px monospace';c.fillText('AMN-AI · Mașini și personaje · comparație de proporții în test',24,34);
    for(let variant=0;variant<4;variant++){
     const x=variant%2*800,y=Math.floor(variant/2)*390+60;
     c.save();c.beginPath();c.rect(x,y,790,345);c.clip();c.translate(x,y);c.scale(4,4);c.translate(-410,-506);c.imageSmoothingEnabled=false;c.drawImage(bg,0,0,960,640);
     Street.drawPedestrian(c,{...Street.streetFrame(1500,weather,false).people[0],x:438,y:572,umbrella:false});
     Street.drawCat(c,{...Street.streetFrame(5000,weather,false).cat,x:575,y:574});
     Street.drawCar(c,{x:500,y:590,direction:variant%2?-1:1,variant,elapsed:33,lights:false},false);c.restore();
    }
   };window.paintStreetReview();
   return {steps,leftWalkerPixels:left,catRasters:cats.map(c=>c.size),roadRasters:road.size,models};
  });
  assert.equal(proof.steps,641);assert.ok(proof.catRasters.every(n=>n>30));assert.ok(proof.roadRasters>100);
  if(EVIDENCE){mkdirSync(EVIDENCE,{recursive:true});writeFileSync(path.join(EVIDENCE,'street-cycle-proof.json'),JSON.stringify(proof,null,2));await page.screenshot({path:path.join(EVIDENCE,'vehicle-proportions.png'),fullPage:true});}
  assert.ok(proof.models.every(m=>m.roofWhole),JSON.stringify(proof.models));
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
