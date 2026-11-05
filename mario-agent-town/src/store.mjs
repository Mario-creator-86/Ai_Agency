import {DatabaseSync} from 'node:sqlite';
import {mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {agents,initialSettings} from './agents.mjs';
export class Store{
 constructor(directory){mkdirSync(directory,{recursive:true});this.db=new DatabaseSync(join(directory,'town.sqlite'));this.db.exec(`PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,at TEXT NOT NULL,type TEXT NOT NULL,agent TEXT,body TEXT NOT NULL); CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,agent TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,result TEXT NOT NULL DEFAULT '',parent TEXT,depth INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,at TEXT NOT NULL,sender TEXT NOT NULL,channel TEXT NOT NULL,text TEXT NOT NULL); CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,agent TEXT NOT NULL,at TEXT NOT NULL,text TEXT NOT NULL); CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,agent TEXT NOT NULL,at TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL); CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,at TEXT NOT NULL,agent TEXT NOT NULL,provider TEXT NOT NULL,status TEXT NOT NULL);`);if(!this.get('settings'))this.set('settings',initialSettings);for(const a of agents)if(!this.get('agent:'+a.id))this.set('agent:'+a.id,{provider:'demo',model:'',enabled:true,lastAuto:0});this.db.prepare("UPDATE tasks SET status='queued' WHERE status='running'").run();this.db.prepare("UPDATE runs SET status='interrupted' WHERE status='running'").run();if(!this.messages().length)this.message('system','townhall','Bine ai venit, Mario. Orașul este pregătit. Conectează un furnizor în Setări pentru conversații AI reale. Mișcarea personajelor nu consumă abonamentul.');}
 get(k){const r=this.db.prepare('SELECT value FROM kv WHERE key=?').get(k);return r?JSON.parse(r.value):null;}
 set(k,v){this.db.prepare('INSERT OR REPLACE INTO kv VALUES (?,?)').run(k,JSON.stringify(v));return v;}
 event(type,agent,body){const r={id:randomUUID(),at:new Date().toISOString(),type,agent,body};this.db.prepare('INSERT INTO events VALUES (?,?,?,?,?)').run(r.id,r.at,type,agent,JSON.stringify(body));return r;}
 events(){return this.db.prepare('SELECT * FROM events ORDER BY rowid DESC LIMIT 60').all().map(e=>({...e,body:JSON.parse(e.body)}));}
 message(sender,channel,text){const r={id:randomUUID(),at:new Date().toISOString(),sender,channel,text};this.db.prepare('INSERT INTO messages VALUES (?,?,?,?,?)').run(r.id,r.at,sender,channel,text);return r;}
 messages(){return this.db.prepare('SELECT * FROM (SELECT rowid,* FROM messages ORDER BY rowid DESC LIMIT 300) ORDER BY rowid').all();}
 task(agent,title,parent=null,depth=0){const t={id:randomUUID(),agent,title,status:'queued',created:new Date().toISOString(),updated:new Date().toISOString(),result:'',parent,depth};this.db.prepare('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)').run(...Object.values(t));this.event('task',agent,{text:'Sarcină nouă: '+title});return t;}
 updateTask(id,status,result=''){this.db.prepare('UPDATE tasks SET status=?,result=?,updated=? WHERE id=?').run(status,result,new Date().toISOString(),id);}
 tasks(){return this.db.prepare('SELECT * FROM tasks ORDER BY created DESC LIMIT 200').all();}
 memory(agent,text){this.db.prepare('INSERT INTO memories VALUES (?,?,?,?)').run(randomUUID(),agent,new Date().toISOString(),text);}
 memories(agent){return this.db.prepare('SELECT text FROM memories WHERE agent=? ORDER BY rowid DESC LIMIT 20').all(agent).map(x=>x.text);}
 artifact(agent,title,content){const r={id:randomUUID(),agent,at:new Date().toISOString(),title,content};this.db.prepare('INSERT INTO artifacts VALUES (?,?,?,?,?)').run(...Object.values(r));return r;}
 artifacts(){return this.db.prepare('SELECT id,agent,at,title FROM artifacts ORDER BY rowid DESC LIMIT 100').all();}
 run(agent,provider){const id=randomUUID();this.db.prepare('INSERT INTO runs VALUES (?,?,?,?,?)').run(id,new Date().toISOString(),agent,provider,'running');return id;}
 endRun(id,status){this.db.prepare('UPDATE runs SET status=? WHERE id=?').run(status,id);}
 runsToday(){const start=new Date();start.setHours(0,0,0,0);return Number(this.db.prepare('SELECT COUNT(*) n FROM runs WHERE at>=?').get(start.toISOString()).n);}
 snapshot(){return {agents:agents.map(a=>({...a,...this.get('agent:'+a.id)})),settings:this.get('settings'),tasks:this.tasks(),messages:this.messages(),events:this.events(),artifacts:this.artifacts(),runsToday:this.runsToday()};}
 close(){this.db.close();}
}
