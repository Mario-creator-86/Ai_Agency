import { PRESENTATION as S } from './pixel_presentation.js';
import AUDIO from './ui_audio.json' with { type: 'json' };

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

/** Only committed live events can produce a cue. Replay, stale news and failed runs never sound like success. */
export function audioCue(event, live, now = Date.now()) {
  const at = Date.parse(event?.timestamp || '');
  if (!live || !event?.event_id || !Number.isFinite(at) || Math.abs(now - at) > AUDIO.max_event_age_ms) return null;
  const kind = event.event_type, status = event.payload?.status;
  if (kind === 'agent.run_completed') return status === 'SUCCEEDED' ? 'task' : ['FAILED', 'ABORTED'].includes(status) ? 'error' : null;
  if (['publishing.video_published', 'publishing.reconciled_published'].includes(kind)) return 'project';
  if (kind === 'media.render_failed') return 'error';
  if (kind === 'media.qc_evaluated' && status === 'FAILED') return 'warning';
  if (kind === 'governance.approval_requested') return 'notification';
  if (kind === 'agent.message_posted' && event.payload?.to_agent_id === null) return 'notification';
  return null;
}

export class StudioAudio {
  constructor() {
    this.context=null;this.master=null;this.air=null;this.airGain=null;this.rain=null;this.rainGain=null;
    this.sources=new Set();this.last=new Map();this.previous=new Map();this.enabled=false;this.unlocked=false;this.events=0;
    this.buffers=new Map();this.loadErrors=[];this.loading=null;this.seen=new Set();this.pending=null;this.cueTimer=0;this.lastCue=-Infinity;this.lastKey=-Infinity;this.variant=0;
    this.volume=S.sound.default_volume;this.onChange=()=>{};
    try{this.enabled=localStorage.getItem('amn-studio-sound')==='on';
      const saved=localStorage.getItem('amn-studio-volume'),v=Number(saved);if(saved!==null&&v>0&&v<=1)this.volume=v;}catch{}
    this.gesture=()=>{if(this.enabled&&!this.unlocked)void this.unlock();};
    document.addEventListener('pointerdown',this.gesture,{passive:true});document.addEventListener('keydown',this.gesture);
    document.addEventListener('visibilitychange',()=>{if(document.hidden)this.pause();});
    window.addEventListener('storage',event=>{if(event.key==='amn-studio-sound'){this.enabled=event.newValue==='on';if(!this.enabled)this.pause();this.applyMute();this.onChange();}});
    this.mediaObserver=new MutationObserver(records=>{for(const record of records)for(const node of Array.from(record.addedNodes))if(node instanceof Element){if(node.matches('audio,video,iframe'))this.muteNode(node);node.querySelectorAll('audio,video,iframe').forEach(el=>this.muteNode(el));}});
    this.mediaObserver.observe(document.body,{subtree:true,childList:true});this.applyMute();
  }
  async loadSamples() {
    if(this.loading)return this.loading;
    this.loading=Promise.all(Object.values(AUDIO.sounds).flatMap(spec=>spec.files).map(async file=>{
      try{const response=await fetch(AUDIO.base+file);if(!response.ok)throw Error(String(response.status));
        const buffer=await this.context.decodeAudioData(await response.arrayBuffer());
        let peak=0;for(let channel=0;channel<buffer.numberOfChannels;channel++){const data=buffer.getChannelData(channel);for(const sample of data)peak=Math.max(peak,Math.abs(sample));}
        if(peak>0)for(let channel=0;channel<buffer.numberOfChannels;channel++){const data=buffer.getChannelData(channel);for(let i=0;i<data.length;i++)data[i]*=.7/peak;}
        this.buffers.set(file,buffer);
      }catch{this.loadErrors.push(file);}
    }));
    return this.loading;
  }
  async unlock() {
    try {
      if(!this.context){this.context=new AudioContext();this.master=this.context.createGain();this.master.gain.value=0;this.master.connect(this.context.destination);
        const noise=this.context.createBuffer(1,this.context.sampleRate*2,this.context.sampleRate),data=noise.getChannelData(0);
        let seed=1234567;for(let i=0;i<data.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;data[i]=seed/2147483648-1;}
        const loop=(frequency)=>{const source=this.context.createBufferSource(),filter=this.context.createBiquadFilter(),g=this.context.createGain();
          source.buffer=noise;source.loop=true;filter.type='lowpass';filter.frequency.value=frequency;g.gain.value=0;
          source.connect(filter).connect(g).connect(this.master);source.start();return {source,g};};
        const air=loop(360),rain=loop(2400);this.air=air.source;this.airGain=air.g;this.rain=rain.source;this.rainGain=rain.g;
      }
      await this.context.resume();this.unlocked=this.context.state==='running';
      if(!this.enabled){this.pause();return false;}
      this.setVolume(this.volume);void this.loadSamples();
    }catch{this.unlocked=false;}
    this.applyMute();this.onChange();return this.unlocked;
  }
  setVolume(value){this.volume=Math.max(0,Math.min(1,Number(value)||0));
    if(this.master)this.master.gain.setTargetAtTime(this.enabled?this.volume:0,this.context.currentTime,.06);
  }
  async toggle(){this.enabled=!this.enabled;try{localStorage.setItem('amn-studio-sound',this.enabled?'on':'off');}catch{}
    if(this.enabled)await this.unlock();else this.pause();this.applyMute();this.onChange();return this.enabled;
  }
  muteNode(node){
    const muted=!this.enabled;
    if(node instanceof HTMLMediaElement)node.muted=muted;
    else if(node instanceof HTMLIFrameElement){try{const url=new URL(node.src);if(url.hostname==='www.youtube-nocookie.com')node.contentWindow?.postMessage(JSON.stringify({event:'command',func:muted?'mute':'unMute',args:[]}),url.origin);}catch{}}
  }
  applyMute(){document.body.dataset.uiSound=this.enabled?'on':'off';document.querySelectorAll('audio,video,iframe').forEach(node=>this.muteNode(node));}
  pause(){window.clearTimeout(this.cueTimer);this.cueTimer=0;this.pending=null;
    for(const source of this.sources){try{source.stop();}catch{}}this.sources.clear();
    if(this.master){this.master.gain.cancelScheduledValues(0);this.master.gain.value=0;}
    if(this.context?.state==='running')this.context.suspend().catch(()=>{});
  }
  /** One notification wins a burst. The others are dropped, never queued for a later avalanche. */
  onEvent(event,live){
    const kind=audioCue(event,live);if(!kind||this.seen.has(event.event_id))return;
    this.seen.add(event.event_id);if(this.seen.size>1000)this.seen.delete(this.seen.values().next().value);
    if(!this.enabled||!this.unlocked||document.hidden)return;
    if(!this.pending||AUDIO.sounds[kind].priority>AUDIO.sounds[this.pending].priority)this.pending=kind;
    if(this.cueTimer)return;
    this.cueTimer=window.setTimeout(()=>{const cue=this.pending;this.pending=null;this.cueTimer=0;if(cue)this.playCue(cue);},AUDIO.coalesce_ms);
  }
  playCue(kind){
    const now=performance.now(),spec=AUDIO.sounds[kind];
    if(!spec||!this.enabled||!this.unlocked||document.hidden||this.context.state!=='running'||now-this.lastCue<AUDIO.minimum_gap_ms||now-(this.last.get('cue:'+kind)??-Infinity)<spec.cooldown_ms)return false;
    const buffer=this.buffers.get(spec.files[0]);if(!buffer)return false;
    // An alert gets a clear space in the mix; typing does not compete with it.
    for(const source of this.sources){try{source.stop();}catch{}}this.sources.clear();
    this.playBuffer(buffer,spec.gain);this.lastCue=now;this.last.set('cue:'+kind,now);return true;
  }
  playBuffer(buffer,gain,pan=0){
    if(this.sources.size>=AUDIO.max_voices)return;
    const source=this.context.createBufferSource(),level=this.context.createGain(),stereo=this.context.createStereoPanner();
    source.buffer=buffer;level.gain.value=gain;stereo.pan.value=Math.max(-1,Math.min(1,pan));
    source.connect(level).connect(stereo).connect(this.master);this.sources.add(source);
    source.onended=()=>{this.sources.delete(source);source.disconnect();level.disconnect();stereo.disconnect();};source.start();this.events++;
  }
  update(active,weather,people,physics,elapsed,street=null){
    if(!active||!this.enabled||!this.unlocked){this.pause();return;}
    if(this.context.state==='suspended'){this.context.resume().then(()=>{if(this.enabled)this.setVolume(this.volume);else this.pause();}).catch(()=>{});return;}
    const at=this.context.currentTime,wind=weather.available?(weather.windKph||0):0;
    this.airGain.gain.setTargetAtTime(S.sound.air_gain*(.12+Math.min(1,wind/30)*.2),at,.7);
    this.rainGain.gain.setTargetAtTime(weather.available&&['rain','drizzle','storm'].includes(weather.condition)?S.sound.rain_gain*.4:0,at,.7);
    const now=performance.now();
    if(now-this.lastKey<AUDIO.keyboard_gap_ms||now-this.lastCue<2500||this.sources.size)return;
    const typing=people.find(({motion})=>motion.authorized&&motion.animate&&['type','write'].includes(motion.action));
    if(!typing)return;
    const files=AUDIO.sounds.key.files,buffer=this.buffers.get(files[this.variant++%files.length]);
    if(buffer){this.playBuffer(buffer,AUDIO.sounds.key.gain,(typing.p.x/960-.5)*.8);this.lastKey=now;}
  }
  status(){return {enabled:this.enabled,unlocked:this.unlocked,state:this.context?.state||'locked',sources:this.sources.size,events:this.events,volume:this.volume,samples:this.buffers.size,loadErrors:[...this.loadErrors]};}
}
