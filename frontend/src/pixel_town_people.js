// Original town cast: shaped silhouettes, jointed walk/pedal frames and restrained colour ramps.
import { pixelPen, blitActor, shade } from './pixel_art.js';
import { PIXEL_LAYOUT } from './pixel_desks.js';
import { drawTownAtlas } from './pixel_actor_atlas.js';
const P = PIXEL_LAYOUT.life.palette;
const INK = '#292b3b', SOFT = '#474151';
const WALK = [
  [-4, -8, -7, 0, 3, -7, 5, -1], [-3, -8, -5, 0, 4, -8, 5, -3],
  [0, -8, -1, 0, 2, -7, 1, -5], [3, -7, 4, -1, -1, -8, -3, 0],
  [4, -8, 7, 0, -3, -7, -5, -1], [3, -8, 5, 0, -4, -8, -5, -3],
  [0, -8, 1, 0, -2, -7, -1, -5], [-3, -7, -4, -1, 1, -8, 3, 0],
];
const SKINS = ['#d6a17e', '#c78f70', '#e5b58b', '#b97f65'];
const HAIR = ['#4d3840', '#343647', '#80634e', '#564553'];
const humanBounds = { width: 48, height: 62, ox: 22, oy: 59 };

function head(pen, x, y, skin, hair, style, blink = false) {
  const { rect: r, polygon: poly, line } = pen;
  poly([[x-4,y-7],[x+2,y-8],[x+5,y-5],[x+5,y+1],[x+3,y+3],[x-2,y+2],[x-5,y-2]], INK);
  poly([[x-2,y-5],[x+3,y-5],[x+4,y-2],[x+5,y-1],[x+4,y+1],[x+2,y+2],[x-1,y+1],[x-3,y-1]], skin);
  r(x+1,y-4,2,3,shade(skin,17)); r(x-3,y-1,2,3,shade(skin,-21));
  r(x+5,y-1,1,2,skin); r(x+3,y+2,2,1,shade(skin,-29));
  poly([[x-5,y-2],[x-5,y-6],[x-3,y-8],[x+2,y-9],[x+4,y-7],[x+4,y-5],[x+1,y-4],[x-1,y-5],[x-2,y]], hair);
  line(x-3,y-6,x+1,y-7,shade(hair,28)); r(x-2,y-5,2,1,shade(hair,15));
  r(x+2,y-2,1,1,blink ? shade(skin,-28) : INK); r(x+1,y-4,3,1,shade(hair,-10));
  if (style === 1) { poly([[x-5,y-3],[x-2,y-2],[x-2,y+4],[x-4,y+5],[x-6,y+2]],hair); r(x-5,y,1,3,shade(hair,20)); }
  if (style === 2) { r(x-4,y-10,3,3,hair); r(x,y-10,2,2,hair); }
  if (style === 3) { pen.ellipse(x-5,y-6,3,3,hair); r(x-6,y-7,2,1,shade(hair,25)); }
}

