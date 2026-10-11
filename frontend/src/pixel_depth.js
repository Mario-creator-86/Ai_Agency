import { PIXEL_LAYOUT } from './pixel_desks.js';
import { drawOutdoorLight } from './pixel_environment.js';
import { weatherEffects } from './hq_weather.js';

const plates = new WeakMap();

/** Feet/prop base order is independent of facing direction and registration/agent order. */
export function depthOrder(items) {
  return [...items].sort((a,b)=>a.depth-b.depth || String(a.id).localeCompare(String(b.id)));
}

export function streetLighting(moment,layout=PIXEL_LAYOUT) {
  const day=Math.max(0,Math.min(1,moment.daylight));
  if(day===1)return 'none';
  const brightness=layout.depth.sprite_night_brightness+(1-layout.depth.sprite_night_brightness)*day;
  const saturation=layout.depth.sprite_night_saturation+(1-layout.depth.sprite_night_saturation)*day;
  return `brightness(${brightness}) saturate(${saturation})`;
}

export function insidePolygon(x,y,points) {
  let inside=false;
  for(let i=0,j=points.length-1;i<points.length;j=i++){
    const a=points[i],b=points[j];
    if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside;
  }
  return inside;
}

/** The original foliage palette distinguishes leaves/petals from gaps showing the road. */
export function foliagePixel(r,g,b) {
  return (g-r>=5 && g>=b*.9)
    || (r<55 && g<65 && b<75 && g>r+3)
    || (r>70 && g>55 && b<g*.7 && r<g*1.65)
    || (r>150 && g>130 && b<g*.94 && r-g<85)
    || (r>125 && r>g*1.3 && r>b*1.08 && b>g*.7);
}

function foregroundPlate(image,layout) {
  if(!image?.complete || !image.naturalWidth || typeof document==='undefined')return null;
  let plate=plates.get(image);
  if(plate)return plate;
  const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
  const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),mask=new Uint8Array(canvas.width*canvas.height);
  const sx=canvas.width/layout.world.width,sy=canvas.height/layout.world.height;
  const regions=layout.depth.foreground_regions.map(region=>({...region,
    bounds:{x0:Math.floor(Math.min(...region.polygon.map(p=>p[0]))*sx),x1:Math.min(canvas.width,Math.ceil(Math.max(...region.polygon.map(p=>p[0]))*sx)),
      y0:Math.floor(Math.min(...region.polygon.map(p=>p[1]))*sy),y1:Math.min(canvas.height,Math.ceil(Math.max(...region.polygon.map(p=>p[1]))*sy))}}));
  for(const region of regions)for(let y=region.bounds.y0;y<region.bounds.y1;y++)for(let x=region.bounds.x0;x<region.bounds.x1;x++){
    const index=y*canvas.width+x,offset=index*4;
    if(insidePolygon((x+.5)/sx,(y+.5)/sy,region.polygon)
      &&(region.material==='solid'||foliagePixel(pixels.data[offset],pixels.data[offset+1],pixels.data[offset+2])))mask[index]=1;
  }
  // Keep small shaded leaf interiors, but leave genuine gaps to the street transparent.
  const closed=mask.slice();
  for(let y=1;y<canvas.height-1;y++)for(let x=1;x<canvas.width-1;x++){
    const i=y*canvas.width+x;if(mask[i])continue;
    let neighbours=0;for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++)neighbours+=mask[i+dy*canvas.width+dx];
    if(neighbours>=6)closed[i]=1;
  }
  let opaque=0;for(let i=0;i<closed.length;i++){pixels.data[i*4+3]=closed[i]?255:0;opaque+=closed[i];}
  ctx.putImageData(pixels,0,0);
  plate={mask:canvas,opaque,graded:null,key:null};plates.set(image,plate);return plate;
}

/** A runtime compositor mask reuses exact approved artwork pixels; no replacement image. */
export function drawSceneForeground(ctx,image,moment,weather,layout=PIXEL_LAYOUT) {
  const plate=foregroundPlate(image,layout);if(!plate)return false;
  // Regrade when light visibly changes, rather than recopying the native image every tick.
  const steps=layout.depth.light_steps;
  const light={...moment,daylight:Math.round(moment.daylight*steps)/steps,dusk:Math.round(moment.dusk*steps)/steps};
  const key=`${light.daylight}:${light.dusk}:${weatherEffects(weather).cloudiness}`;
  if(plate.key!==key){
    const canvas=plate.graded||document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
    const c=canvas.getContext('2d');c.drawImage(image,0,0);
    c.save();c.scale(canvas.width/layout.world.width,canvas.height/layout.world.height);drawOutdoorLight(c,light,weather);c.restore();
    c.globalCompositeOperation='destination-in';c.drawImage(plate.mask,0,0);c.globalCompositeOperation='source-over';
    plate.graded=canvas;plate.key=key;
  }
  ctx.save();ctx.imageSmoothingEnabled=false;ctx.drawImage(plate.graded,0,0,layout.world.width,layout.world.height);ctx.restore();return true;
}

export function foregroundStatus(image) {
  const plate=plates.get(image);return {ready:Boolean(plate),opaque:plate?.opaque||0};
}
