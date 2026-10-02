import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {bucharestTime} from '../src/office_clock.js';
test('Bucharest clock uses 24h and the correct local weekday independently of host timezone',()=>{
 const result=bucharestTime(new Date('2026-09-11T21:05:00Z'));
 assert.equal(result.text,'00:05');assert.equal(result.day,6);
 assert.equal(bucharestTime(new Date('2026-01-01T11:45:00Z')).text,'13:45');
 assert.equal(bucharestTime(new Date('2026-07-01T11:45:00Z')).text,'14:45');
});
test('Bucharest DST jumps and repeats the correct hour',()=>{
 assert.equal(bucharestTime(new Date('2026-03-29T00:59:00Z')).text,'02:59');
 assert.equal(bucharestTime(new Date('2026-03-29T01:00:00Z')).text,'04:00');
 assert.equal(bucharestTime(new Date('2026-10-25T00:59:00Z')).text,'03:59');
 assert.equal(bucharestTime(new Date('2026-10-25T01:00:00Z')).text,'03:00');
});

// SELL-08 / PAGE-13: the page's clock, sun, street and labels follow the studio's own place, served
// in the snapshot; Bucharest is only the fallback for a snapshot that says nothing.
const LISBON={timezone:'Europe/Lisbon',latitude:38.7223,longitude:-9.1393,city:'Lisboa',holiday_country:'PT',studioName:'Estúdio Demo'};

test('with no place given the studio is drawn in Bucharest, the fallback',async(t)=>{
 const clock=await import('../src/office_clock.js');
 clock.setStudioPlace(null);
 t.after(()=>clock.setStudioPlace(null));
 assert.equal(clock.studioPlace().timeZone,'Europe/Bucharest');
 assert.equal(clock.studioPlace().city,'București');
 assert.equal(clock.studioTime(new Date('2026-07-01T11:45:00Z')).text,'14:45');
});

test('the clock follows Europe/Lisbon when the snapshot names it, whatever the host zone',async(t)=>{
 const clock=await import('../src/office_clock.js');
 clock.setStudioPlace(LISBON);
 t.after(()=>clock.setStudioPlace(null));
 assert.equal(clock.studioTime(new Date('2026-07-01T11:45:00Z')).text,'12:45');
 assert.equal(clock.studioTime(new Date('2026-01-01T11:45:00Z')).text,'11:45');
 // the fixed Bucharest reading is unchanged for those who ask for it by name
 assert.equal(clock.bucharestTime(new Date('2026-07-01T11:45:00Z')).text,'14:45');
 assert.equal(clock.studioPlace().city,'Lisboa');
 assert.equal(clock.studioPlace().holidayCountry,'PT');
});

test('a broken value keeps the fallback for that value only; an unknown holiday country has no holidays',async(t)=>{
 const clock=await import('../src/office_clock.js');
 const place=clock.setStudioPlace({timezone:'Mars/Olympus',latitude:120,longitude:-9.1393,city:'  ',holiday_country:'Portugal'});
 t.after(()=>clock.setStudioPlace(null));
 assert.equal(place.timeZone,'Europe/Bucharest');
 assert.equal(place.lat,44.4268);
 assert.equal(place.lon,-9.1393);
 assert.equal(place.city,'București');
 assert.equal(place.holidayCountry,'');
});

test('the sun, the street, the title and the scene label follow the studio place',async(t)=>{
 const clock=await import('../src/office_clock.js');
 const {timeOfDay,solarElevation}=await import('../src/hq_time.js');
 const {isPublicHoliday}=await import('../src/street_schedule.js');
 const {solarState}=await import('../src/studio_frame.js');
 const {titleCaption,titleKeptCaption}=await import('../src/title_frame.js');
 clock.setStudioPlace(LISBON);
 t.after(()=>clock.setStudioPlace(null));
 const at=new Date('2026-06-21T20:30:00Z');
 // 21:30 in Lisbon, the sun just under the horizon there; 23:30 and full night in Bucharest
 const lisbon=timeOfDay(at);
 assert.equal(lisbon.text,'21:30');
 assert.equal(lisbon.elevation,solarElevation(at,38.7223,-9.1393));
 assert.notEqual(lisbon.phase,'night');
 assert.equal(timeOfDay(at,{lat:44.4268,lon:26.1025,timeZone:'Europe/Bucharest'}).phase,'night');
 assert.notEqual(solarState(at.getTime()),'night');
 // 1 December is a Romanian holiday, not a Portuguese one the page knows about
 assert.equal(isPublicHoliday(2026,12,1),false);
 assert.equal(isPublicHoliday(2026,12,1,'RO'),true);
 const caption=titleCaption({text:'21:30',phase:'dusk'});
 assert.match(caption,/Lisboa/);
 assert.match(caption,/Estúdio Demo/);
 assert.doesNotMatch(caption,/București|AMN-AI/);
 assert.match(titleKeptCaption({text:'21:30'},''),/Estúdio Demo, Lisboa/);
});

test('no page module names Bucharest as a place it draws, outside the fallback',()=>{
 const files=['office_engine.js','hq_world.js','title_frame.js','stream_keep.js','studio_frame.js','hq_time.js','street_schedule.js'];
 for(const name of files){
  const src=fs.readFileSync(new URL(`../src/${name}`,import.meta.url),'utf8');
  const code=src.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'');
  assert.ok(!/'BUCUREȘTI'|București|Europe\/Bucharest|44\.4268/.test(code),name);
 }
 const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
 assert.ok(!/Sediul AMN-AI, București|•  BUCUREȘTI/.test(html),'index.html');
});

test('the place is kept in this browser for the next title, and a refusing storage changes nothing',async(t)=>{
 const store=new Map();
 const previous=globalThis.localStorage;
 globalThis.localStorage={getItem:(k)=>store.get(k)??null,setItem:(k,v)=>store.set(k,String(v)),removeItem:(k)=>store.delete(k)};
 t.after(()=>{globalThis.localStorage=previous;});
 const clock=await import('../src/office_clock.js');
 clock.setStudioPlace(LISBON);
 assert.equal(JSON.parse(store.get('amn.studioPlace')).city,'Lisboa');
 clock.setStudioPlace(null);
 assert.equal(store.has('amn.studioPlace'),false);
 globalThis.localStorage={getItem(){throw new Error('denied');},setItem(){throw new Error('denied');},removeItem(){throw new Error('denied');}};
 assert.equal(clock.setStudioPlace(LISBON).city,'Lisboa');
 clock.setStudioPlace(null);
});
