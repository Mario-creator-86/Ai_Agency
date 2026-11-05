// Pixel coordinates refer to the 1536 × 1024 original village painting.
// The runtime still uses a 0..20 world, preserving the existing world API.
export const MAP_SIZE={width:1536,height:1024};
export const worldPoint=(x,y)=>({x:x/MAP_SIZE.width*20,y:y/MAP_SIZE.height*20});
export const pixelPoint=(x,y)=>({x:x/20*MAP_SIZE.width,y:y/20*MAP_SIZE.height});
export const BUILDINGS=[
 {id:'tudor',name:'Tudor',subtitle:'Biblioteca',icon:'▤',color:'#a76bea',bounds:[73,43,319,247],gate:[201,282],label:[200,50]},
 {id:'ana',name:'Ana',subtitle:'Asistență & agendă',icon:'✉',color:'#27bba9',bounds:[354,70,573,250],gate:[461,282],label:[461,59]},
 {id:'mario',name:'Mario · CEO',subtitle:'Reședința CEO',icon:'♛',color:'#e8b94b',bounds:[609,15,930,258],gate:[770,282],label:[769,24]},
 {id:'radu',name:'Radu',subtitle:'Observatorul',icon:'⌕',color:'#d79037',bounds:[948,45,1197,255],gate:[1070,282],label:[1070,34]},
 {id:'alex',name:'Alex',subtitle:'Coordonare',icon:'◷',color:'#32ae9e',bounds:[1210,68,1484,256],gate:[1340,282],label:[1340,58]},
 {id:'maria',name:'Maria',subtitle:'Leo Studio',icon:'▶',color:'#ee6267',bounds:[100,316,359,531],gate:[230,608],label:[231,305]},
 {id:'townhall',name:'Town Hall',subtitle:'Centrul de comandă',icon:'⌂',color:'#edac49',bounds:[554,265,983,507],gate:[628,524],label:[768,261]},
 {id:'david',name:'David',subtitle:'Laboratorul de automatizări',icon:'⚙',color:'#509ce1',bounds:[1177,317,1485,550],gate:[1315,608],label:[1325,306]},
 {id:'irina',name:'Irina',subtitle:'Finanțe & piețe',icon:'◈',color:'#e9b939',bounds:[73,657,366,875],gate:[221,901],label:[220,645]},
 {id:'sofia',name:'Sofia',subtitle:'Calitate & verificare',icon:'✓',color:'#a489e6',bounds:[445,684,710,875],gate:[570,901],label:[570,674]},
 {id:'elena',name:'Elena',subtitle:'Casa poveștilor',icon:'✎',color:'#dc5a97',bounds:[831,677,1117,875],gate:[964,901],label:[966,665]},
 {id:'victor',name:'Victor',subtitle:'Atelierul de film',icon:'▣',color:'#35bbd5',bounds:[1184,650,1477,875],gate:[1310,901],label:[1320,638]}
];
export const FOUNTAIN={x:768,y:575,rx:79,ry:58};
export const MEETING_POINTS=[[622,540],[618,581],[639,625],[700,667],[760,677],[822,667],[890,625],[914,580],[905,536],[850,520]].map(p=>worldPoint(...p));
export const CEO_START=worldPoint(768,718);
// The wide paths plus open central plaza avoid the painted roofs and garden walls.
const segments=[
 [100,282,1450,282,42], [80,608,1465,608,40], [150,901,1465,901,38],
 [401,282,401,901,38], [1143,282,1143,901,36], [768,282,768,930,34],
 [230,532,230,608,28],[1315,540,1315,608,28],
 [201,245,201,282,25],[461,245,461,282,25],[1070,245,1070,282,25],[1340,245,1340,282,25],
 [221,870,221,901,25],[570,870,570,901,25],[964,870,964,901,25],[1310,870,1310,901,25]
];
function distanceSegment(x,y,[ax,ay,bx,by]){const dx=bx-ax,dy=by-ay;const t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy)));return Math.hypot(x-(ax+t*dx),y-(ay+t*dy));}
export function isWalkable(x,y){
 const p=pixelPoint(x,y);if(p.x<65||p.x>1480||p.y<252||p.y>939)return false;
 if(BUILDINGS.some(b=>p.x>b.bounds[0]-5&&p.x<b.bounds[2]+5&&p.y>b.bounds[1]-3&&p.y<b.bounds[3]+5))return false;
 if(((p.x-FOUNTAIN.x)/FOUNTAIN.rx)**2+((p.y-FOUNTAIN.y)/FOUNTAIN.ry)**2<1.2)return false;
 const plaza=p.x>560&&p.x<990&&p.y>488&&p.y<691;
 return plaza||segments.some(s=>distanceSegment(p.x,p.y,s)<=s[4]);
}
const STEP=.25,gridKey=(x,y)=>x+','+y;
export function nearestWalkable(point){if(isWalkable(point.x,point.y))return point;const gx=Math.round(point.x/STEP),gy=Math.round(point.y/STEP);for(let r=1;r<=12;r++)for(let dx=-r;dx<=r;dx++)for(const dy of [-r,r]){const p={x:(gx+dx)*STEP,y:(gy+dy)*STEP};if(isWalkable(p.x,p.y))return p;}return null;}
export function findPath(from,to){
 const safe=nearestWalkable(to);if(!safe)return [];const start={x:Math.round(from.x/STEP),y:Math.round(from.y/STEP)},end={x:Math.round(safe.x/STEP),y:Math.round(safe.y/STEP)};
 const open=[{...start,g:0,f:0}],parents=new Map(),costs=new Map([[gridKey(start.x,start.y),0]]),visited=new Set();
 while(open.length&&visited.size<7000){open.sort((a,b)=>a.f-b.f);const n=open.shift(),key=gridKey(n.x,n.y);if(visited.has(key))continue;visited.add(key);
 if(n.x===end.x&&n.y===end.y){const path=[];let cursor=key;while(parents.has(cursor)){const [x,y]=cursor.split(',').map(Number);path.unshift({x:x*STEP,y:y*STEP});cursor=parents.get(cursor);}return path;}
 for(const [dx,dy]of [[1,0],[-1,0],[0,1],[0,-1]]){const x=n.x+dx,y=n.y+dy,key2=gridKey(x,y),g=n.g+1;if(!isWalkable(x*STEP,y*STEP)||g>=(costs.get(key2)??Infinity))continue;costs.set(key2,g);parents.set(key2,key);open.push({x,y,g,f:g+Math.abs(x-end.x)+Math.abs(y-end.y)});}
 }return [];
}
