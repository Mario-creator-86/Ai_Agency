/** Contact-driven pixel character rig. Ambient fiction; independent of employee state. */
const TAU=Math.PI*2;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const point=(x,y)=>({x,y});
const add=(a,b)=>point(a.x+b.x,a.y+b.y);
const mix=(a,b,t)=>a+(b-a)*t;
const fraction=v=>((v%1)+1)%1;

/** Two fixed-length bones, with the bend side selecting knee/elbow orientation. */
export function jointBetween(root,target,upper,lower,bend=1) {
 const dx=target.x-root.x,dy=target.y-root.y,d=Math.max(.0001,Math.hypot(dx,dy));
 const reach=clamp(d,Math.abs(upper-lower)+.0001,upper+lower-.0001);
 const along=(upper*upper-lower*lower+reach*reach)/(2*reach);
 const away=Math.sqrt(Math.max(0,upper*upper-along*along))*bend;
 return point(root.x+dx/d*along-dy/d*away,root.y+dy/d*along+dx/d*away);
}
function footCycle(phase,stride,stance,lift) {
 const t=fraction(phase),extent=stride*stance/2;
 if(t<stance)return {x:extent-stride*t,y:0,contact:true};
 const swing=(t-stance)/(1-stance);
 return {x:mix(-extent,extent,swing),y:-Math.sin(swing*Math.PI)*lift,contact:false};
}
export function actorPose(actor) {
 const mode=actor.activity,scale=actor.scale||1;
 const distance=(actor.distance||0)/scale;
 const moving=actor.moving!==false;
 const run=mode==='run',bike=mode==='bike',skate=mode==='skate';
 const stride=run?34:24,phase=distance/stride+(actor.phase||0)/TAU;
 const left=moving?footCycle(phase,stride,run?.35:.62,run?9:4):{x:-3,y:0,contact:true};
 const right=moving?footCycle(phase+.5,stride,run?.35:.62,run?9:4):{x:3,y:0,contact:true};
 const flight=run&&!left.contact&&!right.contact;
 let hip=point(0,run?-17-(flight?1.5:0):-17);
 let shoulder=point(run?5:1,hip.y-10),head=point(shoulder.x+1,shoulder.y-6);
 let footBack=point(left.x,left.y),footFront=point(right.x,right.y);
 let handBack=point(-right.x*.65,-15),handFront=point(-left.x*.65,-15);
 let crank=0,wheel=distance/8,push=false;
 if(run){
  handBack=point(-right.x*.9+3,-20+Math.sin(phase*TAU)*2);
  handFront=point(-left.x*.9+3,-20-Math.sin(phase*TAU)*2);
 }
 if(bike) {
  hip=point(-6,-17);shoulder=point(3,-25);head=point(7,-30);
  crank=distance/110*TAU+(actor.phase||0);
  footBack=point(Math.cos(crank)*4,-7+Math.sin(crank)*4);
  footFront=point(-Math.cos(crank)*4,-7-Math.sin(crank)*4);
  handBack=point(14,-23);handFront=point(16,-22);
 }
 if(skate) {
  const t=actor.skatePhase||0;
  hip=point(-1,-16);shoulder=point(2,-25);head=point(4,-30);
  footFront=point(6,-6);footBack=point(-7,-6);
  push=t>=.18&&t<.53;
  if(t<.18) {footBack=point(mix(-7,8,t/.18),-6*(1-t/.18)-Math.sin(t/.18*Math.PI)*4);}
  else if(push) {footBack=point(8-Math.min(19,(actor.pushDistance||0)/scale),0);hip.y=-14;}
  else if(t<.85){const u=(t-.53)/.32;footBack=point(mix(-11,-7,u),-Math.sin(u*Math.PI)*5-6*u);}
  handBack=point(-9,-18);handFront=point(10,-20);
 }
 // All held objects use these hands as their attachment transforms.
 const phone=point(head.x+4,head.y+1);
 if(mode==='phone') handFront=phone;
 if(mode==='smoke'&&!moving) handFront=point(head.x+6,head.y+5);
 if(actor.bag||mode==='commute'||mode==='shopping') handFront=point(4+Math.sin(phase*TAU)*1.1,-12);
 if(mode==='phone')handFront=phone;
 if(mode==='dog')handFront=point(6,-17);
 const legBack=jointBetween(hip,footBack,9.5,9.5,-1),legFront=jointBetween(hip,footFront,9.5,9.5,-1);
 const elbowBack=jointBetween(shoulder,handBack,7,7,1),elbowFront=jointBetween(shoulder,handFront,7,7,1);
 return {hip,shoulder,head,footBack,footFront,handBack,handFront,legBack,legFront,elbowBack,elbowFront,
  phone,crank,wheel,push,flight,leftContact:left.contact,rightContact:right.contact};
}

