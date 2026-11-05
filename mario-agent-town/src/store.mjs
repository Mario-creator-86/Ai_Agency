import {DatabaseSync} from 'node:sqlite';
import {mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {agents,initialSettings,agentsFor,teamInfo,TEAMS} from './agents.mjs';
export class Store{
 constructor(directory,team='v1'){this.team=TEAMS[team]?team:'v1';this.charter=TEAMS[this.team].charter;mkdirSync(directory,{recursive:true});this.db=new DatabaseSync(join(directory,'town.sqlite'));this.db.exec(`PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,at TEXT NOT NULL,type TEXT NOT NULL,agent TEXT,body TEXT NOT NULL); CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,agent TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,result TEXT NOT NULL DEFAULT '',parent TEXT,depth INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,at TEXT NOT NULL,sender TEXT NOT NULL,channel TEXT NOT NULL,text TEXT NOT NULL); CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,agent TEXT NOT NULL,at TEXT NOT NULL,text TEXT NOT NULL); CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,agent TEXT NOT NULL,at TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL); CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,at TEXT NOT NULL,agent TEXT NOT NULL,provider TEXT NOT NULL,status TEXT NOT NULL);`);if(!this.get('settings'))this.set('settings',initialSettings);for(const a of agentsFor(this.team))if(!this.get('agent:'+a.id))this.set('agent:'+a.id,{provider:'demo',model:'',enabled:true,lastAuto:0});this.migrate();this.db.prepare("UPDATE tasks SET status='queued' WHERE status='running'").run();this.db.prepare("UPDATE runs SET status='interrupted' WHERE status='running'").run();if(!this.messages().length)this.message('system','townhall',(this.team==='v1'?'':`${teamInfo(this.team).label}: aceleași personaje, alte meserii, conversații și memorie separate. `)+'Bine ai venit, Mario. Orașul este pregătit. Conectează un furnizor în Setări pentru conversații AI reale. Mișcarea personajelor nu consumă abonamentul.');}
 settings(){return {...initialSettings,...this.get('settings')};}
 get(k){const r=this.db.prepare('SELECT value FROM kv WHERE key=?').get(k);return r?JSON.parse(r.value):null;}
 set(k,v){this.db.prepare('INSERT OR REPLACE INTO kv VALUES (?,?)').run(k,JSON.stringify(v));return v;}
 event(type,agent,body){const r={id:randomUUID(),at:new Date().toISOString(),type,agent,body};this.db.prepare('INSERT INTO events VALUES (?,?,?,?,?)').run(r.id,r.at,type,agent,JSON.stringify(body));return r;}
 events(){return this.db.prepare('SELECT * FROM events ORDER BY rowid DESC LIMIT 60').all().map(e=>({...e,body:JSON.parse(e.body)}));}
 message(sender,channel,text){const r={id:randomUUID(),at:new Date().toISOString(),sender,channel,text};this.db.prepare('INSERT INTO messages VALUES (?,?,?,?,?)').run(r.id,r.at,sender,channel,text);return r;}
 messages(){return this.db.prepare('SELECT * FROM (SELECT rowid,* FROM messages ORDER BY rowid DESC LIMIT 300) ORDER BY rowid').all();}
 task(agent,title,parent=null,depth=0,project=null){const t={id:randomUUID(),agent,title,status:'queued',created:new Date().toISOString(),updated:new Date().toISOString(),result:'',parent,depth,project};this.db.prepare('INSERT INTO tasks(id,agent,title,status,created,updated,result,parent,depth,project) VALUES (?,?,?,?,?,?,?,?,?,?)').run(...Object.values(t));this.event('task',agent,{text:'Sarcină nouă: '+title});return t;}
 updateTask(id,status,result=''){this.db.prepare('UPDATE tasks SET status=?,result=?,updated=? WHERE id=?').run(status,result,new Date().toISOString(),id);}
 tasks(){return this.db.prepare('SELECT * FROM tasks ORDER BY created DESC LIMIT 200').all();}
 memory(agent,text){this.db.prepare('INSERT INTO memories VALUES (?,?,?,?)').run(randomUUID(),agent,new Date().toISOString(),text);}
 memories(agent){return this.db.prepare('SELECT text FROM memories WHERE agent=? ORDER BY rowid DESC LIMIT 20').all(agent).map(x=>x.text);}
 artifact(agent,title,content,project=null){const r={id:randomUUID(),agent,at:new Date().toISOString(),title,content,project};this.db.prepare('INSERT INTO artifacts(id,agent,at,title,content,project) VALUES (?,?,?,?,?,?)').run(...Object.values(r));return r;}
 artifacts(){return this.db.prepare('SELECT id,agent,at,title,project FROM artifacts ORDER BY rowid DESC LIMIT 100').all();}
 run(agent,provider){const id=randomUUID();this.db.prepare('INSERT INTO runs VALUES (?,?,?,?,?)').run(id,new Date().toISOString(),agent,provider,'running');return id;}
 endRun(id,status){this.db.prepare('UPDATE runs SET status=? WHERE id=?').run(status,id);}
 runsToday(){const start=new Date();start.setHours(0,0,0,0);return Number(this.db.prepare('SELECT COUNT(*) n FROM runs WHERE at>=?').get(start.toISOString()).n);}
 members(){return agentsFor(this.team);}
 snapshot(){return {team:teamInfo(this.team),teams:Object.values(TEAMS).map(t=>({id:t.id,label:t.label})),agents:[...agentsFor(this.team),...this.hiredStaff()].map(a=>({...a,...this.get('agent:'+a.id)})),settings:this.settings(),projects:this.projects(),meetings:this.meetings(),staff:this.staff(),tasks:this.tasks(),messages:this.messages(),events:this.events(),artifacts:this.artifacts(),runsToday:this.runsToday()};}

 // v3: shared projects, real meetings and agent-to-agent social history.
 migrate(){
  const columns=table=>this.db.prepare(`PRAGMA table_info(${table})`).all().map(c=>c.name);
  if(!columns('tasks').includes('project'))this.db.exec('ALTER TABLE tasks ADD COLUMN project TEXT');
  if(!columns('artifacts').includes('project'))this.db.exec('ALTER TABLE artifacts ADD COLUMN project TEXT');
  this.db.exec(`CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,goal TEXT NOT NULL,lead TEXT NOT NULL,members TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS paper_trades(id TEXT PRIMARY KEY,agent TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,qty REAL NOT NULL,entry REAL NOT NULL,entry_at TEXT NOT NULL,entry_source TEXT NOT NULL,bench_entry REAL,exit REAL,exit_at TEXT,status TEXT NOT NULL,note TEXT NOT NULL DEFAULT '');
   CREATE TABLE IF NOT EXISTS staff(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,director TEXT NOT NULL,status TEXT NOT NULL,profile TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS meetings(id TEXT PRIMARY KEY,topic TEXT NOT NULL,project TEXT,chair TEXT NOT NULL,participants TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,transcript TEXT NOT NULL DEFAULT '[]',summary TEXT NOT NULL DEFAULT '',artifact TEXT);`);
  // A meeting cannot resume mid-discussion after a crash; mark it honestly instead of replaying it.
  this.db.prepare("UPDATE meetings SET status='interrupted',updated=? WHERE status IN ('queued','running')").run(new Date().toISOString());
 }
 project(title,goal,lead,members){const now=new Date().toISOString();const p={id:randomUUID(),title,goal,lead,members:[...new Set([lead,...members])],status:'active',created:now,updated:now};this.db.prepare('INSERT INTO projects(id,title,goal,lead,members,status,created,updated) VALUES (?,?,?,?,?,?,?,?)').run(p.id,title,goal,lead,JSON.stringify(p.members),p.status,now,now);this.event('project',lead,{text:'Proiect nou: '+title,id:p.id});return p;}
 getProject(id){const p=id&&this.db.prepare('SELECT * FROM projects WHERE id=?').get(id);return p?{...p,members:JSON.parse(p.members)}:null;}
 projects(){return this.db.prepare('SELECT * FROM projects ORDER BY created DESC LIMIT 50').all().map(p=>({...p,members:JSON.parse(p.members)}));}
 projectStatus(id,status){this.db.prepare('UPDATE projects SET status=?,updated=? WHERE id=?').run(status,new Date().toISOString(),id);}
 projectArtifacts(id){return this.db.prepare('SELECT id,agent,at,title FROM artifacts WHERE project=? ORDER BY rowid DESC LIMIT 20').all(id);}
 meeting({topic,project=null,chair,participants}){const now=new Date().toISOString();const m={id:randomUUID(),topic,project,chair,participants,status:'queued',created:now,updated:now,transcript:[],summary:'',artifact:null};this.db.prepare('INSERT INTO meetings(id,topic,project,chair,participants,status,created,updated) VALUES (?,?,?,?,?,?,?,?)').run(m.id,topic,project,chair,JSON.stringify(participants),'queued',now,now);return m;}
 meetingUpdate(id,fields){const allowed=['status','transcript','summary','artifact'];const keys=Object.keys(fields).filter(k=>allowed.includes(k));if(!keys.length)return;this.db.prepare(`UPDATE meetings SET ${keys.map(k=>k+'=?').join(',')},updated=? WHERE id=?`).run(...keys.map(k=>k==='transcript'?JSON.stringify(fields[k]):fields[k]),new Date().toISOString(),id);}
 meetings(limit=12){return this.db.prepare('SELECT * FROM meetings ORDER BY created DESC LIMIT ?').all(limit).map(m=>({...m,participants:JSON.parse(m.participants),transcript:JSON.parse(m.transcript)}));}
 lastSpoke(agent){return this.db.prepare('SELECT at FROM messages WHERE sender=? ORDER BY rowid DESC LIMIT 1').get(agent)?.at||null;}
 pairLast(a,b){return this.get('social')?.[[a,b].sort().join('|')]||0;}
 touchPair(a,b){const s=this.get('social')||{};s[[a,b].sort().join('|')]=Date.now();this.set('social',s);}

 candidate({name,role,director,profile}){const now=new Date().toISOString();const id='w-'+randomUUID().slice(0,8);this.db.prepare('INSERT INTO staff(id,name,role,director,status,profile,created,updated) VALUES (?,?,?,?,?,?,?,?)').run(id,name,role,director,'candidate',JSON.stringify(profile),now,now);this.event('hiring','alex',{text:`Candidat propus pentru ${director}: ${name}`,id});return this.staffMember(id);}
 staffMember(id){const r=this.db.prepare('SELECT * FROM staff WHERE id=?').get(id);return r?{...r,profile:JSON.parse(r.profile)}:null;}
 staff(){return this.db.prepare('SELECT * FROM staff ORDER BY created DESC LIMIT 60').all().map(r=>({...r,profile:JSON.parse(r.profile)}));}
 staffStatus(id,status){this.db.prepare('UPDATE staff SET status=?,updated=? WHERE id=?').run(status,new Date().toISOString(),id);}
 // Hired staff become agents: same tools and memory, reporting to their director.
 hiredStaff(){return this.staff().filter(w=>w.status==='hired').map(w=>({id:w.id,name:w.name,role:`${w.role} · echipa ${w.director}`,director:w.director,house:'',color:'#f2c230',icon:'vest',staff:true,sheet:w.profile.sheet,personality:w.profile.personality||'Harnic, atent, învață repede.',mission:`Lucrezi în echipa directorului ${w.director}, ca ${w.role}. ${w.profile.mission||''} Raportezi directorului tău și lui Mario. Nu inventezi acces, rezultate sau date.`,deliverable:w.profile.deliverable||'Livrabile cerute de director.',kpi:'Sarcini încheiate și verificate de director.',goal:w.profile.firstTask||'Întreabă-ți directorul ce are mai urgent și începe.'}));}

 paperOpen(t){const r={id:randomUUID(),...t,status:'open'};this.db.prepare('INSERT INTO paper_trades(id,agent,symbol,side,qty,entry,entry_at,entry_source,bench_entry,status,note) VALUES (?,?,?,?,?,?,?,?,?,?,?)').run(r.id,r.agent,r.symbol,r.side,r.qty,r.entry,r.entry_at,r.entry_source,r.bench_entry??null,'open',r.note||'');return r;}
 paperClose(id,price){const t=this.db.prepare("SELECT * FROM paper_trades WHERE id=? AND status='open'").get(id);if(!t)return null;this.db.prepare("UPDATE paper_trades SET status='closed',exit=?,exit_at=? WHERE id=?").run(price,new Date().toISOString(),id);return {...t,exit:price,status:'closed'};}
 paperTrades(){return this.db.prepare('SELECT * FROM paper_trades ORDER BY entry_at DESC LIMIT 200').all();}
 close(){this.db.close();}
}
