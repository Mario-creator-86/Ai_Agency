import test from 'node:test';
import assert from 'node:assert/strict';
import {audioCue} from '../src/pixel_sound.js';
const now=Date.parse('2026-10-17T10:00:00Z');
const event=(type,status)=>({event_id:'real-event',event_type:type,timestamp:new Date(now).toISOString(),payload:{status}});
test('sound cues require a fresh live event and distinguish task, project, warning, failure and notification',()=>{
 assert.equal(audioCue(event('agent.run_completed','SUCCEEDED'),true,now),'task');assert.equal(audioCue(event('agent.run_completed','FAILED'),true,now),'error');
 assert.equal(audioCue(event('publishing.video_published'),true,now),'project');assert.equal(audioCue(event('media.qc_evaluated','FAILED'),true,now),'warning');
 assert.equal(audioCue(event('governance.approval_requested'),true,now),'notification');
 assert.equal(audioCue(event('agent.run_completed','SUCCEEDED'),false,now),null);assert.equal(audioCue(event('agent.run_completed','SUCCEEDED'),true,now+60000),null);
 assert.equal(audioCue(event('agent.run_started'),true,now),null);
});