export function drawPedestrian(ctx, p) {
  const coat = P.coat[p.id % P.coat.length], skin = SKINS[p.id % SKINS.length], hair = HAIR[p.id % HAIR.length];
  if(drawTownAtlas(ctx,'pedestrian',p)){
    if(p.umbrella){
      ctx.save();ctx.translate(p.x,p.y);ctx.scale(p.direction*PIXEL_LAYOUT.life.character_scale,PIXEL_LAYOUT.life.character_scale);
      const {line,polygon:poly,rect:r}=pixelPen(ctx);
      line(7,-58,7,-28,'#bcb1a3');poly([[-11,-55],[-7,-60],[1,-63],[8,-64],[16,-61],[23,-56]],INK);
      poly([[-9,-56],[-5,-60],[2,-62],[8,-62],[16,-59],[21,-56]],shade(coat,24));
      line(7,-62,7,-56,shade(coat,-30));line(7,-62,-5,-56,shade(coat,-30));line(7,-62,18,-56,shade(coat,-30));r(6,-65,1,3,'#c9bca3');
      ctx.restore();
    }
    return;
  }
  ctx.save();ctx.translate(p.x,p.y);ctx.scale(PIXEL_LAYOUT.life.character_scale,PIXEL_LAYOUT.life.character_scale);ctx.translate(-p.x,-p.y);
  blitActor(ctx, `walker:${p.id}:${p.step}:${p.umbrella}:${p.blink}`, humanBounds, p.x, p.y, p.direction, c => {
    const pen = pixelPen(c), { rect: r, line, polygon: poly, ellipse } = pen;
    const q = WALK[p.step % 8], bob = p.step % 4 === 1 ? -1 : 0;
    ellipse(0,1,10,2,'#24263b75');
    const limb = (hip,kx,ky,fx,fy,dark) => {
      line(hip,-16,kx,ky,INK,4); line(kx,ky,fx,fy-2,INK,4);
      line(hip,-15,kx,ky,dark,2); line(kx,ky,fx,fy-2,dark,2);
      line(fx-1,fy,fx+3,fy,INK,2); r(fx+1,fy-1,3,1,'#8a7b76');
    };
    limb(2,q[4],q[5],q[6],q[7], '#575567');
    limb(-2,q[0],q[1],q[2],q[3], '#6b6677');
    const arm = Math.round((q[2] - q[6]) / 4);
    line(-3,-29+bob,-6+arm,-23+bob,SOFT,4); line(-6+arm,-23+bob,-7+arm,-17+bob,shade(coat,-23),3);
    r(-8+arm,-17+bob,2,3,shade(skin,-18));
    poly([[-5,-31+bob],[1,-33+bob],[5,-29+bob],[4,-17],[-5,-16],[-7,-20]],INK);
    poly([[-4,-30+bob],[1,-31+bob],[4,-28+bob],[3,-18],[-4,-18],[-5,-22]],coat);
    line(-4,-28+bob,-4,-21,shade(coat,-28),2); line(2,-28+bob,2,-20,shade(coat,24));
    line(-3,-19,2,-19,shade(coat,-20)); r(0,-27+bob,1,6,shade(coat,-18)); r(1,-24+bob,1,1,'#d1bea0');
    if (p.id === 1) { poly([[-4,-23],[-1,-22],[3,-22],[6,-15],[-7,-15]],shade(coat,-9)); line(-6,-16,4,-16,shade(coat,-31)); }
    r(-1,-34+bob,3,3,shade(skin,-21)); r(-3,-32+bob,3,1,'#e5d9b8'); r(0,-32+bob,2,2,'#cfc4a7');
    head(pen,0,-37+bob,skin,hair,p.id%4,p.blink);
    line(3,-28+bob,5-arm,-23+bob,INK,4); line(5-arm,-23+bob,4-arm,-18+bob,INK,3);
    line(3,-28+bob,5-arm,-23+bob,shade(coat,6),3); line(5-arm,-23+bob,4-arm,-18+bob,shade(skin,-10),2);
    r(3-arm,-18+bob,2,3,skin);
    if (p.id === 2 && !p.umbrella) {
      line(4-arm,-17,7-arm,-15,'#b59670'); poly([[4-arm,-15],[10-arm,-15],[11-arm,-7],[4-arm,-7]],INK);
      r(5-arm,-14,5,6,'#9a7958'); r(6-arm,-13,3,1,'#c3a178'); r(9-arm,-13,1,5,'#765a49');
    }
    if (p.id === 3) { line(-4,-30,3,-17,'#e4ccaa'); poly([[-6,-28],[-3,-30],[-1,-24],[-4,-20],[-7,-21]],shade(coat,-30)); line(-5,-26,-4,-22,shade(coat,10)); }
    if (p.umbrella) {
      line(8,-51,8,-21,'#b3aba7'); line(8,-21,6,-20,'#b3aba7'); r(7,-25,2,3,skin);
      poly([[-8,-49],[-5,-53],[0,-56],[7,-57],[14,-55],[21,-51],[23,-48]],INK);
      poly([[-6,-50],[-3,-53],[3,-55],[8,-55],[16,-53],[21,-49]],shade(coat,20));
      line(7,-55,7,-49,shade(coat,-22)); line(7,-55,-2,-49,shade(coat,-22)); line(7,-55,17,-49,shade(coat,-22));
      r(-6,-49,7,1,coat); r(3,-49,8,1,coat); r(14,-49,7,1,coat); r(7,-59,1,3,'#d2c4a9');
    }
  });
  ctx.restore();
}

