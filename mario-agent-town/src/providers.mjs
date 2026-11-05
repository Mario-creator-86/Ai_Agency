import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {join,delimiter} from 'node:path';
import {homedir} from 'node:os';
export function executable(name){
 const override=process.env[name.toUpperCase()+'_BIN'];if(override)return override;
 for(const p of (process.env.PATH||'').split(delimiter))for(const suffix of process.platform==='win32'?['.exe','']:[''])if(existsSync(join(p,name+suffix)))return join(p,name+suffix);
 // Execute npm JS entry points directly; never pass user prompts to cmd.exe.
 const prefixes=[process.env.APPDATA&&join(process.env.APPDATA,'npm'),...((process.env.PATH||'').split(delimiter))].filter(Boolean);
 const rel=name==='codex'?'@openai/codex/bin/codex.js':'@anthropic-ai/claude-code/cli.js';
 for(const p of prefixes){const candidate=join(p,'node_modules',rel);if(existsSync(candidate))return candidate;}
 const native=join(homedir(),'.local','bin',name+(process.platform==='win32'?'.exe':''));return existsSync(native)?native:null;
}
export function cliArgs(provider,model=''){
 if(model&&!/^[\w:./-]{1,100}$/.test(model))throw new Error('Numele modelului conține caractere nepermise.');
 const args=provider==='codex'?['exec','--json','--ephemeral','--skip-git-repo-check','--sandbox','read-only','--ignore-user-config','-']:['-p','--output-format','json','--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--setting-sources',''];
 if(model)args.push('--model',model);return args;
}
export function subscriptionEnvironment(){const env={...process.env};for(const k of ['OPENAI_API_KEY','CODEX_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL','CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY'])delete env[k];return env;}
export function parseCliOutput(provider,output){
 if(provider==='claude'){const value=JSON.parse(output);if(value.is_error)throw new Error(value.result||'Claude Code a raportat o eroare.');if(typeof value.result!=='string'||!value.result.trim())throw new Error('Claude nu a returnat text.');return value.result;}
 let answer='',failure='';for(const l of output.split('\n')){let e;try{e=JSON.parse(l);}catch{continue;}if(e.type==='item.completed'&&e.item?.type==='agent_message')answer=e.item.text;if(e.type==='turn.failed'||e.type==='error')failure=e.error?.message||e.message||'Codex a raportat o eroare.';}if(failure)throw new Error(failure);if(!answer)throw new Error('Codex nu a returnat un mesaj final.');return answer;
}
async function runCli(provider,model,prompt,cwd,signal){
 const file=executable(provider);if(!file)throw new Error(`${provider} nu este instalat sau nu este în PATH. Vezi README pentru instalare și autentificare.`);
 if(/\.cmd$/i.test(file))throw new Error('Configurează un executabil .exe sau intrarea .js în '+provider.toUpperCase()+'_BIN.');
 const args=cliArgs(provider,model);const command=/\.m?js$/i.test(file)?process.execPath:file;const argv=/\.m?js$/i.test(file)?[file,...args]:args;
 return new Promise((resolve,reject)=>{let stdout='',stderr='',settled=false;const child=spawn(command,argv,{cwd,env:subscriptionEnvironment(),stdio:['pipe','pipe','pipe'],windowsHide:true,signal});const done=(err,value)=>{if(settled)return;settled=true;clearTimeout(timer);err?reject(err):resolve(value);};const timer=setTimeout(()=>{child.kill();done(new Error('Furnizorul a depășit 180 secunde. Verifică loginul și limitele abonamentului.'));},180000);child.on('error',e=>done(e));child.stdout.on('data',b=>{stdout+=b;if(stdout.length>2000000){child.kill();done(new Error('Răspuns prea mare.'));}});child.stderr.on('data',b=>{stderr=(stderr+b).slice(-12000);});child.on('close',code=>{if(code!==0)return done(new Error(`${provider} a ieșit cu codul ${code}. Verifică autentificarea/limitele în terminal. ${stderr.slice(-300)}`));try{done(null,parseCliOutput(provider,stdout));}catch(e){done(e);}});child.stdin.on('error',()=>{});child.stdin.end(prompt);});
}
export async function complete(provider,model,messages,cwd,signal){
 if(provider==='codex'||provider==='claude')return runCli(provider,model,messages.map(m=>`${m.role.toUpperCase()}:\n${m.content}`).join('\n\n'),cwd,signal);
 if(!['ollama','ollama-cloud'].includes(provider))throw new Error('Alege un furnizor real în Setări. Modul Demo nu apelează AI.');
 if(!model)throw new Error('Completează numele unui model Ollama instalat/disponibil în cont.');
 const base=provider==='ollama-cloud'?'https://ollama.com':(process.env.OLLAMA_URL||'http://127.0.0.1:11434');
 if(provider==='ollama-cloud'&&!process.env.OLLAMA_API_KEY)throw new Error('Adaugă OLLAMA_API_KEY în .env sau folosește Ollama local autentificat pentru modelele cloud.');
 const response=await fetch(base+'/api/chat',{method:'POST',headers:{'Content-Type':'application/json',...(provider==='ollama-cloud'?{Authorization:'Bearer '+process.env.OLLAMA_API_KEY}:{})},body:JSON.stringify({model,messages,stream:false,format:'json'}),signal:AbortSignal.any([signal,AbortSignal.timeout(180000)])});
 if(!response.ok)throw new Error(`Ollama HTTP ${response.status}. Verifică modelul, autentificarea și cota.`);const json=await response.json();if(!json.message?.content)throw new Error('Ollama nu a returnat text.');return json.message.content;
}
export async function diagnostics(){let local={available:false,models:[]};try{const r=await fetch((process.env.OLLAMA_URL||'http://127.0.0.1:11434')+'/api/tags',{signal:AbortSignal.timeout(2000)});if(r.ok){const j=await r.json();local={available:true,models:(j.models||[]).map(x=>x.name)};}}catch{}return {codex:{installed:!!executable('codex'),authentication:'Se verifică prin codex login status în terminalul tău.'},claude:{installed:!!executable('claude'),authentication:'Autentificare în aplicația oficială Claude Code.'},ollama:local,'ollama-cloud':{configured:!!process.env.OLLAMA_API_KEY},integrations:{youtube:false,gmail:false,calendar:false,videoRenderer:false}};}
