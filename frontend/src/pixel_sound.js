import { PRESENTATION as S } from './pixel_presentation.js';

/** Original synthesis, with no sample download or copied soundtrack. */
export function foley(context, destination, kind, pan = 0, gain = .025) {
  if (['key','step','paper','chair'].includes(kind)) {
    const at=context.currentTime,source=context.createBufferSource(),envelope=context.createGain(),filter=context.createBiquadFilter(),stereo=context.createStereoPanner();
    const duration=kind==='paper'?.16:kind==='chair'?.23:.045;
    const buffer=context.createBuffer(1,Math.ceil(context.sampleRate*duration),context.sampleRate),data=buffer.getChannelData(0);
    let seed=6109;for(let i=0;i<data.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;data[i]=(seed/2147483648-1)*Math.exp(-i/data.length*5);}
    source.buffer=buffer;filter.type='lowpass';filter.frequency.value=kind==='paper'?3200:kind==='chair'?290:kind==='step'?500:1900;
    stereo.pan.value=Math.max(-1,Math.min(1,pan));envelope.gain.value=gain;
    source.connect(filter).connect(envelope).connect(stereo).connect(destination);source.start(at);return source;
  }
  const at=context.currentTime, oscillator=context.createOscillator(), envelope=context.createGain();
  const stereo=context.createStereoPanner();stereo.pan.value=Math.max(-1,Math.min(1,pan));
  const cup=kind==='cup', paper=kind==='paper';
  oscillator.type=paper?'sawtooth':cup?'sine':'triangle';
  oscillator.frequency.setValueAtTime(cup?1450:kind==='bird'?1800:610,at);
  oscillator.frequency.exponentialRampToValueAtTime(cup?1100:kind==='bird'?2600:90,at+.075);
  envelope.gain.setValueAtTime(.00001,at);envelope.gain.exponentialRampToValueAtTime(gain,at+.004);
  envelope.gain.exponentialRampToValueAtTime(.00001,at+(cup?.35:.09));
  oscillator.connect(envelope).connect(stereo).connect(destination);
  oscillator.start(at);oscillator.stop(at+(cup?.4:.1));
  return oscillator;
}

export class StudioAudio {
  constructor() {
    this.context=null;this.master=null;this.air=null;this.airGain=null;this.rain=null;this.rainGain=null;
    this.sources=new Set();this.last=new Map();this.previous=new Map();this.enabled=false;this.unlocked=false;this.events=0;
    this.volume=S.sound.default_volume;
    try{this.enabled=localStorage.getItem('amn-studio-sound')==='on';
      const saved=localStorage.getItem('amn-studio-volume'),v=Number(saved);if(saved!==null&&v>=0&&v<=1)this.volume=v;}catch{}
  }
  async unlock() {
    try {
      if(!this.context){this.context=new AudioContext();this.master=this.context.createGain();this.master.connect(this.context.destination);
        const noise=this.context.createBuffer(1,this.context.sampleRate*2,this.context.sampleRate),data=noise.getChannelData(0);
        let seed=1234567;for(let i=0;i<data.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;data[i]=seed/2147483648-1;}
        const loop=(frequency)=>{const source=this.context.createBufferSource(),filter=this.context.createBiquadFilter(),g=this.context.createGain();
          source.buffer=noise;source.loop=true;filter.type='lowpass';filter.frequency.value=frequency;g.gain.value=0;
          source.connect(filter).connect(g).connect(this.master);source.start();return {source,g};};
        const air=loop(360),rain=loop(2400);this.air=air.source;this.airGain=air.g;this.rain=rain.source;this.rainGain=rain.g;
      }
      await this.context.resume();this.unlocked=true;this.setVolume(this.volume);
    }catch{this.unlocked=false;}
    return this.unlocked;
  }
  setVolume(value){this.volume=Math.max(0,Math.min(1,Number(value)||0));
    if(this.master)this.master.gain.setTargetAtTime(this.volume,this.context.currentTime,.06);
    try{localStorage.setItem('amn-studio-volume',String(this.volume));}catch{}
  }
  async toggle(){this.enabled=this.enabled&&!this.unlocked?true:!this.enabled;try{localStorage.setItem('amn-studio-sound',this.enabled?'on':'off');}catch{}
    if(this.enabled)await this.unlock();else this.pause();return this.enabled&&this.unlocked;
  }
  pause(){for(const source of this.sources){try{source.stop();}catch{}}this.sources.clear();
    if(this.context?.state==='running')this.context.suspend().catch(()=>{});}
  update(active,weather,people,physics,elapsed,street=null){
    if(!active||!this.enabled||!this.unlocked){this.pause();return;}
    if(this.context.state==='suspended'){this.context.resume().catch(()=>{});return;}
    const at=this.context.currentTime,wind=weather.available?(weather.windKph||0):0;
    this.airGain.gain.setTargetAtTime(S.sound.air_gain*Math.min(1,wind/30),at,.7);
    this.rainGain.gain.setTargetAtTime(weather.available&&['rain','drizzle','storm'].includes(weather.condition)?S.sound.rain_gain:0,at,.7);
    const emit=(id,kind,slot,x)=>{
      if(this.last.get(id)===slot||this.sources.size>=S.sound.max_sources)return;
      this.last.set(id,slot);const node=foley(this.context,this.master,kind,(x/960-.5)*1.7,kind==='key'?S.sound.key_gain:S.sound.foley_gain);
      this.sources.add(node);node.onended=()=>{this.sources.delete(node);node.disconnect();};this.events++;
    };
    for(const {p,motion} of people){if(!motion.authorized||!motion.animate)continue;
      const previous=this.previous.get(p.id);
      if(['type','write'].includes(motion.action))emit(p.id+':key','key',Math.floor((elapsed+p.x*11)/S.sound.keyboard_interval_ms),p.x);
      else if(motion.action==='coffee'&&motion.progress>.9&&(previous?.action!=='coffee'||previous.progress<=.9))emit(p.id+':cup','cup',elapsed,p.x);
      else if(motion.action==='relax'&&previous?.action!=='relax')emit(p.id+':chair','chair',elapsed,p.x);
      this.previous.set(p.id,{action:motion.action,progress:motion.progress});
    }
    if(street?.people)for(const person of street.people)if(person.x>0&&person.x<960)
      emit('street:'+person.id,'step',Math.floor((elapsed+person.id*133)/420),person.x);
    if(street?.bicycle?.x>480&&street.bicycle.x<491)emit('bike','cup',Math.floor(elapsed/15000),street.bicycle.x);
    if(street?.birds?.length)emit('bird','bird',Math.floor(elapsed/37000),street.birds[0]?.x||100);
    for(const paper of physics.papers)if(paper.collisions>0)emit(paper.id+':paper','paper',paper.cycle+':'+paper.collisions,paper.x);
  }
  status(){return {enabled:this.enabled,unlocked:this.unlocked,state:this.context?.state||'locked',sources:this.sources.size,events:this.events,volume:this.volume};}
}
