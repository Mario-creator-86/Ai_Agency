// Pixel coordinates refer to the 1536 × 1024 original village painting.
// The runtime still uses a 0..20 world, preserving the existing world API.
export const MAP_SIZE={width:1536,height:1024};
export const worldPoint=(x,y)=>({x:x/MAP_SIZE.width*20,y:y/MAP_SIZE.height*20});
export const pixelPoint=(x,y)=>({x:x/20*MAP_SIZE.width,y:y/20*MAP_SIZE.height});

// owner = who lives/works there. door = painted front door, yard = walkable strip
// between the door and the garden gate, gate = point on the public road.
export const BUILDINGS=[
 {id:'tudor',owner:'tudor',name:'Tudor',subtitle:'Family · casa familiei',icon:'♥',color:'#a76bea',bounds:[73,43,319,247],door:[201,214],yard:[181,214,222,262],gate:[201,282],label:[200,50]},
 {id:'ana',owner:'ana',name:'Ana',subtitle:'Inbox & email',icon:'✉',color:'#27bba9',bounds:[354,70,573,250],door:[464,214],yard:[444,214,486,262],gate:[461,282],label:[461,59]},
 {id:'mario',owner:'mario',name:'Mario · CEO',subtitle:'Reședința CEO',icon:'♛',color:'#e8b94b',bounds:[609,15,930,258],door:[770,198],yard:[742,198,798,262],gate:[770,282],label:[769,24]},
 {id:'radu',owner:'radu',name:'Radu',subtitle:'Research · observatorul',icon:'⌕',color:'#d79037',bounds:[948,45,1197,255],door:[1080,214],yard:[1058,214,1100,262],gate:[1070,282],label:[1070,34]},
 {id:'victor',owner:'victor',name:'Victor',subtitle:'Trading · casa ceasului',icon:'↗',color:'#32ae9e',bounds:[1210,68,1484,256],door:[1347,214],yard:[1326,214,1368,262],gate:[1340,282],label:[1340,58]},
 {id:'maria',owner:'maria',name:'Maria',subtitle:'YouTube · Leo Studio',icon:'▶',color:'#ee6267',bounds:[100,316,359,531],door:[232,505],yard:[208,505,256,566],gate:[230,608],label:[231,305]},
 {id:'townhall',owner:'alex',name:'Town Hall',subtitle:'Alex · Chief of Staff',icon:'⌂',color:'#edac49',bounds:[554,298,983,507],door:[770,446],yard:[712,446,828,515],gate:[770,520],label:[768,261]},
 {id:'david',owner:'david',name:'David',subtitle:'Products · atelierul',icon:'⚙',color:'#509ce1',bounds:[1177,317,1485,550],door:[1296,512],yard:[1280,512,1340,566],gate:[1315,608],label:[1325,306]},
 {id:'irina',owner:'irina',name:'Irina',subtitle:'Money · banca',icon:'◈',color:'#e9b939',bounds:[73,657,366,875],door:[204,806],yard:[184,806,226,882],gate:[221,901],label:[220,645]},
 {id:'sofia',owner:'sofia',name:'Sofia',subtitle:'AI News · casa știrilor',icon:'✦',color:'#a489e6',bounds:[445,684,710,875],door:[572,816],yard:[551,816,594,882],gate:[570,901],label:[570,674]},
 {id:'elena',owner:'elena',name:'Elena',subtitle:'Outreach · casa scrisorilor',icon:'✎',color:'#dc5a97',bounds:[831,677,1117,875],door:[968,816],yard:[946,816,990,882],gate:[964,901],label:[966,665]},
 {id:'studio',owner:null,name:'Studio',subtitle:'Anexa de producție YouTube',icon:'▣',color:'#35bbd5',bounds:[1184,650,1477,875],door:[1306,816],yard:[1290,816,1334,882],gate:[1310,901],label:[1320,638]}
];
export const homeOf=id=>BUILDINGS.find(b=>b.owner===id)||null;
export const FOUNTAIN={x:768,y:575,rx:79,ry:58};
// Points in front of the Town Hall where the CEO and chief of staff wait after a meeting.
export const HALL_FRONT={mario:[702,516],alex:[836,516]};
export const MEETING_POINTS=[[622,540],[618,581],[639,625],[700,667],[760,677],[822,667],[890,625],[914,580],[905,536],[850,520]].map(p=>worldPoint(...p));
export const CEO_START=worldPoint(768,718);
// Where newcomers enter the village (road by the bridge).
export const VILLAGE_ENTRY=[90,901];

