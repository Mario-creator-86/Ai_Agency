// Authored 48 × 60 frames, drawn into the existing seat footprint. Bible colours remain identity.
import { pixelPen, shade } from './pixel_art.js';
const INK = '#2c2a38';

function rearHair(pen,p,m,hx,hy) {
  const {rect:r,line,polygon:poly,ellipse}=pen;
  const hair=p.hair, dark=shade(hair,-20), mid=shade(hair,13), light=shade(hair,30);
  const shift=pts=>pts.map(([x,y])=>[x+hx,y+hy]);
  poly(shift([[18,5],[22,3],[28,3],[32,6],[34,11],[32,18],[29,21],[20,21],[17,17],[16,10]]),INK);
  poly(shift([[19,6],[23,4],[28,5],[31,7],[32,12],[30,19],[26,20],[20,18],[18,14],[18,9]]),hair);
  poly(shift([[20,6],[25,5],[29,7],[28,9],[24,8],[20,10],[18,13],[18,10]]),mid);
  line(21+hx,6+hy,26+hx,6+hy,light); line(19+hx,9+hy,21+hx,8+hy,light);
  line(29+hx,11+hy,28+hx,17+hy,dark,2);line(25+hx,13+hy,24+hx,19+hy,dark);
  line(19+hx,15+hy,22+hx,18+hy,mid);r(30+hx,9+hy,1,4,mid);r(22+hx,10+hy,1,2,mid);
  if(p.hairStyle==='short'){line(19+hx,17+hy,29+hx,18+hy,dark,2);r(23+hx,18+hy,3,1,mid);}
  if(p.hairStyle==='bob'){
    poly(shift([[17,11],[20,14],[30,14],[33,12],[33,22],[30,24],[18,23],[16,20]]),hair);
    line(18+hx,15+hy,18+hx,21+hy,mid);line(21+hx,17+hy,22+hx,22+hy,light);
    line(29+hx,16+hy,30+hx,21+hy,dark,2);line(19+hx,23+hy,29+hx,23+hy,dark);
  }
  if(p.hairStyle==='long'){
    poly(shift([[18,13],[31,13],[33,20],[32,28],[28,35],[20,35],[17,30],[16,21]]),dark);
    poly(shift([[19,14],[29,14],[31,21],[29,29],[26,33],[20,32],[18,26]]),hair);
    line(20+hx,16+hy,19+hx,25+hy,mid);line(19+hx,25+hy,22+hx,31+hy,mid);
    line(23+hx,17+hy,23+hx,29+hy,light);line(28+hx,18+hy,27+hx,30+hy,dark,2);
    r(24+hx,31+hy,2,2,mid);
  }
  if(p.hairStyle==='wavy'){
    poly(shift([[16,9],[16,5],[19,2],[21,5],[24,2],[27,4],[30,3],[33,6],[33,10]]),hair);
    line(18+hx,5+hy,20+hx,4+hy,light);line(25+hx,4+hy,28+hx,5+hy,mid);
    r(16+hx,14+hy,2,3,hair);r(31+hx,17+hy,2,3,hair);
  }
  if(p.hairStyle==='bun'){
    ellipse(23+hx,5+hy,6,5,dark);ellipse(23+hx,4+hy,5,4,hair);
    line(20+hx,3+hy,24+hx,2+hy,light);line(20+hx,6+hy,25+hx,7+hy,mid);
    r(28+hx,5+hy,2,3,p.accent);
  }
  if(p.silver){line(18+hx,12+hy,20+hx,17+hy,'#aeb2b5',2);line(31+hx,12+hy,29+hx,16+hy,'#919ca5');}
  if(p.streak){line(29+hx,7+hy,28+hx,16+hy,p.accent,2);if(p.hairStyle==='long')line(28+hx,16+hy,27+hx,29+hy,p.accent);}
}

