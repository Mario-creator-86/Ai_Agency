import { PRESENTATION as S } from './pixel_presentation.js';
import { PIXEL_LAYOUT } from './pixel_desks.js';

/** Map a flat screen onto its calibrated desk plane, including inclined workstations. */
export function projectScreen(ctx,source,corners){
  const w=source.videoWidth||source.width,h=source.videoHeight||source.height;
  if(!w||!h)return;
  const vertices=[[0,0],[w,0],[w,h],[0,h]];
  for(const indices of [[0,1,2],[0,2,3]]){
    const [a,b,c]=indices.map(i=>vertices[i]),[p,q,r]=indices.map(i=>corners[i]);
    const det=(b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]);
    if(!det)continue;
    const ax=((q[0]-p[0])*(c[1]-a[1])-(r[0]-p[0])*(b[1]-a[1]))/det;
    const bx=((r[0]-p[0])*(b[0]-a[0])-(q[0]-p[0])*(c[0]-a[0]))/det;
    const ay=((q[1]-p[1])*(c[1]-a[1])-(r[1]-p[1])*(b[1]-a[1]))/det;
    const by=((r[1]-p[1])*(b[0]-a[0])-(q[1]-p[1])*(c[0]-a[0]))/det;
    ctx.save();ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.lineTo(...r);ctx.closePath();ctx.clip();
    ctx.transform(ax,ay,bx,by,p[0]-ax*a[0]-bx*a[1],p[1]-ay*a[0]-by*a[1]);
    ctx.drawImage(source,0,0);ctx.restore();
  }
}

/** A screen must clear its desk; never hide an invalid stand with a minimum height. */
export function monitorSupport(monitor){
  if(!monitor.housing)return null;
  const bottom=Math.max(monitor.polygon[2][1],monitor.polygon[3][1])+1;
  const desktop=monitor.housing.desktop_y;
  if(!Number.isFinite(desktop)||desktop-bottom<2)throw new RangeError('Monitor intersects its desktop');
  return {bottom,desktop,x:(monitor.polygon[2][0]+monitor.polygon[3][0])/2};
}

