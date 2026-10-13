import PORTRAITS from '../../config/pixel_portraits.json' with {type:'json'};
import {ACTORS} from './pixel_actor_atlas.js';
import {paintSeated} from './pixel_seated_art.js';
import {shade} from './pixel_art.js';
export {PORTRAITS};
let image=null,loading;

/** Separate frontal profile art; desk ensembles continue to face their actual monitors. */
export function portraitChoice(profile){
 const person=ACTORS.staff.find(p=>p.employee_id===profile.employeeId
  &&Object.entries(p.appearance).every(([key,value])=>profile[key]===value));
 if(!person)return null;
 return PORTRAITS.profiles.find(p=>p.employee_id===person.employee_id
  &&p.roles.some(r=>r.toLowerCase()===profile.role))||null;
}
export function portraitInfo(profile){
 const choice=portraitChoice(profile);
 return {orientation:'front',background_role:profile.role,background:choice?.background||'personal office',
  source:choice&&image?'native_atlas':'front_fallback',asset:choice&&image?PORTRAITS.asset:null};
}
export function loadPortraitAtlas(){
 if(loading)return loading;
 if(typeof Image==='undefined')return Promise.resolve(false);
 loading=new Promise(resolve=>{
  const candidate=new Image();
  candidate.onload=()=>{
   const valid=candidate.naturalWidth===PORTRAITS.width&&candidate.naturalHeight===PORTRAITS.height;
   if(valid)image=candidate;resolve(valid);
  };
  candidate.onerror=()=>resolve(false);candidate.src=PORTRAITS.asset;
 });
 return loading;
}
export function drawAgentPortrait(ctx,profile){
 const {width,height}=ctx.canvas,choice=portraitChoice(profile);
 ctx.save();ctx.imageSmoothingEnabled=false;ctx.clearRect(0,0,width,height);
 if(choice&&image){
  const [x,y,w,h]=choice.rect;
  // Contain without stretching a face if a caller uses a different card aspect ratio.
  const scale=Math.min(width/w,height/h),dw=w*scale,dh=h*scale;
  ctx.fillStyle=shade(profile.desk,-35);ctx.fillRect(0,0,width,height);
  ctx.drawImage(image,x,y,w,h,(width-dw)/2,(height-dh)/2,dw,dh);
 }else{
  // New hires/changed appearance never borrow another employee's generated face.
  ctx.fillStyle=shade(profile.desk,-50);ctx.fillRect(0,0,width,height);
  const unit=height/48;
  ctx.fillStyle=shade(profile.desk,-25);ctx.fillRect(0,height*.15,width,height*.06);
  for(let i=0;i<9;i++){ctx.fillStyle=i%2?shade(profile.coat,-30):shade(profile.accent,-35);ctx.fillRect(i*width/9,height*.22,width/16,height*.32);}
  ctx.translate(width/2-25*unit,-2*unit);ctx.scale(unit,unit);
  paintSeated(ctx,profile,{sway:0,breath:0,glance:0,blink:false,gesture:'rest',gestureFrame:0,animate:false},true,false);
 }
 ctx.restore();return true;
}
