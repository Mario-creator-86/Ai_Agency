import {MAP_SIZE,BUILDINGS,FOUNTAIN,CEO_START,HALL,HALL_FRONT,VILLAGE_ENTRY,PROPS,CODE_PROPS,EFFECTS,worldPoint,pixelPoint,isWalkable,findPath,smoothPath,nearestWalkable,homeOf} from './village-layout.js';

// Everything drawn here is presentation. Movement, effects and sound never consume AI and
// never prove work: "working", speech bubbles with text and meetings come from backend state.
const WALK_ROWS=[0,1,2,1];
const DIR={left:0,right:1,front:2,back:3};
const query=new URLSearchParams(globalThis.location?.search||'');
const wpt=(p)=>worldPoint(p[0],p[1]);
const dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
const rand=(a,b)=>a+Math.random()*(b-a);
const pairKey=(a,b)=>[a,b].sort().join('|');

export function bucharestHour(){const forced=Number(query.get('hour'));if(query.has('hour')&&Number.isFinite(forced))return forced;const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Bucharest',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(x=>[x.type,x.value]));return Number(p.hour)+Number(p.minute)/60;}
// Sunrise and sunset in Bucharest (44.43 N, 26.10 E) for a date, in local hours (NOAA approximation).
export function sunTimes(date=new Date()){const rad=Math.PI/180,start=Date.UTC(date.getUTCFullYear(),0,0),day=Math.floor((date-start)/864e5);
 const g=2*Math.PI/365*(day-1),decl=.006918-.399912*Math.cos(g)+.070257*Math.sin(g)-.006758*Math.cos(2*g)+.000907*Math.sin(2*g)-.002697*Math.cos(3*g)+.00148*Math.sin(3*g);
 const eq=229.18*(.000075+.001868*Math.cos(g)-.032077*Math.sin(g)-.014615*Math.cos(2*g)-.040849*Math.sin(2*g)),lat=44.43*rad;
 const ha=Math.acos(Math.cos(90.833*rad)/(Math.cos(lat)*Math.cos(decl))-Math.tan(lat)*Math.tan(decl))/rad;
 const offset=-new Date(date.toLocaleString('en-US',{timeZone:'UTC'})).getTime()/36e5+new Date(date.toLocaleString('en-US',{timeZone:'Europe/Bucharest'})).getTime()/36e5;
 const noon=(720-4*26.10-eq)/60+offset;return {sunrise:noon-ha/15,sunset:noon+ha/15};}
let sunCache={key:'',sun:null};
// 0 = full day, 1 = deep night. Twilight lasts about an hour around sunrise and sunset.
export function darkness(h,date=new Date()){const key=date.toDateString();if(sunCache.key!==key)sunCache={key,sun:sunTimes(date)};const {sunrise,sunset}=sunCache.sun;
 if(h>=sunrise+.6&&h<sunset-.4)return 0;if(h>=sunset+1.3||h<sunrise-1.1)return 1;if(h>=sunset-.4)return Math.min(1,(h-sunset+.4)/1.7);return Math.max(0,1-(h-sunrise+1.1)/1.7);}

class Ambience{
 constructor(){this.ctx=null;this.on=true;this.next=0;}
 start(){if(this.ctx||!this.on)return;try{const ctx=new AudioContext();this.ctx=ctx;this.master=ctx.createGain();this.master.gain.value=.5;this.master.connect(ctx.destination);
  // Very quiet wind: filtered brown noise with a slow swell.
  const buffer=ctx.createBuffer(1,ctx.sampleRate*4,ctx.sampleRate),data=buffer.getChannelData(0);let last=0;for(let i=0;i<data.length;i++){last=(last+.02*(Math.random()*2-1))/1.02;data[i]=last*3.2;}
  const noise=ctx.createBufferSource();noise.buffer=buffer;noise.loop=true;const lp=ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=420;const g=ctx.createGain();g.gain.value=.018;const lfo=ctx.createOscillator();lfo.frequency.value=.07;const lfoGain=ctx.createGain();lfoGain.gain.value=.008;lfo.connect(lfoGain).connect(g.gain);noise.connect(lp).connect(g).connect(this.master);noise.start();lfo.start();
  this.next=ctx.currentTime+3;}catch{this.ctx=null;}}
 setOn(on){this.on=on;if(this.ctx)this.master.gain.setTargetAtTime(on?.5:0,this.ctx.currentTime,.3);else if(on)this.start();}
 tick(night){const ctx=this.ctx;if(!ctx||!this.on||ctx.currentTime<this.next)return;this.next=ctx.currentTime+(night?rand(5,11):rand(9,24));night?this.cricket(ctx):this.bird(ctx);}
 bird(ctx){const t0=ctx.currentTime,notes=2+Math.floor(Math.random()*3),base=rand(2300,3400),pan=ctx.createStereoPanner();pan.pan.value=rand(-.8,.8);pan.connect(this.master);
  for(let i=0;i<notes;i++){const t=t0+i*rand(.11,.17),o=ctx.createOscillator(),g=ctx.createGain();o.type='sine';o.frequency.setValueAtTime(base*rand(.9,1.1),t);o.frequency.exponentialRampToValueAtTime(base*rand(1.25,1.5),t+.07);g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.022,t+.015);g.gain.exponentialRampToValueAtTime(.0001,t+.1);o.connect(g).connect(pan);o.start(t);o.stop(t+.12);}}
 cricket(ctx){const t0=ctx.currentTime;for(let i=0;i<6;i++){const t=t0+i*.06,o=ctx.createOscillator(),g=ctx.createGain();o.frequency.value=4600;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.006,t+.01);g.gain.linearRampToValueAtTime(0,t+.04);o.connect(g).connect(this.master);o.start(t);o.stop(t+.05);}}
}

