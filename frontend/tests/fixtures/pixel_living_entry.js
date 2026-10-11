import {OfficeEngine} from '../../src/pixel_office.js';
import {ACTORS,seatedPhysicsStatus} from '../../src/pixel_actor_atlas.js';
import {PRESENTATION} from '../../src/pixel_presentation.js';
import {PIXEL_LAYOUT} from '../../src/pixel_desks.js';
import {foley} from '../../src/pixel_sound.js';
import bible from './pixel_actors_bible.json' with {type:'json'};
export {OfficeEngine,ACTORS,PRESENTATION,PIXEL_LAYOUT,foley,seatedPhysicsStatus};

export async function mountFixture(){
 const engine=new OfficeEngine(document.querySelector('canvas'),{parked:true,dataLive:()=>true,reducedMotion:()=>false,
   fetchMedia:async()=>new Blob([await (await fetch('/fixture.mp4')).arrayBuffer()],{type:'video/mp4'})});
 await engine.ready;engine.schedule=()=>{};engine.parked=false;
 engine.setCharacterBible(bible);
 const roles=['Director','LeadResearcher','FactChecker','ScriptWriter','VoiceArtist','VideoEditor','Publisher','Accountant'];
 const agents=ACTORS.staff.map((person,i)=>({id:person.employee_id,display_name:bible.find(c=>c.employee_id===person.employee_id).canonical_name,
   role_name:roles[i],pixel_slot:PIXEL_LAYOUT.stations.findIndex(s=>s.role===roles[i]),runtime_state:'IDLE',lifecycle:'ACTIVE',version:1}));
 engine.setAgents(agents);
 engine.weather.state={available:true,condition:'partly_cloudy',windKph:18,temperatureC:22,intensity:.2,cloudCover:.5};
 engine.weatherReceivedAt=Date.now();engine.weatherObservedUtc=new Date().toISOString();
 let time=0;
 const setMode=(mode='IDLE')=>{
   engine.setAgents(agents.map(a=>({...a,runtime_state:mode,version:2})));
   engine.presentation=new Map(agents.map((a,i)=>[a.id,{agent_id:a.id,lifecycle:'ACTIVE',runtime_state:mode,version:2,
     cycle:PRESENTATION.cycles[mode]||[],phase_ms:i*7301,monitor:'on'}]));
   engine.presentationReceived=Date.now();engine.presentationAt=0;
 };
 setMode();engine.draw(0);
 window.__livingFixture={engine,setMode,physics:seatedPhysicsStatus};
 window.render_game_to_text=()=>JSON.stringify(engine.diagnostics());
 window.advanceTime=async ms=>{const end=time+ms;while(time<end){time=Math.min(end,time+PRESENTATION.max_catchup_ms);engine.lifeElapsed=time;engine.lifeFrameAt=null;engine.draw(time);}return engine.diagnostics();};
 return engine;
}