export function drawBicycle(ctx, b) {
  if(drawTownAtlas(ctx,'bicycle',b))return;
  ctx.save();ctx.translate(b.x,b.y);ctx.scale(PIXEL_LAYOUT.life.character_scale,PIXEL_LAYOUT.life.character_scale);ctx.translate(-b.x,-b.y);
  blitActor(ctx, `cycle:${b.step}`, { width: 65, height: 57, ox: 29, oy: 54 }, b.x,b.y,1,c => {
    const pen = pixelPen(c), { rect:r,line,polygon:poly,ellipse } = pen;
    const theta = b.step * Math.PI / 4, pedal = [Math.round(Math.cos(theta)*5)-2, Math.round(Math.sin(theta)*5)-10];
    const far = [-4-pedal[0],-20-pedal[1]];
    ellipse(1,1,28,2,'#24263b75');
    for (const wheel of [-17,19]) {
      ellipse(wheel,-9,9,9,INK,2); ellipse(wheel,-9,7,7,'#a9a9a7',1);
      for (let i=0;i<4;i++) { const angle=theta+i*Math.PI/2; line(wheel,-9,wheel+Math.round(Math.cos(angle)*6),-9+Math.round(Math.sin(angle)*6),'#8a8f98'); }
      r(wheel,-10,2,2,'#ddd0ad'); r(wheel-5,-17,6,1,'#d0c7b2');
    }
    line(-5,-25,-1,-20,INK,5); line(-1,-20,far[0],far[1],'#5d5364',4); line(far[0]-1,far[1],far[0]+3,far[1],INK,2);
    const tube = (a,b,color='#b48865') => {line(...a,...b,INK,3);line(...a,...b,color);};
    tube([-17,-9],[-7,-25]); tube([-7,-25],[-2,-10]); tube([-2,-10],[-17,-9]);
    tube([-7,-25],[12,-25],'#d7ab76'); tube([12,-25],[-2,-10]); tube([12,-25],[19,-9],'#d7ab76');
    line(-7,-25,-7,-29,'#b5b1a8',2); line(-12,-29,-3,-29,INK,3); line(-11,-30,-4,-30,'#88745b');
    line(12,-25,13,-32,'#c6bda8',2); line(13,-32,9,-34,INK,2); line(10,-34,15,-34,'#c8b8a0');
    ellipse(-2,-10,3,3,'#6d6466',1); line(-2,-10,pedal[0],pedal[1],'#c6bda8');
    line(-5,-25,5,-21,INK,5); line(5,-21,pedal[0],pedal[1]-1,INK,4);
    line(-5,-25,5,-21,'#6b6274',3); line(5,-21,pedal[0],pedal[1]-1,'#81748b',2);
    line(pedal[0]-1,pedal[1],pedal[0]+4,pedal[1],INK,2); r(pedal[0]+1,pedal[1]-1,3,1,'#b5a391');
    poly([[-9,-27],[-8,-34],[-2,-39],[2,-38],[4,-32],[-2,-27]],INK);
    poly([[-7,-28],[-6,-34],[-2,-37],[1,-36],[2,-32],[-2,-29]],'#749393');
    line(-6,-34,-4,-31,'#527074',2); line(-2,-36,0,-33,'#a2b2a2');
    head(pen,0,-42,'#d8aa84','#3c3744',2);
    line(2,-34,6,-31,INK,4); line(6,-31,11,-33,INK,3);
    line(2,-34,6,-31,'#a1b2a3',3); line(6,-31,11,-33,'#d8aa84',2); r(10,-34,3,2,'#e8bc92');
    poly([[18,-32],[28,-32],[26,-24],[19,-24]],'#584b50'); r(19,-31,8,6,'#aa9a7d');
    for(let x=20;x<27;x+=2)line(x,-30,x,-25,'#ddd0a5'); line(18,-32,28,-32,'#d2bc92');
    line(-24,-14,-11,-14,'#989b95'); line(14,-17,22,-17,'#989b95');
  });
  ctx.restore();
}

