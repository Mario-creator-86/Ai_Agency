import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {build} from 'vite';
import tailwindcss from '@tailwindcss/vite';
import {chromium} from 'playwright';
const root=fileURLToPath(new URL('../..',import.meta.url));
test('dialog states, section navigation, model fields and responsive shells',async()=>{
 const files=['style.css','office_scene.css','serial_room.css','owner_decisions.css','pixel_studio.css','studio_dashboard.css'];
 if(existsSync(path.join(root,'src/dialog_finish.css')))files.push('dialog_finish.css');
 const entry=files.map(f=>`import ${JSON.stringify(path.join(root,'src',f).replaceAll('\\','/'))};`).join('\n')+'\n'+['dialog_rail.js','settings.js','provider_production.js'].map(f=>`export * from ${JSON.stringify(path.join(root,'src',f).replaceAll('\\','/'))};`).join('\n');
 const built=await build({root,configFile:false,publicDir:false,logLevel:'silent',plugins:[tailwindcss(),{name:'review',resolveId:id=>id.replaceAll('\\','/').endsWith('/review')||id==='review'?'\0review':null,load:id=>id==='\0review'?entry:null}],build:{write:false,minify:false,lib:{entry:'review',name:'Review',formats:['iife']}}});
 const outputs=(Array.isArray(built)?built[0]:built).output;
 const css=outputs.filter(x=>x.type==='asset'&&x.fileName.endsWith('.css')).map(x=>x.source).join('\n');
 const js=outputs.find(x=>x.type==='chunk').code;
 const html=readFileSync(path.join(root,'index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>',`<style>${css}</style></head>`);
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1920,height:1080},reducedMotion:'reduce'});
 try{
  await page.route('**/*',r=>r.request().url()==='http://ui-review.invalid/'?r.fulfill({body:html,contentType:'text/html'}):r.abort());
  await page.goto('http://ui-review.invalid/');await page.addScriptTag({content:js});
  await page.evaluate(()=>{
   document.body.classList.remove('is-title');document.getElementById('login').hidden=true;document.getElementById('workspace').hidden=false;
   const list=document.getElementById('storyboards-list');
   list.innerHTML='<article class="storyboard-card"><div class="storyboard-header"><div><h4 class="storyboard-title">Titlu foarte lung pentru verificarea unui film respins</h4><div class="storyboard-meta"><span>Aspect: <strong>9:16</strong></span><span>5 scene</span><span>Stare: <strong class="storyboard-state text-error" data-status="REJECTED">respins</strong></span></div></div><div class="storyboard-actions"><button>Detalii</button><button>Foaia de filmare</button><button class="btn-render-video">Randare 9:16</button><button>Verifică QC</button></div></div></article>';
   document.getElementById('media-modal').showModal();
  });
  const state=await page.locator('[data-status="REJECTED"]').evaluate(e=>({display:getComputedStyle(e).display,height:e.getBoundingClientRect().height,parent:e.parentElement.getBoundingClientRect().height}));
  assert.equal(state.display,'inline','a status word must not become a full error panel');assert.ok(state.parent<30);
  await page.keyboard.press('Escape');
  await page.evaluate(()=>{
   const d=document.getElementById('research-modal'),pane=d.querySelector('.dialog-pane');
   pane.style.position='relative';
   pane.querySelectorAll(':scope > div').forEach(e=>{e.style.minHeight='800px';e.style.contentVisibility='visible';});
   d.showModal();Review.attachRail(d.querySelector('.dialog-body'));
  });
  await page.locator('a[href="#rs-topics"]').click();
  const offset=await page.locator('#rs-topics').evaluate(t=>t.getBoundingClientRect().top-t.closest('.dialog-body').getBoundingClientRect().top);
  assert.ok(offset>=0&&offset<50,'section heading lands inside its own scroller, offset='+offset);
  await page.keyboard.press('Escape');
  await page.evaluate(()=>Review.initSettings(async p=>{
   if(p==='/settings')return {catalog:{},integrations:[],providers:[],roles:[{id:'r',name:'Director',required_capabilities:[]}],models:[{id:'m',provider_id:'p',model_name:'Model test',is_available:true,capabilities:[]}],agents:[{id:'a',role_id:'r',display_name:'Agent test',model_id:'m'}],routing:[]};
   if(p==='/publishing/channels')return {channels:[]};
   return {};
  }));
  await page.locator('#open-settings').click();await page.locator('.settings-tabs button').getByText('Angajați',{exact:true}).click();
  const field=await page.locator('select[aria-label="Model principal pentru Agent test"]').evaluate(e=>({previous:e.previousElementSibling?.textContent,inActions:!!e.closest('.settings-actions')}));
  assert.equal(field.previous,'Model principal');assert.equal(field.inActions,false,'primary model stays beside its label');
  const tab=page.locator('.settings-tabs button').getByText('Video și sunet',{exact:true});await tab.click();
  assert.equal(await tab.evaluate(e=>e===document.activeElement),true,'selected section keeps keyboard focus after repaint');
  const channels=page.locator('.settings-tabs button').getByText('Canale',{exact:true});await channels.click();await page.waitForSelector('.settings-content p:has-text("Niciun canal")');assert.equal(await channels.evaluate(e=>e===document.activeElement),true,'async channel loading keeps the selected tab focused');
  await page.evaluate(()=>Review.renderProviderProduction(document.querySelector('.settings-content'),{id:'fixture',status:'VERIFIED'},{kind_info:{has_voices:true},models:[],voices:[]},{api:async()=>({}),run:()=>{}}));
  const toggle=await page.locator('.settings-toggle input').evaluate(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,direction:getComputedStyle(e.parentElement).flexDirection}));
  assert.ok(toggle.width<=22&&toggle.height<=22,'checkbox must not inherit the full-width text field geometry');assert.equal(toggle.direction,'row');
  await page.setViewportSize({width:390,height:900});
  await page.locator('.settings-tabs button').getByText('Despre studio',{exact:true}).click();
  const selected=await page.locator('.settings-tabs [aria-current=page]').evaluate(e=>{const r=e.getBoundingClientRect(),nav=e.parentElement.getBoundingClientRect();return r.left>=nav.left-1&&r.right<=nav.right+1;});
  assert.equal(selected,true,'repainting a narrow tab strip must keep the selected tab visible');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#runbook-modal .dialog-rail a[href="#rb-queue"]').count(),1,'the queue has its own section link');
  for(const width of [1920,1366,768,390]){
   await page.setViewportSize({width,height:width===1366?768:900});
   for(const id of ['media-modal','research-modal','story-modal','runbook-modal','autonomy-modal','workforce-modal','publishing-modal','mail-modal','agent-inspector']){
    await page.locator('#'+id).evaluate(d=>d.showModal());
    const box=await page.locator('#'+id).evaluate(d=>{const r=d.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,over:d.scrollWidth>d.clientWidth+2};});
    assert.ok(box.x>=-1&&box.right<=width+1&&!box.over,JSON.stringify({id,width,...box}));
    assert.ok(box.y>=-1&&box.bottom<=(width===1366?768:900)+1);
    if(width<=1100&&await page.locator('#'+id+' .dialog-rail').count()){const gap=await page.locator('#'+id).evaluate(d=>d.querySelector('.dialog-pane').getBoundingClientRect().top-d.querySelector('.dialog-rail').getBoundingClientRect().bottom);assert.ok(gap>=-1,'section menu must not overlap content '+id+' '+width+' gap='+gap);}
    await page.keyboard.press('Escape');
   }
  }
 }finally{await browser.close();}
});
