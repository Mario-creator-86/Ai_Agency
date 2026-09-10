import test from 'node:test';
import assert from 'node:assert/strict';
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
