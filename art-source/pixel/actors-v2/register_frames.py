"""Read original generated alpha; write registration metadata. Raster files are never edited."""
from pathlib import Path
import json
import hashlib
import subprocess
import shutil
from PIL import Image

root=Path(__file__).resolve().parents[3]
# Preserve the current v3 seated geometry when re-running the original registration entry point.
if (root/'config/pixel_actors.json').is_file() and json.loads((root/'config/pixel_actors.json').read_text(encoding='utf-8')).get('version',2)>=3:
 import runpy
 runpy.run_path(str(root/'art-source/pixel/actors-v2/register_staff_frames.py'),run_name='__main__')
 raise SystemExit(0)
folder=root/'frontend/public/assets/pixel'
atlases={
 'walk':('town-walk-v2.png',[0,310,620,920,1254]),
 'pets':('town-cycle-pets-v2.png',[0,399,660,950,1254]),
 'staff_a':('staff-a-v2.png',[0,310,620,934,1254]),
 'staff_b':('staff-b-v2.png',[0,300,627,940,1254]),
 'idle':('staff-idle-v2.png',[0,312,628,937,1254]),
}
manifest={'atlases':{},'staff':[],'sizes':{'pedestrian':49,'bicycle':51,'cat':22,'dog':18},'version':2}
for name,(file,rows) in atlases.items():
 image=Image.open(folder/file).convert('RGBA');w,h=image.size
 assert (w,h)==(1254,1254)
 pix=image.load();groups=[]
 for row in range(4):
  frames=[]
  for col in range(4):
   x0=int(col*w/4);x1=int((col+1)*w/4)
   occupied=[(x,y) for y in range(rows[row],rows[row+1]) for x in range(x0,x1) if pix[x,y][3]>=160]
   assert len(occupied)>1000,(name,row,col)
   # Registration ignores isolated neighbouring-cell flecks; the original PNG is untouched.
   remaining=set(occupied);components=[]
   while remaining:
    start=remaining.pop();component=[start];stack=[start]
    while stack:
     x,y=stack.pop()
     for dx,dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
      point=(x+dx,y+dy)
      if point in remaining:remaining.remove(point);stack.append(point);component.append(point)
    components.append(component)
   main=max(components,key=len)
   mx0=min(x for x,y in main);mx1=max(x for x,y in main);my0=min(y for x,y in main);my1=max(y for x,y in main)
   occupied=[point for component in components for point in component
             if component is main or any(mx0-6<=x<=mx1+6 and my0-6<=y<=my1+6 for x,y in component)]
   left=min(p[0] for p in occupied);right=max(p[0] for p in occupied)
   top=min(p[1] for p in occupied);bottom=max(p[1] for p in occupied)
   heads=[x for x,y in occupied if y<top+(bottom-top)*0.22]
   anchor=sum(heads)/len(heads) if name!='pets' else (left+right)/2
   frames.append({'x':left,'y':top,'width':right-left+1,'height':bottom-top+1,'anchor_x':round(anchor-left,2)})
  groups.append({'height':max(f['height'] for f in frames),'frames':frames})
 manifest['atlases'][name]={'url':'/assets/pixel/'+file,'width':w,'height':h,'sha256':hashlib.sha256((folder/file).read_bytes()).hexdigest(),'rows':groups}
characters=json.loads((root/'frontend/tests/fixtures/pixel_actors_bible.json').read_text(encoding='utf-8'))
order=['Sarah Executive','Dr. Aris Researcher','Elena Fact-Checker','Marcus Scriptwriter','Lyra Voice Artist','Kael Video Editor','Vera Distribution Hub','Nadia Accountant']
for index,label in enumerate(order):
 character=next(c for c in characters if c['canonical_name']==label)
 palette=character['palette_json']
 coat=next(palette[k] for k in ['coat','suit','vest','hoodie','sweater','shirt','blazer','cardigan'] if k in palette)
 hair=palette.get('hair',palette.get('bun'))
 manifest['staff'].append({'employee_id':character['employee_id'],'atlas':'staff_a' if index<4 else 'staff_b','row':index%4,'idle_row':index//2,'idle_col':index%2*2,'hair':hair,'coat':coat})
# Derive appearance checks through the same runtime profile function, not a second palette parser.
profile_script = "import {readFileSync} from 'node:fs';import {characterProfile} from './frontend/src/pixel_people.js';const bible=JSON.parse(readFileSync('frontend/tests/fixtures/pixel_actors_bible.json','utf8'));console.log(JSON.stringify(bible.map(c=>characterProfile({id:c.employee_id},c))));"
profiles = {p['employeeId']: p for p in json.loads(subprocess.check_output(
    [shutil.which('node'), '--input-type=module', '-e', profile_script], cwd=root, text=True, encoding='utf-8'))}
appearance_keys = ['skin','coat','shirt','hair','accent','hairStyle','glasses','headset','streak','silver','beard','ledger']
for staff in manifest['staff']:
    staff['appearance'] = {key: profiles[staff['employee_id']][key] for key in appearance_keys}
(root/'config/pixel_actors.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('Five unchanged RGBA atlases registered; 80 frames and eight actual identities.')
