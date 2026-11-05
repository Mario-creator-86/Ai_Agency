import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setFetcher,indicators,extractFinancials,parseRss,htmlToText,DATA_TOOLS,riskCheck} from '../src/datatools.mjs';
import {Store} from '../src/store.mjs';
import {Runtime,compactResults} from '../src/runtime.mjs';
import {toolsFor,agentsFor} from '../src/agents.mjs';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
// Offline: a fake network that serves fixed Yahoo-style data and refuses everything else.
const day=864e5,T0=Date.UTC(2025,0,1)/1000;
function series(n,start,drift,wobble){return Array.from({length:n},(_,i)=>start*(1+drift*i)+Math.sin(i/3)*wobble);}
function chartJson(sym,closes){return {chart:{result:[{meta:{symbol:sym,longName:sym+' Inc',currency:'USD',fullExchangeName:'NasdaqGS',regularMarketPrice:closes.at(-1),chartPreviousClose:closes.at(-2),regularMarketTime:T0+closes.length*86400,fiftyTwoWeekHigh:Math.max(...closes),fiftyTwoWeekLow:Math.min(...closes)},timestamp:closes.map((_,i)=>T0+i*86400),indicators:{quote:[{open:closes,high:closes.map(c=>c*1.01),low:closes.map(c=>c*.99),close:closes,volume:closes.map(()=>1e6)}]}}]}};}
const prices={AAPL:series(260,100,.002,2),MSFT:series(260,200,.001,3),SPY:series(260,400,.0008,4)};
function fake(url){const u=String(url);const m=u.match(/chart\/([^?]+)/);if(m){const s=decodeURIComponent(m[1]);if(!prices[s])return Promise.resolve(new Response('{}',{status:404}));return Promise.resolve(new Response(JSON.stringify(chartJson(s,prices[s]))));}
 if(u.includes('news.google.com'))return Promise.resolve(new Response('<rss><channel><item><title>Fed holds rates - Reuters</title><link>https://example.com/a</link><pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate><source url="x">Reuters</source></item></channel></rss>'));
 return Promise.reject(new Error('offline test: '+u));}
test('indicators are computed correctly from closes',()=>{const rows=Array.from({length:30},(_,i)=>({t:i*day,o:i+1,h:i+1.5,l:i+.5,c:i+1,ac:i+1,v:100}));const r=indicators(rows);
 assert.equal(r.last,30);assert.equal(r.sma20,20.5);assert.equal(r.rsi14,100,'only gains gives RSI 100');assert.equal(r.maxDrawdownPct,0);assert.equal(r.return1mPct,round((30/9-1)*100));});
function round(v){return Math.round(v*100)/100;}
test('quotes, history and risk come from the fetched data, with sources',async()=>{setFetcher(fake);try{
 const q=await DATA_TOOLS.market_quote.fn({symbols:['AAPL','BAD SYMBOL','ZZZ']});assert.equal(q.quotes[0].price,Math.round(prices.AAPL.at(-1)*1e4)/1e4);assert.match(q.quotes[1].error,/invalid/);assert.match(q.quotes[2].error,/404/);assert.match(q.quotes[0].source,/finance\.yahoo\.com/);assert.equal(q.quotes[0].changePct1d,Math.round((prices.AAPL.at(-1)/prices.AAPL.at(-2)-1)*1e4)/100,'daily change uses the previous bar');
 const h=await DATA_TOOLS.price_history.fn({symbol:'MSFT'});assert.equal(h.bars,260);assert.ok(h.indicators.sma200);assert.ok(h.closesSample.length<=42);
 const r=await riskCheck({symbols:['AAPL','MSFT'],capital:10000,riskPct:1,entry:100,stop:95});assert.equal(r.positionSizing.quantity,20,'1% of 10 000 at 5 per share = 20');assert.equal(r.positionSizing.maxLoss,100);assert.equal(r.correlation.AAPL.AAPL,1);assert.ok(r.portfolio.historicalVaR95_1dPct>=0);
 const n=await DATA_TOOLS.news_search.fn({query:'fed'});assert.equal(n.items[0].source,'Reuters');}finally{setFetcher((...a)=>fetch(...a));}});
test('SEC facts: newest concept wins and annual periods are full years',()=>{const f=(start,end,val,form='10-K',filed=end)=>({start,end,val,form,filed});
 const facts={facts:{'us-gaap':{Revenues:{units:{USD:[f('2008-07-01','2009-06-30',58)]}},RevenueFromContractWithCustomerExcludingAssessedTax:{units:{USD:[f('2024-07-01','2025-06-30',280),f('2025-07-01','2026-06-30',330),f('2026-01-01','2026-03-31',80,'10-Q')]}},OperatingIncomeLoss:{units:{USD:[f('2025-07-01','2026-06-30',150)]}}},dei:{EntityCommonStockSharesOutstanding:{units:{shares:[{end:'2026-07-20',val:7}]}}}}};
 const r=extractFinancials(facts);assert.deepEqual(r.annual.revenue.map(x=>x.value),[330,280]);assert.equal(r.quarterly.revenue[0].value,80);assert.equal(r.derived.revenueGrowthYoYPct,17.9);assert.equal(r.derived.operatingMarginPct,45.5);assert.equal(r.sharesOutstanding.value,7);});
