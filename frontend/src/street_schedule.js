/**
 * How busy the street in front of the headquarters is, by the real hour and day in Bucharest.
 *
 * The profiles are the city's rhythm as anyone who lives there knows it, not a count from a
 * sensor: the street is at its fullest in the rush hours (08:00-09:00 and 17:30-18:30 on a
 * working day), quiet at midday, nearly empty in the small hours, slower at the weekend, and a
 * Romanian public holiday reads as a Sunday. Weights are relative likelihoods. The hour and the
 * day are the only inputs; the weather's share is applied by hq_traffic.js and hq_pedestrians.js,
 * and the whole rule is put together in hq_events.js `streetRule`.
 */
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
  const late=goingOut?NIGHT_OUT:QUIET, small=carryNight?NIGHT_OUT:QUIET;
  /** @type {Array<[number, ReturnType<typeof profile>]>} */
  const anchors=weekend?[
    [0,small],[2,small],[4,QUIET],[6,LAZY_MORNING],[9,LAZY_MORNING],[11,WEEKEND],[18,WEEKEND],
    [21,evening],[23,late],[24,late],
  ]:[
    // The working day: the morning rush peaks from 08:00 to 09:00, the evening one from 17:30
    // to 18:30; between them the street is at its lunch and afternoon pace.
    [0,small],[2,small],[4,QUIET],[5.5,EARLY],[7,MORNING],[8,COMMUTE],[9,COMMUTE],[10.5,AFTERNOON],
    [13,LUNCH],[16,AFTERNOON],[17.5,HOME],[18.5,HOME],[21,evening],[23,late],[24,late],
  ];
  const i=anchors.findIndex(([h])=>Number(h)>hour);
  const [start,a]=anchors[Math.max(0,i-1)], [end,b]=anchors[i<0?anchors.length-1:i];
  const t=(hour-Number(start))/Math.max(0.5,Number(end)-Number(start));
  return {people:Math.round(a.people*(1-t)+b.people*t),traffic:a.traffic*(1-t)+b.traffic*t,
    activities:blendWeights(a.activities,b.activities,t),vehicles:blendWeights(a.vehicles,b.vehicles,t)};
}

/**
 * Orthodox Easter Sunday in the Gregorian calendar (Meeus' Julian computus plus the 13 days the
 * calendars are apart between 1900 and 2099). 2026 → 12 April.
 * @param {number} year
 * @returns {[number, number]} [month 1-12, day]
 */
export function orthodoxEaster(year) {
  const a=year%4, b=year%7, c=year%19;
  const d=(19*c+15)%30, e=(2*a+4*b-d+34)%7;
  const julian=new Date(Date.UTC(year, Math.floor((d+e+114)/31)-1, ((d+e+114)%31)+1));
  const g=new Date(julian.getTime()+13*86400000);
  return [g.getUTCMonth()+1, g.getUTCDate()];
}

/** Romania's fixed public holidays (Codul muncii, art. 139), as MM-DD. */
const FIXED_HOLIDAYS=new Set(['01-01','01-02','01-06','01-07','01-24','05-01','06-01','08-15','11-30','12-01','12-25','12-26']);

/**
 * Whether a date in Bucharest is a Romanian public holiday: the fixed ones, and Orthodox Good
 * Friday, Easter, Easter Monday, Rusalii (Pentecost) and its Monday.
 * @param {number} year @param {number} month 1-12 @param {number} day
 */
export function isPublicHoliday(year, month, day) {
  const mmdd=`${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
  if(FIXED_HOLIDAYS.has(mmdd)) return true;
  const [em,ed]=orthodoxEaster(year);
  const easter=Date.UTC(year,em-1,ed), today=Date.UTC(year,month-1,day);
  const offset=Math.round((today-easter)/86400000);
  return offset===-2||offset===0||offset===1||offset===49||offset===50;
}

export function weightedChoice(weights,rng) {
  const entries=Object.entries(weights).filter(([,w])=>w>0);
  let value=rng()*entries.reduce((sum,[,w])=>sum+w,0);
  for(const [key,weight] of entries) {value-=weight;if(value<0)return key;}
  return entries.at(-1)?.[0] || 'walk';
}
