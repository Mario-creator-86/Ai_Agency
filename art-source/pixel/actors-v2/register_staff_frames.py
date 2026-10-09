"""Read original RGBA sheets and register complete figures and seated contact landmarks."""
from pathlib import Path
import hashlib
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "config/pixel_actors.json"

def components(points):
    remaining = set(points)
    result = []
    while remaining:
        component = [remaining.pop()]
        stack = component.copy()
        while stack:
            x, y = stack.pop()
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                point = x+dx, y+dy
                if point in remaining:
                    remaining.remove(point)
                    component.append(point)
                    stack.append(point)
        result.append(component)
    return result

def bounds(points):
    return min(x for x,y in points), min(y for x,y in points), max(x for x,y in points), max(y for x,y in points)

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
for key in ["staff_a", "staff_b", "idle"]:
    asset = manifest["atlases"][key]
    path = ROOT / "frontend/public" / asset["url"].lstrip("/")
    image = Image.open(path).convert("RGBA")
    width, height = image.size
    pixels = image.load()
    frames = [[] for _ in range(4)]
    for col in range(4):
        x0,x1 = col*width//4,(col+1)*width//4
        cuts = [0]
        for boundary in [height//4,height//2,height*3//4]:
            cuts.append(min(range(boundary-20,boundary+21),key=lambda y:sum(pixels[x,y][3]>=160 for x in range(x0,x1))))
        cuts.append(height)
        for row in range(4):
            groups = components([(x,y) for y in range(cuts[row],cuts[row+1]) for x in range(x0,x1) if pixels[x,y][3]>=160])
            main = max(groups,key=len)
            left,top,right,bottom = bounds(main)
            nearby = [point for group in groups if group is main or any(left-6<=x<=right+6 and top-6<=y<=bottom+6 for x,y in group) for point in group]
            left,top,right,bottom = bounds(nearby)
            fw,fh = right-left+1,bottom-top+1
            assert fh<height/3 and fw<width/3
            head = [x for x,y in nearby if y<top+fh*.22]
            occupancy = [sum(pixels[x,top+y][3]>=160 for x in range(left,right+1)) for y in range(fh)]
            # The contact plane is the transition from the broad hips/coat to the narrower shins.
            search = range(round(fh*.70),min(fh-8,round(fh*.86)))
            seat_y = max(search,key=lambda y:sum(occupancy[y-5:y])-sum(occupancy[y:y+5]))+2
            waist = [x-left for x,y in nearby if top+seat_y-12<=y<top+seat_y-4]
            frames[row].append({"x":left,"y":top,"width":fw,"height":fh,"anchor_x":round(sum(head)/len(head)-left,2),"seat_x":round(sum(waist)/len(waist),2),"seat_y":seat_y})
    asset.update(width=width,height=height,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=[{"height":max(f["height"] for f in row),"frames":row} for row in frames])
manifest["version"] = 3
MANIFEST.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
print("48 complete seated figures registered; original PNG files are unchanged.")