// Furniture that nobody may stand on: painted benches and planters around the plaza,
// plus placed props. Rectangles in map pixels.
export const OBSTACLES=[
 [545,532,612,576],[932,532,1000,576],[553,606,627,652],[917,606,990,652],
 [650,515,672,542],[868,515,890,542],[650,606,674,640],[866,606,890,640]
];
// Extra props cut from the ChatGPT atlas, placed on grass (never on paths).
// x,y = feet/base point in map pixels; w = drawn width in map pixels.
export const PROPS=[
 {sprite:'well',x:1092,y:468,w:50},
 {sprite:'noticeboard',x:505,y:548,w:46},
 {sprite:'planter',x:676,y:960,w:38},{sprite:'planter',x:856,y:960,w:38},
 {sprite:'pine',x:30,y:600,w:58},{sprite:'oak',x:1505,y:610,w:80},
 {sprite:'flowerbed',x:1236,y:985,w:70},{sprite:'lamp',x:718,y:972,w:20},{sprite:'lamp',x:818,y:972,w:20}
];
// Small props drawn in code (barrels, crates, the retro pop vending machine).
export const CODE_PROPS=[
 {kind:'vending',x:1028,y:560},
 {kind:'barrel',x:1150,y:970},{kind:'barrel',x:1170,y:978},{kind:'crate',x:1128,y:976},
 {kind:'crate',x:340,y:968},{kind:'barrel',x:362,y:975},
 {kind:'crate',x:1420,y:560},{kind:'barrel',x:150,y:556}
];

// Animated overlays, placed on the painted details they belong to.
export const EFFECTS={
 chimneys:[[160,58],[405,60],[1293,66],[150,328],[195,322],[1253,318],[165,640],[510,686],[1281,646]],
 lamps:[[170,183],[232,183],[497,170],[703,178],[836,178],[1318,180],[1381,180],[447,493],[1093,493],[455,600],[1083,600],[540,183],[1288,800],[1388,800],[1027,793],[938,793]],
 banners:[[675,372,24,58],[845,372,24,58]],
 screens:[[166,428,46,70],[214,428,46,70],[262,428,52,70],[1238,438,30,24]],
 water:[{kind:'fountain',x:768,y:563,rx:62,ry:30},{kind:'stream',points:[[10,770],[22,830],[40,880],[60,930],[110,960],[160,1000],[200,1024]]}],
 windows:[[132,120],[264,120],[128,170],[268,170],[432,120],[497,120],[692,95],[768,90],[846,95],[700,150],[840,150],[1034,170],[1262,120],[1416,120],[1265,180],[1408,180],[150,450],[300,450],[618,404],[922,404],[1220,420],[1300,435],[132,780],[272,780],[625,780],[655,780],[880,780],[1040,780],[1260,770],[1335,770]],
 cherry:[[255,25],[960,25],[1500,420]]
};

// Town Hall interior: one big table, 12 chairs. Mario at the head (top).
// Coordinates are in the same 1536 × 1024 space as the map so the camera is shared.
export const HALL={
 table:[662,300,874,872],door:[768,1000],aisles:{left:500,right:1036},
 seats:[
  {id:0,x:768,y:262,facing:'front',role:'head'},
  ...[0,1,2,3,4].map(i=>({id:1+i,x:651,y:372+i*108,facing:'right',side:'left'})),
  ...[0,1,2,3,4].map(i=>({id:6+i,x:885,y:372+i*108,facing:'left',side:'right'})),
  {id:11,x:768,y:945,facing:'back',role:'foot'}
 ],
 // Mario heads the table; Alex at his right hand; the foot chair is for interview candidates.
 assignment:{mario:0,alex:6,maria:1,ana:7,radu:2,victor:8,irina:3,david:9,sofia:4,elena:10,tudor:5}
};

