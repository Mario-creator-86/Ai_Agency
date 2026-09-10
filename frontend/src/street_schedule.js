/** Art-directed urban rhythms, not measurements of a real city. Weights are relative likelihoods. */
const ordinary = {walk:24,phone:6,dog:5,cat:3,smoke:2,angry:1};
const cars = {sedan:26,hatchback:20,wagon:12,suv:10,coupe:6,pickup:3,taxi:8,van:7,minibus:3,bus:5};
const profile=(people,traffic,activities,vehicles={})=>({people,traffic,activities:{...ordinary,...activities},vehicles:{...cars,...vehicles}});
const QUIET=profile(3,.12,{walk:32,phone:3,dog:2,cat:16,run:2,friends:4,smoke:1},{taxi:24,van:1,bus:0,minibus:0});
const NIGHT_OUT=profile(7,.32,{walk:23,phone:8,dog:2,cat:9,run:1,friends:18,party:28,smoke:5},{taxi:42,van:1,bus:0,minibus:0});
const EARLY=profile(5,.3,{walk:23,run:25,dog:13,bike:7,commute:12,cat:5},{bus:9,van:10});
const MORNING=profile(11,.7,{walk:20,run:30,dog:12,bike:12,commute:27,cat:1},{bus:16,minibus:5,van:9});
const COMMUTE=profile(15,.94,{walk:20,run:5,dog:5,bike:11,commute:45,cat:1},{bus:18,minibus:6,van:12});
const LUNCH=profile(16,.68,{walk:30,run:3,dog:8,bike:8,commute:12,friends:22,shopping:18,cat:1},{van:16,bus:7});
const AFTERNOON=profile(13,.64,{walk:30,run:4,dog:8,bike:12,commute:14,friends:14,shopping:22,skate:7},{van:12});
const HOME=profile(17,.92,{walk:25,run:14,dog:14,bike:16,commute:28,friends:12,shopping:14,skate:7},{bus:15,minibus:5});
const EVENING=profile(12,.5,{walk:30,run:8,dog:15,bike:8,friends:24,party:7,shopping:5,skate:6},{taxi:20,van:2,bus:3});
const SOCIAL=profile(17,.67,{walk:24,run:4,dog:9,bike:5,friends:30,party:27,smoke:4,skate:5},{taxi:30,van:2,bus:4});
const LAZY_MORNING=profile(5,.23,{walk:27,run:23,dog:20,bike:9,commute:3,cat:5},{bus:3,van:2});
const WEEKEND=profile(13,.51,{walk:30,run:19,dog:16,bike:16,friends:24,shopping:16,skate:12,commute:3},{bus:5,van:3});
const SUNDAY_EVENING=profile(8,.35,{walk:35,run:8,dog:20,friends:15,party:2,bike:8,commute:4},{taxi:12,van:2,bus:3});

function blendWeights(a,b,t) {
  return Object.fromEntries([...new Set([...Object.keys(a),...Object.keys(b)])].map(k=>[k,(a[k]||0)*(1-t)+(b[k]||0)*t]));
}
export function dailyRhythm(hour, day) {
  const weekend=day===0||day===6;
  // Saturday 01:00 belongs to Friday's night out; Sunday 01:00 to Saturday's.
  const carryNight=day===0||day===6, goingOut=day===5||day===6;
  const evening=goingOut?SOCIAL:day===0?SUNDAY_EVENING:EVENING;
  /** @type {Array<[number, ReturnType<typeof profile>]>} */
  const anchors=[
    [0,carryNight?NIGHT_OUT:QUIET], [2,carryNight?NIGHT_OUT:QUIET], [4,QUIET],
    [6,weekend?LAZY_MORNING:EARLY], [7,weekend?LAZY_MORNING:MORNING],
    [10,weekend?WEEKEND:COMMUTE], [13,weekend?WEEKEND:LUNCH],
    [16,weekend?WEEKEND:AFTERNOON], [18,weekend?WEEKEND:HOME],
    [21,evening], [23,goingOut?NIGHT_OUT:QUIET], [24,goingOut?NIGHT_OUT:QUIET],
  ];
  const i=anchors.findIndex(([h])=>Number(h)>hour);
  const [start,a]=anchors[Math.max(0,i-1)], [end,b]=anchors[i<0?anchors.length-1:i];
  const t=(hour-Number(start))/Math.max(1,Number(end)-Number(start));
  return {people:Math.round(a.people*(1-t)+b.people*t),traffic:a.traffic*(1-t)+b.traffic*t,
    activities:blendWeights(a.activities,b.activities,t),vehicles:blendWeights(a.vehicles,b.vehicles,t)};
}
export function weightedChoice(weights,rng) {
  const entries=Object.entries(weights).filter(([,w])=>w>0);
  let value=rng()*entries.reduce((sum,[,w])=>sum+w,0);
  for(const [key,weight] of entries) {value-=weight;if(value<0)return key;}
  return entries.at(-1)?.[0] || 'walk';
}
