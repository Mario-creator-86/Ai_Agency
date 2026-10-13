import test from 'node:test';
import assert from 'node:assert/strict';
import { newestFirst, preserveReading } from '../src/activity_lists.js';

test('activity dates sort newest first without mutating API results; tied mail keeps reverse causal order', () => {
  const rows = [{id:'old',created_at:'2026-10-01'}, {id:'new',created_at:'2026-10-03'}, {id:'reply',created_at:'2026-10-03'}];
  assert.deepEqual(newestFirst(rows).map(r=>r.id), ['new','reply','old']);
  assert.deepEqual(newestFirst(rows,{oldestFirst:true}).map(r=>r.id), ['reply','new','old']);
  assert.equal(rows[0].id,'old');
});

function view(scrollTop) {
  const scroller={scrollTop, style:{overflowAnchor:'auto'},getBoundingClientRect:()=>({top:0,bottom:300,height:300})};
  const positions=new Map([['a',0],['b',150],['c',300],['d',450]]);
  const cards=()=>[...positions].map(([key,pos])=>({getAttribute:n=>n==='data-card-key'?key:null,
    getBoundingClientRect:()=>({top:pos-scroller.scrollTop,bottom:pos+150-scroller.scrollTop,height:150})}));
  const host={...scroller,parentElement:scroller,ownerDocument:{defaultView:{getComputedStyle:n=>({overflowY:n===scroller?'auto':'visible'})}},
    querySelectorAll:cards,getBoundingClientRect:()=>({top:-scroller.scrollTop,bottom:600-scroller.scrollTop,height:600})};
  return {scroller,host,positions};
}

test('prepending cards preserves the same visible card and its offset when reading older entries',()=>{
  const {scroller,host,positions}=view(200);
  const restore=preserveReading(host);
  for(const [id,pos] of positions) positions.set(id,pos+240);
  restore();
  assert.equal(scroller.scrollTop,440);
  assert.equal(positions.get('b')-scroller.scrollTop,-50);
  assert.equal(scroller.style.overflowAnchor,'auto');
});

test('at the top new cards stay visible; a removed anchor falls back to the next visible card',()=>{
  const pinned=view(0);
  const restore=preserveReading(pinned.host);
  for(const [id,pos] of pinned.positions) pinned.positions.set(id,pos+100);
  restore(); assert.equal(pinned.scroller.scrollTop,0);
  const reading=view(200);
  const recover=preserveReading(reading.host);
  reading.positions.delete('b');
  for(const [id,pos] of reading.positions) reading.positions.set(id,pos+80);
  recover(); assert.equal(reading.scroller.scrollTop,280);
});
