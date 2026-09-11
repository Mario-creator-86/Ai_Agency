// Exports the renderer's palette (the single colour source, frontend/src/office_palette.js)
// to art-source/palette.json so Blender materials use exactly the same ramps.
// Run: node scripts/export_palette.mjs
import fs from 'node:fs';
import path from 'node:path';
import * as P from '../frontend/src/office_palette.js';

const out = {
  generated_from: 'frontend/src/office_palette.js',
  ambient: P.AMBIENT,
  ui: P.UI,
  facade: P.FACADE,
  street: P.STREET,
  sky: P.SKY,
  city: P.CITY,
  materials: P.MAT,
  skin: P.SKIN,
  hair: P.HAIR,
  cloth: P.CLOTH,
  departments: Object.fromEntries(
    Object.entries(P.DEPARTMENTS).map(([k, d]) => [k, { ...d }]),
  ),
};
const file = path.resolve('art-source/palette.json');
fs.mkdirSync(path.dirname(file), { recursive: true });
fs.writeFileSync(file, JSON.stringify(out, null, 2) + '\n');
console.log(`wrote ${file}`);
