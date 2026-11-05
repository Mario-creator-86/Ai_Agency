import http from 'node:http';
import {readFileSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import {resolve,dirname,extname,join,relative as relativePath,isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Store} from './src/store.mjs';
import {Runtime,everyone,localClock} from './src/runtime.mjs';
import {agents,providerIds,TEAMS} from './src/agents.mjs';
import {diagnostics} from './src/providers.mjs';
import {sourceStatus} from './src/datatools.mjs';
const root=dirname(fileURLToPath(import.meta.url));const arg=name=>{const i=process.argv.indexOf(name);return i>=0?process.argv[i+1]:undefined;};const port=Number(arg('--port')||process.env.PORT||8012);const preview=process.argv.includes('--preview')||process.env.TOWN_PREVIEW==='1';const host=arg('--host')||process.env.HOST||(preview?'0.0.0.0':'127.0.0.1');
const dataRoot=process.env.TOWN_DATA_DIR||join(root,'data');mkdirSync(dataRoot,{recursive:true});const teamFile=join(dataRoot,'active-team.json');
const streams=new Set();let world={ceo:{x:10,y:14},meeting:false};const notify=()=>{const text='data: '+JSON.stringify({at:Date.now()})+'\n\n';for(const r of streams)r.write(text);};
// Each team version has its own database and agent folders. V1 keeps the original locations.
const openTeam=team=>{const dir=team==='v1'?dataRoot:join(dataRoot,team);const s=new Store(dir,team);return {store:s,runtime:new Runtime(s,team==='v1'?root:dir,notify)};};
let activeTeam='v1';try{const t=JSON.parse(readFileSync(teamFile,'utf8')).team;if(TEAMS[t])activeTeam=t;}catch{}
let {store,runtime}=openTeam(activeTeam);
function switchTeam(team){if(!TEAMS[team])throw new Error('Versiune de echipă necunoscută.');if(team===activeTeam)return;const brains=Object.fromEntries(agents.map(a=>[a.id,store.get('agent:'+a.id)]).filter(([,c])=>c));runtime.close();store.close();
 ({store,runtime}=openTeam(team));activeTeam=team;writeFileSync(teamFile,JSON.stringify({team}));world={...world,meeting:false};
 // A team opened for the first time inherits the brains chosen in the previous team.
 if(!store.get('brainsCopied')){for(const a of store.members()){const old=brains[a.id],now=store.get('agent:'+a.id);if(old&&now&&now.provider==='demo'&&old.provider!=='demo')store.set('agent:'+a.id,{...now,provider:old.provider,model:old.model});}store.set('brainsCopied',true);}
 store.event('team','mario',{text:'Versiunea activă: '+TEAMS[team].label});notify();}
const json=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(data));};
const validAgent=id=>everyone().some(a=>a.id===id);const text=(value,max)=>{if(typeof value!=='string'||!value.trim()||value.length>max)throw new Error('Text invalid sau prea lung.');return value.trim();};
async function body(req){if(!req.headers['content-type']?.startsWith('application/json'))throw new Error('Este necesar JSON.');let b='';for await(const c of req){b+=c;if(b.length>250000)throw new Error('Cerere prea mare.');}try{return JSON.parse(b||'{}');}catch{throw new Error('Cerere JSON invalidă.');}}
const server=http.createServer(async(req,res)=>{try{
 const reqHost=req.headers.host||'';if(!preview&&!/^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(reqHost))return json(res,403,{error:'Acces local.'});
 if(req.headers.origin&&new URL(req.headers.origin).host!==reqHost)return json(res,403,{error:'Origine nepermisă.'});
 const url=new URL(req.url,'http://localhost');const path=url.pathname;
 if(req.method==='GET'&&path==='/api/state'){const day=localClock().day;const met=Object.entries(store.get('met')||{}).filter(([,d])=>d===day).map(([k])=>k);return json(res,200,{...store.snapshot(),runtime:runtime.status(),world,metToday:met});}
 if(req.method==='GET'&&path==='/api/sources')return json(res,200,await sourceStatus());
 if(req.method==='GET'&&path==='/api/portfolio')return json(res,200,store.paperTrades().length?await runtime.portfolio():{mode:'SIMULARE',positions:[],closedTrades:0,realizedPnl:0,unrealizedPnl:0});
 if(req.method==='GET'&&path==='/api/diagnostics')return json(res,200,await diagnostics());
 if(req.method==='GET'&&path==='/api/events'){res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive'});res.write(': connected\n\n');streams.add(res);req.on('close',()=>streams.delete(res));return;}
 if(req.method==='GET'&&path.startsWith('/api/artifacts/')){const r=store.db.prepare('SELECT * FROM artifacts WHERE id=?').get(path.split('/').pop());return json(res,r?200:404,r||{error:'Livrabil inexistent.'});}
 if(req.method==='GET'&&path==='/api/export')return json(res,200,{...store.snapshot(),exportedAt:new Date().toISOString()});
 if(req.method==='POST'){
 const b=await body(req);
 if(path==='/api/chat'){const channel=text(b.channel,60);const project=channel.startsWith('project:')?store.getProject(channel.slice(8)):null;if(channel!=='townhall'&&!project&&!validAgent(channel))throw new Error('Canal invalid.');const message=text(b.text,12000);let targets=channel==='townhall'||project?[...new Set((message.match(/@[\w-]+/g)||[]).map(x=>x.slice(1).toLowerCase()).filter(validAgent))]:[channel];if(!targets.length)targets=[project?project.lead:'alex'];if(runtime.queue.length+targets.length>100)throw new Error('Coada este plină.');store.message('mario',channel,message);for(const id of targets)runtime.enqueue({agent:id,text:message,channel,depth:0,project:project?.id||null});notify();return json(res,202,{ok:true});}
 if(path==='/api/tasks'){if(!validAgent(b.agent))throw new Error('Agent invalid.');const t=store.task(b.agent,text(b.title,2000));runtime.enqueue({agent:t.agent,text:t.title,taskId:t.id,channel:t.agent,depth:0});notify();return json(res,201,t);}
 if(path==='/api/tasks/retry'){const t=store.db.prepare('SELECT * FROM tasks WHERE id=?').get(b.id);if(!t||!['blocked','cancelled'].includes(t.status))throw new Error('Sarcină indisponibilă pentru reluare.');store.updateTask(t.id,'queued');runtime.enqueue({agent:t.agent,text:t.title,taskId:t.id,channel:t.agent,depth:t.depth});notify();return json(res,200,{ok:true});}
 if(path==='/api/settings'){const old=store.settings();const next={...old};for(const k of ['autonomy','paused'])if(k in b){if(typeof b[k]!=='boolean')throw new Error('Setare invalidă.');next[k]=b[k];}if('social' in b){if(typeof b.social!=='boolean')throw new Error('Setare invalidă.');next.social=b.social;}if('standup' in b){if(typeof b.standup!=='string'||!/^(([01]\d|2[0-3]):[0-5]\d)?$/.test(b.standup))throw new Error('Ora ședinței zilnice este invalidă.');next.standup=b.standup;}for(const [k,min,max]of [['intervalMinutes',5,1440],['dailyRunLimit',1,1000]])if(k in b){if(!Number.isInteger(b[k])||b[k]<min||b[k]>max)throw new Error('Limită invalidă: '+k);next[k]=b[k];}store.set('settings',next);if(next.paused){runtime.controller?.abort();}else{void runtime.pump();}notify();return json(res,200,next);}
 if(path==='/api/agents'){if(!validAgent(b.id)||!providerIds.includes(b.provider))throw new Error('Agent sau furnizor invalid.');if(typeof b.model!=='string'||b.model.length>100)throw new Error('Model invalid.');if(typeof b.enabled!=='boolean')throw new Error('Setare invalidă.');const c=store.get('agent:'+b.id);store.set('agent:'+b.id,{...c,provider:b.provider,model:b.model.trim(),enabled:b.enabled});notify();return json(res,200,{ok:true});}
 if(path==='/api/world'){if(b.ceo){for(const k of ['x','y'])if(!Number.isFinite(b.ceo[k])||b.ceo[k]<0||b.ceo[k]>20)throw new Error('Poziție invalidă.');world.ceo=b.ceo;}if(typeof b.meeting==='boolean'){world.meeting=b.meeting;store.event('meeting','mario',{text:b.meeting?'CEO a convocat echipa la Town Hall.':'Ședința s-a încheiat.'});}notify();return json(res,200,world);}

 if(path==='/api/meeting'){if(typeof b.active!=='boolean')throw new Error('Setare invalidă.');world.meeting=b.active;store.event('meeting','mario',{text:b.active?'Mario a convocat ședința în Town Hall.':'Ședința s-a încheiat.'});if(!b.active&&runtime.active&&['meeting','room','interview'].includes(runtime.active.kind))runtime.controller?.abort();notify();return json(res,200,world);}
 if(path==='/api/meeting/say'){if(!world.meeting)throw new Error('Nu este nicio ședință în desfășurare.');const to=b.to==='all'?'all':text(b.to,40);return json(res,202,runtime.say(to,text(b.text,4000),Array.isArray(b.present)?b.present.filter(x=>typeof x==='string'):null));}
 if(path==='/api/meeting/discuss'){const m=runtime.startMeeting({topic:b.topic,project:b.project||null,participants:Array.isArray(b.participants)?b.participants:null});notify();return json(res,201,m);}
 if(path==='/api/projects'){if(!validAgent(b.lead)||!Array.isArray(b.members)||!b.members.every(validAgent))throw new Error('Echipă invalidă.');const p=store.project(text(b.title,120),text(b.goal,2000),b.lead,b.members);notify();return json(res,201,p);}
 if(path==='/api/projects/status'){if(!store.getProject(b.id)||!['active','paused','done'].includes(b.status))throw new Error('Proiect sau stare invalidă.');store.projectStatus(b.id,b.status);notify();return json(res,200,{ok:true});}
 if(path==='/api/encounter'){return json(res,200,runtime.encounter(b.a,b.b));}
 if(path==='/api/staff/request'){return json(res,202,runtime.proposeCandidate(b.director,typeof b.reason==='string'&&b.reason.trim()?b.reason.trim().slice(0,500):'Mario a cerut ajutor pentru această echipă.'));}
 if(path==='/api/staff/decide'){if(typeof b.yes!=='boolean')throw new Error('Decizie invalidă.');const r=runtime.hire(text(b.id,40),b.yes);notify();return json(res,200,r);}
 if(path==='/api/team'){switchTeam(text(b.team,10));return json(res,200,{team:activeTeam});}
 if(path==='/api/stop'){const s=store.get('settings');store.set('settings',{...s,paused:true,autonomy:false});runtime.stop();store.db.prepare("UPDATE tasks SET status='cancelled' WHERE status='queued'").run();notify();return json(res,200,{ok:true});}
 return json(res,404,{error:'Rută inexistentă.'});
 }
 if(req.method!=='GET')return json(res,405,{error:'Metodă nepermisă.'});
 const relative=path==='/'?'index.html':decodeURIComponent(path).replace(/^\//,'');const file=resolve(root,'public',relative);const containment=relativePath(resolve(root,'public'),file);if(containment.startsWith('..')||isAbsolute(containment)||!existsSync(file))return json(res,404,{error:'Fișier inexistent.'});const types={'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.png':'image/png','.webp':'image/webp','.svg':'image/svg+xml'};res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"});res.end(readFileSync(file));
 }catch(e){json(res,400,{error:e.message});}});
const heartbeat=setInterval(()=>{for(const r of streams)r.write(': heartbeat\n\n');},20000);
server.on('error',e=>{console.error(e.code==='EADDRINUSE'?`Portul ${port} este deja folosit. Probabil orașul rulează deja: deschide http://127.0.0.1:${port}. Altfel, schimbă PORT în .env.`:'Serverul nu a putut porni: '+e.message);process.exit(1);});
server.listen(port,host,()=>console.log(`Mario Agent Town: http://${host}:${port}\nDatele și autentificările rămân pe calculator. Ctrl+C pentru oprire.`));
for(const sig of ['SIGINT','SIGTERM'])process.on(sig,()=>{clearInterval(heartbeat);runtime.close();for(const r of streams)r.end();server.close(()=>{store.close();process.exit(0);});});