// The wide paths plus open central plaza avoid the painted roofs and garden walls.
const segments=[
 [100,282,1450,282,42], [80,608,1465,608,40], [70,901,1465,901,38],
 [401,282,401,901,38], [1143,282,1143,901,36], [768,282,768,930,34],
 [230,532,230,608,28],[1315,540,1315,608,28],
 [201,245,201,282,25],[461,245,461,282,25],[1070,245,1070,282,25],[1340,245,1340,282,25],
 [221,870,221,901,25],[570,870,570,901,25],[964,870,964,901,25],[1310,870,1310,901,25]
];
function distanceSegment(x,y,[ax,ay,bx,by]){const dx=bx-ax,dy=by-ay;const t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy)));return Math.hypot(x-(ax+t*dx),y-(ay+t*dy));}
const inRect=(x,y,r,pad=0)=>x>=r[0]-pad&&x<=r[2]+pad&&y>=r[1]-pad&&y<=r[3]+pad;
export function isWalkable(x,y){
 const p=pixelPoint(x,y);if(p.x<40||p.x>1480||p.y<198||p.y>939)return false;
 if(OBSTACLES.some(r=>inRect(p.x,p.y,r,2)))return false;
 if(BUILDINGS.some(b=>p.x>=b.yard[0]-10&&p.x<=b.yard[2]+10&&p.y>=b.yard[1]&&p.y<=b.yard[3]+8))return true;
 if(BUILDINGS.some(b=>p.x>b.bounds[0]-5&&p.x<b.bounds[2]+5&&p.y>b.bounds[1]-3&&p.y<b.bounds[3]+5))return false;
 if(((p.x-FOUNTAIN.x)/FOUNTAIN.rx)**2+((p.y-FOUNTAIN.y)/FOUNTAIN.ry)**2<1.06)return false;
 const plaza=p.x>560&&p.x<990&&p.y>488&&p.y<691;
 return plaza||segments.some(s=>distanceSegment(p.x,p.y,s)<=s[4]);
}
const STEP=.25,gridKey=(x,y)=>x+','+y;
export function nearestWalkable(point){if(isWalkable(point.x,point.y))return point;const gx=Math.round(point.x/STEP),gy=Math.round(point.y/STEP);for(let r=1;r<=12;r++)for(let dx=-r;dx<=r;dx++)for(const dy of [-r,r]){const p={x:(gx+dx)*STEP,y:(gy+dy)*STEP};if(isWalkable(p.x,p.y))return p;}return null;}
function clearLine(a,b){const d=Math.hypot(b.x-a.x,b.y-a.y),n=Math.ceil(d/.025);for(let i=1;i<n;i++){const t=i/n;if(!isWalkable(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t))return false;}return true;}
// String-pulling turns the grid staircase into natural straight walks along the paths.
export function smoothPath(from,path){if(path.length<3)return path;const out=[];let anchor=from,i=0;while(i<path.length){let j=path.length-1;while(j>i&&!clearLine(anchor,path[j]))j--;out.push(path[j]);anchor=path[j];i=j+1;}return out;}
// Nearest walkable grid cell to a point (doors may sit between grid cells).
function snapCell(point){const gx=Math.round(point.x/STEP),gy=Math.round(point.y/STEP);let best=null,bd=Infinity;for(let r=0;r<=4;r++){for(let dx=-r;dx<=r;dx++)for(let dy=-r;dy<=r;dy++){if(Math.max(Math.abs(dx),Math.abs(dy))!==r)continue;const x=gx+dx,y=gy+dy;if(!isWalkable(x*STEP,y*STEP))continue;const d=Math.hypot(x*STEP-point.x,y*STEP-point.y);if(d<bd){bd=d;best={x,y};}}if(best)return best;}return null;}
// A* on a 0.25-unit grid with a binary heap.
export function findPath(from,to){
 const safe=nearestWalkable(to);if(!safe)return [];const end=snapCell(safe);const start={x:Math.round(from.x/STEP),y:Math.round(from.y/STEP)};if(!end)return [];
 const heap=[{x:start.x,y:start.y,g:0,f:0}],parents=new Map(),costs=new Map([[gridKey(start.x,start.y),0]]),visited=new Set();
 const push=n=>{heap.push(n);let i=heap.length-1;while(i>0){const p=(i-1)>>1;if(heap[p].f<=heap[i].f)break;[heap[p],heap[i]]=[heap[i],heap[p]];i=p;}};
 const pop=()=>{const top=heap[0],last=heap.pop();if(heap.length){heap[0]=last;let i=0;for(;;){const l=2*i+1,r=l+1;let m=i;if(l<heap.length&&heap[l].f<heap[m].f)m=l;if(r<heap.length&&heap[r].f<heap[m].f)m=r;if(m===i)break;[heap[m],heap[i]]=[heap[i],heap[m]];i=m;}}return top;};
 while(heap.length&&visited.size<12000){const n=pop(),key=gridKey(n.x,n.y);if(visited.has(key))continue;visited.add(key);
 if(n.x===end.x&&n.y===end.y){const path=[];let cursor=key;while(parents.has(cursor)){const [x,y]=cursor.split(',').map(Number);path.unshift({x:x*STEP,y:y*STEP});cursor=parents.get(cursor);}const s0={x:start.x*STEP,y:start.y*STEP};if(Math.hypot(s0.x-from.x,s0.y-from.y)>.01&&isWalkable(s0.x,s0.y))path.unshift(s0);if(isWalkable(to.x,to.y)&&Math.hypot(to.x-end.x*STEP,to.y-end.y*STEP)<.3)path.push({x:to.x,y:to.y});return path;}
 for(const [dx,dy]of [[1,0],[-1,0],[0,1],[0,-1]]){const x=n.x+dx,y=n.y+dy,key2=gridKey(x,y),g=n.g+1;if(!isWalkable(x*STEP,y*STEP)||g>=(costs.get(key2)??Infinity))continue;costs.set(key2,g);parents.set(key2,key);push({x,y,g,f:g+Math.abs(x-end.x)+Math.abs(y-end.y)});}
 }return [];
}
