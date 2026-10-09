import ACTORS from '../../config/pixel_actors.json' with { type: 'json' };
import { seatedGeometry, StaffPoseTrack } from './pixel_staff_pose.js';
import { PIXEL_LAYOUT } from './pixel_desks.js';
export { ACTORS };
const images=new Map();
const poses = new StaffPoseTrack();
let loading;

/** Own-origin static art only. A failed sheet preserves the code-drawn fallback. */
export function loadActorAtlases() {
  if(loading)return loading;
  if(typeof Image==='undefined')return Promise.resolve(false);
  loading=Promise.all(Object.entries({ ...ACTORS.atlases, chair_cleanplate: ACTORS.chair_cleanplate }).map(([key,asset])=>new Promise(resolve=>{
    const image=new Image();
    image.onload=()=>{if(image.naturalWidth===asset.width&&image.naturalHeight===asset.height){images.set(key,image);resolve(true);}else resolve(false);};
    image.onerror=()=>resolve(false);image.src=asset.url;
  }))).then(results=>results.every(Boolean));
  return loading;
}
export function actorAtlasStatus(){return {loaded:images.size,total:Object.keys(ACTORS.atlases).length+1};}

function registered(key,row,col,x,y,height) {
  const image=images.get(key),group=ACTORS.atlases[key]?.rows[row],frame=group?.frames[col];
  if(!image||!frame)return null;
  const scale=height/group.height,w=frame.width*scale,h=frame.height*scale;
  return {image,frame,left:x-frame.anchor_x*scale,top:y-h,width:w,height:h,scale};
}
function paint(ctx,r,bob=0){
  const f=r.frame,split=Math.floor(f.height*0.72),dh=split*r.scale;
  ctx.imageSmoothingEnabled=false;
  ctx.drawImage(r.image,f.x,f.y,f.width,split,r.left,r.top-bob,r.width,dh);
  ctx.drawImage(r.image,f.x,f.y+split,f.width,f.height-split,r.left,r.top+dh,r.width,r.height-dh);
}

export function drawTownAtlas(ctx,kind,actor){
  let key='pets',row=0,col=Math.floor(actor.step/2)%4,height=ACTORS.sizes[kind];
  if(kind==='pedestrian'){key='walk';row=actor.id%4;}
  else if(kind==='car'){key='cars';row=actor.variant%ACTORS.atlases.cars.rows.length;col=0;}
  else if(kind==='dog')row=3;
  else if(kind==='cat'){
    row=actor.pose==='walk'?1:2;
    col=actor.pose==='walk'?col:actor.pose==='groom'?1:actor.pose==='stretch'?2:actor.blink?3:0;
    height=ACTORS.sizes.cat;
  }
  if (['pedestrian','bicycle'].includes(kind)) height *= PIXEL_LAYOUT.life.character_scale;
  const r=registered(key,row,col,0,0,height);
  if(!r)return false;
  ctx.save();ctx.translate(actor.x,actor.y);ctx.scale(actor.direction||1,1);
  const bob=kind==='cat'&&['groom','stretch'].includes(actor.pose)?Math.floor(actor.step/2)%2:0;
  if (kind==='car') paintVehicle(ctx,r,actor); else paint(ctx,r,bob);
  ctx.restore();return true;
}

function paintVehicle(ctx,r,actor) {
  ctx.imageSmoothingEnabled=false; whole(ctx,r);
  const speed=(PIXEL_LAYOUT.world.width+2*PIXEL_LAYOUT.life.street_margin)/PIXEL_LAYOUT.life.car_cycle_ms;
  for (const wheel of r.frame.wheels) {
    const x=r.left+wheel.x*r.width,y=r.top+wheel.y*r.height,radius=wheel.rim*r.height;
    const angle=(actor.elapsed*speed/(wheel.tyre*r.height)) % (2*Math.PI);
    ctx.save();ctx.beginPath();ctx.arc(x,y,radius,0,2*Math.PI);ctx.clip();
    ctx.translate(x,y);ctx.rotate(angle);ctx.translate(-x,-y);whole(ctx,r);ctx.restore();
  }
  if(actor.wet){ctx.fillStyle='#b9af8635';ctx.fillRect(r.left,2,r.width,1);}
  if(actor.lights){
    const x=r.left+r.width*.97,y=r.top+r.height*.57;
    ctx.fillStyle='#ffe5ac24';ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+40,y-4);ctx.lineTo(x+40,y+10);ctx.closePath();ctx.fill();
    ctx.fillStyle='#ffe7b5';ctx.fillRect(x-1,y-1,2,2);
  }
}

