import { appearance } from './street_actor.js';
import { bucharestTime } from './office_clock.js';
import { dailyRhythm, weightedChoice } from './street_schedule.js';
/** Ambient fiction only. Never emits product events or represents employee activity. */
export function streetClock(date = new Date()) {
  const {hour,day,text}=bucharestTime(date);
  const daylight = Math.max(0, Math.min(1, (hour - 5.5) / 2, (20.5 - hour) / 2));
  return {hour,day,text,daylight,...dailyRhythm(hour,day),
    birds:daylight>0.1,minute:Math.floor(date.getTime()/60000)};
}
export function mixColor(a,b,t) {
  const parts=[1,3,5].map(i=>Math.round(parseInt(a.slice(i,i+2),16)*(1-t)+parseInt(b.slice(i,i+2),16)*t).toString(16).padStart(2,'0'));
  return '#'+parts.join('');
}
export function randomSource(seed) {
  let value = seed >>> 0;
  return () => {value += 0x6d2b79f5; let t = value;
    t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;};
}
const pick = (items, rng) => items[Math.floor(rng() * items.length)];
export const VEHICLE_MODELS = [
  {kind:'sedan',w:90,h:30}, {kind:'hatchback',w:72,h:32},
  {kind:'wagon',w:106,h:33}, {kind:'suv',w:103,h:39},
  {kind:'coupe',w:84,h:26}, {kind:'pickup',w:110,h:36},
  {kind:'taxi',w:92,h:31}, {kind:'van',w:112,h:40},
  {kind:'minibus',w:130,h:44}, {kind:'bus',w:168,h:46},
];
/** @param {Function} rng @param {boolean | {vehicles: Record<string, number>}} schedule */
export function randomVehicle(rng, schedule = false) {
  const kind=typeof schedule==='object' ? weightedChoice(schedule.vehicles,rng) : null;
  const model = typeof schedule==='object' && schedule
    ? VEHICLE_MODELS.find(m=>m.kind===kind) || VEHICLE_MODELS[0]
    : pick(schedule ? VEHICLE_MODELS.slice(0,8) : VEHICLE_MODELS,rng);
  const body = model.kind === 'taxi' ? '#d2ae55' : pick(['#a35047','#467e78','#677ea0','#b8bbad','#c29268','#625a80','#3c5060','#8c5365'],rng);
  return {...model,body,roof:body};
}
export function depthSortedTraffic(cars) {
  return [...cars].filter(c=>c.visible !== false).sort((a,b)=>a.laneOffset-b.laneOffset);
}
/** Scanline circle: genuinely circular silhouette, rasterized without smoothing. */
export function pixelDisc(ctx, cx, cy, radius, color) {
  ctx.fillStyle=color;
  for(let y=-radius;y<=radius;y++) {
    const half=Math.floor(Math.sqrt(radius*radius-y*y));
    ctx.fillRect(Math.round(cx)-half,Math.round(cy)+y,half*2+1,1);
  }
}
export const PHRASES = [
 'AJUNG IN CATEVA MINUTE.', 'NE VEDEM LA CAFENEA?', 'AM RATAT AUTOBUZUL!',
 'AI LUAT PAINE?', 'TE SUN CAND AJUNG.', 'AZI MERG PE JOS.',
 'CE FACEM IN WEEKEND?', 'PASTREAZA-MI UN LOC.', 'AM GASIT CHEILE!',
 'E FRUMOS AFARA.', 'VIN CU BICICLETA.', 'MA AUZI ACUM?',
 'MA OPRESC LA MAGAZIN.', 'NE VEDEM IN PARC.', 'BINE, VORBIM MAI TARZIU.',
 ...['CINCI','ZECE','DOUA','TREI','SAPTE','DOUAZECI'].map(n=>'AJUNG IN '+n+' MINUTE.'),
 ...['GARA','BIBLIOTECA','BRUTARIE','STATIE','CINEMA','TERASA','PIATA','COLT'].map(loc=>'NE VEDEM LA '+loc+'?'),
 ...['CHEILE','PORTOFELUL','OCHELARII','UMBRELA','BILETELE','CASTILE'].map(item=>'AI GASIT '+item+'?'),
 ...['LUNI','MARTI','MIERCURI','JOI','VINERI','SAMBATA','DUMINICA'].map(day=>'RAMANE PE '+day+'?'),
 ...['UN CEAI','O CAFEA','O PAUZA','O PLIMBARE','UN FILM','O LIMONADA'].map(item=>'CE ZICI DE '+item+'?'),
];
export class StreetLife {
  constructor(seed, width, clock = streetClock()) {
    this.rng=randomSource(seed); this.width=width; this.people=[]; this.nextSpawn=0;
    this.phrases=[]; this.lastPhrase=''; this.phraseContext='all'; this.clock=clock;
    this.groupSequence=0;
    while(this.people.length<clock.people) this.spawn(true);
  }
  phrase(contextual=false) {
    const context=contextual&&(this.clock.hour<6||this.clock.hour>=23)?'night':'all';
    if(context!==this.phraseContext) {this.phrases=[];this.phraseContext=context;}
    if(!this.phrases.length) {
      // Closed shops and daytime errands do not appear in late-night conversations.
      this.phrases=PHRASES.filter(line=>context!=='night'||!/(AUTOBUZ|PAINE|CAFENEA|MAGAZIN|PARC|BIBLIOTECA|BRUTARIE|CINEMA|TERASA|PIATA|CAFEA|LIMONADA)/.test(line));
      for(let i=this.phrases.length-1;i>0;i--) {const j=Math.floor(this.rng()*(i+1)); [this.phrases[i],this.phrases[j]]=[this.phrases[j],this.phrases[i]];}
      if(this.phrases.at(-1)===this.lastPhrase) [this.phrases[0],this.phrases[this.phrases.length-1]]=[this.phrases.at(-1),this.phrases[0]];
    }
    this.lastPhrase=this.phrases.pop(); return this.lastPhrase;
  }
  spawn(initial=false) {
    const rng=this.rng;
    let activity=weightedChoice(this.clock.activities,rng);
    const dir=rng()<0.5?1:-1;
    const available=Math.max(0,this.clock.people-this.people.length);
    if(!available) return;
    const groupedNow=this.people.filter(p=>p.groupId!==null).length;
    const groupBudget=Math.max(0,Math.max(2,Math.floor(this.clock.people*.55))-groupedNow);
    if((available<2||groupBudget<2) && (activity==='friends'||activity==='party')) activity='walk';
    const grouped=activity==='friends'||activity==='party';
    const count=grouped?Math.min(available,groupBudget,2+Math.floor(rng()*3)):1;
    const groupId=grouped?++this.groupSequence:null;
    const origin=initial?rng()*this.width:dir>0?-45:this.width+45;
    const groupSpeed=16+rng()*8;
    for(let member=0;member<count;member++) {
    const stationary=activity==='smoke';
    const speed=grouped?groupSpeed:({cat:25,run:65,bike:90,skate:48,angry:38,commute:34,shopping:22})[activity] || 18+rng()*15;
    this.people.push({activity,groupId,member,dir,x:origin-dir*member*19,
      speed,stopX:80+rng()*(this.width-160),pause:stationary?12+rng()*25:0,
      ...appearance(rng,activity),
      phase:rng()*Math.PI*2,depth:activity==='bike'||activity==='skate'?0:2+rng(),
      bag:['commute','shopping'].includes(activity)||(activity==='walk'&&rng()<.2),
      distance:0,moving:true,velocity:speed*.8,skatePeriod:3.2+rng()*1.8,skatePhase:0,pushDistance:0,
      dog:activity==='dog',age:0,talkAt:3+rng()*7,talkUntil:0,speech:'',tone:pick(['#d1aa7a','#71808a','#3a3433'],rng)});
    }
  }
  update(dt, clock) {
    this.clock=clock; this.nextSpawn-=dt;
    for(const p of this.people) {
      p.age+=dt;
      // Substeps preserve push/contact transitions even when a frame arrives late.
      let remaining=Math.min(dt,.25);
      while(remaining>0) {
        const step=Math.min(remaining,1/120);remaining-=step;
        let speed=p.speed;
        if(p.activity==='skate') {
          const previous=p.skatePhase;
          p.skatePhase=(p.skatePhase+step)%p.skatePeriod;
          const pushing=p.skatePhase>=.18&&p.skatePhase<.53;
          if(previous<.18&&p.skatePhase>=.18)p.pushDistance=0;
          p.velocity=Math.max(18,Math.min(p.speed,p.velocity+(pushing?45:-5)*step));
          speed=p.velocity;
          if(pushing)p.pushDistance+=speed*step;
        }
        const stopped=p.pause>0&&Math.abs(p.x-p.stopX)<.001;
        let distance=stopped?0:speed*step;
        const toStop=(p.stopX-p.x)*p.dir;
        if(p.pause>0&&toStop>=0&&toStop<distance)distance=toStop;
        if(stopped)p.pause=Math.max(0,p.pause-step);
        p.moving=distance>0;
        p.x+=distance*p.dir;p.distance+=distance;
      }
      if(p.activity==='phone' && p.age>=p.talkAt) {
        p.speech=this.phrase(true); p.talkUntil=p.age+4; p.talkAt=p.age+12+this.rng()*18;
      }
    }
    this.people=this.people.filter(p=>p.x>-130&&p.x<this.width+130);
    if(this.people.length<clock.people&&this.nextSpawn<=0) {this.spawn();this.nextSpawn=(2+this.rng()*9)*(14/Math.max(3,clock.people));}
  }
}

/** Replace vehicles only beyond the visible street and only when both loop gaps allow it. */
export function refreshVehicle(car, cars, width, rng, clock) {
  const candidate=randomVehicle(rng,clock), loop=width+300;
  const safe=cars.every(other=>{
    if(other===car||other.dir!==car.dir) return true;
    const distance=((other.x-car.x)%loop+loop)%loop;
    return distance>=candidate.w+24 && loop-distance>=other.style.w+24;
  });
  if(safe) car.style=candidate;
  car.speed=(48+rng()*50)*car.dir;
  car.visible=rng()<clock.traffic;
}
