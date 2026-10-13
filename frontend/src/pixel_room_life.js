import { PRESENTATION as S } from './pixel_presentation.js';
const plants=new WeakMap();

function foliage(background) {
  if (plants.has(background)) return plants.get(background);
  const surfaces=S.plants.map(p=>{
    const c=document.createElement('canvas');c.width=p.w*2;c.height=p.h*2;
    const x=c.getContext('2d');x.drawImage(background,p.x*background.width/960,p.y*background.height/640,
      p.w*background.width/960,p.h*background.height/640,0,0,c.width,c.height);
    const pixels=x.getImageData(0,0,c.width,c.height);
    for(let i=0;i<pixels.data.length;i+=4){const [r,g,b]=pixels.data.slice(i,i+3);
      if (!(g>r*1.04 && g>b*1.05 && g>25)) pixels.data[i+3]=0;
    }
    x.putImageData(pixels,0,0);return {p,c};
  });
  plants.set(background,surfaces);return surfaces;
}

/** Bounded light loose-body simulation with gravity, drag and floor/furniture contacts. */
export class RoomPhysics {
  constructor() { this.papers=new Map();this.last=0; }
  frame(elapsed,weather,positions) {
    const wind=weather.available && Number.isFinite(weather.windKph) ? Math.max(0,weather.windKph) : 0;
    const dt=Math.min(S.max_catchup_ms,Math.max(0,elapsed-this.last))/1000;this.last=elapsed;
    const visible=new Set(positions.map(p=>p.id));
    for(const key of this.papers.keys())if(!visible.has(key))this.papers.delete(key);
    for(const [index,p] of positions.entries()){
      const seat=p.seating;if(!seat?.contacts)continue;
      let body=this.papers.get(p.id);
      if(!body){body={x:p.x+10,y:seat.desktop_y-2,vx:0,vy:0,angle:0,angular:0,cycle:-1,settled:true,surface:'desk',collisions:0};this.papers.set(p.id,body);}
      const phase=(elapsed+index*17391)%S.physics.paper_cycle_ms,cycle=Math.floor((elapsed+index*17391)/S.physics.paper_cycle_ms);
      if(wind>=S.physics.paper_air_threshold_kph && phase<S.physics.paper_launch_ms && cycle!==body.cycle){
        body.x=p.x+12;body.y=seat.desktop_y-2;body.vx=10+wind*.25;body.vy=-16;
        body.angular=2.2;body.settled=false;body.surface='air';body.cycle=cycle;
      }
      if(body.settled || dt===0)continue;
      let remaining=dt;
      while(remaining>.0001){const step=Math.min(S.fixed_step_ms/1000,remaining);remaining-=step;
        body.vx+=(wind*.06-body.vx*S.physics.paper_drag)*step;body.vy+=S.physics.gravity*step;
        const before=body.y;body.x+=body.vx*step;body.y+=body.vy*step;
        body.angle+=body.angular*step;body.angular*=Math.exp(-.7*step);
        const floor=seat.floor_y-1;
        for(const solid of seat.solids || [])if(body.x>solid.x-2&&body.x<solid.x+solid.w+2&&before<=solid.y&&body.y>=solid.y){
          body.y=solid.y;body.vy=-body.vy*S.physics.bounce;body.vx*=.6;body.collisions++;body.surface='furniture';
        }
        body.x=Math.max(seat.floor_plane.min_x+2,Math.min(seat.floor_plane.max_x-2,body.x));
        if(body.y>=floor){body.y=floor;body.vy=-body.vy*S.physics.bounce;body.vx*=.65;body.collisions++;body.surface='floor';
          if(Math.abs(body.vy)<2){body.settled=true;body.vx=body.vy=body.angular=0;body.angle=0;}}
      }
    }
    return {wind,papers:[...this.papers].map(([id,p])=>({id,...p}))};
  }
}

export function drawRoomLife(ctx,background,elapsed,weather,physics) {
  if(!background.complete || !background.naturalWidth)return;
  const wind=weather.available && Number.isFinite(weather.windKph) ? Math.min(1,weather.windKph/40) : 0;
  for(const [i,{p,c}] of foliage(background).entries()){
    const sway=(.003+wind*.016)*Math.sin(elapsed/(1600+i*133)+i*1.4);
    ctx.save();ctx.translate(...p.pivot);ctx.rotate(sway);ctx.translate(-p.pivot[0],-p.pivot[1]);
    ctx.imageSmoothingEnabled=false;ctx.drawImage(c,p.x,p.y,p.w,p.h);ctx.restore();
  }
  for(const [i,lamp] of S.lights.entries()){
    const phase=(elapsed+i*31017)%lamp.period_ms;
    // One soft, rare dip, never a strobe or a permanent flashing loop.
    if(phase<750){const dim=Math.sin(phase/750*Math.PI)*.10;
      const g=ctx.createRadialGradient(lamp.x,lamp.y,1,lamp.x,lamp.y+18,39);
      g.addColorStop(0,`rgba(70,38,20,${dim})`);g.addColorStop(1,'rgba(70,38,20,0)');
      ctx.fillStyle=g;ctx.fillRect(lamp.x-40,lamp.y-20,80,70);}
  }
  for(const paper of physics.papers){
    ctx.save();ctx.translate(paper.x,paper.y);ctx.rotate(paper.angle);
    ctx.fillStyle='#392c2440';ctx.fillRect(-2,1,6,1);ctx.fillStyle='#d8c498';ctx.fillRect(-3,-2,6,3);
    ctx.fillStyle='#786b50';ctx.fillRect(-2,-1,3,.5);ctx.restore();
  }
}