export class Town {
 constructor(canvas,{select,move,nearby,encounter,sceneChange}){
  this.canvas=canvas;this.ctx=canvas.getContext('2d');this.select=select;this.onMove=move;this.onNearby=nearby;this.onEncounter=encounter;this.onScene=sceneChange;
  this.people=new Map();this.keys=new Set();this.pan={x:0,y:0};this.zoom=1;this.last=0;this.hover=null;this.meeting=false;this.scene='village';this.followScene=true;
  this.ceo={id:'mario',name:'Mario',...CEO_START,path:[],dir:2,anim:0,where:'village',hall:null,role:'ceo',speed:1.4,color:'#e6bb5b'};
  this.images={};this.load('map','/assets/village-map-v2.webp');this.load('mario','/assets/mario-sprites.webp');
  for(const name of ['bench','lamp','pine','oak','flowerbed','well','noticeboard','planter'])this.load('prop:'+name,`/assets/props/${name}.webp`);
  this.sheets=new Map();this.met=new Set();this.pending=new Set();this.seenMessages=null;
  this.fx={leaves:[],birds:[],petals:[],flies:Array.from({length:26},()=>({x:rand(20,1500),y:rand(250,1000),p:rand(0,6.28)}))};
  this.sound=new Ambience();const wake=()=>this.sound.start();window.addEventListener('pointerdown',wake,{once:true});window.addEventListener('keydown',wake,{once:true});
  this.setupInput();this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(canvas);
  requestAnimationFrame(t=>this.frame(t));
 }
 load(key,src){const img=new Image();img.src=src;img.onload=()=>img.ready=true;img.onerror=()=>img.failed=true;this.images[key]=img;return img;}
 sheet(id,base,vest){
  if(this.sheets.has(id))return this.sheets.get(id);
  const entry={ready:false,image:null};this.sheets.set(id,entry);const img=new Image();img.src=`/assets/characters/${base}.webp`;
  img.onload=()=>{if(!vest){entry.image=img;entry.ready=true;return;}
   // New hires reuse an existing sheet; a yellow work vest is painted over the torso in code.
   const c=document.createElement('canvas');c.width=img.width;c.height=img.height;const g=c.getContext('2d');g.drawImage(img,0,0);const cw=img.width/4,ch=img.height/4;
   const layer=document.createElement('canvas');layer.width=img.width;layer.height=img.height;const v=layer.getContext('2d');v.drawImage(img,0,0);v.globalCompositeOperation='source-atop';
   for(let r=0;r<4;r++)for(let col=0;col<4;col++){const side=col<2,x0=col*cw+cw*(side?.4:.35),w=cw*(side?.22:.3),y0=r*ch+ch*(r===3?.42:.33),h=ch*(r===3?.2:.24);v.fillStyle='#f4c21fe8';v.fillRect(x0,y0,w,h);v.fillStyle='#dfe6e9d0';v.fillRect(x0,y0+h*.55,w,h*.1);v.fillRect(x0,y0+h*.78,w,h*.08);}
   g.drawImage(layer,0,0);entry.image=c;entry.ready=true;};
  return entry;
 }
 // ---------- state from the backend ----------
 update(state){
  this.state=state;this.selected=state.channel;this.meeting=!!state.world.meeting;
  this.working=new Set([state.runtime.active?.agent,...state.tasks.filter(t=>t.status==='running').map(t=>t.agent)].filter(Boolean));
  this.conversation=state.runtime.conversation||(state.runtime.active?.kind==='conversation'?{a:state.runtime.active.agent,b:state.runtime.active.partner}:null);
  this.speaker=state.runtime.meeting?.speaker||null;
  for(const k of state.metToday||[])this.met.add(k);
  const staff=new Map((state.staff||[]).map(w=>[w.id,w]));
  for(const a of state.agents){if(this.people.has(a.id))continue;const w=staff.get(a.id);const home=homeOf(a.staff?a.director:a.id);
   const start=a.staff?wpt(home.door):wpt(home?.door||[770,520]);
   this.people.set(a.id,{id:a.id,name:a.name,role:a.staff?'worker':a.id==='alex'?'chief':'director',director:a.director||null,color:a.color,sheet:this.sheet(a.id,a.staff?(a.sheet||w?.profile?.sheet||'alex'):a.id,!!a.staff),...start,path:[],dir:2,anim:Math.random(),where:a.staff?'house':'village',hall:null,wait:rand(.5,3),speed:a.staff?rand(.85,1):rand(.7,.85),hold:0});}
  // Candidates arrive on foot from the road by the bridge; rejected ones walk back out.
  for(const w of state.staff||[]){if(w.status==='hired'||this.people.has(w.id)&&w.status!=='rejected')continue;
   if(w.status==='candidate'&&!this.people.has(w.id)){const s=wpt(VILLAGE_ENTRY);this.people.set(w.id,{id:w.id,name:w.name,role:'candidate',director:w.director,color:'#f2c230',sheet:this.sheet(w.id,w.profile.sheet||'alex',true),...s,path:[],dir:1,anim:0,where:'village',hall:null,wait:0,speed:.9,hold:0});}
   if(w.status==='rejected'&&this.people.get(w.id))this.people.get(w.id).role='leaving';}
  for(const p of this.people.values()){const w=staff.get(p.id);if(p.role==='candidate'&&w?.status==='hired'){p.role='worker';p.hired=true;}}
  // Real messages become speech bubbles over the speaker.
  const fresh=this.seenMessages?state.messages.filter(m=>!this.seenMessages.has(m.id)):[];this.seenMessages=new Set(state.messages.map(m=>m.id));
  for(const m of fresh){const p=m.sender==='mario'?this.ceo:this.people.get(m.sender);if(!p)continue;const at=m.text.match(/^@([\w-]+):\s*/);p.bubble={text:at?m.text.slice(at[0].length):m.text,until:performance.now()+7000};if(at)p.lookAt=at[1];}
 }
 presentInHall(){return [...this.people.values()].filter(p=>p.where==='hall'&&p.seated).map(p=>p.id);}
 setScene(scene,manual=true){if(this.scene===scene)return;this.scene=scene;if(manual)this.followScene=false;this.onScene?.(scene);}
 setSound(on){this.sound.setOn(on);}
 resize(){const b=this.canvas.getBoundingClientRect();this.width=b.width;this.height=b.height;const d=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.round(b.width*d);this.canvas.height=Math.round(b.height*d);this.ctx.setTransform(d,0,0,d,0,0);}
 view(){const top=this.width<600?133:127,bottom=118;const availableH=Math.max(250,this.height-top-bottom);const scale=Math.min((this.width-26)/MAP_SIZE.width,availableH/MAP_SIZE.height)*this.zoom;return {scale,x:(this.width-MAP_SIZE.width*scale)/2+this.pan.x,y:top+(availableH-MAP_SIZE.height*scale)/2+this.pan.y,w:MAP_SIZE.width*scale,h:MAP_SIZE.height*scale};}
 px(x,y){const v=this.view();return {x:v.x+x*v.scale,y:v.y+y*v.scale};}
 screen(x,y){const p=pixelPoint(x,y);return this.px(p.x,p.y);}
 world(x,y){const v=this.view();return worldPoint((x-v.x)/v.scale,(y-v.y)/v.scale);}
 setZoom(value){this.zoom=Math.max(.7,Math.min(3,value));this.canvas.closest('.city-panel')?.classList.toggle('zoomed',this.zoom>1.15);const b=document.getElementById('zoomReset');if(b)b.textContent=Math.round(this.zoom*100)+'%';}
 // ---------- input ----------
 setupInput(){
  const c=this.canvas;
  c.addEventListener('pointerdown',e=>{c.focus();this.drag={x:e.clientX,y:e.clientY,pan:{...this.pan},moved:false};c.setPointerCapture(e.pointerId);});
  c.addEventListener('pointermove',e=>{if(this.drag&&e.buttons){const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;if(Math.hypot(dx,dy)>5)this.drag.moved=true;if(this.drag.moved)this.pan={x:this.drag.pan.x+dx,y:this.drag.pan.y+dy};return;}const r=c.getBoundingClientRect();this.hover=this.hit(e.clientX-r.left,e.clientY-r.top);c.style.cursor=this.hover?'pointer':'grab';});
  c.addEventListener('pointerleave',()=>{this.hover=null;});
  c.addEventListener('pointerup',e=>{const dragged=this.drag?.moved;this.drag=null;if(dragged)return;const r=c.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,hit=this.hit(x,y);
   if(hit){if(hit.id==='mario')this.onNearby?.('Acasă la Mario · CEO');else if(hit.owner===null)this.onNearby?.(hit.name+' · '+hit.subtitle);else if(hit.owner&&hit.owner!=='mario'&&!this.people.has(hit.owner))this.onNearby?.(`Casa lui ${hit.name} este liberă în această versiune.`);else this.select(hit.owner||hit.id);}
   else if(this.scene==='village'&&this.ceo.where==='village'&&!this.meeting)this.ceo.path=smoothPath(this.ceo,findPath(this.ceo,this.world(x,y)));});
  c.addEventListener('wheel',e=>{e.preventDefault();this.setZoom(this.zoom*(e.deltaY>0?.93:1.07));},{passive:false});
  c.addEventListener('keydown',e=>{const key=e.key.toLowerCase();if(['arrowup','arrowdown','arrowleft','arrowright','w','a','s','d','shift'].includes(key)){e.preventDefault();this.keys.add(key);}
   if(key==='t'){const near=[...this.people.values()].filter(p=>p.where===this.ceo.where).sort((a,b)=>this.gap(a)-this.gap(b))[0];if(near)this.select(near.id);}if(key==='m')this.select('alex');});
  c.addEventListener('keyup',e=>this.keys.delete(e.key.toLowerCase()));c.addEventListener('blur',()=>this.keys.clear());window.addEventListener('blur',()=>this.keys.clear());
 }
 gap(p){return p.where==='hall'?Math.hypot(p.hall.x-(this.ceo.hall?.x||0),p.hall.y-(this.ceo.hall?.y||0))/77:dist(p,this.ceo);}
 posOf(p){if(p.where==='hall'&&p.hall)return this.px(p.hall.x,p.hall.y);return this.screen(p.x,p.y);}
 hit(x,y){
  const v=this.view(),list=[this.ceo,...this.people.values()].filter(p=>p.where!=='house'&&(this.scene==='hall'?p.where==='hall':p.where==='village'));
  for(const p of list){const s=this.posOf(p),h=(this.scene==='hall'?150:82)*v.scale;if(Math.abs(x-s.x)<h*.3&&y<s.y&&y>s.y-h)return p;}
  if(this.scene==='hall')return null;const px=(x-v.x)/v.scale,py=(y-v.y)/v.scale;
  return BUILDINGS.find(b=>px>=b.bounds[0]&&px<=b.bounds[2]&&py>=b.bounds[1]&&py<=b.bounds[3])||null;
 }
 // ---------- movement ----------
 go(p,to){const target=nearestWalkable(to);if(!target){p.path=[];return false;}p.path=smoothPath(p,findPath(p,target));p.goal=target;return p.path.length>0||dist(p,target)<.05;}
 blocked(p,nx,ny){if(p.ghostUntil>performance.now())return null;for(const o of [this.ceo,...this.people.values()]){if(o===p||o.where!==p.where||o.where!=='village')continue;const d=Math.hypot(o.x-nx,o.y-ny),limit=p.id==='mario'?.18:.34;if(d<limit&&d<Math.hypot(o.x-p.x,o.y-p.y))return o;}return null;}
 step(p,dt){
  if(!p.path.length)return false;const to=p.path[0],dx=to.x-p.x,dy=to.y-p.y,d=Math.hypot(dx,dy),amount=dt*p.speed;
  let nx=d<amount?to.x:p.x+dx/d*amount,ny=d<amount?to.y:p.y+dy/d*amount;
  if(!isWalkable(nx,ny)){if(p.goal&&!p.replanned){p.replanned=true;this.go(p,p.goal);}else p.path.shift();return false;}
  p.replanned=false;
  const other=this.blocked(p,nx,ny);
  if(other){// Walk around the other person: try a small sidestep, otherwise wait and re-plan.
   const sx=-dy/d*.06,sy=dx/d*.06;for(const k of [1,-1]){const ax=p.x+sx*k+dx/d*amount*.5,ay=p.y+sy*k+dy/d*amount*.5;if(isWalkable(ax,ay)&&!this.blocked(p,ax,ay)){p.x=ax;p.y=ay;p.blockedT=0;this.face(p,dx,dy);p.anim+=dt;return true;}}
   p.blockedT=(p.blockedT||0)+dt;p.jam=(p.jam||0)+dt;if(p.blockedT>1.6){p.blockedT=0;if(p.goal)this.go(p,p.goal);}if(p.jam>3){p.jam=0;p.ghostUntil=performance.now()+900;}this.face(p,dx,dy);return false;}
  p.blockedT=0;p.jam=Math.max(0,(p.jam||0)-dt);p.x=nx;p.y=ny;if(d<amount)p.path.shift();this.face(p,dx,dy);p.anim+=dt;return true;
 }
 face(p,dx,dy){p.dir=Math.abs(dx)>Math.abs(dy)?(dx>0?1:0):(dy>0?2:3);}
 lookAt(p,o){this.face(p,o.x-p.x,o.y-p.y);}
 stepHall(p,dt){
  if(!p.hallPath?.length)return false;const to=p.hallPath[0],dx=to.x-p.hall.x,dy=to.y-p.hall.y,d=Math.hypot(dx,dy),amount=dt*125;
  if(d<amount){p.hall.x=to.x;p.hall.y=to.y;p.hallPath.shift();}else{p.hall.x+=dx/d*amount;p.hall.y+=dy/d*amount;}this.face(p,dx,dy);p.anim+=dt;return true;
 }
 seatFor(p){if(p.id==='mario')return HALL.seats[0];if(p.role==='candidate')return HALL.seats[11];const i=HALL.assignment[p.id];return i===undefined?null:HALL.seats[i];}
 hallRoute(p,seat){const door={x:HALL.door[0],y:HALL.door[1]};if(!seat){const others=[...this.people.values()].filter(o=>o.where==='hall'&&!this.seatFor(o)).indexOf(p);return [{x:768,y:950},{x:420+Math.max(0,others)*70,y:965}];}
  if(seat.role==='foot')return [{x:768,y:985},{x:seat.x,y:seat.y}];
  const left=seat.role==='head'||seat.side==='left',aisle=left?HALL.aisles.left:HALL.aisles.right;
  if(seat.role==='head')return [{x:aisle,y:985},{x:aisle,y:seat.y},{x:seat.x-90,y:seat.y},{x:seat.x,y:seat.y}];
  return [{x:aisle,y:985},{x:aisle,y:seat.y},{x:seat.x+(left?-60:60),y:seat.y},{x:seat.x,y:seat.y}];
 }
 exitHallRoute(p){const s=p.hall;const aisle=s.x<768?HALL.aisles.left:HALL.aisles.right;return s.y>900?[{x:HALL.door[0],y:HALL.door[1]}]:[{x:aisle,y:s.y},{x:aisle,y:950},{x:HALL.door[0],y:HALL.door[1]}];}
 // The door counts as busy only while someone stands still in the doorway; after 2 s the next person squeezes out anyway.
 doorBusy(){const d=wpt(BUILDINGS.find(b=>b.id==='townhall').door);const busy=[this.ceo,...this.people.values()].some(o=>o.where==='village'&&!o.walking&&dist(o,d)<.2);if(!busy){this.doorWait=0;return false;}this.doorWait=(this.doorWait||0)+1/60;return this.doorWait<2;}
 enterHall(p){p.where='hall';p.seated=false;p.hall={x:HALL.door[0],y:HALL.door[1]};p.hallPath=this.hallRoute(p,this.seatFor(p));p.path=[];}
 leaveHall(p){p.where='village';p.hall=null;p.seated=false;const d=wpt(BUILDINGS.find(b=>b.id==='townhall').door);p.x=d.x;p.y=d.y;p.path=[];p.wait=0;p.returning=p.id!=='mario';p.ghostUntil=performance.now()+1200;this.doorWait=0;}
 home(p){return homeOf(p.role==='worker'||p.role==='candidate'?p.director:p.id);}
 yardPoint(b,center=false){const [x0,y0,x1,y1]=b.yard;return wpt(center?[(x0+x1)/2,(y0+y1)/2]:[rand(x0+8,x1-8),rand(y0+14,y1-6)]);}
 inYard(p,b){const q=pixelPoint(p.x,p.y);return q.x>=b.yard[0]-2&&q.x<=b.yard[2]+2&&q.y>=b.yard[1]-2&&q.y<=b.yard[3]+2;}
 atDoor(p,b){return dist(p,wpt(b.door))<.22;}
 // Decide what one character should be doing right now, following Mario's rules.
 brain(p,dt){
  const meeting=this.meeting&&p.role!=='leaving',home=this.home(p),townhall=BUILDINGS.find(b=>b.id==='townhall');
  const working=this.working.has(p.id)&&!meeting;
  if(p.where==='house'){if(working||p.houseUntil>performance.now())return;if(p.role==='candidate')return;// walk back out through the door
   const b=home||townhall;const d=wpt(b.door);p.where='village';p.x=d.x;p.y=d.y;p.alpha=0;p.path=[];p.wait=.3;return;}
  if(p.where==='hall'){
   if(meeting||(p.role==='candidate'&&this.meeting)){if(!p.hallPath?.length&&!p.seated){const seat=this.seatFor(p);if(seat&&Math.hypot(p.hall.x-seat.x,p.hall.y-seat.y)<2){p.seated=true;p.dir=DIR[seat.facing];}else if(!seat)p.dir=3;}return;}
   if(!p.leaving){p.leaving=true;p.seated=false;p.hallPath=this.exitHallRoute(p);}
   if(!p.hallPath.length){if(performance.now()-(this.lastExit||0)<450||this.doorBusy())return;this.lastExit=performance.now();p.leaving=false;this.leaveHall(p);}return;}
  // village
  if(meeting||(p.role==='candidate'&&!p.hired)){
   if(p.role==='candidate'&&!this.meeting){if(!p.path.length&&dist(p,wpt([828+20,528]))>.2)this.go(p,wpt([830,530]));if(!p.path.length)this.lookAt(p,this.ceo);return;}
   if(this.atDoor(p,townhall)){this.enterHall(p);return;}if(!p.path.length||p.goalKind!=='hall'){p.goalKind='hall';this.go(p,wpt(townhall.door));}return;}
  if(p.role==='leaving'){if(!p.path.length){if(dist(p,wpt(VILLAGE_ENTRY))<.3){this.people.delete(p.id);return;}this.go(p,wpt(VILLAGE_ENTRY));}return;}
  if(working){const b=home||townhall;if(this.atDoor(p,b)){p.where='house';p.path=[];return;}if(p.goalKind!=='work'||!p.path.length){p.goalKind='work';this.go(p,wpt(b.door));}return;}
  if(p.goalKind==='work'||p.goalKind==='hall')p.goalKind=null;
  if(p.goalKind==='report'&&!p.hired)p.goalKind=null;
  // Mario walks by: idle characters stop and turn toward him.
  // After a meeting the chief of staff waits with Mario in front of the Town Hall.
  if(p.role==='chief'&&p.afterMeeting){p.returning=false;const spot=wpt(HALL_FRONT.alex);if(dist(this.ceo,spot)>4&&dist(p,spot)<.2){p.afterMeeting=false;return;}if(dist(p,spot)>.15){if(!p.path.length)this.go(p,spot);}else{p.path=[];this.lookAt(p,this.ceo);}return;}
  if(p.returning&&((p.role==='worker'&&dist(p,wpt(townhall.door))>1.5)||this.inYard(p,home||townhall)||(p.role==='chief'&&!p.path.length)))p.returning=false;
  if(!p.returning&&this.ceo.where==='village'&&dist(p,this.ceo)<2&&p.goalKind!=='talk'){p.watching=true;if(p.path.length)p.paused=p.path,p.path=[];this.lookAt(p,this.ceo);return;}
  if(p.watching){p.watching=false;if(p.paused){p.path=p.paused;p.paused=null;}}
  if(p.hold>0){p.hold-=dt;if(p.partner)this.lookAt(p,p.partner);if(p.hold<=0)p.partner=null;return;}
  // A real AI conversation pulls the two speakers together.
  const c=this.conversation;if(c&&(c.a===p.id||c.b===p.id)){const other=this.people.get(c.a===p.id?c.b:c.a);if(other&&other.where==='village'){if(dist(p,other)<.55){p.path=[];this.lookAt(p,other);return;}if(!p.path.length||p.goalKind!=='talk'){p.goalKind='talk';if(c.a===p.id)this.go(p,other);}return;}}
  if(p.goalKind==='talk')p.goalKind=null;
  if(p.path.length)return;p.wait-=dt;if(p.wait>0)return;
  if(p.role==='worker'&&p.hired&&home){// A new hire first walks to the director's house and starts there.
   if(this.atDoor(p,home)){p.hired=false;p.where='house';p.houseUntil=performance.now()+8000;p.path=[];return;}if(p.goalKind!=='report'){p.goalKind='report';this.go(p,wpt(home.door));}return;}
  if(p.role==='worker'){// Workers roam the whole town along the paths.
   const spots=[[230,608],[461,282],[1070,282],[1340,282],[620,700],[920,700],[401,450],[1143,450],[221,901],[964,901],[1310,901],[700,282],[1000,608],[540,901]];
   this.go(p,wpt(spots[Math.floor(Math.random()*spots.length)]));p.wait=rand(2,6);return;}
  const b=home||townhall;// Directors stay in their own yard and pace a little.
  if(!this.inYard(p,b)){this.go(p,this.yardPoint(b,true));p.wait=rand(1,3);return;}
  this.go(p,this.yardPoint(b));p.wait=rand(3,8);
 }
 encounters(){
  const hallDoor=wpt(BUILDINGS.find(b=>b.id==='townhall').door);const list=[...this.people.values()].filter(p=>p.where==='village'&&p.role!=='leaving'&&p.role!=='candidate'&&!p.returning&&!this.meeting&&dist(p,hallDoor)>.8);
  for(const a of list){if(a.role!=='worker'||a.hold>0||!a.path.length)continue;
   for(const b of list){if(a===b||b.hold>0)continue;if(dist(a,b)>.5)continue;const key=pairKey(a.id,b.id);if(this.met.has(key)||this.pending.has(key))continue;
    // They have not talked today: stop, ask what the other is working on, both take notes.
    this.pending.add(key);this.met.add(key);for(const [x,y] of [[a,b],[b,a]]){x.hold=5.5;x.partner=y;if(x.path.length){x.paused=null;x.resume=x.goal;}x.path=[];this.lookAt(x,y);}
    a.bubble={text:`La ce lucrezi, ${b.name}?`,until:performance.now()+2800,local:true};setTimeout(()=>{b.bubble={text:'Îți arăt pe tabla de sarcini. Notăm amândoi.',until:performance.now()+2800,local:true};},2400);
    a.notes=b.notes=performance.now()+5500;Promise.resolve(this.onEncounter?.(a.id,b.id)).finally(()=>this.pending.delete(key));}
  }
 }
 tick(dt){
  const k=this.keys,ceo=this.ceo;
  if(this.meeting&&ceo.where==='village'){if(!ceo.path.length||ceo.goalKind!=='hall'){ceo.goalKind='hall';this.go(ceo,wpt(BUILDINGS.find(b=>b.id==='townhall').door));}if(this.atDoor(ceo,BUILDINGS.find(b=>b.id==='townhall')))this.enterHall(ceo);}
  if(ceo.where==='hall'){if(!this.meeting){if(!ceo.leaving){ceo.leaving=true;ceo.seated=false;ceo.hallPath=this.exitHallRoute(ceo);}if(!ceo.hallPath.length&&performance.now()-(this.lastExit||0)>650&&!this.doorBusy()){this.lastExit=performance.now();ceo.leaving=false;this.leaveHall(ceo);ceo.goalKind='front';this.go(ceo,wpt(HALL_FRONT.mario));const alex=this.people.get('alex');if(alex)alex.afterMeeting=true;}}
   else if(!ceo.hallPath?.length&&!ceo.seated){ceo.seated=true;ceo.dir=2;}ceo.walking=this.stepHall(ceo,dt);}
  else{let dx=0,dy=0;if(k.has('w')||k.has('arrowup'))dy--;if(k.has('s')||k.has('arrowdown'))dy++;if(k.has('a')||k.has('arrowleft'))dx--;if(k.has('d')||k.has('arrowright'))dx++;
   ceo.walking=false;if((dx||dy)&&!this.meeting){ceo.path=[];const speed=(k.has('shift')?2.4:1.4)*dt,d=Math.hypot(dx,dy),nx=ceo.x+dx/d*speed,ny=ceo.y+dy/d*speed;if(isWalkable(nx,ny)&&!this.blocked(ceo,nx,ny)){ceo.x=nx;ceo.y=ny;ceo.walking=true;ceo.anim+=dt;}else if(isWalkable(nx,ceo.y)&&!this.blocked(ceo,nx,ceo.y)){ceo.x=nx;ceo.walking=true;ceo.anim+=dt;}else if(isWalkable(ceo.x,ny)&&!this.blocked(ceo,ceo.x,ny)){ceo.y=ny;ceo.walking=true;ceo.anim+=dt;}this.face(ceo,dx,dy);}
   else{ceo.speed=1.4;ceo.walking=this.step(ceo,dt);}
   if(ceo.walking&&Date.now()-(this.lastSave||0)>1000){this.lastSave=Date.now();this.onMove?.({x:ceo.x,y:ceo.y});}}
  for(const p of [...this.people.values()]){this.brain(p,dt);if(!this.people.has(p.id))continue;
   if(p.where==='hall')p.walking=this.stepHall(p,dt);
   else if(p.where==='village'){p.walking=this.step(p,dt);if(!p.path.length&&p.resume&&p.hold<=0){this.go(p,p.resume);p.resume=null;}}
   if(p.alpha!==undefined&&p.alpha<1)p.alpha=Math.min(1,p.alpha+dt*3);
   if(p.lookAt){const o=p.lookAt==='mario'?this.ceo:this.people.get(p.lookAt);if(o&&o.where===p.where&&!p.walking&&!p.seated){p.where==='hall'?this.face(p,o.hall.x-p.hall.x,o.hall.y-p.hall.y):this.lookAt(p,o);}if(!p.bubble||p.bubble.until<performance.now())p.lookAt=null;}}
  // Idle people never stand on top of each other.
  const idle=[...this.people.values()].filter(p=>p.where==='village'&&!p.walking);for(const a of idle)for(const b of idle){if(a===b)continue;const d=dist(a,b);if(d<.3){const ang=d>1e-4?Math.atan2(a.y-b.y,a.x-b.x):(a.id<b.id?0:Math.PI)+Math.random()*.6,nx=a.x+Math.cos(ang)*.012,ny=a.y+Math.sin(ang)*.012;if(isWalkable(nx,ny)){a.x=nx;a.y=ny;}else if(isWalkable(a.x-Math.sin(ang)*.012,a.y+Math.cos(ang)*.012)){a.x-=Math.sin(ang)*.012;a.y+=Math.cos(ang)*.012;}}}
  this.encounters();
  if(this.followScene){const want=this.ceo.where==='hall'?'hall':'village';if(this.scene!==want)this.setScene(want,false);}
  if(!this.meeting)this.followScene=true;
 }
 // ---------- drawing helpers ----------
 sprite(p,x,y,h,{clipY=null,alpha=1}={}){
  const c=this.ctx,ceo=p.id==='mario',entry=ceo?{image:this.images.mario,ready:this.images.mario.ready}:p.sheet;if(!entry?.ready)return;
  const img=entry.image,rows=ceo?3:4,sw=img.width/4,sh=img.height/rows;
  let row=1;if(p.seated&&!ceo)row=3;else if(p.walking)row=WALK_ROWS[Math.floor(p.anim*8)%4];
  const breathe=!p.walking&&!p.seated?1+Math.sin(performance.now()/650+(p.anim||0)*9)*.012:1;
  const w=h*sw/sh,hh=h*breathe;c.save();c.globalAlpha=alpha;if(clipY!==null){c.beginPath();c.rect(x-w,y-hh*1.2,w*2,clipY-(y-hh*1.2));c.clip();}
  c.imageSmoothingEnabled=true;c.drawImage(img,p.dir*sw,row*sh,sw,sh,x-w/2,y-hh*.91,w,hh);c.restore();
 }
 pill(x,y,text,{color='#f2d494',bg='#182c26ed',border='#b8964f',font=10}={}){
  const c=this.ctx;c.font=`600 ${font}px 'Segoe UI',sans-serif`;c.textAlign='center';const w=c.measureText(text).width+17,h=font+12;c.save();c.shadowColor='#12271d80';c.shadowBlur=5;c.shadowOffsetY=2;c.fillStyle=bg;c.strokeStyle=border;c.lineWidth=1;c.beginPath();c.roundRect(x-w/2,y-h/2,w,h,5);c.fill();c.stroke();c.restore();c.fillStyle=color;c.fillText(text,x,y+font*.35);
 }
 bubble(x,y,text,{local=false}={}){
  const c=this.ctx,font=11,maxW=190;c.font=`500 ${font}px 'Segoe UI',sans-serif`;const words=text.replace(/\s+/g,' ').trim().split(' ');const lines=[];let line='';
  for(const w of words){const t=line?line+' '+w:w;if(c.measureText(t).width>maxW&&line){lines.push(line);line=w;if(lines.length===3)break;}else line=t;}if(lines.length<3&&line)lines.push(line);if(lines.length===3&&words.join(' ').length>lines.join(' ').length)lines[2]=lines[2].replace(/.{0,2}$/,'…');
  const w=Math.max(...lines.map(l=>c.measureText(l).width))+18,h=lines.length*14+12,bx=Math.max(6,Math.min(this.width-w-6,x-w/2)),by=y-h-10;
  c.save();c.shadowColor='#0005';c.shadowBlur=6;c.fillStyle=local?'#fff8e8f0':'#ffffff';c.strokeStyle=local?'#c9b07a':'#5d8f6a';c.lineWidth=1.2;c.beginPath();c.roundRect(bx,by,w,h,9);c.fill();c.stroke();c.beginPath();c.moveTo(x-6,by+h);c.lineTo(x,by+h+8);c.lineTo(x+6,by+h);c.fill();c.restore();
  c.fillStyle='#22302a';c.textAlign='left';lines.forEach((l,i)=>c.fillText(l,bx+9,by+18+i*14));
 }
 // ---------- village scenery ----------
 drawMap(v){const c=this.ctx;c.save();c.shadowColor='#040c08a0';c.shadowBlur=30;c.shadowOffsetY=8;c.fillStyle='#3c5230';c.beginPath();c.roundRect(v.x-4,v.y-4,v.w+8,v.h+8,10);c.fill();c.restore();
  c.save();c.beginPath();c.roundRect(v.x,v.y,v.w,v.h,7);c.clip();const map=this.images.map;if(map.ready)c.drawImage(map,v.x,v.y,v.w,v.h);else{c.fillStyle='#315734';c.fillRect(v.x,v.y,v.w,v.h);c.fillStyle='#f9e1ad';c.font='16px Georgia';c.textAlign='center';c.fillText(map.failed?'Ilustrația nu este disponibilă · verifică folderul assets':'Se pregătește satul…',this.width/2,this.height/2);}c.restore();
  c.strokeStyle='#c2a56a';c.lineWidth=2;c.beginPath();c.roundRect(v.x-2,v.y-2,v.w+4,v.h+4,8);c.stroke();}
 // Re-draws thin slices of the painting with a small offset: the art itself appears to move.
 warp(sx,sy,sw,sh,amp,t,{vertical=true,anchorTop=false,speed=3,freq=5}={}){const c=this.ctx,v=this.view(),map=this.images.map,n=vertical?Math.ceil(sw/2):Math.ceil(sh/2);
  for(let i=0;i<n;i++){const f=i/n;if(vertical){const off=Math.sin(t*speed+f*freq)*amp;c.drawImage(map,sx+i*2,sy,2,sh,v.x+(sx+i*2)*v.scale,v.y+(sy+off)*v.scale,2*v.scale+.5,sh*v.scale);}
   else{const k=anchorTop?f:1;const off=Math.sin(t*speed+f*freq)*amp*k;c.drawImage(map,sx,sy+i*2,sw,2,v.x+(sx+off)*v.scale,v.y+(sy+i*2)*v.scale,sw*v.scale,2*v.scale+.5);}}}
 water(t){const c=this.ctx,s=this.view().scale,f=EFFECTS.water[0],cx=this.px(f.x,f.y);
  c.save();c.beginPath();c.ellipse(cx.x,cx.y,f.rx*s,f.ry*s,0,0,Math.PI*2);c.clip();this.warp(f.x-f.rx,f.y-f.ry,f.rx*2,f.ry*2,1.3,t,{vertical:false,speed:2.4,freq:9});c.restore();
  c.save();c.strokeStyle='#e6fdffb0';c.lineWidth=Math.max(.7,s);for(let i=0;i<3;i++){const ph=(t/1.4+i/3)%1;c.globalAlpha=(1-ph)*.55;c.beginPath();c.ellipse(cx.x,cx.y+4*s,(14+ph*44)*s,(5+ph*18)*s,0,0,Math.PI*2);c.stroke();}
  // falling streams from the tiers
  c.globalAlpha=.85;for(let i=0;i<14;i++){const a=i/14*Math.PI*2,ph=(t*1.6+i*.37)%1,r=18+ph*20,x=cx.x+Math.cos(a)*r*s,y=cx.y-38*s+ph*ph*30*s+Math.sin(a)*6*s;c.fillStyle=i%2?'#dbfbff':'#8de6f2';c.beginPath();c.ellipse(x,y,1.1*s,2.4*s,0,0,Math.PI*2);c.fill();}
  for(let i=0;i<5;i++){const ph=(t*2+i*.2)%1;c.fillStyle='#effeff';c.globalAlpha=1-ph;c.beginPath();c.arc(cx.x+Math.sin(i*2.1)*3*s,cx.y-(70-ph*24)*s,1.3*s,0,Math.PI*2);c.fill();}c.restore();
  // stream + pond: shimmering highlights travelling downstream
  const pts=EFFECTS.water[1].points;c.save();c.globalCompositeOperation='screen';for(let i=0;i<pts.length-1;i++){const [ax,ay]=pts[i],[bx,by]=pts[i+1];for(let j=0;j<4;j++){const ph=(t*.25+j/4+i*.13)%1,x=ax+(bx-ax)*ph+Math.sin(t*2+j)*10,y=ay+(by-ay)*ph,q=this.px(x+20,y);c.globalAlpha=.35*Math.sin(ph*Math.PI);c.fillStyle='#d8fbff';c.beginPath();c.ellipse(q.x,q.y,7*s,1.6*s,.6,0,Math.PI*2);c.fill();}}c.restore();}
 smoke(t){const c=this.ctx,s=this.view().scale;for(const [x,y] of EFFECTS.chimneys){for(let i=0;i<5;i++){const ph=(t/5+i/5+x*.001)%1,q=this.px(x+Math.sin(ph*4+x)*6+ph*16,y-6-ph*58);c.globalAlpha=.3*(1-ph)*Math.min(1,ph*6);c.fillStyle='#f4efe8';c.beginPath();c.ellipse(q.x,q.y,(3.5+ph*9)*s,(3+ph*7)*s,0,0,Math.PI*2);c.fill();}}c.globalAlpha=1;}
 screens(t){const c=this.ctx,s=this.view().scale;c.save();c.globalCompositeOperation='screen';for(const [x,y,w,h] of EFFECTS.screens){const q=this.px(x,y),flick=.12+.1*Math.sin(t*7+x)+(Math.sin(t*23+y)>.94?.18:0);c.globalAlpha=flick;c.fillStyle='#9fe9ff';c.fillRect(q.x,q.y,w*s,h*s);c.globalAlpha=.12;c.fillStyle='#ffffff';const line=((t*30+x)%h);c.fillRect(q.x,q.y+line*s,w*s,1.5*s);}c.restore();}
 leaves(t,dt){const c=this.ctx,s=this.view().scale,fx=this.fx;
  if(fx.leaves.length<5&&Math.random()<dt*.5)fx.leaves.push({x:-20,y:rand(200,980),vx:rand(40,70),p:rand(0,6),c:['#9bbf4a','#d7a53a','#c9772f','#7aa63c'][Math.floor(Math.random()*4)]});
  for(const [cx,cy] of EFFECTS.cherry)if(fx.petals.length<14&&Math.random()<dt*.6)fx.petals.push({x:cx+rand(-30,30),y:cy+rand(0,30),vx:rand(10,25),vy:rand(12,22),p:rand(0,6)});
  for(const l of fx.leaves){l.x+=l.vx*dt;l.p+=dt*3;l.y+=Math.sin(l.p)*12*dt+8*dt;const q=this.px(l.x,l.y);c.save();c.translate(q.x,q.y);c.rotate(l.p);c.fillStyle=l.c;c.beginPath();c.ellipse(0,0,4*s,2*s,0,0,Math.PI*2);c.fill();c.restore();}
  for(const l of fx.petals){l.x+=l.vx*dt+Math.sin(l.p)*8*dt;l.y+=l.vy*dt;l.p+=dt*2.5;const q=this.px(l.x,l.y);c.fillStyle='#ffc6dd';c.globalAlpha=.9;c.beginPath();c.ellipse(q.x,q.y,2.4*s,1.5*s,l.p,0,Math.PI*2);c.fill();c.globalAlpha=1;}
  fx.leaves=fx.leaves.filter(l=>l.x<1560);fx.petals=fx.petals.filter(l=>l.y<l.y+999&&l.y<1030&&l.x<1560&&l.p<60);}
 birds(t,dt,night){const c=this.ctx,s=this.view().scale,fx=this.fx;if(!night&&fx.birds.length<1&&Math.random()<dt*.04){const n=3+Math.floor(Math.random()*3),y=rand(60,400);fx.birds.push(...Array.from({length:n},(_,i)=>({x:-40-i*26,y:y+(i%2)*14+i*6,vx:rand(70,90),p:rand(0,6)})));}
  c.strokeStyle='#2b2a26';c.lineWidth=Math.max(1,1.3*s);for(const b of fx.birds){b.x+=b.vx*dt;b.p+=dt*10;const q=this.px(b.x,b.y),w=6*s,f=Math.sin(b.p)*3*s;c.beginPath();c.moveTo(q.x-w,q.y-f);c.quadraticCurveTo(q.x-w/2,q.y-f-2*s,q.x,q.y);c.quadraticCurveTo(q.x+w/2,q.y-f-2*s,q.x+w,q.y-f);c.stroke();}fx.birds=fx.birds.filter(b=>b.x<1600);}
 clouds(t){const c=this.ctx,s=this.view().scale;c.save();c.globalCompositeOperation='multiply';for(let i=0;i<3;i++){const x=((t*9+i*620)%2200)-330,y=180+i*290,q=this.px(x,y);const g=c.createRadialGradient(q.x,q.y,0,q.x,q.y,230*s);g.addColorStop(0,'#8a958c40');g.addColorStop(1,'#8a958c00');c.fillStyle=g;c.beginPath();c.ellipse(q.x,q.y,260*s,140*s,0,0,Math.PI*2);c.fill();}c.restore();}
 propDraws(){const out=[];for(const p of PROPS){const img=this.images['prop:'+p.sprite];if(!img?.ready)continue;out.push({y:p.y,draw:()=>{const q=this.px(p.x,p.y),s=this.view().scale,w=p.w*s,h=w*img.height/img.width;this.ctx.drawImage(img,q.x-w/2,q.y-h*.94,w,h);}});}
  for(const p of CODE_PROPS)out.push({y:p.y,draw:()=>this.codeProp(p)});return out;}
 codeProp(p){const c=this.ctx,s=this.view().scale,q=this.px(p.x,p.y);c.save();c.translate(q.x,q.y);c.scale(s,s);c.lineWidth=1.2;c.strokeStyle='#3b2416';
  c.fillStyle='#1f2b1a55';c.beginPath();c.ellipse(0,0,p.kind==='vending'?16:9,3.5,0,0,Math.PI*2);c.fill();
  if(p.kind==='barrel'){const g=c.createLinearGradient(-8,0,8,0);g.addColorStop(0,'#6e3f1e');g.addColorStop(.5,'#b06b34');g.addColorStop(1,'#6a3a1b');c.fillStyle=g;c.beginPath();c.roundRect(-8,-20,16,20,4);c.fill();c.stroke();c.fillStyle='#8b8f92';c.fillRect(-8,-16,16,2);c.fillRect(-8,-6,16,2);c.fillStyle='#c98b4b';c.beginPath();c.ellipse(0,-20,8,2.6,0,0,Math.PI*2);c.fill();c.stroke();}
  else if(p.kind==='crate'){c.fillStyle='#b98444';c.fillRect(-9,-16,18,16);c.strokeRect(-9,-16,18,16);c.fillStyle='#d9a560';c.beginPath();c.moveTo(-9,-16);c.lineTo(-4,-20);c.lineTo(13,-20);c.lineTo(9,-16);c.closePath();c.fill();c.stroke();c.beginPath();c.moveTo(-9,-16);c.lineTo(9,0);c.moveTo(9,-16);c.lineTo(-9,0);c.stroke();}
  else if(p.kind==='vending'){// Retro pop vending machine, drawn in code.
   const g=c.createLinearGradient(-14,0,14,0);g.addColorStop(0,'#c0352f');g.addColorStop(.5,'#ef5a4a');g.addColorStop(1,'#a8291f');c.fillStyle=g;c.beginPath();c.roundRect(-14,-44,28,44,5);c.fill();c.stroke();
   c.fillStyle='#fff3d6';c.beginPath();c.roundRect(-11,-41,22,7,3);c.fill();c.fillStyle='#c0352f';c.font='bold 5px sans-serif';c.textAlign='center';c.fillText('POP!',0,-36);
   c.fillStyle='#bfe9f2';c.beginPath();c.roundRect(-11,-31,15,18,2);c.fill();c.stroke();const cols=['#ffd23f','#3fa7d6','#59cd90','#ee6352'];for(let r=0;r<3;r++)for(let k=0;k<3;k++){c.fillStyle=cols[(r+k)%4];c.fillRect(-9.5+k*4.6,-29+r*5.8,3,4.2);}
   c.fillStyle='#ffe9a8';c.fillRect(6,-30,4,2.5);c.fillRect(6,-26,4,2.5);c.fillStyle='#2b2b2b';c.fillRect(-10,-9,15,4);c.fillStyle='#ffd23f';c.beginPath();c.arc(8,-14,1.6,0,Math.PI*2);c.fill();
   const glow=.35+.25*Math.sin(performance.now()/400);c.fillStyle=`rgba(255,240,200,${glow})`;c.fillRect(-11,-31,15,18);}
  c.restore();}
 lighting(t,dark){if(dark<=0.01&&darkness(this.hour)<=0.01){this.lampsDay(t);return;}
  const c=this.ctx,v=this.view(),s=v.scale,h=this.hour;
  const sunset=sunCache.sun?.sunset??18,dusk=Math.max(0,1-Math.abs(h-sunset)/1.4);c.save();c.beginPath();c.rect(v.x,v.y,v.w,v.h);c.clip();
  if(dusk>0){c.globalCompositeOperation='soft-light';c.fillStyle=`rgba(255,140,60,${.5*dusk})`;c.fillRect(v.x,v.y,v.w,v.h);}
  c.globalCompositeOperation='multiply';c.fillStyle=`rgba(${Math.round(255-170*dark)},${Math.round(255-150*dark)},${Math.round(255-60*dark)},1)`;c.fillRect(v.x,v.y,v.w,v.h);
  c.globalCompositeOperation='lighter';
  for(const [x,y] of EFFECTS.windows){const q=this.px(x,y),f=.8+.2*Math.sin(t*3+x);const g=c.createRadialGradient(q.x,q.y,0,q.x,q.y,16*s);g.addColorStop(0,`rgba(255,190,90,${.55*dark*f})`);g.addColorStop(1,'rgba(255,170,60,0)');c.fillStyle=g;c.fillRect(q.x-16*s,q.y-16*s,32*s,32*s);}
  for(const [x,y] of EFFECTS.lamps){const q=this.px(x,y),f=.9+.1*Math.sin(t*9+x*3)*Math.sin(t*3.3+y);const g=c.createRadialGradient(q.x,q.y,0,q.x,q.y,58*s);g.addColorStop(0,`rgba(255,214,130,${.75*dark*f})`);g.addColorStop(.25,`rgba(255,190,90,${.3*dark*f})`);g.addColorStop(1,'rgba(255,170,60,0)');c.fillStyle=g;c.fillRect(q.x-58*s,q.y-58*s,116*s,116*s);}
  for(const b of BUILDINGS)if(b.owner&&this.working.has(b.owner)){const q=this.px(b.door[0],b.door[1]-30),g=c.createRadialGradient(q.x,q.y,0,q.x,q.y,40*s);g.addColorStop(0,`rgba(255,220,150,${.35+.45*dark})`);g.addColorStop(1,'rgba(255,200,120,0)');c.fillStyle=g;c.fillRect(q.x-40*s,q.y-40*s,80*s,80*s);}
  if(dark>.4)for(const f of this.fx.flies){f.p+=.016;const q=this.px(f.x+Math.sin(f.p*.7)*30,f.y+Math.cos(f.p*.9)*18),a=Math.max(0,Math.sin(f.p*2))*dark;c.fillStyle=`rgba(230,255,140,${a})`;c.beginPath();c.arc(q.x,q.y,1.8*s,0,Math.PI*2);c.fill();}
  c.restore();}
 lampsDay(t){const c=this.ctx,s=this.view().scale;c.save();c.globalCompositeOperation='lighter';for(const [x,y] of EFFECTS.lamps){const q=this.px(x,y),f=.08+.04*Math.sin(t*4+x);const g=c.createRadialGradient(q.x,q.y,0,q.x,q.y,12*s);g.addColorStop(0,`rgba(255,220,140,${f})`);g.addColorStop(1,'rgba(255,200,100,0)');c.fillStyle=g;c.fillRect(q.x-12*s,q.y-12*s,24*s,24*s);}c.restore();}
 // ---------- Town Hall interior: one big table, twelve chairs ----------
 drawHall(t){
  const c=this.ctx,v=this.view(),s=v.scale,P=(x,y)=>this.px(x,y),R=(x0,y0,x1,y1)=>{const a=P(x0,y0);return [a.x,a.y,(x1-x0)*s,(y1-y0)*s];};
  c.save();c.beginPath();c.roundRect(v.x,v.y,v.w,v.h,7);c.clip();c.fillStyle='#2a1d16';c.fillRect(v.x,v.y,v.w,v.h);
  // stone surround and wood floor
  let g=c.createLinearGradient(0,P(0,200).y,0,P(0,1024).y);g.addColorStop(0,'#8a5a34');g.addColorStop(1,'#6e4426');c.fillStyle=g;c.fillRect(...R(300,200,1236,1024));
  c.strokeStyle='#5a3620';c.lineWidth=Math.max(.6,1.2*s);for(let x=300;x<1236;x+=46){const a=P(x,200),b=P(x,1024);c.beginPath();c.moveTo(a.x,a.y);c.lineTo(b.x,b.y);c.stroke();}
  for(let x=300,i=0;x<1236;x+=46,i++)for(let y=200+(i%2)*80;y<1024;y+=160){const a=P(x,y),b=P(x+46,y);c.beginPath();c.moveTo(a.x,a.y);c.lineTo(b.x,b.y);c.stroke();}
  // back wall with windows, banners and clock
  g=c.createLinearGradient(0,P(0,60).y,0,P(0,205).y);g.addColorStop(0,'#efe0c2');g.addColorStop(1,'#d9c39c');c.fillStyle=g;c.fillRect(...R(300,60,1236,205));c.fillStyle='#7a4a2a';c.fillRect(...R(300,170,1236,205));c.fillStyle='#5b351d';c.fillRect(...R(300,200,1236,208));
  const dark=darkness(this.hour);for(const wx of [400,560,976,1136]){const [x,y,w,h]=R(wx-40,80,wx+40,165);c.fillStyle=dark>.5?'#1d2a4a':dark>0?'#e7a46a':'#a9d8f2';c.beginPath();c.roundRect(x,y,w,h,[w/2,w/2,3,3]);c.fill();c.strokeStyle='#8a6a3a';c.lineWidth=3*s;c.stroke();c.beginPath();c.moveTo(x+w/2,y);c.lineTo(x+w/2,y+h);c.moveTo(x,y+h*.55);c.lineTo(x+w,y+h*.55);c.lineWidth=1.5*s;c.stroke();}
  for(const bx of [680,856]){c.save();for(let i=0;i<16;i++){const f=i/16,off=Math.sin(t*2.2+f*5)*2.5*f;const [x,y,w,h]=R(bx-18,70+i*7,bx+18,70+i*7+7.5);c.fillStyle=i>13?'#9e1f24':'#b8262c';c.fillRect(x+off*s,y,w,h);}const em=P(bx,105);c.fillStyle='#f0c24a';c.beginPath();c.arc(em.x+Math.sin(t*2.2+2)*s,em.y,7*s,0,Math.PI*2);c.fill();c.restore();}
  const ck=P(768,112);c.fillStyle='#f6eedb';c.strokeStyle='#b88a3a';c.lineWidth=4*s;c.beginPath();c.arc(ck.x,ck.y,26*s,0,Math.PI*2);c.fill();c.stroke();const now=new Date(),hr=(this.hour%12)/12*Math.PI*2,mn=now.getMinutes()/60*Math.PI*2;c.strokeStyle='#3a2a1a';c.lineWidth=2.5*s;c.beginPath();c.moveTo(ck.x,ck.y);c.lineTo(ck.x+Math.sin(hr)*13*s,ck.y-Math.cos(hr)*13*s);c.moveTo(ck.x,ck.y);c.lineTo(ck.x+Math.sin(mn)*19*s,ck.y-Math.cos(mn)*19*s);c.stroke();
  // red carpet and doorway
  c.fillStyle='#8f2a2a';c.fillRect(...R(620,250,916,1024));c.strokeStyle='#e0b34a';c.lineWidth=2*s;c.strokeRect(...R(628,258,908,1024));
  c.fillStyle='#3b2416';c.fillRect(...R(718,1004,818,1024));
  // wall sconces
  for(const [x,y] of [[470,120],[1066,120]]){const q=P(x,y),f=.8+.2*Math.sin(t*8+x);const gg=c.createRadialGradient(q.x,q.y,0,q.x,q.y,70*s);gg.addColorStop(0,`rgba(255,210,120,${.55*f})`);gg.addColorStop(1,'rgba(255,190,90,0)');c.fillStyle=gg;c.fillRect(q.x-70*s,q.y-70*s,140*s,140*s);c.fillStyle='#ffd27a';c.beginPath();c.ellipse(q.x,q.y,4*s,7*s,0,0,Math.PI*2);c.fill();}
  // people & furniture in the right order: chairs → seated people → table → foot sitter → foot chair back
  const inHall=[this.ceo,...this.people.values()].filter(p=>p.where==='hall'&&p.hall);const H=150;
  const seatOf=p=>p.seated?this.seatFor(p):null;
  for(const seat of HALL.seats){if(seat.role!=='foot')this.chair(seat,s);}
  const walkers=inHall.filter(p=>!p.seated).sort((a,b)=>a.hall.y-b.hall.y);
  for(const p of walkers.filter(p=>p.hall.y<HALL.table[3]))this.drawHallPerson(p,H);
  const table=HALL.table;for(const p of inHall.filter(p=>p.seated&&seatOf(p)?.role!=='foot'))this.drawHallPerson(p,H,seatOf(p));
  // the table
  const [tx,ty,tw,th]=R(table[0],table[1],table[2],table[3]);c.save();c.shadowColor='#0007';c.shadowBlur=18*s;c.shadowOffsetY=10*s;g=c.createLinearGradient(tx,0,tx+tw,0);g.addColorStop(0,'#7b4a26');g.addColorStop(.5,'#a8693a');g.addColorStop(1,'#7b4a26');c.fillStyle=g;c.beginPath();c.roundRect(tx,ty,tw,th,18*s);c.fill();c.restore();
  c.strokeStyle='#5a331b';c.lineWidth=4*s;c.beginPath();c.roundRect(tx,ty,tw,th,18*s);c.stroke();c.strokeStyle='#c98f55';c.lineWidth=1.5*s;c.beginPath();c.roundRect(tx+8*s,ty+8*s,tw-16*s,th-16*s,12*s);c.stroke();
  for(const seat of HALL.seats){if(seat.role==='head'){this.paper(768,350,s,0);continue;}if(seat.role==='foot'){this.paper(768,780,s,0);continue;}const left=seat.side==='left';this.paper(left?705:831,seat.y+10,s,left?-.2:.2);this.cup(left?725:811,seat.y-22,s);}
  for(const p of inHall.filter(p=>p.seated&&seatOf(p)?.side))this.drawHallPerson(p,H,seatOf(p),{upper:true});
  const ctr=P(768,560);c.fillStyle='#2f5d3a';c.beginPath();c.ellipse(ctr.x,ctr.y,30*s,16*s,0,0,Math.PI*2);c.fill();for(let i=0;i<9;i++){const a=i/9*Math.PI*2;c.fillStyle=['#ff8fb1','#ffd166','#f4f1de'][i%3];c.beginPath();c.arc(ctr.x+Math.cos(a)*18*s,ctr.y+Math.sin(a)*8*s,4.5*s,0,Math.PI*2);c.fill();}
  for(const p of inHall.filter(p=>p.seated&&seatOf(p)?.role==='foot'))this.drawHallPerson(p,H,seatOf(p));
  this.chair(HALL.seats[11],s,true);
  for(const p of walkers.filter(p=>p.hall.y>=HALL.table[3]))this.drawHallPerson(p,H);
  // name plates: big and readable
  for(const p of inHall){const seat=seatOf(p);const q=P(p.hall.x,p.hall.y);const font=Math.max(9,Math.min(14,13*s+4)),label=(p.id==='mario'?'♛ ':'')+p.name+(p.role==='candidate'?' · candidat':'');this.ctx.font=`600 ${font}px 'Segoe UI',sans-serif`;const half=this.ctx.measureText(label).width/2+9;const lx=seat?.side==='left'?q.x-52*s-half:seat?.side==='right'?q.x+52*s+half:q.x;const y=seat?.role==='head'?this.px(0,HALL.table[1]).y-H*.85*s-font:seat?.role==='foot'?q.y+44*s:seat?q.y-40*s:q.y+14*s;const speaking=this.speaker===p.id;this.pill(lx,y,label,{border:speaking?'#8be08a':p.id==='mario'?'#e7bf5b':(p.color||'#b8964f'),color:speaking?'#c9f7b5':'#fff4d6',font});}
  c.restore();
  c.strokeStyle='#c2a56a';c.lineWidth=2;c.beginPath();c.roundRect(v.x-2,v.y-2,v.w+4,v.h+4,8);c.stroke();
 }
 paper(x,y,s,rot){const c=this.ctx,q=this.px(x,y);c.save();c.translate(q.x,q.y);c.rotate(rot);c.fillStyle='#f7f1e1';c.fillRect(-13*s,-9*s,26*s,18*s);c.fillStyle='#b9ae95';for(let i=0;i<3;i++)c.fillRect(-9*s,(-5+i*4)*s,18*s,1.2*s);c.restore();}
 cup(x,y,s){const c=this.ctx,q=this.px(x,y);c.fillStyle='#f3f3ef';c.beginPath();c.arc(q.x,q.y,5.5*s,0,Math.PI*2);c.fill();c.fillStyle='#6b3e22';c.beginPath();c.arc(q.x,q.y,3.6*s,0,Math.PI*2);c.fill();}
 chair(seat,s,frontBack=false){const c=this.ctx,q=this.px(seat.x,seat.y),wood='#6b3d1f',cush='#a7262c';c.save();c.lineWidth=2*s;c.strokeStyle='#3b210f';
  if(seat.role==='head'){c.fillStyle='#5a3218';c.beginPath();c.roundRect(q.x-56*s,q.y-92*s,112*s,140*s,[44*s,44*s,6*s,6*s]);c.fill();c.stroke();c.fillStyle=cush;c.beginPath();c.roundRect(q.x-44*s,q.y-80*s,88*s,120*s,[36*s,36*s,4*s,4*s]);c.fill();c.fillStyle='#e8bd4b';c.beginPath();c.arc(q.x,q.y-94*s,10*s,0,Math.PI*2);c.fill();}
  else if(seat.role==='foot'){if(!frontBack){c.restore();return;}c.fillStyle=wood;c.beginPath();c.roundRect(q.x-34*s,q.y-48*s,68*s,62*s,8*s);c.fill();c.stroke();c.fillStyle=cush;c.fillRect(q.x-26*s,q.y-40*s,52*s,40*s);c.fillStyle=wood;c.fillRect(q.x-30*s,q.y+12*s,8*s,22*s);c.fillRect(q.x+22*s,q.y+12*s,8*s,22*s);}
  else{const dir=seat.side==='left'?-1:1;c.fillStyle=wood;c.beginPath();c.roundRect(q.x+dir*30*s-6*s,q.y-84*s,12*s,88*s,4*s);c.fill();c.stroke();c.fillStyle=cush;c.beginPath();c.roundRect(q.x-26*s+dir*8*s,q.y-30*s,44*s,24*s,6*s);c.fill();c.stroke();c.fillStyle=wood;c.fillRect(q.x-20*s+dir*8*s,q.y-8*s,6*s,16*s);c.fillRect(q.x+12*s+dir*8*s,q.y-8*s,6*s,16*s);}
  c.restore();}
 drawHallPerson(p,H,seat=null,{upper=false}={}){const v=this.view(),s=v.scale,q=this.px(p.hall.x,p.hall.y);
  // Seated at the long sides: legs go under the table, head and shoulders stay above it.
  if(upper){const h=H*.86*s;this.sprite(p,q.x,q.y+4*s,h,{clipY:q.y+4*s-h*.43});return;}
  if(seat?.role==='head'){// Mario at the head: the table covers him below the waist.
   const top=this.px(0,HALL.table[1]).y;this.sprite(p,q.x,top+H*.36*s,H*1.08*s,{clipY:top+6*s});}
  else if(seat?.role==='foot')this.sprite(p,q.x,q.y+4*s,H*s);
  else if(seat)this.sprite(p,q.x,q.y+4*s,H*.86*s);
  else this.sprite(p,q.x,q.y,H*s);
  if(p.bubble&&p.bubble.until>performance.now())this.bubble(q.x,q.y-(seat?.role==='head'?175:H*.95)*s,p.bubble.text,p.bubble);
  if(this.speaker===p.id){this.ctx.strokeStyle='#8be08a';this.ctx.lineWidth=2.5;this.ctx.beginPath();this.ctx.ellipse(q.x,q.y+6*s,40*s,12*s,0,0,Math.PI*2);this.ctx.stroke();}}
 // ---------- frame ----------
 frame(t){
  const dt=Math.min((t-(this.last||t))/1000,.05),time=t/1000;this.last=t;this.hour=bucharestHour();const dark=darkness(this.hour);this.working=this.working||new Set();
  if(!this.width){requestAnimationFrame(t=>this.frame(t));return;}
  this.tick(dt);this.sound.tick(dark>.6);const c=this.ctx;c.clearRect(0,0,this.width,this.height);const v=this.view();
  if(this.scene==='hall'){this.drawHall(time);}
  else{this.drawMap(v);if(this.images.map.ready){
   c.save();c.beginPath();c.roundRect(v.x,v.y,v.w,v.h,7);c.clip();
   this.water(time);for(const [x,y,w,h] of EFFECTS.banners)this.warp(x,y,w,h,1.6,time,{vertical:false,anchorTop:true,speed:2.6,freq:6});this.screens(time);if(dark<.7)this.clouds(time);
   const draws=this.propDraws();for(const p of [...this.people.values(),this.ceo])if(p.where==='village')draws.push({y:pixelPoint(p.x,p.y).y,draw:()=>this.villagePerson(p)});
   draws.sort((a,b)=>a.y-b.y).forEach(d=>d.draw());
   this.smoke(time);this.leaves(time,dt);this.birds(time,dt,dark>.5);this.lighting(time,dark);c.restore();
   this.overlays(v);}}
  this.tooltip(v);requestAnimationFrame(t=>this.frame(t));
 }
 villagePerson(p){const c=this.ctx,s=this.view().scale,pos=this.screen(p.x,p.y),ceo=p.id==='mario';c.fillStyle='#12291d66';c.beginPath();c.ellipse(pos.x,pos.y,12*s,4*s,0,0,Math.PI*2);c.fill();this.sprite(p,pos.x,pos.y,(ceo?91:82)*s,{alpha:p.alpha??1});}
 overlays(v){
  const s=v.scale,now=performance.now();
  for(const b of BUILDINGS){if(this.hover?.id===b.id){const c=this.ctx;c.save();c.strokeStyle=b.color;c.lineWidth=2;c.shadowColor=b.color;c.shadowBlur=12;c.strokeRect(v.x+b.bounds[0]*s,v.y+b.bounds[1]*s,(b.bounds[2]-b.bounds[0])*s,(b.bounds[3]-b.bounds[1])*s);c.restore();}
   const q=this.px(b.label[0],b.label[1]),present=!b.owner||b.owner==='mario'||this.people.has(b.owner);this.pill(q.x,q.y,(b.id==='townhall'?'⌂ Town Hall':b.icon+' '+b.name)+(present?'':' · liberă'),{border:present?b.color:'#7d7d70',color:b.id==='mario'?'#ffe59a':present?'#fff4d6':'#b9b6a8',font:s<.45?7:Math.min(11,11*s+4)});
   const inside=[...this.people.values()].filter(p=>p.where==='house'&&this.home(p)?.id===b.id&&this.working.has(p.id));if(inside.length){const d=this.px(b.door[0],b.door[1]-52);this.pill(d.x,d.y,'● '+inside.map(p=>p.name).join(', ')+' lucrează la birou',{color:'#c6efa5',border:'#6baf65',font:9});}}
  for(const p of [...this.people.values(),this.ceo]){if(p.where!=='village')continue;const pos=this.screen(p.x,p.y),ceo=p.id==='mario';
   const roomy=s>.55,show=ceo||this.hover?.id===p.id||this.selected===p.id||(roomy&&(dist(p,this.ceo)<2||p.role!=='director'));if(show)this.pill(pos.x,pos.y-(ceo?83:75)*s,ceo?'♛ Mario':p.name+(p.role==='candidate'?' · candidat':p.role==='worker'?' · echipa '+(this.state?.agents.find(a=>a.id===p.director)?.name||p.director):''),{border:ceo?'#e7bf5b':p.color||'#f2c230',font:9});
   if(p.notes>now)this.pill(pos.x+18*s,pos.y-40*s,'✎',{font:9,border:'#c9b07a'});
   if(p.bubble&&p.bubble.until>now)this.bubble(pos.x,pos.y-(ceo?92:84)*s,p.bubble.text,p.bubble);}
 }
 tooltip(v){const tooltip=document.getElementById('mapTooltip');if(!tooltip)return;if(this.hover){tooltip.hidden=false;const p=this.hover.bounds?{x:v.x+this.hover.label[0]*v.scale,y:v.y+this.hover.label[1]*v.scale}:this.posOf(this.hover);tooltip.style.left=Math.max(12,Math.min(this.width-235,p.x-70))+'px';tooltip.style.top=Math.max(122,p.y+16)+'px';const owner=this.hover.bounds?this.state?.agents.find(a=>a.id===this.hover.owner):null;tooltip.textContent=this.hover.bounds?(owner?`${this.hover.name} · ${owner.role}`:this.hover.owner&&this.hover.owner!=='mario'?`Casa lui ${this.hover.name} · nu face parte din echipa actuală`:this.hover.name+' · '+this.hover.subtitle):this.hover.name+' · '+(this.state?.agents.find(a=>a.id===this.hover.id)?.role||'CEO');}else tooltip.hidden=true;}
}