test('web pages are read as text and private network addresses are refused',async()=>{const t=htmlToText('<html><head><title>T</title><script>evil()</script></head><body><p>Hello</p><p>World</p></body></html>');assert.equal(t.title,'T');assert.doesNotMatch(t.text,/evil/);assert.match(t.text,/Hello\nWorld/);
 for(const url of ['http://127.0.0.1/','http://192.168.1.10/','http://10.0.0.5/','http://169.254.169.254/','file:///etc/passwd','http://localhost:8012/','http://[::1]/','http://[::ffff:127.0.0.1]/','http://0.0.0.0/'])await assert.rejects(()=>DATA_TOOLS.web_page.fn({url}),/blocate|nepermis|http\/https|locală|Port/,url);});
test('rss parser handles CDATA and entities',()=>{const items=parseRss('<rss><item><title><![CDATA[A &amp; B]]></title><link>https://x.y</link></item></rss>');assert.equal(items[0].title,'A & B');});
test('every role has the sources of its job and only the trading ops role trades on paper',()=>{
 assert.ok(toolsFor('v2','david').includes('risk_check'));assert.ok(toolsFor('v2','irina').includes('company_financials'));assert.ok(toolsFor('v2','tudor').includes('macro_series'));assert.ok(toolsFor('v3','radu').includes('youtube_suggest'));
 for(const t of ['v1','v2','v3'])for(const a of agentsFor(t)){const tools=toolsFor(t,a.id);assert.ok(tools.includes('news_search')&&tools.includes('web_page'),t+' '+a.id+' can research');if(tools.includes('paper_trade'))assert.ok((t==='v2'&&a.id==='ana')||(t==='v1'&&a.id==='victor'),t+' '+a.id+' must not trade');}
 assert.equal(toolsFor('v2','w-x','david').includes('risk_check'),true,'hires inherit their director tools');});
test('agent uses a data tool, gets the real result next round, and a forbidden tool is refused',async()=>{setFetcher(fake);const dir=mkdtempSync(join(tmpdir(),'agent-town-data-'));const store=new Store(dir,'v2');store.set('agent:david',{provider:'ollama',model:'fake',enabled:true,lastAuto:0});const seen=[];let n=0;
 const rt=new Runtime(store,dir,()=>{},async(p,m,messages)=>{seen.push(messages.at(-1).content);return JSON.stringify(++n===1?{reply:'Verific.',actions:[{type:'risk_check',symbols:['AAPL','MSFT']},{type:'paper_trade',action:'open',symbol:'AAPL',side:'LONG',qty:1}]}:{reply:'Gata.',actions:[]});});
 try{await sleep(5);rt.enqueue({agent:'david',text:'Riscul pentru AAPL și MSFT',channel:'david',depth:0});for(let i=0;i<200&&(rt.active||rt.queue.length);i++)await sleep(10);
  assert.equal(n,2);assert.match(seen[1],/correlation/);assert.match(seen[1],/Doar responsabilul de operațiuni/);assert.equal(store.paperTrades().length,0);assert.ok(store.events().some(e=>e.type==='source'));}
 finally{rt.close();store.close();rmSync(dir,{recursive:true,force:true});setFetcher((...a)=>fetch(...a));}});
test('paper trading records the fetched price and reports profit against the benchmark',async()=>{setFetcher(fake);const dir=mkdtempSync(join(tmpdir(),'agent-town-paper-'));const store=new Store(dir,'v2');const rt=new Runtime(store,dir);
 try{const ana=agentsFor('v2').find(a=>a.id==='ana');const o=await rt.paperTrade(ana,{action:'open',symbol:'AAPL',side:'LONG',qty:10,note:'test'});assert.equal(o.simulated,true);assert.equal(o.entry,Math.round(prices.AAPL.at(-1)*1e4)/1e4);
  await assert.rejects(()=>rt.paperTrade(ana,{action:'open',symbol:'AAPL',side:'MAYBE',qty:1}),/LONG sau SHORT/);
  const p=await rt.portfolio();assert.match(p.mode,/SIMULARE/);assert.equal(p.positions.length,1);assert.equal(p.positions[0].unrealizedPnl,0);
  const c=await rt.paperTrade(ana,{action:'close',id:o.id});assert.equal(c.closed.status,'closed');assert.equal((await rt.portfolio()).closedTrades,1);}
 finally{rt.close();store.close();rmSync(dir,{recursive:true,force:true});setFetcher((...a)=>fetch(...a));}});
test('tool output sent to the model stays within budget',()=>{const big={x:'a'.repeat(50000)};const out=compactResults([big,big,big,big,big]);assert.ok(out.length<32000);assert.match(out,/truncated/);});
import {parseDecision} from '../src/runtime.mjs';
test('actions are found when the model writes prose and then a JSON block',()=>{
 const text='Am adus trei subiecte. Brieful e salvat.\n\n**1. Apa** — dovada {cerere}\n\n```json\n{"reply":"Brief salvat.","actions":[{"type":"write_artifact","title":"Brief","content":"text cu \\"ghilimele\\" și {acolade}"}]}\n```';
 const d=parseDecision(text);assert.equal(d.actions.length,1);assert.equal(d.actions[0].title,'Brief');assert.match(d.reply,/Am adus trei subiecte/);assert.doesNotMatch(d.reply,/write_artifact/);
 assert.deepEqual(parseDecision('Doar text, fără JSON.').actions,[]);assert.equal(parseDecision('{"reply":"ok","actions":[]}').reply,'ok');
 assert.equal(parseDecision('Text {"reply":"scurt","actions":[{"type":"remember","text":"x"}]}').reply,'scurt','short prose falls back to the JSON reply');});
