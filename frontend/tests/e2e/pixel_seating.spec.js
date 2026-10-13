// Real Playwright Canvas, isolated synthetic states; never contacts the production backend.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { chromium } from 'playwright';
const FRONTEND=fileURLToPath(new URL('../..',import.meta.url)), EVIDENCE=process.env.E2E_EVIDENCE;
test('eight integrated chairs remain grounded through 60 seconds, state transitions and pause; only upper joints move', {timeout:120000}, async()=>{
 const result=await build({root:FRONTEND,configFile:false,publicDir:false,logLevel:'warn',build:{write:false,minify:false,lib:{entry:path.join(FRONTEND,'tests/fixtures/pixel_seating_entry.js'),name:'Art',formats:['iife']}}});
 const code=(Array.isArray(result)?result[0]:result).output.find(o=>o.type==='chunk').code;
 const bible=JSON.parse(readFileSync(path.join(FRONTEND,'tests/fixtures/pixel_actors_bible.json'),'utf8'));
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1600,height:920}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.route('**/*',r=>{
   const url=new URL(r.request().url());
   if(url.pathname.startsWith('/assets/pixel/'))return r.fulfill({contentType:'image/png',body:readFileSync(path.join(FRONTEND,'public/assets/pixel',path.basename(url.pathname)))});
   if(url.pathname==='/')return r.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><style>body{margin:0;background:#222538}canvas{display:block;image-rendering:pixelated}</style><canvas width="1600" height="920"></canvas>'});
   return r.abort();
  });
  await page.goto('http://seating.invalid/');await page.addScriptTag({content:code});
  const proof=await page.evaluate(async bible=>{
   await Art.loadActorAtlases();
   if(Art.actorAtlasStatus().loaded!==Art.actorAtlasStatus().total)throw Error('missing original art');
   const bg=new Image();await new Promise(resolve=>{bg.onload=resolve;bg.src=Art.PIXEL_LAYOUT.background;});
   const c=document.querySelector('canvas').getContext('2d');c.imageSmoothingEnabled=false;
   const roles=['Director','LeadResearcher','FactChecker','ScriptWriter','VoiceArtist','VideoEditor','Publisher','Accountant'];
   const names=['Sarah','Aris','Elena','Marcus','Lyra','Kael','Vera','Nadia'];
   const members=Art.PIXEL_LAYOUT.stations.map((s,i)=>{
    const person=Art.ACTORS.staff[roles.indexOf(s.role)],a={id:person.employee_id,role_name:s.role,lifecycle:'ACTIVE',runtime_state:'IDLE'};
    return {s,i,a,profile:Art.characterProfile(a,bible.find(b=>b.employee_id===a.id)),name:names[roles.indexOf(s.role)]};
   });
   window.paintReview=(time=0,mode='IDLE',animate=true)=>{
    c.fillStyle='#222538';c.fillRect(0,0,1600,920);c.fillStyle='#efdfb6';c.font='20px monospace';c.fillText('AMN-AI · Personaj + scaun · stări de test: '+mode+' · '+(time/1000).toFixed(1)+' s',24,32);
    for(const {s,i,a,profile,name} of members){
     const x=i%4*400+16,y=Math.floor(i/4)*440+68,left=s.x-44,top=s.y-82;
     c.save();c.beginPath();c.rect(x,y,368,352);c.clip();c.translate(x,y);c.scale(4,4);c.translate(-left,-top);
     c.drawImage(bg,0,0,960,640);Art.clearEmptyChair(c,profile,s,Art.PIXEL_LAYOUT);
     Art.drawSeatedPerson(c,profile,Art.characterMotion({...a,runtime_state:mode},time,animate),s.x,s.y,s.scale,false,s.orientation,s.seating);
     c.restore();c.fillStyle='#efdfb6';c.font='18px monospace';c.fillText(name+' · '+s.role,x,y+385);
    }
   };
   const hash=(x,y,w,h)=>{const bytes=c.getImageData(Math.round(x),Math.round(y),Math.round(w),Math.round(h)).data;let n=2166136261;for(const b of bytes)n=Math.imul(n^b,16777619);return n>>>0;};
   const rows=members.map(m=>({name:m.name,feet:new Set(),chair:new Set(),head:new Set()}));
   let steps=0;
   for(let time=0;time<=60000;time+=125){
    const mode=time<15000?'IDLE':time<30000?'WORKING':time<45000?'THINKING':'REVIEWING';window.paintReview(time,mode);
    members.forEach(({s,i,profile},index)=>{
     const choice=Art.staffAtlasChoice(profile,{}),f=Art.ACTORS.atlases[choice.key].rows[choice.row].frames[0],p=Art.seatedGeometry(f,s.x,s.y,60,s.seating);
     const x=i%4*400+16+(p.left-(s.x-44))*4,y=Math.floor(i/4)*440+68+(p.top-(s.y-82))*4;
     rows[index].feet.add(hash(x,y+p.height*.57*4,p.width*4,p.height*.4*4));
     // Rear-facing chairs occupy the centre; the old side-view rectangle included moving sleeves.
     rows[index].chair.add(hash(x+p.width*.40*4,y+p.height*.56*4,p.width*.22*4,p.height*.22*4));
     rows[index].head.add(hash(x,y,p.width*4,p.height*.32*4));
    });steps++;
   }
   const last=hash(0,0,1600,920);window.paintReview(60000,'REVIEWING',false);const stopped=hash(0,0,1600,920);window.paintReview(70000,'REVIEWING',false);const stoppedLater=hash(0,0,1600,920);
   // Compare the actual ensemble region; headings deliberately display test time.
   window.paintReview(60000,'REVIEWING',false);const frozen=members.map(({i})=>hash(i%4*400+16,Math.floor(i/4)*440+68,368,352));window.paintReview(90000,'REVIEWING',false);
   const again=members.map(({i})=>hash(i%4*400+16,Math.floor(i/4)*440+68,368,352));
   return {steps,rows:rows.map(r=>({name:r.name,feet:r.feet.size,chair:r.chair.size,head:r.head.size})),frozen,again};
  },bible);
  for(const r of proof.rows){assert.equal(r.feet,1,r.name+' shoes/base/pelvis do not change');assert.equal(r.chair,1,r.name+' chair back remains fixed');assert.ok(r.head>20,r.name+' moves continuously');}
  assert.equal(proof.steps,481);assert.deepEqual(proof.frozen,proof.again);
  if(EVIDENCE){mkdirSync(EVIDENCE,{recursive:true});writeFileSync(path.join(EVIDENCE,'chair-cycle-proof.json'),JSON.stringify(proof,null,2));
   for(const [time,mode] of [[0,'IDLE'],[23000,'WORKING'],[38000,'THINKING'],[53000,'REVIEWING']]){await page.evaluate(({time,mode})=>window.paintReview(time,mode),{time,mode});await page.screenshot({path:path.join(EVIDENCE,'chairs-'+mode.toLowerCase()+'.png'),fullPage:true});}
  }
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