function rearHead(pen,p,m) {
  const {rect:r,line,polygon:poly,ellipse}=pen;
  const hx=m.glance*2, hy=m.breath;
  r(21+hx,18+hy,8,7,shade(p.skin,-28));r(23+hx,20+hy,4,4,shade(p.skin,-10));
  ellipse(16+hx,14+hy,2,3,shade(p.skin,-22));ellipse(33+hx,14+hy,2,3,p.skin);
  r(16+hx,13+hy,1,3,shade(p.skin,9));r(33+hx,14+hy,1,2,shade(p.skin,-29));
  rearHair(pen,p,m,hx,hy);
  if(m.glance){
    const right=m.glance>0, x=right?29:15;
    poly([[x,9+hy],[x+4,10+hy],[x+5,13+hy],[x+6,14+hy],[x+4,15+hy],[x+4,18+hy],[x+1,20+hy],[x-1,17+hy]],shade(p.skin,-15));
    r(x+1,12+hy,3,4,p.skin);r(x+4,14+hy,2,1,shade(p.skin,15));r(x+2,12+hy,1,1,m.blink?shade(p.skin,-30):INK);
    line(x,10+hy,x+3,11+hy,shade(p.hair,-15));r(x+2,18+hy,2,1,shade(p.skin,-43));
    if(p.glasses){line(x-1,12+hy,x+4,12+hy,p.accent);r(x,13+hy,1,2,p.accent);r(x+4,13+hy,1,2,p.accent);line(x,15+hy,x+4,15+hy,shade(p.accent,-15));}
    if(p.beard)line(x,18+hy,x+3,19+hy,shade(p.hair,10));
  } else if(p.glasses){line(14,12+hy,17,12+hy,p.accent);line(32,12+hy,35,13+hy,p.accent);}
  if(p.headset){
    line(17+hx,8+hy,20+hx,5+hy,INK,3);line(20+hx,5+hy,29+hx,5+hy,INK,3);line(29+hx,5+hy,33+hx,9+hy,INK,3);
    line(18+hx,7+hy,21+hx,5+hy,p.accent);line(21+hx,5+hy,28+hx,5+hy,p.accent);
    r(13+hx,11+hy,5,9,INK);r(14+hx,12+hy,3,6,shade(p.accent,-15));r(14+hx,12+hy,1,4,shade(p.accent,28));
    r(32+hx,11+hy,5,9,INK);r(33+hx,12+hy,3,6,p.accent);line(35+hx,18+hy,37+hx,19+hy,INK);
  }
}

function sleeve(pen,p,shoulder,elbow,wrist,near=true) {
  const {line,ellipse}=pen;
  line(...shoulder,...elbow,INK,6);line(...elbow,...wrist,INK,4);
  line(...shoulder,...elbow,shade(p.coat,near?3:-25),4);
  line(...elbow,...wrist,shade(p.coat,near?17:-13),3);
  line(elbow[0]-1,elbow[1],elbow[0]+1,elbow[1]-1,shade(p.coat,-29));
  ellipse(wrist[0],wrist[1]-1,2,2,p.skin);line(wrist[0]-1,wrist[1]+1,wrist[0]+1,wrist[1]+1,shade(p.skin,-24));
}

