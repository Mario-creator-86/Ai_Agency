import { pixelPen, shade } from './pixel_art.js';
import { drawTownAtlas } from './pixel_actor_atlas.js';
import { PIXEL_LAYOUT } from './pixel_desks.js';

/** Detailed local art first; a shaped vehicle remains available if its PNG cannot load. */
export function drawCar(ctx, vehicle, wet) {
  if (drawTownAtlas(ctx, 'car', { ...vehicle, wet })) return;
  ctx.save(); ctx.translate(vehicle.x, vehicle.y); ctx.scale(vehicle.direction, 1);
  const { polygon: poly, line, ellipse, rect: r } = pixelPen(ctx);
  const body = PIXEL_LAYOUT.life.vehicle_colours[vehicle.variant % 4], ink = '#292b3b';
  ellipse(0, 1, 39, 2, '#22263755');
  poly([[-44,-8],[-42,-19],[-29,-22],[-18,-33],[12,-33],[27,-22],[42,-18],[45,-8]], ink);
  poly([[-42,-9],[-40,-18],[-28,-20],[-16,-31],[11,-31],[26,-20],[40,-17],[43,-9]], body);
  poly([[-24,-21],[-15,-29],[-4,-29],[-4,-21]], '#96abb1');
  poly([[-1,-29],[10,-29],[22,-21],[-1,-21]], '#7b939e');
  line(-17,-28,-7,-28,'#d3cdb3'); line(1,-28,8,-28,'#c6c0ad');
  line(-3,-30,-3,-10,shade(body,-30)); line(23,-20,23,-10,shade(body,-30));
  line(-39,-17,39,-17,shade(body,27)); line(-38,-10,40,-10,shade(body,-23));
  r(-1,-19,4,1,'#c5b89f'); r(20,-23,4,3,ink); r(21,-22,2,1,shade(body,29));
  for (const x of [-28,29]) {
    ellipse(x,-5,7,7,ink); ellipse(x,-5,5,5,'#474754'); ellipse(x,-5,3,3,'#a9aaa4');
    const speed=(PIXEL_LAYOUT.world.width+2*PIXEL_LAYOUT.life.street_margin)/PIXEL_LAYOUT.life.car_cycle_ms;
    const angle=vehicle.elapsed*speed/7;
    for(let spoke=0;spoke<3;spoke++){
      const a=angle+spoke*Math.PI*2/3;
      line(x,-5,x+Math.cos(a)*3,-5+Math.sin(a)*3,'#d7d2bb');
    }
    r(x,-5,1,1,ink);
  }
  r(-42,-16,2,4,'#b56349'); r(41,-16,3,3,vehicle.lights?'#ffe7b5':'#c6c8b9');
  r(-44,-8,4,2,'#9d9a8c'); r(40,-8,5,2,'#a4a292');
  if(wet)r(-37,4,76,1,'#b9af8635');
  if(vehicle.lights)poly([[44,-14],[83,-19],[83,-2]],'#ffe5ac24');
  ctx.restore();
}
