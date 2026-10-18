import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { build } from 'vite';
import { chromium } from 'playwright';

const frontend=fileURLToPath(new URL('../..',import.meta.url));
test('all five windows follow outside light while frames and indoor pixels stay intact',async()=>{
 const modules=['pixel_windows.js','pixel_environment.js','pixel_sky.js','hq_weather.js','pixel_desks.js'];
 const entry=modules.map(m=>`export * from ${JSON.stringify(path.join(frontend,'src',m).replaceAll('\\','/'))};`).join('\n');
 const built=await build({root:frontend,configFile:false,publicDir:false,logLevel:'silent',plugins:[{name:'windows-review',resolveId:id=>id.replaceAll('\\','/').endsWith('/review')||id==='review'?'\0review':null,load:id=>id==='\0review'?entry:null}],build:{write:false,minify:false,lib:{entry:'review',name:'Windows',formats:['iife']}}});
 const code=(Array.isArray(built)?built[0]:built).output.find(o=>o.type==='chunk').code;
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1536,height:1024}});
 try{
  await page.route('**/*',r=>{const u=new URL(r.request().url());if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:'<style>body{margin:0;background:#111}canvas{width:100vw;height:100vh;object-fit:contain;image-rendering:pixelated}</style><canvas id="scene" width="960" height="640"></canvas>'});if(u.pathname==='/scene.png')return r.fulfill({body:readFileSync(path.join(frontend,'public/assets/pixel/studio-detailed.png')),contentType:'image/png'});return r.abort();});
  await page.goto('http://window-review.invalid/');await page.addScriptTag({content:code});
  await page.evaluate(async()=>{window.image=new Image();image.src='/scene.png';await image.decode();});
  const results=[];
  for(const [name,date] of [['day','2026-10-17T10:00:00Z'],['night','2026-10-17T21:00:00Z'],['dusk','2026-10-17T15:20:00Z']]){
   const result=await page.evaluate(date=>{
    const c=document.querySelector('canvas');c.width=image.naturalWidth;c.height=image.naturalHeight;const ctx=c.getContext('2d');ctx.setTransform(c.width/960,0,0,c.height/640,0,0);ctx.imageSmoothingEnabled=false;
    const moment=Windows.outdoorMoment(new Date(date)),weather=Windows.normalizeWeather(null);
    ctx.drawImage(image,0,0,960,640);Windows.drawOutdoorLight(ctx,moment,weather);Windows.drawOutdoorSky(ctx,image,moment,weather);
    const before=ctx.getImageData(0,0,c.width,c.height).data;
    Windows.drawWindowViews(ctx,image,moment,weather);
    const after=ctx.getImageData(0,0,c.width,c.height).data,panes=Windows.PIXEL_LAYOUT.outdoors.windows;
    let outsideChanged=0,protectedChanged=0,frameChanged=0;
    const windows=panes.map(p=>({id:p.id,count:0,light:0}));
    for(let py=0;py<c.height;py++)for(let px=0;px<c.width;px++){
     const x=(px+.5)*960/c.width,y=(py+.5)*640/c.height;
     const i=(py*c.width+px)*4,changed=Math.max(...[0,1,2].map(n=>Math.abs(after[i+n]-before[i+n])))>3;
     const index=panes.findIndex(p=>x>=p.x&&x<p.x+p.width&&y>=p.y&&y<p.y+p.height);
     if(index<0){if(changed)outsideChanged++;continue;}
     const p=panes[index],safe=p.occluders.some(o=>x>o.x+2&&x<o.x+o.width-2&&y>o.y+2&&y<o.y+o.height-2&&(Math.max(before[i],before[i+1],before[i+2])<145));
     if(safe&&changed)protectedChanged++;
     if(changed&&p.frame_bars.some(o=>x>=o.x&&x<o.x+o.width&&y>=o.y&&y<o.y+o.height))frameChanged++;
     if(changed){windows[index].count++;windows[index].light+=(after[i]+after[i+1]+after[i+2])/3;}
    }
    for(const p of windows)p.light/=Math.max(1,p.count);
    return {phase:moment.phase,outsideChanged,protectedChanged,frameChanged,windows};
   },date);results.push(result);
   assert.equal(result.outsideChanged,0,'no walls, furniture or exterior replaced');
   assert.equal(result.protectedChanged,0,'lamps and globe occlude the window');
   assert.equal(result.frameChanged,0,'original wooden mullions and transoms remain intact');
   assert.ok(result.windows.every(p=>p.count>100),'every window has a live view');
   if(process.env.E2E_EVIDENCE){mkdirSync(process.env.E2E_EVIDENCE,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_EVIDENCE,'windows-'+name+'.png')});}
  }
  assert.equal(results[0].phase,'day');assert.equal(results[1].phase,'night');
  for(let i=0;i<5;i++)assert.ok(results[1].windows[i].light<results[0].windows[i].light*.75,JSON.stringify({day:results[0].windows[i],night:results[1].windows[i]}));
 }finally{await browser.close();}
});
