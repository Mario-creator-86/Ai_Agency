// Sends one tiny request to each AI brain through the town's own adapters and writes the result.
import {complete,executable} from './src/providers.mjs';
import {writeFileSync,mkdirSync} from 'node:fs';
const out=[];const log=s=>{out.push(s);console.log(s);};
const msgs=[{role:'system',content:'Raspunde doar JSON: {"reply":"..."}'},{role:'user',content:'Spune "salut" intr-un cuvant.'}];
mkdirSync('workspaces/_test',{recursive:true});
for(const [p,model] of [['claude',''],['codex',''],['ollama','gpt-oss:20b-cloud']]){
 const t=Date.now();log(`[${p}] executabil: ${p==='ollama'?'http://127.0.0.1:11434':executable(p)}`);
 try{const r=await complete(p,model,msgs,'workspaces/_test',new AbortController().signal);log(`[${p}] OK in ${Date.now()-t} ms: ${r.slice(0,200)}`);}
 catch(e){log(`[${p}] EROARE in ${Date.now()-t} ms: ${e.message.slice(0,600)}`);}
}
writeFileSync('test-creiere-raport.txt',out.join('\r\n'));
