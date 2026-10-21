import test from 'node:test';
import assert from 'node:assert/strict';
import { dashboardMetrics, audienceCards, queuePreview, audienceHtml, StudioDashboard } from '../src/studio_dashboard.js';

const now = Date.parse('2026-10-16T10:00:00Z');
test('unread metrics stay unknown, while a read empty list is zero', () => {
  assert.equal(dashboardMetrics({now}).queued.value, '—');
  const got = dashboardMetrics({now, projects: [], queued: [], completed: []});
  assert.equal(got.projects.value, '0'); assert.equal(got.queued.value, '0'); assert.equal(got.completed.value, '0');
});
test('projects count open films, excluding rejected and already published films', () => {
  const projects = ['DRAFT','APPROVED','IN_PRODUCTION','RENDERED','REJECTED','CLOSED'].map((status,i)=>({id:String(i),status}));
  projects.push({id:'published',status:'RENDERED',publication:{status:'PUBLISHED'}});
  assert.equal(dashboardMetrics({now,projects}).projects.value,'4');
});
test('daily budget never borrows the monthly ceiling', () => {
  const budget = {today:{spent_usd:'2'},budgets:[{period:'MONTHLY',limit_usd:'300',spent_usd:'15.25'}]};
  assert.match(dashboardMetrics({now,budget}).budget.value, /2,00 \/ —/);
  budget.budgets.push({period:'DAILY',limit_usd:'30',spent_usd:'2'});
  assert.match(dashboardMetrics({now,budget}).budget.value,/2,00 \/ 30,00/);
});
test('today uses studio timezone and completion time; saturated reads are lower bounds', () => {
  const completed = [{status:'COMPLETED',id:'a',completed_at:'2026-10-15T22:30:00Z'},{status:'COMPLETED',id:'b',completed_at:'2026-10-15T19:00:00Z'}];
  assert.equal(dashboardMetrics({now,completed,timeZone:'Europe/Bucharest'}).completed.value,'1');
  const queued = Array.from({length:100},(_,i)=>({id:String(i),status:'QUEUED'}));
  assert.equal(dashboardMetrics({now,queued}).queued.value,'≥100');
});
test('queue preview uses ready time then worker priority, with deferred work after ready work', () => {
  const tasks = [
    {id:'later',status:'QUEUED',priority:100,next_attempt_at:'2026-10-17T00:00:00Z'},
    {id:'low',status:'QUEUED',priority:1,next_attempt_at:'2026-10-15T00:00:00Z'},
    {id:'high',status:'QUEUED',priority:5,next_attempt_at:'2026-10-16T09:00:00Z'},
    {id:'done',status:'COMPLETED',priority:100},
  ];
  assert.deepEqual(queuePreview(tasks,now).map(t=>t.id),['high','low','later']);
});
test('audience is matched by bound remote channel, never by the first account', () => {
  const channels=[{id:'slot-a',channel_type:'MAIN_FACTUAL',channel_name:'Canal A',remote_channel_id:'remote-a'},{id:'slot-b',channel_type:'OFFICE_SERIAL',channel_name:'Canal B',remote_channel_id:'remote-b'}];
  const connections=[{id:'b',connected:true,last_checked_at:'2026-10-16T09:59:00Z',channel:{id:'remote-b',view_count:'0',subscriber_count:'0'}},{id:'a',connected:true,last_checked_at:'2026-10-16T09:59:00Z',channel:{id:'remote-a',view_count:'123',subscriber_count:'45'}}];
  const rows=audienceCards(channels,connections,now);
  assert.equal(rows[0].views,'123'); assert.equal(rows[0].subscribers,'45'); assert.equal(rows[1].views,'0');
});
test('hidden, absent or invalid audience figures do not become zero; stale timestamp stays visible', () => {
  const channel={id:'slot',channel_type:'MAIN_FACTUAL',remote_channel_id:'remote'};
  const connection={connected:true,last_checked_at:'2026-10-01T00:00:00Z',channel:{id:'remote',view_count:null,subscriber_count:'12',hidden_subscriber_count:true}};
  const [row]=audienceCards([channel],[connection],now);
  assert.equal(row.views,'—'); assert.equal(row.subscribers,'Ascunși'); assert.equal(row.stale,true);
  assert.match(row.note,/01\.10\.2026/);
  connection.channel.view_count='not-a-number';
  assert.equal(audienceCards([channel],[connection],now)[0].views,'—');
});
test('audience HTML escapes names and includes both labels and measurement note', () => {
  const html=audienceHtml([{id:'x',name:'<img src=x onerror=alert(1)>',views:'0',subscribers:'—',note:'Date indisponibile',stale:true}]);
  assert.ok(!html.includes('<img')); assert.match(html,/&lt;img/); assert.match(html,/Vizualizări/); assert.match(html,/Abonați/);
});
test('project pagination includes older open films and refuses a non-advancing page', async () => {
  const calls=[];
  const dashboard=new StudioDashboard({root:/** @type {Document} */(/** @type {unknown} */({addEventListener(){}})),api:async path=>{
    calls.push(path);
    return path.endsWith('offset=0') ? {storyboards:[{id:'old-published',status:'RENDERED',publication:{status:'PUBLISHED'}}],next_offset:100} : {storyboards:[{id:'open',status:'APPROVED'}],next_offset:null};
  }});
  const projects=await dashboard.readProjects(()=>true);
  assert.equal(dashboardMetrics({projects}).projects.value,'1'); assert.equal(calls.length,2);
  dashboard.api=async()=>({storyboards:[],next_offset:0});
  await assert.rejects(()=>dashboard.readProjects(()=>true),/Project page unavailable/);
  assert.equal(await dashboard.readProjects(()=>false),null);
});
test('a slot bound to an account never borrows another account for the same remote channel', () => {
  const channels=[{id:'slot',channel_type:'MAIN_FACTUAL',remote_channel_id:'remote',youtube_connection_id:'bound'}];
  const connections=[{id:'other',channel:{id:'remote',view_count:'999'}}];
  assert.equal(audienceCards(channels,connections,now)[0].views,'—');
});