const SKINS=['#f0cdb3','#dfb592','#c99770','#b78361','#95654b','#794d39','#59392c','#432d25'];
const HAIR=['#201e23','#33251e','#65462f','#a67946','#d0b67d','#81827c'];
export function appearance(rng,activity) {
 const pick=list=>list[Math.floor(rng()*list.length)];
 const youth=activity==='skate';
 return {skin:pick(SKINS),hair:pick(HAIR),hairStyle:pick(['crop','curls','long','bun','shaved','waves']),
  headwear:activity==='bike'||youth?'helmet':pick(['none','none','none','cap','beanie','headscarf','turban']),
  glasses:rng()<.18,beard:!youth&&rng()<.2,ageBand:youth?'young':'adult',
  scale:youth?.83+rng()*.09:.90+rng()*.10,bodyWidth:6+Math.floor(rng()*3),
  coat:pick(['#b56c58','#548982','#777aab','#8b6a88','#b49a60','#6a8a66','#a8af9c']),
  trousers:pick(['#303e4e','#41433e','#55463d','#344e49']),
  outfit:youth?'hoodie':pick(['shirt','jacket','tunic','sweater']),
  shoes:pick(['#253031','#775844','#c8c9ac'])};
}
function pixel(ctx,x,y,w,h,color){ctx.fillStyle=color;ctx.fillRect(Math.round(x),Math.round(y),Math.max(1,Math.round(w)),Math.max(1,Math.round(h)));}
function line(ctx,a,b,width,color){
 const steps=Math.max(1,Math.ceil(Math.max(Math.abs(b.x-a.x),Math.abs(b.y-a.y))));
 for(let i=0;i<=steps;i++)pixel(ctx,mix(a.x,b.x,i/steps)-width/2,mix(a.y,b.y,i/steps)-width/2,width,width,color);
}
function disc(ctx,x,y,r,color){for(let y0=-r;y0<=r;y0++){const dx=Math.floor(Math.sqrt(r*r-y0*y0));pixel(ctx,x-dx,y+y0,dx*2+1,1,color);}}
function ring(ctx,x,y,r,angle){
 disc(ctx,x,y,r,'#142d30');disc(ctx,x,y,r-1,'#9daea4');disc(ctx,x,y,r-3,'#29493f');
 for(let i=0;i<3;i++)line(ctx,point(x,y),point(x+Math.cos(angle+i*TAU/3)*(r-2),y+Math.sin(angle+i*TAU/3)*(r-2)),1,'#b3c4b6');
 disc(ctx,x,y,1,'#e0dab6');
}
/** Render one body in profile. Mirroring flips the complete skeleton AND every held prop. */
export function drawHuman(ctx,actor,baseline) {
 const pose=actorPose(actor),s=actor.scale||1;
 const p=v=>point(v.x*s,v.y*s);
 const rect=(x,y,w,h,c)=>pixel(ctx,x*s,y*s,w*s,h*s,c);
 const bone=(a,b,w,c)=>line(ctx,p(a),p(b),Math.max(1,w*s),c);
 ctx.save();ctx.translate(Math.round(actor.x),Math.round(baseline));ctx.scale(actor.dir,1);
 // Contact shadow stays on the ground even during the aerial phase of running.
 pixel(ctx,-12*s,0,24*s,2,'#081d174f');pixel(ctx,-8*s,-1,16*s,1,'#081d1730');
 if(actor.activity==='bike') {
  ring(ctx,-16*s,-8*s,Math.round(8*s),pose.wheel);ring(ctx,17*s,-8*s,Math.round(8*s),pose.wheel);
  for(const [a,b] of [[[-16,-8],[-7,-18]],[[-7,-18],[0,-7]],[[0,-7],[-16,-8]],[[0,-7],[12,-21]],[[12,-21],[17,-8]],[[-7,-18],[12,-21]]])bone(point(a[0],a[1]),point(b[0],b[1]),2,actor.coat);
  rect(-11,-19,10,2,'#1d302c');bone(point(12,-21),point(14,-25),2,'#adc1b1');rect(13,-25,6,2,'#1b322f');
  bone(point(0,-7),pose.footBack,1,'#b8c3b1');bone(point(0,-7),pose.footFront,1,'#b8c3b1');
 }
 if(actor.activity==='skate'){
  rect(-14,-6,29,2,'#d0a66f');rect(-12,-4,25,1,'#715a43');
  disc(ctx,-9*s,-2*s,2,'#c1c9ad');disc(ctx,10*s,-2*s,2,'#c1c9ad');
 }
 // Far limbs precede the torso; near limbs and attached objects follow it.
 bone(pose.hip,pose.legBack,3,'#263b3d');bone(pose.legBack,pose.footBack,3,'#263b3d');
 bone(pose.shoulder,pose.elbowBack,3,'#39564f');bone(pose.elbowBack,pose.handBack,2,actor.skin);
 rect(pose.footBack.x-2,pose.footBack.y-2,6,2,actor.shoes||'#283733');
 bone(pose.hip,pose.shoulder,actor.bodyWidth||7,actor.coat);
 bone(add(pose.hip,point(-2,-1)),add(pose.shoulder,point(-2,1)),1,'#ffffff20');
 if(actor.outfit==='tunic')rect(pose.hip.x-4,pose.hip.y-2,9,6,actor.coat);
 if(actor.outfit==='jacket'||actor.activity==='commute')bone(add(pose.shoulder,point(2,1)),add(pose.hip,point(2,-1)),1,'#202f3455');
 if(actor.activity==='commute'){rect(pose.shoulder.x,pose.shoulder.y,3,2,'#e6ddbf');rect(pose.shoulder.x+1,pose.shoulder.y+2,1,5,'#60405e');}
 const hx=pose.head.x-4,hy=pose.head.y-5;
 rect(hx+1,hy,7,10,actor.skin);rect(hx,hy+2,9,6,actor.skin);
 rect(hx+8,hy+5,2,2,actor.skin);rect(hx+1,hy+7,1,2,'#794c3944');
 // Directional face: ear behind the eye; the nose is on the facing side.
 rect(hx+6,hy+4,1,2,'#263038');rect(hx+7,hy+8,2,1,'#80523d');
 if(actor.beard)rect(hx+4,hy+8,5,2,actor.hair);
 const hair=actor.hair||'#33251e',style=actor.hairStyle||'crop';
 rect(hx,hy-1,8,3,hair);rect(hx,hy+1,2,5,hair);
 if(style==='curls'||style==='waves'){rect(hx-1,hy,3,3,hair);rect(hx+2,hy-2,3,2,hair);rect(hx+6,hy-1,3,2,hair);}
 if(style==='long')rect(hx-1,hy+2,3,11,hair);
 if(style==='bun')rect(hx-3,hy,4,4,hair);
 if(style==='shaved')rect(hx+1,hy,7,1,actor.skin);
 const gear=actor.headwear||'none';
 if(gear==='helmet'){rect(hx-1,hy-2,10,4,'#d8b97c');rect(hx+1,hy-1,2,2,'#746a54');rect(hx+5,hy-1,2,2,'#746a54');rect(hx,hy+3,1,6,'#726545');}
 if(gear==='cap'){rect(hx-1,hy-2,9,3,actor.coat);rect(hx+6,hy,5,1,actor.coat);}
 if(gear==='beanie'){rect(hx-1,hy-3,9,4,actor.coat);rect(hx,hy-4,7,1,actor.coat);}
 if(gear==='headscarf'){rect(hx-2,hy-2,10,3,actor.coat);rect(hx-2,hy+1,3,12,actor.coat);rect(hx-1,hy+10,8,3,actor.coat);}
 if(gear==='turban'){rect(hx-2,hy-4,11,5,'#ddd6bc');rect(hx,hy-5,7,2,'#ddd6bc');rect(hx+2,hy-3,5,1,'#a9a589');}
 if(actor.glasses){rect(hx+4,hy+3,5,1,'#ccd6bf');rect(hx+4,hy+5,4,1,'#ccd6bf');rect(hx+4,hy+3,1,3,'#ccd6bf');}
 bone(pose.hip,pose.legFront,3,actor.trousers);bone(pose.legFront,pose.footFront,3,actor.trousers);
 rect(pose.footFront.x-2,pose.footFront.y-2,6,2,actor.shoes||'#283733');
 bone(pose.shoulder,pose.elbowFront,3,actor.coat);bone(pose.elbowFront,pose.handFront,2,actor.skin);
 rect(pose.handFront.x-1,pose.handFront.y-1,3,3,actor.skin);
 const hand=pose.handFront;
 if(actor.activity==='phone') {rect(hand.x,hand.y-3,2,7,'#162938');rect(hand.x,hand.y-2,1,3,'#8faeb1');}
 else if(actor.bag||actor.activity==='commute'||actor.activity==='shopping') {
  // Handle starts inside the closed hand; bag weight hangs vertically from it.
  rect(hand.x-1,hand.y+1,4,1,'#a5a287');rect(hand.x-1,hand.y+1,1,3,'#a5a287');rect(hand.x+2,hand.y+1,1,3,'#a5a287');
  rect(hand.x-3,hand.y+4,9,7,actor.activity==='shopping'?'#cdb786':'#48504a');
  rect(hand.x-3,hand.y+4,9,1,'#b1ae90');rect(hand.x,hand.y+7,2,1,'#b1ae90');
 }
 if(actor.activity==='smoke'&&actor.moving===false){
  rect(hand.x+1,hand.y,5,1,'#d7ceb5');rect(hand.x+5,hand.y,1,1,'#cb9673');
  for(let i=0;i<3;i++){const t=((actor.age||0)*.4+i/3)%1;pixel(ctx,(hand.x+5+Math.sin(t*4)*2)*s,(hand.y-t*12)*s,1,2,'#b5c8bf55');}
 }
 if(actor.activity==='party'){rect(hand.x,hand.y,4,5,'#dec5a2');rect(hand.x,hand.y,4,1,'#f1e4c3');}
 if(actor.activity==='angry')rect(hx+5,hy+3,3,1,'#442f2d');
 ctx.restore();
 return {pose,hand:{x:actor.x+actor.dir*hand.x*s,y:baseline+hand.y*s}};
}
export function drawAnimal(ctx,actor,baseline,dog=false) {
 const s=dog?1: .7, x=dog?actor.x-actor.dir*27:actor.x;
 const phase=(actor.distance||0)/(dog?20:16)*TAU+(actor.phase||0);
 ctx.save();ctx.translate(Math.round(x),Math.round(baseline));ctx.scale(actor.dir*s,s);
 const c=dog?'#c69d71':actor.tone;
 pixel(ctx,-12,0,25,2,'#0b20194d');
 for(let i=0;i<4;i++){
  const swing=Math.sin(phase+(i%2)*Math.PI+(i>1?Math.PI:0));
  const root=point(i<2?-7:7,-7),foot=point(root.x+swing*3,Math.min(0,-swing*3));
  line(ctx,root,foot,2,i%2?c:'#66503e');
 }
 pixel(ctx,-11,-13,23,8,c);pixel(ctx,6,-20,9,10,c);pixel(ctx,7,-24,3,5,c);
 pixel(ctx,12,-23,3,4,c);pixel(ctx,12,-18,1,1,'#203b32');pixel(ctx,14,-16,4,3,dog?'#ecd7ad':c);
 pixel(ctx,17,-17,2,2,'#20332e');line(ctx,point(-10,-11),point(-15,-20+Math.sin(phase)*2),2,c);
 if(dog){pixel(ctx,7,-11,8,2,'#659082');pixel(ctx,6,-9,5,3,'#eeddbb');}
 ctx.restore();return {x:x+actor.dir*9,y:baseline-11};
}
