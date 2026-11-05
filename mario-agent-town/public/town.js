import {MAP_SIZE,BUILDINGS,FOUNTAIN,MEETING_POINTS,CEO_START,worldPoint,pixelPoint,isWalkable,findPath} from './village-layout.js';

// Painted scenery and local sprite animation never manufacture operational activity.
// Live work indicators are driven only by the backend runtime state.
export class Town {
 constructor(canvas,{select,move,nearby}){
  this.canvas=canvas;this.ctx=canvas.getContext('2d');this.select=select;this.onMove=move;this.onNearby=nearby;
  this.people=[];this.keys=new Set();this.pan={x:0,y:0};this.zoom=1;this.last=0;this.hover=null;this.meeting=false;
  this.ceo={id:'mario',name:'Mario',...CEO_START,path:[],step:0,dir:2,color:'#e6bb5b'};
  this.map=new Image();this.map.src='/assets/village-map-v2.webp';this.map.onload=()=>this.mapReady=true;this.map.onerror=()=>this.mapFailed=true;
  this.avatar=new Image();this.avatar.src='/assets/mario-sprites.webp';this.avatar.onload=()=>this.avatarReady=true;
  this.sheets=new Map();this.setupInput();this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(canvas);
  requestAnimationFrame(t=>this.frame(t));
 }
 update(state){
  this.state=state;this.paused=state.settings.paused;this.active=state.runtime.active?.agent;this.selected=state.channel;
  if(!this.people.length){this.people=state.agents.map((a,i)=>{const home=BUILDINGS.find(b=>b.id===a.id);const image=new Image();image.src=`/assets/characters/${a.id}.webp`;const entry={image,ready:false};image.onload=()=>entry.ready=true;this.sheets.set(a.id,entry);return {...a,...worldPoint(...home.gate),path:[],step:0,dir:2,wait:3+i*.55};});}
  if(this.meeting!==state.world.meeting){this.meeting=state.world.meeting;this.people.forEach((p,i)=>{this.go(p,this.meeting?MEETING_POINTS[i]:worldPoint(...BUILDINGS.find(b=>b.id===p.id).gate));p.wait=this.meeting?999:3;});}
 }
 resize(){const b=this.canvas.getBoundingClientRect();this.width=b.width;this.height=b.height;const d=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.round(b.width*d);this.canvas.height=Math.round(b.height*d);this.ctx.setTransform(d,0,0,d,0,0);}
 view(){const top=this.width<600?133:127,bottom=118;const availableH=Math.max(250,this.height-top-bottom);const scale=Math.min((this.width-26)/MAP_SIZE.width,availableH/MAP_SIZE.height)*this.zoom;return {scale,x:(this.width-MAP_SIZE.width*scale)/2+this.pan.x,y:top+(availableH-MAP_SIZE.height*scale)/2+this.pan.y,w:MAP_SIZE.width*scale,h:MAP_SIZE.height*scale};}
 screen(x,y,z=0){const v=this.view(),p=pixelPoint(x,y);return {x:v.x+p.x*v.scale,y:v.y+p.y*v.scale-z*v.scale};}
 world(x,y){const v=this.view();return worldPoint((x-v.x)/v.scale,(y-v.y)/v.scale);}
 go(p,to){p.path=findPath(p,to);}
 setZoom(value){this.zoom=Math.max(.7,Math.min(2.5,value));document.getElementById('zoomReset').textContent=Math.round(this.zoom*100)+'%';}
 setupInput(){
  const c=this.canvas;
  c.addEventListener('pointerdown',e=>{c.focus();this.drag={x:e.clientX,y:e.clientY,pan:{...this.pan},moved:false};c.setPointerCapture(e.pointerId);});
  c.addEventListener('pointermove',e=>{if(this.drag&&e.buttons){const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;if(Math.hypot(dx,dy)>5)this.drag.moved=true;if(this.drag.moved)this.pan={x:this.drag.pan.x+dx,y:this.drag.pan.y+dy};return;}const r=c.getBoundingClientRect();this.hover=this.hit(e.clientX-r.left,e.clientY-r.top);c.style.cursor=this.hover?'pointer':'grab';});
  c.addEventListener('pointerleave',()=>{this.hover=null;});
  c.addEventListener('pointerup',e=>{const dragged=this.drag?.moved;this.drag=null;if(dragged)return;const r=c.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,hit=this.hit(x,y);if(hit){if(hit.id==='mario')this.onNearby?.('Acasă la Mario · CEO');else this.select(hit.id);}else this.go(this.ceo,this.world(x,y));});
  c.addEventListener('wheel',e=>{e.preventDefault();this.setZoom(this.zoom*(e.deltaY>0?.93:1.07));},{passive:false});
  c.addEventListener('keydown',e=>{const key=e.key.toLowerCase();if(['arrowup','arrowdown','arrowleft','arrowright','w','a','s','d','shift'].includes(key)){e.preventDefault();this.keys.add(key);}if(key==='t'&&this.people.length){const nearest=[...this.people].sort((a,b)=>Math.hypot(a.x-this.ceo.x,a.y-this.ceo.y)-Math.hypot(b.x-this.ceo.x,b.y-this.ceo.y))[0];this.select(nearest.id);}if(key==='m')this.select('alex');});
  c.addEventListener('keyup',e=>this.keys.delete(e.key.toLowerCase()));c.addEventListener('blur',()=>this.keys.clear());window.addEventListener('blur',()=>this.keys.clear());
 }
 hit(x,y){
  for(const p of [this.ceo,...this.people]){const s=this.screen(p.x,p.y,32);if(Math.hypot(x-s.x,y-s.y)<Math.max(12,35*this.view().scale))return p;}
  const v=this.view(),px=(x-v.x)/v.scale,py=(y-v.y)/v.scale;
  return BUILDINGS.find(b=>px>=b.bounds[0]&&px<=b.bounds[2]&&py>=b.bounds[1]&&py<=b.bounds[3])||null;
 }
 movePerson(p,dt,speed){
  if(!p.path.length)return false;const to=p.path[0],dx=to.x-p.x,dy=to.y-p.y,d=Math.hypot(dx,dy),amount=dt*speed;
  if(d<amount){p.x=to.x;p.y=to.y;p.path.shift();}else{p.x+=dx/d*amount;p.y+=dy/d*amount;}
  p.dir=Math.abs(dx)>Math.abs(dy)?(dx>0?1:0):(dy>0?2:3);p.step+=dt*8;return true;
 }
 tick(dt){
  let dx=0,dy=0;const k=this.keys;if(k.has('w')||k.has('arrowup'))dy--;if(k.has('s')||k.has('arrowdown'))dy++;if(k.has('a')||k.has('arrowleft'))dx--;if(k.has('d')||k.has('arrowright'))dx++;
  this.ceo.walking=false;if(dx||dy){this.ceo.path=[];const speed=(k.has('shift')?2.4:1.4)*dt,d=Math.hypot(dx,dy),nx=this.ceo.x+dx/d*speed,ny=this.ceo.y+dy/d*speed;
   if(isWalkable(nx,ny)){this.ceo.x=nx;this.ceo.y=ny;this.ceo.walking=true;this.ceo.step+=dt*8;}this.ceo.dir=Math.abs(dx)>Math.abs(dy)?(dx>0?1:0):(dy>0?2:3);
  }else this.ceo.walking=this.movePerson(this.ceo,dt,1.4);
  if(this.ceo.walking&&Date.now()-(this.lastSave||0)>1000){this.lastSave=Date.now();this.onMove?.({x:this.ceo.x,y:this.ceo.y});}
  this.people.forEach((p,i)=>{p.walking=false;if(!this.paused){p.wait-=dt;if(!p.path.length&&!this.meeting&&p.wait<=0){let to;if(this.active===p.id)to=worldPoint(...BUILDINGS.find(b=>b.id===p.id).gate);else if(p.id==='alex'&&Math.hypot(p.x-this.ceo.x,p.y-this.ceo.y)>1.5)to={x:this.ceo.x-.7,y:this.ceo.y+.3};else{const choices=[...BUILDINGS.filter(b=>b.id!=='mario').map(b=>worldPoint(...b.gate)),...MEETING_POINTS];to=choices[Math.floor(Math.random()*choices.length)];}this.go(p,to);p.wait=6+Math.random()*9;}p.walking=this.movePerson(p,dt,.8);}
   p.seated=this.meeting&&!p.path.length;p.looking=Math.hypot(p.x-this.ceo.x,p.y-this.ceo.y)<2.8;if(p.looking&&!p.walking){const dx=this.ceo.x-p.x,dy=this.ceo.y-p.y;p.dir=Math.abs(dx)>Math.abs(dy)?(dx>0?1:0):(dy>0?2:3);}
  });
 }
 pill(x,y,text,{color='#f2d494',bg='#182c26ed',border='#b8964f',font=10}={}){
  const c=this.ctx;c.font=`600 ${font}px 'Segoe UI',sans-serif`;c.textAlign='center';const w=c.measureText(text).width+17,h=22;c.save();c.shadowColor='#12271d80';c.shadowBlur=5;c.shadowOffsetY=2;c.fillStyle=bg;c.strokeStyle=border;c.lineWidth=1;c.beginPath();c.roundRect(x-w/2,y-h/2,w,h,5);c.fill();c.stroke();c.restore();c.fillStyle=color;c.fillText(text,x,y+3.5);
 }
 scenery(t){
  const c=this.ctx,v=this.view();c.save();c.shadowColor='#040c08a0';c.shadowBlur=30;c.shadowOffsetY=8;c.fillStyle='#3c5230';c.beginPath();c.roundRect(v.x-4,v.y-4,v.w+8,v.h+8,10);c.fill();c.restore();
  c.save();c.beginPath();c.roundRect(v.x,v.y,v.w,v.h,7);c.clip();if(this.mapReady){c.imageSmoothingEnabled=true;c.drawImage(this.map,v.x,v.y,v.w,v.h);}else{c.fillStyle='#315734';c.fillRect(v.x,v.y,v.w,v.h);c.fillStyle='#f9e1ad';c.font='16px Georgia';c.textAlign='center';c.fillText(this.mapFailed?'Ilustrația nu este disponibilă · verifică folderul assets':'Se pregătește satul…',this.width/2,this.height/2);}c.restore();c.strokeStyle='#c2a56a';c.lineWidth=2;c.beginPath();c.roundRect(v.x-2,v.y-2,v.w+4,v.h+4,8);c.stroke();
  if(!this.mapReady)return;
  // Decorative water, butterflies and chimney smoke do not consume AI tokens.
  const water=this.screen(...Object.values(worldPoint(FOUNTAIN.x,FOUNTAIN.y)));const s=v.scale;
  c.save();c.strokeStyle='#c9faffb0';c.lineWidth=Math.max(.8,s);for(let i=0;i<3;i++){const phase=(t/1300+i/3)%1;c.globalAlpha=(1-phase)*.6;c.beginPath();c.ellipse(water.x,water.y+12*s,(20+phase*42)*s,(6+phase*12)*s,0,0,Math.PI*2);c.stroke();}c.globalAlpha=1;
  for(let i=0;i<7;i++){const phase=t/650+i*.8;c.fillStyle=i%2?'#dbfbff':'#7ddfed';const x=water.x+Math.sin(phase)*15*s,y=water.y-(34+Math.cos(phase)*12)*s;c.beginPath();c.ellipse(x,y,1.2*s,2.5*s,0,0,Math.PI*2);c.fill();}
  for(const [x,y]of [[154,69],[1293,88],[193,332],[1300,330],[102,672],[1260,674]]){for(let i=0;i<3;i++){const p=(t/4200+i/3)%1;const px=v.x+(x+Math.sin(p*5)*8)*s,py=v.y+(y-p*38)*s;c.globalAlpha=.19*(1-p);c.fillStyle='#f6ead4';c.beginPath();c.ellipse(px,py,(4+p*7)*s,(7+p*10)*s,0,0,Math.PI*2);c.fill();}}
  c.globalAlpha=1;for(let i=0;i<5;i++){const phase=t/1400+i*2,x=530+i*96+Math.sin(phase)*35,y=660+Math.cos(phase*.8)*32;c.fillStyle=['#ffc7e0','#ffe28c','#c7a2ff'][i%3];const px=v.x+x*s,py=v.y+y*s;c.fillRect(px,py,2*s,2*s);c.fillRect(px+3*s,py+Math.sin(phase*8)*2*s,2*s,2*s);}c.restore();
 }
 character(p){
  const c=this.ctx,s=this.view().scale,pos=this.screen(p.x,p.y),ceo=p.id==='mario',sheet=ceo?{image:this.avatar,ready:this.avatarReady}:this.sheets.get(p.id);
  c.fillStyle='#12291d66';c.beginPath();c.ellipse(pos.x,pos.y,12*s,4*s,0,0,Math.PI*2);c.fill();
  if(sheet?.ready){const cols=4,rows=ceo?3:4,row=p.seated&&!ceo?3:p.walking?(Math.floor(p.step)%2?0:2):1,sw=sheet.image.width/cols,sh=sheet.image.height/rows;const h=(ceo?91:82)*s,w=h*sw/sh;
   c.imageSmoothingEnabled=true;c.drawImage(sheet.image,p.dir*sw,row*sh,sw,sh,pos.x-w/2,pos.y-h*.91,w,h);
  }else{const step=p.walking?Math.sin(p.step)*2*s:0;c.fillStyle='#342d29';c.fillRect(pos.x-5*s,pos.y-10*s,4*s,(10+step)*s);c.fillRect(pos.x+2*s,pos.y-10*s,4*s,(10-step)*s);c.fillStyle=p.color;c.beginPath();c.roundRect(pos.x-8*s,pos.y-29*s,16*s,20*s,4*s);c.fill();c.fillStyle='#e0b486';c.beginPath();c.arc(pos.x,pos.y-37*s,9*s,0,Math.PI*2);c.fill();}
  const show=ceo||this.hover?.id===p.id||this.selected===p.id||this.meeting;if(show)this.pill(pos.x,pos.y-(ceo?83:75)*s,ceo?'♛ Mario':p.name,{border:ceo?'#e7bf5b':p.color,font:9});
  if(this.active===p.id)this.pill(pos.x,pos.y-102*s,'● Lucrează',{color:'#c6efa5',border:'#6baf65',font:9});
 }
 frame(t){
  const dt=Math.min((t-(this.last||t))/1000,.05);this.last=t;if(this.people.length){this.tick(dt);const c=this.ctx;c.clearRect(0,0,this.width,this.height);this.scenery(t);
   const v=this.view();for(const b of BUILDINGS){if(this.hover?.id===b.id){c.save();c.strokeStyle=b.color;c.lineWidth=2;c.shadowColor=b.color;c.shadowBlur=12;c.strokeRect(v.x+b.bounds[0]*v.scale,v.y+b.bounds[1]*v.scale,(b.bounds[2]-b.bounds[0])*v.scale,(b.bounds[3]-b.bounds[1])*v.scale);c.restore();}const x=v.x+b.label[0]*v.scale,y=v.y+b.label[1]*v.scale;this.pill(x,y,b.icon+' '+b.name,{border:b.color,color:b.id==='mario'?'#ffe59a':'#fff4d6',font:Math.max(8,Math.min(11,11*v.scale+4))});}
   [...this.people,this.ceo].sort((a,b)=>a.y-b.y).forEach(p=>this.character(p));
   const tooltip=document.getElementById('mapTooltip');if(this.hover){tooltip.hidden=false;const p=this.hover.bounds?{x:v.x+this.hover.label[0]*v.scale,y:v.y+this.hover.label[1]*v.scale}:this.screen(this.hover.x,this.hover.y,110);tooltip.style.left=Math.max(12,Math.min(this.width-235,p.x-70))+'px';tooltip.style.top=Math.max(122,p.y+16)+'px';tooltip.textContent=this.hover.name+' · '+(this.hover.subtitle||this.hover.role||'CEO');}else tooltip.hidden=true;
  }requestAnimationFrame(t=>this.frame(t));
 }
}