export class StudioScreens {
  constructor(fetchMedia=null){this.fetchMedia=fetchMedia;this.media=null;this.video=null;this.url=null;this.asset=null;this.error=null;this.generation=0;this.pending=false;this.playing=false;this.surfaces=new Map();this.artwork=new Map();}
  async loadArtwork(){
    return Promise.all(S.monitors.filter(m=>m.artwork).map(m=>new Promise(resolve=>{
      const image=new Image();
      image.onload=()=>{const size=m.artwork.source_size;
        if(image.naturalWidth===size[0]&&image.naturalHeight===size[1])this.artwork.set(m.desk_id,image);
        resolve(this.artwork.has(m.desk_id));};
      image.onerror=()=>resolve(false);image.src=m.artwork.asset;
    })));
  }
  drawArtwork(ctx){
    for(const monitor of S.monitors.filter(m=>m.artwork)){
      const image=this.artwork.get(monitor.desk_id);if(!image)continue;
      ctx.save();ctx.beginPath();monitor.artwork.mask.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.clip();
      ctx.imageSmoothingEnabled=false;ctx.drawImage(image,0,0,PIXEL_LAYOUT.world.width,PIXEL_LAYOUT.world.height);ctx.restore();
    }
  }
  async setMedia(media){
    this.media=media;const item=media?.local?.find(v=>v.size>0&&v.size<=S.media_max_bytes);
    if(item?.id===this.asset||this.pending)return;
    const epoch=++this.generation;this.release();this.asset=item?.id||null;
    if(!item||!this.fetchMedia)return;
    this.pending=true;
    try{
      const blob=await this.fetchMedia(item.stream);
      if(epoch!==this.generation)return;
      this.url=URL.createObjectURL(blob);this.video=document.createElement('video');
      this.video.src=this.url;this.video.muted=true;this.video.loop=true;this.video.playsInline=true;this.video.preload='auto';
      this.video.addEventListener('error',()=>{this.error='Filmul local nu poate fi decodat.';this.playing=false;});
      this.error=null;
    }catch{if(epoch===this.generation)this.error='Filmul local nu poate fi redat.';}
    finally{if(epoch===this.generation)this.pending=false;}
  }
  release(){this.video?.pause();this.video?.removeAttribute('src');this.video?.load();this.video=null;
    if(this.url)URL.revokeObjectURL(this.url);this.url=null;this.playing=false;}
  clear(){this.generation++;this.pending=false;this.media=null;this.asset=null;this.error=null;this.release();this.dialog?.close();}
  active(on){
    if(!this.video)return;
    if(on && !this.playing){this.playing=true;this.video.play().catch(()=>{this.playing=false;this.error='Apasă Film pentru a porni redarea.';});}
    else if(!on){this.video.pause();this.playing=false;}
  }
  draw(ctx,positions,motions,elapsed){
    const screens=[];
    for(const p of positions){
      const motion=motions.get(p.id);if(!motion)continue;
      for(const monitor of S.monitors.filter(m=>m.desk_id===p.desk_id)){
      const corners=monitor.polygon,x=Math.min(...corners.map(v=>v[0])),y=Math.min(...corners.map(v=>v[1]));
      const w=Math.max(...corners.map(v=>v[0]))-x,h=Math.max(...corners.map(v=>v[1]))-y;
      const off=motion.monitor==='off'||['PAUSED','UNKNOWN'].includes(motion.mode);
      let support;try{support=monitorSupport(monitor);}catch{continue;}
      // A missing repair asset preserves the original furniture rather than drawing a false panel.
      if(monitor.artwork&&!this.artwork.has(monitor.desk_id))continue;
      if(support&&!monitor.artwork){
        const cx=corners.reduce((n,p)=>n+p[0],0)/4,cy=corners.reduce((n,p)=>n+p[1],0)/4;
        ctx.beginPath();corners.forEach(([px,py],i)=>{const point=[px+(px<cx?-1:1),py+(py<cy?-1:1)];if(i)ctx.lineTo(...point);else ctx.moveTo(...point);});ctx.closePath();
        ctx.fillStyle='#111e28';ctx.fill();ctx.strokeStyle='#57717b';ctx.lineWidth=.5;ctx.stroke();
        ctx.fillStyle='#283c46';ctx.fillRect(support.x-1,support.bottom,2,support.desktop-support.bottom);
        ctx.fillStyle='#17262e';ctx.fillRect(support.x-6,support.desktop-1,12,1.5);
        ctx.fillStyle=off?'#645741':'#92bfb2';ctx.fillRect(corners[2][0]-2,corners[2][1]+.5,.5,.5);
      }
      ctx.save();ctx.beginPath();ctx.moveTo(...corners[0]);for(const point of corners.slice(1))ctx.lineTo(...point);ctx.closePath();ctx.clip();
      ctx.fillStyle=off?'#161b23':'#263a4b';ctx.fillRect(x,y,w,h);
      const film=!off&&this.video?.readyState>=2&&['IDLE','REVIEWING'].includes(motion.mode);
      if(film){ctx.imageSmoothingEnabled=false;projectScreen(ctx,this.video,corners);}
      else if(!off){
        let surface=this.surfaces.get(monitor);
        if(!surface){surface=document.createElement('canvas');surface.width=Math.ceil(w*2);surface.height=Math.ceil(h*2);this.surfaces.set(monitor,surface);}
        const content=surface.getContext('2d');content.setTransform(2,0,0,2,0,0);content.fillStyle='#263a4b';content.fillRect(0,0,w,h);
        content.fillStyle='#a3bbc160';content.fillRect(1,1,w-2,1);
        const actualWorking=['WORKING','REVIEWING'].includes(motion.mode);
        const scroll=actualWorking&&motion.animate?Math.floor(elapsed/1200)%4:0;
        for(let i=0;i<4;i++){content.fillStyle=i===scroll?'#75bba9':'#688397';content.fillRect(2,4+i*2,Math.max(2,(w-4)*(1-(i%3)*.2)),.6);}
        if(this.media?.youtube?.length){content.fillStyle='#bb5c55';content.fillRect(w-5,2,3,2);}
        if(motion.mode==='THINKING'&&motion.animate){content.fillStyle='#ada1cc';content.fillRect(w-3,h-3,1,1);}
        ctx.imageSmoothingEnabled=false;projectScreen(ctx,surface,corners);
      }
      ctx.restore();screens.push({agent_id:p.id,desk_id:p.desk_id,on:!off,source:film?'local_video':'state',time:film?this.video.currentTime:null});
      }
    }
    return screens;
  }
  openPlayer(){
    this.dialog?.close();
    const dialog=document.createElement('dialog');dialog.className='studio-player';
    this.dialog=dialog;
    const heading=document.createElement('h2');heading.id='studio-player-title';heading.textContent='Filmele studioului';dialog.setAttribute('aria-labelledby',heading.id);dialog.append(heading);
    const close=document.createElement('button');close.type='button';close.textContent='Închide';close.addEventListener('click',()=>dialog.close());dialog.append(close);
    const youtube=this.media?.youtube?.[0];
    if(youtube && /^[A-Za-z0-9_-]{11}$/.test(youtube.id)){
      const label=document.createElement('p');label.textContent=youtube.title;dialog.append(label);
      const frame=document.createElement('iframe');frame.title='YouTube · '+youtube.title;
      frame.src=`https://www.youtube-nocookie.com/embed/${encodeURIComponent(youtube.id)}?playsinline=1&enablejsapi=1&mute=${document.body.dataset.uiSound==='on'?'0':'1'}&origin=${encodeURIComponent(location.origin)}`;
      frame.allow='autoplay; encrypted-media; picture-in-picture';frame.referrerPolicy='strict-origin-when-cross-origin';frame.allowFullscreen=true;dialog.append(frame);
      const link=document.createElement('a');link.textContent='Deschide pe YouTube';link.href=`https://www.youtube.com/watch?v=${encodeURIComponent(youtube.id)}`;link.target='_blank';link.rel='noopener';dialog.append(link);
    }else if(this.url){const video=document.createElement('video');video.src=this.url;video.controls=true;video.playsInline=true;dialog.append(video);}
    else {const empty=document.createElement('p');empty.textContent=this.error||this.media?.empty_reason||'Nu există încă un film redabil în biblioteca studioului.';dialog.append(empty);}
    const before=document.activeElement;dialog.addEventListener('close',()=>{dialog.querySelectorAll('video').forEach(v=>v.pause());dialog.remove();if(this.dialog===dialog)this.dialog=null;/** @type {HTMLElement} */(before)?.focus();});
    document.body.append(dialog);dialog.showModal();close.focus();return dialog;
  }
  status(){return {asset:this.asset,ready:Boolean(this.video?.readyState>=2),playing:this.playing,error:this.error,youtube:this.media?.youtube?.length||0,artwork_ready:this.artwork.size};}
}
