import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PORTRAITS,portraitChoice,portraitInfo,loadPortraitAtlas,drawAgentPortrait} from '../src/pixel_portraits.js';
import {ACTORS} from '../src/pixel_actor_atlas.js';
import {characterProfile} from '../src/pixel_people.js';
import bible from './fixtures/pixel_actors_bible.json' with {type:'json'};

const profiles=PORTRAITS.profiles.map(p=>characterProfile({id:p.employee_id,role_name:p.roles[0]},bible.find(b=>b.employee_id===p.employee_id)));
test('all eight original identities have distinct front portraits and role environments, with valid native crop bounds',()=>{
 const file=readFileSync(new URL('../public'+PORTRAITS.asset,import.meta.url));
 assert.equal(file.readUInt32BE(16),PORTRAITS.width);assert.equal(file.readUInt32BE(20),PORTRAITS.height);
 assert.equal(PORTRAITS.profiles.length,8);assert.equal(new Set(PORTRAITS.profiles.map(p=>p.background)).size,8);
 assert.deepEqual(new Set(PORTRAITS.profiles.map(p=>p.employee_id)),new Set(ACTORS.staff.map(p=>p.employee_id)));
 for(const [i,p] of profiles.entries()){
  const choice=portraitChoice(p);assert.equal(choice.employee_id,PORTRAITS.profiles[i].employee_id);
  assert.equal(portraitInfo(p).orientation,'front');
  const [x,y,w,h]=choice.rect;assert.ok(x>=0&&y>=0&&x+w<=PORTRAITS.width&&y+h<=PORTRAITS.height);
  assert.ok(Math.abs(w/h-PORTRAITS.aspect)<.003);
  for(const other of PORTRAITS.profiles.filter(o=>o!==choice)){const [a,b,c,d]=other.rect;assert.ok(x+w<=a||a+c<=x||y+h<=b||b+d<=y);}
 }
});
test('different employees, changed roles or edited appearance never inherit a generated face by matching names',()=>{
 const p=profiles[1];assert.equal(portraitChoice({...p,employeeId:'new-hire'}),null);
 assert.equal(portraitChoice({...p,hair:'#000000'}),null);
 assert.equal(portraitChoice({...p,role:'accountant'}),null);
 assert.equal(portraitInfo({...p,employeeId:'new-hire'}).source,'front_fallback');
 assert.ok(portraitChoice({...p,role:'researcher'}));
});
test('portrait asset loads once; native drawing uses the identity tile and preserves face aspect',async t=>{
 const previous=globalThis.Image;let loads=0;
 globalThis.Image=class{naturalWidth=PORTRAITS.width;naturalHeight=PORTRAITS.height;set src(value){loads++;assert.equal(value,PORTRAITS.asset);queueMicrotask(()=>this.onload());}};
 t.after(()=>globalThis.Image=previous);
 assert.equal(await loadPortraitAtlas(),true);assert.equal(await loadPortraitAtlas(),true);assert.equal(loads,1);
 for(const profile of profiles){
  const calls=[],ctx={canvas:{width:264,height:198},save(){},restore(){},clearRect(){},fillRect(){},drawImage(...args){calls.push(args);}};
  assert.equal(drawAgentPortrait(ctx,profile),true);assert.equal(calls.length,1);
  const [,x,y,w,h,dx,dy,dw,dh]=calls[0];assert.deepEqual([x,y,w,h],portraitChoice(profile).rect);
  assert.ok(Math.abs(dw/dh-w/h)<1e-9);assert.ok(dx>=0&&dy>=0&&dx+dw<=264.0001&&dy+dh<=198.0001);
  assert.equal(portraitInfo(profile).source,'native_atlas');
 }
});
test('invalid image dimensions are refused instead of showing a neighbouring face',async t=>{
 const previous=globalThis.Image;
 globalThis.Image=class{naturalWidth=100;naturalHeight=100;set src(value){queueMicrotask(()=>this.onload());}};
 t.after(()=>globalThis.Image=previous);
 const isolated=await import('../src/pixel_portraits.js?wrong-native-size');
 assert.equal(await isolated.loadPortraitAtlas(),false);assert.equal(isolated.portraitInfo(profiles[0]).source,'front_fallback');
});