export function staffAtlasChoice(profile,motion){
  const person=ACTORS.staff.find(p=>p.employee_id===profile.employeeId
    &&Object.entries(p.appearance).every(([key,value])=>profile[key]===value));
  if(!person)return null;
  // One stable ensemble is rigged continuously. Independent generated poses are not
  // animation frames: swapping them would move the chair, pelvis and feet.
  return {key:person.atlas,row:person.row,col:ACTORS.atlases[person.atlas].base_column};
}

export function hasSeatedEnsemble(profile) {
  const choice = staffAtlasChoice(profile, {});
  return Boolean(choice && images.has(choice.key) && images.has('chair_cleanplate'));
}

/** The original scene remains the base; only traced empty-chair silhouettes are replaced. */
export function clearEmptyChair(ctx, profile, station, layout) {
  if (!hasSeatedEnsemble(profile) || !station.chair_clear_polygons?.length) return false;
  ctx.save(); ctx.beginPath();
  for (const polygon of station.chair_clear_polygons) {
    ctx.moveTo(...polygon[0]); for (const point of polygon.slice(1)) ctx.lineTo(...point); ctx.closePath();
  }
  ctx.clip(); ctx.imageSmoothingEnabled = false;
  ctx.drawImage(images.get('chair_cleanplate'), 0, 0, layout.world.width, layout.world.height);
  ctx.restore(); return true;
}

function regionPath(ctx, r, region) {
  const points = region.polygon.map(([x,y]) => [r.left+x*r.width, r.top+y*r.height]);
  ctx.moveTo(...points[0]); for (const point of points.slice(1)) ctx.lineTo(...point); ctx.closePath();
}
function whole(ctx,r) {
  const f=r.frame; ctx.drawImage(r.image,f.x,f.y,f.width,f.height,r.left,r.top,r.width,r.height);
}
function joint(ctx,r,region,angle,breath=1) {
  const pivot = { x:r.left+region.pivot[0]*r.width, y:r.top+region.pivot[1]*r.height };
  ctx.save(); ctx.translate(pivot.x,pivot.y); ctx.rotate(angle); ctx.scale(1,breath); ctx.translate(-pivot.x,-pivot.y);
  ctx.beginPath(); regionPath(ctx,r,region); ctx.clip(); whole(ctx,r); ctx.restore();
}

/** Asset identity is employee-bound; the chair and person share a single uniform scale. */
export function drawStaffAtlas(ctx,profile,motion,center,floor,scale,portrait=false,foreground=false,seating=null){
  const choice=staffAtlasChoice(profile,motion);
  if(!choice)return false;
  const r=registered(choice.key,choice.row,choice.col,center,floor,40*scale);
  if(!r || (!portrait && !hasSeatedEnsemble(profile)))return false;
  if(foreground)return true; // Integrated chair already has correct internal occlusion.
  if(!portrait)Object.assign(r,seatedGeometry(r.frame,center,floor,40*scale,seating));
  ctx.save();
  ctx.imageSmoothingEnabled=false;
  if(portrait){
    const f=r.frame;
    ctx.imageSmoothingEnabled=false;
    ctx.drawImage(r.image,f.x,f.y,f.width,f.height*0.5,r.left,r.top,r.width,r.height*0.5);
  }else {
    const rig=r.frame.rig,pose=poses.frame(profile.employeeId,motion);
    ctx.save(); ctx.beginPath(); ctx.rect(r.left-2,r.top-2,r.width+4,r.height+4);
    regionPath(ctx,r,rig.head); regionPath(ctx,r,rig.hand); ctx.clip('evenodd'); whole(ctx,r); ctx.restore();
    joint(ctx,r,rig.hand,pose.hand); joint(ctx,r,rig.head,pose.head,pose.breath);
  }
  ctx.restore();return true;
}
