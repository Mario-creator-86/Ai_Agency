/** Europe/Bucharest uses the browser timezone database, including seasonal DST. */
const formatter=new Intl.DateTimeFormat('en-GB',{
 timeZone:'Europe/Bucharest',hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',
 hour:'2-digit',minute:'2-digit',second:'2-digit',
});
export function bucharestTime(date=new Date()) {
 const parts=Object.fromEntries(formatter.formatToParts(date).map(p=>[p.type,p.value]));
 return {text:parts.hour+':'+parts.minute,
 hour:Number(parts.hour)+Number(parts.minute)/60+Number(parts.second)/3600,
 day:new Date(Date.UTC(Number(parts.year),Number(parts.month)-1,Number(parts.day))).getUTCDay()};
}
const DIGITS=['abcedf','bc','abged','abgcd','fgbc','afgcd','afgecd','abc','abcdefg','abfgcd'];
/** Seven-segment LED display, rasterized with whole pixels. Purely a clock, never a status badge. */
export function drawDigitalTime(ctx,x,y,text) {
 const segments={a:[2,0,7,2],b:[9,2,2,6],c:[9,10,2,6],d:[2,16,7,2],e:[0,10,2,6],f:[0,2,2,6],g:[2,8,7,2]};
 let cursor=Math.round(x);
 for(const char of text) {
  if(char===':') {ctx.fillStyle='#b5f0c4';ctx.fillRect(cursor+2,y+5,2,2);ctx.fillRect(cursor+2,y+12,2,2);cursor+=7;continue;}
  for(const [key,[dx,dy,w,h]] of Object.entries(segments)) {
   ctx.fillStyle=DIGITS[Number(char)]?.includes(key)?'#b5f0c4':'#20382f';
   ctx.fillRect(cursor+dx,Math.round(y)+dy,w,h);
  }
  cursor+=14;
 }
}