export function drawCat(ctx, cat) {
  if(drawTownAtlas(ctx,'cat',cat))return;
  const orange = cat.id === 1, fur = orange ? '#c18b5b' : '#c2b8a3', dark = orange ? '#875c48' : '#827b79', light = orange ? '#e0b985' : '#e7dfc4';
  blitActor(ctx, `cat:${cat.id}:${cat.pose}:${cat.step}:${cat.blink}`, {width:48,height:32,ox:23,oy:29},cat.x,cat.y,cat.direction,c=>{
    const pen=pixelPen(c),{rect:r,line,ellipse,polygon:poly}=pen;
    ellipse(0,1,14,2,'#23283b70');
    if (cat.pose==='sit'||cat.pose==='groom') {
      ellipse(-3,-7,8,8,INK); ellipse(-3,-8,6,6,fur); r(-5,-12,4,5,light);
      poly([[0,-12],[1,-18],[5,-19],[7,-14],[6,-7],[3,-3],[0,-4]],INK);
      poly([[1,-12],[2,-17],[4,-17],[5,-13],[4,-7],[2,-5]],fur);
      line(4,-12,3,-5,light,2);
      line(-8,-3,-16,-3,INK,3); line(-16,-3,-18,-6,INK,3); line(-8,-3,-16,-3,dark); line(-16,-3,-18,-6,dark);
      line(3,-10,4,-1,INK,3); line(3,-9,4,-1,light,2); r(3,-1,5,1,light);
      if(cat.pose==='groom'){
        const lick=cat.step%4<2?0:2;
        line(-1,-9,4,-13+lick,INK,3);line(-1,-9,4,-13+lick,light,2);r(4,-14+lick,3,3,light);
        if(!lick)r(5,-12,2,1,'#cd9290');
      }
    } else {
      const stretch=cat.pose==='stretch', rear=stretch?-11:-7;
      poly([[-12,-8],[-10,stretch?-15:-12],[1,-13],[8,-9],[8,-5],[-10,-4]],INK);
      ellipse(-3,stretch?-10:-8,9,4,fur); line(-10,stretch?-13:-10,-1,-11,dark,2); r(-2,-7,6,3,light);
      for(let i=0;i<4;i++){
        const start=i<2?rear:5, stride=stretch?(i<2?-2:4):[-2,-1,1,2,2,1,-1,-2][(cat.step+i*2)%8];
        line(start,-5,start+stride,-1,INK,3);line(start,-5,start+stride,-1,i%2?dark:light,2);r(start+stride,-1,3,1,light);
      }
      const tail=[-3,-1,1,-1][Math.floor(cat.step/2)];
      line(-12,-9,-18,-12+tail,INK,3);line(-18,-12+tail,-20,-17+tail,INK,3);
      line(-12,-9,-18,-12+tail,fur);line(-18,-12+tail,-20,-17+tail,light);
    }
    const hx=cat.pose==='groom'?2:cat.pose==='sit'?4:7,hy=cat.pose==='sit'||cat.pose==='groom'?-18:cat.pose==='stretch'?-8:-14;
    poly([[hx-5,hy+2],[hx-5,hy-4],[hx-3,hy-7],[hx,hy-4],[hx+4,hy-7],[hx+6,hy-3],[hx+6,hy+2],[hx+3,hy+5],[hx-2,hy+5]],INK);
    poly([[hx-4,hy+1],[hx-4,hy-3],[hx-3,hy-5],[hx,hy-2],[hx+3,hy-4],[hx+5,hy-2],[hx+5,hy+2],[hx+2,hy+4],[hx-2,hy+3]],fur);
    r(hx-3,hy-4,1,2,'#c38d89');r(hx+3,hy-4,1,2,'#c38d89'); r(hx-2,hy+2,6,2,light);
    r(hx-2,hy,2,1,cat.blink?dark:'#dac67d');r(hx+3,hy,2,1,cat.blink?dark:'#dac67d');
    if(!cat.blink){r(hx-1,hy,1,1,INK);r(hx+3,hy,1,1,INK);}
    r(hx+1,hy+2,1,1,'#a77673');r(hx+1,hy+3,1,1,dark); line(hx-4,hy+2,hx-7,hy+1,light);line(hx+4,hy+2,hx+8,hy+1,light);
    r(hx-1,hy-2,1,2,dark);r(hx+2,hy-2,1,1,dark);r(-6,-9,1,3,dark);r(-2,-10,1,2,dark);
  });
}

export function drawDog(ctx, dog) {
  if(drawTownAtlas(ctx,'dog',dog))return;
  blitActor(ctx,`dog:${dog.step}`,{width:42,height:27,ox:22,oy:24},dog.x,dog.y,dog.direction,c=>{
    const {rect:r,line,ellipse,polygon:poly}=pixelPen(c);
    ellipse(0,1,15,2,'#23283b60'); ellipse(-2,-9,11,5,INK);ellipse(-2,-10,9,3,'#b98d68');r(-7,-10,8,3,'#ddba88');
    for(let i=0;i<4;i++){const x=i<2?-9:5,q=WALK[(dog.step+i*2)%8][2]/3;line(x,-7,x+q,-1,INK,3);line(x,-7,x+q,-1,i%2?'#98704f':'#d6b586',2);r(x+q,-1,3,1,'#e1c293');}
    const wag=dog.step%4<2?-2:1;line(-12,-10,-18,-15+wag,INK,3);line(-12,-10,-18,-15+wag,'#d6b586',2);
    poly([[4,-8],[3,-15],[5,-19],[10,-18],[13,-14],[17,-13],[17,-9],[13,-6],[7,-6]],INK);
    poly([[5,-9],[5,-15],[7,-17],[10,-16],[12,-12],[16,-12],[16,-10],[12,-8]],'#c79b73');
    ellipse(5,-14,3,5,'#77574b');r(6,-17,2,3,'#93705a');r(11,-14,1,1,INK);r(16,-12,2,2,INK);r(12,-9,3,1,'#e7cba0');
    line(4,-7,10,-7,'#a25356',2);r(8,-6,1,2,'#d4bd83');
  });
}
