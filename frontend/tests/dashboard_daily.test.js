import test from 'node:test';
import assert from 'node:assert/strict';
import {StudioDashboard,dashboardMetrics} from '../src/studio_dashboard.js';
import {dayWindow,dailyBudget,completionRecord,activeProjects} from '../src/dashboard_daily.js';
test('Bucharest day uses local midnight, including 23/25 hour DST days',()=>{
 for(const [date,start,end]of [['2026-10-17T00:01:00+03:00','2026-10-16T21:00:00.000Z','2026-10-17T21:00:00.000Z'],['2026-03-29T12:00:00Z','2026-03-28T22:00:00.000Z','2026-03-29T21:00:00.000Z'],['2026-10-25T12:00:00Z','2026-10-24T21:00:00.000Z','2026-10-25T22:00:00.000Z']]){const w=dayWindow(Date.parse(date));assert.equal(w.since,start);assert.equal(new Date(w.next).toISOString(),end);}
});
test('daily budget uses one canonical total, keeps holds separate and ignores token subscription/monthly costs',()=>{
 const budget={today:{spent_usd:'9.00',agent_usd:'100'},month:{spent_usd:'999'},budgets:[{period:'DAILY',limit_usd:'20',spent_usd:'9.00',reserved_usd:'3',remaining_usd:'8'},{period:'MONTHLY',limit_usd:'900',spent_usd:'999'}]};
 const got=dailyBudget(budget);assert.equal(got.value,'9,00 / 20,00 USD');assert.match(got.note,/8,00 USD/);assert.equal(got.percent,45);assert.match(got.title,/3,00 USD rezervați/);
});
test('daily zero, unavailable, missing ceiling, overspend and malformed money remain distinct',()=>{
 assert.equal(dailyBudget(null).value,'—');assert.equal(dailyBudget({today:{spent_usd:'0'},budgets:[]}).value,'0,00 / — USD');
 assert.equal(dailyBudget({budgets:[{period:'DAILY',limit_usd:'10',spent_usd:'0',remaining_usd:'10'}]}).percent,0);
 assert.equal(dailyBudget({budgets:[{period:'DAILY',limit_usd:'10',spent_usd:'12',remaining_usd:'0'}]}).percent,100);
 assert.equal(dailyBudget({budgets:[{period:'DAILY',limit_usd:'',spent_usd:null}]}).percent,null);
});
test('only a successful completion event is a completed agent task, using completion timestamp',()=>{
 const w=dayWindow(Date.parse('2026-10-17T12:00:00Z'));
 const event={event_type:'agent.run_completed',aggregate_id:'run',timestamp:'2026-10-16T21:01:00Z',payload:{status:'SUCCEEDED'}};
 assert.equal(completionRecord(event,w).completed_at,event.timestamp);
 for(const bad of [{...event,timestamp:'2026-10-16T20:59:59Z'},{...event,payload:{status:'FAILED'}},{...event,event_type:'agent.state_changed'},{...event,timestamp:'invalid'}])assert.equal(completionRecord(bad,w),null);
});
test('active projects retain real titles and exclude rejected/published, with rendering included',()=>{
 const rows=[{id:'a',title:'Film real',status:'RENDERING'},{id:'b',status:'APPROVED',publication:{status:'PUBLISHED'}},{id:'c',status:'REJECTED'}];
 assert.deepEqual(activeProjects(rows).map(x=>x.title),['Film real']);
});

const root={addEventListener(){},getElementById(){return null;}};
test('completion pages exceed 100, deduplicate task IDs, continue incrementally and fail closed on bad cursors',async()=>{
 const window=dayWindow(Date.parse('2026-10-17T10:00:00Z')),calls=[];
 const event=i=>({event_id:'e'+i,event_type:'agent.run_completed',aggregate_id:'r'+i,timestamp:'2026-10-17T09:00:00Z',payload:{status:'SUCCEEDED'}});
 const dashboard=new StudioDashboard({root,api:async path=>{calls.push(path);const cursor=Number(new URL('http://test'+path).searchParams.get('after'));return cursor===0?{since:window.since,events:Array.from({length:300},(_,i)=>event(i)),next_cursor:300,has_more:true}:{since:window.since,events:[event(299),...Array.from({length:250},(_,i)=>event(i+300))],next_cursor:550,has_more:false};}});
 dashboard.day=window;const first=await dashboard.readCompleted(()=>true);assert.equal(first.records.length,550);assert.equal(calls.length,2);
 dashboard.completionDay=window.day;dashboard.completionCursor=first.cursor;dashboard.data.completed=first.records;
 dashboard.api=async path=>{assert.match(path,/after=550/);return {since:window.since,events:[event(550)],next_cursor:551,has_more:false};};
 assert.equal((await dashboard.readCompleted(()=>true)).records.length,551);
 dashboard.api=async()=>({since:window.since,events:[],next_cursor:550,has_more:true});await assert.rejects(()=>dashboard.readCompleted(()=>true),/cursor did not advance/);
});
test('midnight clears the previous count and spend rather than showing them as today or inventing zero',()=>{
 const dashboard=new StudioDashboard({root,api:async()=>{}});dashboard.paint=()=>{};dashboard.scheduleDay=()=>{};
 dashboard.day=dayWindow(Date.now()-48*3600000);dashboard.data.completed=[{id:'yesterday',status:'COMPLETED',completed_at:new Date(Date.now()-48*3600000).toISOString()}];dashboard.budget={today:{spent_usd:'4'}};
 dashboard.checkDay();assert.equal(dashboard.data.completed,null);assert.equal(dashboard.budget,null);assert.equal(dashboardMetrics(dashboard.data).completed.value,'—');
 dashboard.running=true;const event={event_id:'new',event_type:'agent.run_completed',aggregate_id:'run',timestamp:new Date().toISOString(),payload:{status:'SUCCEEDED'}};
 dashboard.onEvent(event,false);assert.equal(dashboard.pendingCompletions.size,0);dashboard.onEvent(event,true);dashboard.onEvent(event,true);assert.equal(dashboard.pendingCompletions.size,1);
 dashboard.data.completed=[];dashboard.onEvent(event,true);dashboard.onEvent(event,true);assert.equal(dashboardMetrics(dashboard.data).completed.value,'1');
});

test('midnight timer replaces the old day automatically at the Bucharest boundary',()=>{
 const previousWindow=globalThis.window,previousNow=Date.now;let at=Date.parse('2026-10-16T20:59:59.990Z'),callback,delay,refreshed=0;
 globalThis.window={clearTimeout(){},setTimeout(fn,ms){callback=fn;delay=ms;return 1;}};Date.now=()=>at;
 try{const dashboard=new StudioDashboard({root,api:async()=>{}});dashboard.paint=()=>{};dashboard.refresh=async()=>{refreshed++;};dashboard.running=true;dashboard.data.completed=[{id:'old'}];dashboard.scheduleDay();assert.equal(delay,30);const tick=callback;at+=30;tick();assert.equal(dashboard.day.day,'2026-10-17');assert.equal(dashboard.data.completed,null);assert.equal(refreshed,1);assert.ok(delay>23*3600000);}
 finally{Date.now=previousNow;globalThis.window=previousWindow;}
});
