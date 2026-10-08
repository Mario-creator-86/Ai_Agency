import ACTORS from '../../config/pixel_actors.json' with { type: 'json' };
export { ACTORS };
const images=new Map();
let loading;

/** Own-origin static art only. A failed sheet preserves the code-drawn fallback. */
export function loadActorAtlases() {
  if(loading)return loading;
  if(typeof Image==='undefined')return Promise.resolve(false);
  loading=Promise.all(Object.entries(ACTORS.atlases).map(([key,asset])=>new Promise(resolve=>{
    const image=new Image();
    image.onload=()=>{if(image.naturalWidth===asset.width&&image.naturalHeight===asset.height){images.set(key,image);resolve(true);}else resolve(false);};
    image.onerror=()=>resolve(false);image.src=asset.url;
  }))).then(results=>results.every(Boolean));
  return loading;
}
export function actorAtlasStatus(){return {loaded:images.size,total:Object.keys(ACTORS.atlases).length};}

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
  else if(kind==='dog')row=3;
  else if(kind==='cat'){
    row=actor.pose==='walk'?1:2;
    col=actor.pose==='walk'?col:actor.pose==='groom'?1:actor.pose==='stretch'?2:actor.blink?3:0;
    height=ACTORS.sizes.cat;
  }
  const r=registered(key,row,col,0,0,height);
  if(!r)return false;
  ctx.save();ctx.translate(Math.round(actor.x),Math.round(actor.y));ctx.scale(actor.direction||1,1);
  paint(ctx,r);ctx.restore();return true;
}

export function staffAtlasChoice(profile,motion){
  const person=ACTORS.staff.find(p=>p.employee_id===profile.employeeId&&p.hair===profile.hair&&p.coat===profile.coat);
  if(!person)return null;
  if(motion.mode==='IDLE'&&motion.animate&&['sip','stretch'].includes(motion.gesture))return {
    key:'idle',row:person.idle_row,col:person.idle_col+(motion.gesture==='stretch'?1:0)
  };
  return {key:person.atlas,row:person.row,col:motion.mode==='WORKING'?1:motion.mode==='THINKING'?2:motion.mode==='REVIEWING'?3:0};
}

/** Asset identity is employee-bound and palette-checked; generated poses never change runtime. */
export function drawStaffAtlas(ctx,profile,motion,center,floor,scale,portrait=false,foreground=false){
  const choice=staffAtlasChoice(profile,motion);
  if(!choice)return false;
  const r=registered(choice.key,choice.row,choice.col,center,floor,40*scale);
  if(!r)return false;
  const bob=motion.animate?Math.floor(motion.breath/2):0;
  ctx.save();
  if(portrait){
    const f=r.frame;
    ctx.imageSmoothingEnabled=false;
    ctx.drawImage(r.image,f.x,f.y,f.width,f.height*0.5,r.left,r.top,r.width,r.height*0.5);
  }else if(foreground){
    // Face/raised hands and side arms may cross the backrest; the jacket's centre remains behind it.
    ctx.beginPath();ctx.rect(r.left,r.top-r.height*0.05,r.width,r.height*0.39);
    ctx.rect(r.left,r.top+r.height*0.25,r.width*0.23,r.height*0.4);
    ctx.rect(r.left+r.width*0.76,r.top+r.height*0.25,r.width*0.24,r.height*0.4);ctx.clip();
    const tap=motion.animate&&['WORKING','REVIEWING'].includes(motion.mode)?motion.gestureFrame%2:0;
    paint(ctx,r,bob+tap);
  }else paint(ctx,r,bob);
  ctx.restore();return true;
}