export function paintSeated(ctx,p,m,portrait=false,back=true) {
  const pen=pixelPen(ctx),{rect:r,line,polygon:poly,ellipse}=pen;
  const lean=m.sway||0, bob=Math.floor(m.breath/2), coatDark=shade(p.coat,-34);
  if(!portrait){
    poly([[15,39],[34,39],[34,46],[32,56],[27,56],[25,46],[22,46],[20,56],[14,56],[13,46]],INK);
    poly([[15,41],[23,42],[22,47],[18,54],[15,54]],'#555765');poly([[27,42],[32,41],[31,54],[28,54]],'#696876');
    line(16,45,16,51,'#7c7d85');line(28,47,29,52,'#8a8790');
    poly([[14,54],[19,54],[20,58],[18,59],[11,59],[11,57]],INK);poly([[28,54],[32,54],[35,57],[36,59],[27,59]],INK);
    r(13,56,5,1,'#83776f');r(29,56,4,1,'#83776f');
  }
  poly([[14+lean,24+bob],[20+lean,22+bob],[28+lean,22+bob],[35+lean,25+bob],[38+lean,32],[34+lean,41],[16+lean,42],[11+lean,34]],INK);
  poly([[15+lean,26+bob],[21+lean,24+bob],[28+lean,24+bob],[33+lean,26+bob],[35+lean,32],[32+lean,40],[17+lean,40],[14+lean,33]],p.coat);
  poly([[15+lean,27],[19+lean,29],[18+lean,37],[21+lean,40],[17+lean,40],[14+lean,33]],coatDark);
  poly([[29+lean,25],[33+lean,28],[34+lean,32],[31+lean,36],[30+lean,29]],shade(p.coat,21));
  line(18+lean,39,30+lean,39,shade(p.coat,-22));line(24+lean,28,24+lean,38,shade(p.coat,-16));
  line(16+lean,31,20+lean,33,shade(p.coat,-21));line(28+lean,34,32+lean,33,shade(p.coat,-24));
  r(18+lean,37,3,1,shade(p.coat,10));r(29+lean,38,3,1,shade(p.coat,12));
  poly([[19+lean,24],[23+lean,23],[25+lean,25],[28+lean,23],[31+lean,24],[28+lean,27],[21+lean,27]],shade(p.shirt,-10));
  if(/editor|writer/.test(p.role)){poly([[18+lean,25],[20+lean,27],[25+lean,29],[30+lean,27],[32+lean,25],[30+lean,31],[23+lean,32],[18+lean,29]],shade(p.coat,-17));line(21+lean,29,27+lean,30,shade(p.coat,19));}
  if(/accountant|director/.test(p.role)){line(18+lean,27,21+lean,29,shade(p.coat,24));line(28+lean,29,31+lean,27,shade(p.coat,-25));r(31+lean,33,2,1,p.accent);}
  if(m.gesture==='stretch'){
    const q=m.gestureFrame%4<2?0:1;
    sleeve(pen,p,[13,28],[7,14+q],[16,5+q],false);sleeve(pen,p,[35,28],[41,14+q],[32,5+q]);
  } else if(m.gesture==='sip'){
    sleeve(pen,p,[13,28],[8,37],[14,41],false);sleeve(pen,p,[35,28],[43,24],[35,16+m.breath]);
  } else if(['chin','headset'].includes(m.gesture)){
    sleeve(pen,p,[13,28],[8,35],[12,39],false);sleeve(pen,p,[35,28],[42,30],[35,18+m.breath]);
  } else if(['type','mouse','read','write'].includes(m.gesture)){
    const tap=m.animate?m.gestureFrame%2:0;
    sleeve(pen,p,[13,28],[7,29],[9,24-tap],false);sleeve(pen,p,[35,28],[41,29],[40,24+tap]);
  } else {sleeve(pen,p,[13,28],[9,38],[14,44],false);sleeve(pen,p,[35,28],[39,38],[33,44]);}
  if(back&&!portrait)rearHead(pen,p,m);else{
    rearHead(pen,p,{...m,glance:1});
    const y=m.breath;
    poly([[21,8+y],[28,8+y],[31,11+y],[33,15+y],[31,17+y],[29,21+y],[23,21+y],[20,17+y],[19,12+y]],p.skin);
    poly([[20,13+y],[22,15+y],[22,19+y],[26,21+y],[23,21+y],[20,18+y]],shade(p.skin,-23));
    r(25,10+y,4,4,shade(p.skin,18));line(23,11+y,25,11+y,p.hair);line(29,12+y,31,12+y,p.hair);
    r(24,13+y,1,1,m.blink?p.skin:INK);r(30,14+y,1,1,m.blink?p.skin:INK);r(29,16+y,3,1,shade(p.skin,-17));line(26,19+y,29,19+y,shade(p.skin,-43));
    poly([[18,8+y],[20,5+y],[28,5+y],[32,8+y],[30,11+y],[27,8+y],[23,9+y],[21,12+y],[18,13+y]],p.hair);
    line(20,7+y,26,6+y,shade(p.hair,28));
    if(p.glasses){r(22,12+y,5,1,p.accent);r(22,15+y,5,1,p.accent);r(22,13+y,1,2,p.accent);r(26,13+y,1,2,p.accent);line(27,13+y,32,13+y,p.accent);r(31,14+y,1,2,p.accent);}
    if(p.beard)line(24,21+y,29,21+y,shade(p.hair,10));
    if(p.headset){r(17,12+y,4,8,INK);r(18,13+y,2,5,p.accent);line(20,18+y,26,20+y,INK);}
  }
  if(m.gesture==='sip'){
    r(34,13+m.breath,6,7,INK);r(35,14+m.breath,4,5,'#e8d8b7');r(35,13+m.breath,4,1,'#624b48');
    line(40,15+m.breath,41,16+m.breath,'#c8b28b');line(41,16+m.breath,40,18+m.breath,'#c8b28b');r(34,17+m.breath,2,2,p.skin);
  }
}

export function paintDeskHands(ctx,p,m) {
  if(!['type','mouse','read','write','headset','chin'].includes(m.gesture))return;
  const {rect:r,line,polygon:poly,ellipse}=pixelPen(ctx), tap=m.animate?m.gestureFrame%2:0;
  const hand=(x,y)=>{ellipse(x,y,3,2,p.skin);line(x-2,y+1,x+2,y+1,shade(p.skin,-23));r(x-1,y-1,1,1,shade(p.skin,19));};
  if(m.gesture==='type'){
    hand(9,24-tap);hand(40,24+tap);line(7,26-tap,11,26-tap,shade(p.skin,-10));line(38,26+tap,42,26+tap,shade(p.skin,-10));
  }else if(m.gesture==='mouse'){
    ellipse(41+tap,29,3,3,'#424953');ellipse(41+tap,28,2,2,'#b8c1b7');line(41+tap,27,41+tap,29,'#747e7d');hand(40+tap,25);
  }else if(['read','write'].includes(m.gesture)){
    const y=m.gesture==='read'?16+m.breath:27;
    poly([[36,y],[45,y-1],[46,y+10],[37,y+11]],'#62564d');poly([[37,y+1],[44,y],[45,y+9],[38,y+10]],'#ded3b0');
    line(39,y+3,43,y+3,'#9d927a');line(39,y+5,42,y+5,'#9d927a');line(39,y+7,43,y+7,'#9d927a');hand(36,y+7);
    if(m.gesture==='write'){hand(43+tap,y+3);line(43+tap,y+1,41+tap,y+6,'#b38759');r(41+tap,y+6,1,1,INK);}
  }else{hand(35,18+m.breath);if(m.gesture==='headset'){r(33,12+m.breath,3,6,shade(p.accent,-10));r(34,13+m.breath,1,3,p.accent);}}
}
