// Actual workspace, styles, renderer and dashboard; all network answers are isolated fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { chromium } from 'playwright';
import { approvalCardHtml } from '../../src/governance.js';
import { inboxHtml } from '../../src/owner_inbox.js';
import { escapeHtml } from '../../src/html.js';

const FRONTEND=fileURLToPath(new URL('../..',import.meta.url));
const evidence=process.env.E2E_EVIDENCE;
test('dashboard reference layout, truthful cards, navigation and logout cleanup',async()=>{
  const entry=['style.css','office_scene.css','pixel_studio.css','studio_dashboard.css'].map(f=>`import ${JSON.stringify(path.join(FRONTEND,'src',f).replaceAll('\\','/'))};`).join('\n')+
    ['pixel_office.js','drawers.js','studio_dashboard.js'].map(f=>`export * from ${JSON.stringify(path.join(FRONTEND,'src',f).replaceAll('\\','/'))};`).join('\n');
  const result=await build({root:FRONTEND,configFile:false,publicDir:false,logLevel:'silent',plugins:[tailwindcss(),{name:'dashboard-review',resolveId:id=>id.replaceAll('\\','/').endsWith('dashboard-review')?'\0dashboard-review':null,load:id=>id==='\0dashboard-review'?entry:null}],build:{write:false,minify:false,lib:{entry:'dashboard-review',name:'DashboardReview',formats:['iife']}}});
  const output=(Array.isArray(result)?result[0]:result).output;
  const css=output.filter(o=>o.type==='asset'&&o.fileName.endsWith('.css')).map(o=>o.source).join('\n');
  const code=output.find(o=>o.type==='chunk').code;
  const html=readFileSync(path.join(FRONTEND,'index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>',`<style>${css}</style></head>`);
  const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1920,height:1080}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const reports=[];
  try {
    await page.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(url.pathname==='/')return route.fulfill({body:html,contentType:'text/html'});
      if(url.pathname.startsWith('/assets/pixel/')||url.pathname.startsWith('/fonts/')||url.pathname==='/amn-ai-mark.png'){
        const f=path.join(FRONTEND,'public',url.pathname);
        try{return route.fulfill({body:readFileSync(f),contentType:f.endsWith('.png')?'image/png':f.endsWith('.woff2')?'font/woff2':'application/json'});}catch{return route.abort();}
      }
      return route.abort();
    });
    await page.goto('http://dashboard-review.invalid/');await page.addScriptTag({content:code});
    await page.evaluate(async()=>{
      document.body.classList.remove('is-title');document.getElementById('title-stage').hidden=true;document.getElementById('login').hidden=true;document.getElementById('workspace').hidden=false;
      document.getElementById('connection').textContent='Previzualizare · date de test';
      const settings=document.createElement('button');settings.id='open-settings';settings.textContent='Setări';document.querySelector('.topbar-right').append(settings);
      window.menuHits=[];document.querySelectorAll('.toolbar-modules button,#open-settings').forEach(button=>button.addEventListener('click',()=>window.menuHits.push(button.id)));
      window.calls=[];window.channelFailure=false;window.delayAnswer=null;window.connectionReadAt='2026-01-01T00:00:00Z';
      window.dashboard=new DashboardReview.StudioDashboard({api:async(path,options)=>{
        window.calls.push({path,method:options?.method||'GET'});
        if(path.startsWith('/media/storyboards'))return {storyboards:[{id:'test-a',status:'IN_PRODUCTION'},{id:'test-b',status:'APPROVED'},{id:'old',status:'RENDERED',publication:{status:'PUBLISHED'}}],next_offset:null};
        if(path.includes('status=QUEUED'))return [{id:'q',status:'QUEUED',priority:5,task_type:'DAILY_RUN',next_attempt_at:'2026-01-01T00:00:00Z'}];
        if(path.startsWith('/events?'))return {events:[{event_id:'done-event',event_type:'agent.run_completed',aggregate_id:'done',timestamp:new Date().toISOString(),payload:{status:'SUCCEEDED'}}],next_cursor:1,has_more:false,since:new URL('http://test'+path).searchParams.get('since')};
        if(path==='/economy/budget')return {today:{spent_usd:'42.60'},budgets:[{period:'DAILY',spent_usd:'42.60',limit_usd:'60',remaining_usd:'17.40'}]};
        if(path==='/publishing/channels')return {channels:[{id:'slot-a',channel_type:'MAIN_FACTUAL',channel_name:'Canal factual · test',remote_channel_id:'yt-a'},{id:'slot-b',channel_type:'OFFICE_SERIAL',channel_name:'Serial · test',remote_channel_id:'yt-b'}]};
        if(path==='/youtube/connections')return {connections:[{id:'conn-a',connected:true,last_checked_at:window.connectionReadAt,channel:{id:'yt-a',title:'Canal factual · test',view_count:'1200',subscriber_count:'80'}},{id:'conn-b',connected:true,last_checked_at:window.connectionReadAt,channel:{id:'yt-b',title:'Serial · test',view_count:'900',subscriber_count:'45'}}]};
        if(path.includes('/verify')){
          if(window.channelFailure)throw Error('fixture read failure');
          const a=path.includes('conn-a');return {id:a?'conn-a':'conn-b',connected:true,last_checked_at:new Date().toISOString(),channel:{id:a?'yt-a':'yt-b',title:a?'Canal factual · test':'Serial · test',view_count:a?'1201':'901',subscriber_count:a?'81':'46'}};
        }
        throw Error('Unexpected fixture path '+path);
      }});
      window.dashboard.mount();
      window.drawers=new DashboardReview.Drawers();window.drawers.start();
      window.engine=new DashboardReview.OfficeEngine(document.getElementById('office-canvas'),{parked:true,reducedMotion:()=>true,dataLive:()=>false,onSelectAgent:a=>window.selectedAgent=a.id});
      await window.engine.ready;window.engine.resize();
      window.engine.setAgents([{id:'preview-director',display_name:'Sarah · test',role:'Director',lifecycle:'ACTIVE',runtime_state:'IDLE'}]);
      window.dashboard.update({policy:{autonomy_stopped:false},timeZone:'Europe/Bucharest',budget:{today:{spent_usd:'42.60'},budgets:[{period:'DAILY',spent_usd:'42.60',limit_usd:'60',remaining_usd:'17.40'}]}});
      document.getElementById('ledger-count').textContent='Date de test';
      document.getElementById('ledger-now').textContent='Previzualizare locală a interfeței';
      document.getElementById('ledger-filters').innerHTML='<button class="ledger-chip is-active" role="tab" aria-selected="true">Toate</button><button class="ledger-chip" role="tab" aria-selected="false">Producție</button><button class="ledger-chip" role="tab" aria-selected="false">Angajați</button>';
      document.getElementById('ledger-list').innerHTML='<li class="ledger-day">Astăzi · date de test</li>'+Array.from({length:8},(_,i)=>'<li class="ledger-item"><time>15:4'+i+':12</time><div><div class="ledger-head"><strong>Sarah · previzualizare</strong></div><p class="ledger-text">Un mesaj din registrul de activitate, pentru verificarea textului și spațierii. Fără conectare la studio.</p></div></li>').join('');
      document.getElementById('approvals-count').textContent='Test';
    });
    const card=approvalCardHtml({id:'preview-approval',action:'local.preview',action_label:'Cerere de test',risk_tier:'T3',subject:'Previzualizare locală a unei aprobări',cost_label:'necunoscut',requester:'Agent de test',reversible:false},{escape:escapeHtml,now:Date.now(),caveat:'Date de test',tierMeaning:'Exemplu de verificare'});
    await page.locator('#approvals-list').evaluate((el,html)=>el.innerHTML=html,card);
    await page.locator('#owner-inbox-list').evaluate((el,html)=>el.innerHTML=html,inboxHtml([{id:'test-letter',thread_id:'test-thread',subject:'Scrisoare de test',from_name:'Sarah · test',created_at:new Date().toISOString()}],{escape:escapeHtml,read:'ok',timezone:'Europe/Bucharest'}));
    await page.waitForFunction(()=>document.getElementById('dashboard-projects-value').textContent==='2'&&!window.dashboard.busy);
    assert.equal(await page.locator('#dashboard-completed-value').textContent(),'1');
    assert.match(await page.locator('#dashboard-audience').textContent(),/1[.\s]?201/);
    assert.equal(await page.locator('#pixel-roster').isVisible(),false);
    assert.equal(await page.locator('#autonomy-mode-meaning').isVisible(),false);
    assert.equal(await page.locator('#day-will').isVisible(),false);
    assert.equal(await page.locator('#paid-media-governance').isVisible(),false);
    for(const width of [1920,1700,1366,1280,1050,768,390]){
      await page.setViewportSize({width,height:width===1366?768:1080});await page.evaluate(()=>{window.engine.resize();window.scrollTo(0,0);});
      const geometry=await page.evaluate(()=>{
        const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
        const e=window.engine,v=e.viewport,a=v.worldToScreen(0,0),b=v.worldToScreen(e.worldW,e.worldH);
        return {nav:box('#dashboard-nav'),activity:box('.ledger-column'),office:box('.office-panel'),side:box('.side-column'),metrics:box('#dashboard-metrics'),canvas:box('#office-canvas'),overflow:document.documentElement.scrollWidth>innerWidth,worldFits:a.x>=-1&&a.y>=-1&&b.x<=e.canvas.width+1&&b.y<=e.canvas.height+1};
      });
      reports.push({width,...geometry});assert.equal(geometry.overflow,false,JSON.stringify({width,...geometry}));assert.equal(geometry.worldFits,true,'building fits at '+width);
      const headerOverlaps=await page.evaluate(()=>[...document.querySelectorAll('.section-heading')].filter(h=>h.getBoundingClientRect().width>0).flatMap(h=>{
        const children=[...h.children].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0;});
        return children.flatMap((a,i)=>children.slice(i+1).filter(b=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return Math.min(x.right,y.right)>Math.max(x.left,y.left)+1&&Math.min(x.bottom,y.bottom)>Math.max(x.top,y.top)+1;}).map(b=>[a.tagName,b.tagName]));
      }));
      assert.deepEqual(headerOverlaps,[],'header titles, counts and refresh targets are separate at '+width);
      if(width>1100){assert.ok(geometry.nav.right<=geometry.activity.x);assert.ok(geometry.activity.right<=geometry.office.x);assert.ok(geometry.office.right<=geometry.side.x);assert.ok(geometry.metrics.bottom<=geometry.office.y);}
      for(const id of ['open-research-btn','open-media-btn','open-workforce-btn','open-autonomy-btn','open-settings']){
        await page.locator('#'+id).click();assert.equal(await page.evaluate(()=>window.menuHits.at(-1)),id);
      }
      if(evidence&&[1920,1366,390].includes(width)){mkdirSync(evidence,{recursive:true});await page.evaluate(()=>{document.getElementById('dashboard-nav').scrollTop=0;document.getElementById('dashboard-nav').scrollLeft=0;window.scrollTo(0,0);});await page.screenshot({path:path.join(evidence,`dashboard-${width}.png`),fullPage:true});}
    }
    await page.setViewportSize({width:1920,height:1080});await page.evaluate(()=>{window.engine.resize();window.scrollTo(0,0);});
    const point=await page.evaluate(()=>{const e=window.engine,p=e.visiblePositions()[0],s=e.viewport.worldToScreen(p.x,p.y-30),r=e.canvas.getBoundingClientRect();return {x:r.x+s.x/e.dpr,y:r.y+s.y/e.dpr};});
    await page.mouse.click(point.x,point.y);assert.equal(await page.evaluate(()=>window.selectedAgent),'preview-director');
    await page.mouse.move(point.x+170,point.y+150);assert.equal(await page.locator('#office-canvas').getAttribute('title'),'');
    for(const width of [1920,390]){
      await page.setViewportSize({width,height:1080});
      await page.evaluate(()=>{document.documentElement.style.fontSize='32px';window.engine.resize();});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'enlarged text stays inside page at '+width);
      await page.evaluate(()=>document.documentElement.style.fontSize='');
    }
    const calls=await page.evaluate(()=>window.calls.length);await page.evaluate(()=>window.dashboard.refresh());
    const verifies=await page.evaluate(()=>window.calls.filter(c=>c.path.includes('/verify')).length);assert.equal(verifies,2,'YouTube refresh throttled to one minute');
    assert.ok(await page.evaluate(()=>window.calls.length)>calls);
    // Another tab's fresh channel read is reused, with no redundant YouTube verification.
    await page.evaluate(async()=>{window.connectionReadAt=new Date().toISOString();window.dashboard.audienceRead=0;await window.dashboard.refresh();});
    assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.path.includes('/verify')).length),2);
    await page.evaluate(()=>window.connectionReadAt='2026-01-01T00:00:00Z');
    await page.evaluate(async()=>{window.channelFailure=true;window.dashboard.audienceRead=0;await window.dashboard.refresh();});
    assert.match(await page.locator('#dashboard-audience').textContent(),/Actualizare indisponibilă/);
    assert.equal(await page.locator('.dashboard-channel-row').first().getAttribute('data-stale'),'true');
    // Long project names and larger lists stay bounded; completion failure differs from a real zero.
    await page.evaluate(()=>{window.dashboard.data.projects=Array.from({length:8},(_,i)=>({id:'named-'+i,status:'APPROVED',title:'Numele complet al proiectului de test '+i+' '.repeat(1)+'foarte lung '.repeat(8)}));window.dashboard.data.completed=null;window.dashboard.metricErrors.add('completed');window.dashboard.paint();});
    assert.equal(await page.locator('.dashboard-project-name').count(),2);
    assert.equal(await page.locator('.dashboard-project-more').textContent(),'+6 proiecte');
    assert.match(await page.locator('.dashboard-project-name').first().getAttribute('title'),/foarte lung/);
    assert.equal(await page.locator('#dashboard-completed-value').textContent(),'—');
    assert.match(await page.locator('#dashboard-completed-note').textContent(),/Date indisponibile/);
    await page.evaluate(()=>{window.dashboard.data.completed=[];window.dashboard.metricErrors.delete('completed');window.dashboard.paint();});
    assert.equal(await page.locator('#dashboard-completed-value').textContent(),'0');
    // A delayed answer may not repopulate a signed-out dashboard.
    await page.evaluate(()=>{window.dashboard.api=()=>new Promise(resolve=>window.delayAnswer=resolve);void window.dashboard.refresh();window.dashboard.stop();window.delayAnswer([]);});
    await page.waitForTimeout(30);assert.equal(await page.locator('#dashboard-projects-value').textContent(),'—');
    assert.equal(await page.locator('#dashboard-audience').getByText('1.201',{exact:true}).count(),0);
    assert.deepEqual(errors,[]);
    if(evidence)writeFileSync(path.join(evidence,'layout-verification.json'),JSON.stringify({reports,errors},null,2));
  }finally{await browser.close();}
});
