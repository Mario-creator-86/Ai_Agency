// Reads the channels connected in the AI Agency studio (read-only) and writes a short report.
import {listChannels,myChannel,myAnalytics} from './src/youtube-bridge.mjs';
import {writeFileSync} from 'node:fs';
const out=[];const log=s=>{out.push(s);console.log(s);};
try{
 log('Canale conectate în studio: '+listChannels().map(c=>`${c.channel} (${c.channelId}, statistici: ${c.analytics?'da':'nu'})`).join('; '));
 for(const c of listChannels()){try{const ch=await myChannel({channel:c.channelId});log(`\n[${ch.channel}] abonați ${ch.subscribers}, vizualizări ${ch.totalViews}, video-uri ${ch.videoCount}`);for(const v of ch.latestVideos.slice(0,5))log(`  - ${v.published.slice(0,10)} · ${v.views} vizualizări · ${v.privacy} · ${v.title}`);
  if(c.analytics){const a=await myAnalytics({channel:c.channelId,days:28});log(`  Ultimele 28 de zile: ${JSON.stringify(a.totals)}`);log(`  Surse de trafic: ${a.trafficSources.slice(0,5).map(t=>t.insightTrafficSourceType+' '+t.views).join(', ')}`);}}
  catch(e){log(`\n[${c.channel}] EROARE: ${e.message}`);}}
}catch(e){log('EROARE: '+e.message);}
writeFileSync('diagnostic/test-youtube-raport.txt',out.join('\r\n'));
