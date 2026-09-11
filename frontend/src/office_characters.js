/**
 * Office characters — the studio's people as compiled pixel sprites.
 *
 * Appearance is derived from the agent id, so the same agent looks the same on every reload
 * and no two agents look alike. Costume is derived from the role, so a department reads at a
 * glance: lab coats in research, a blazer upstairs, a hoodie in the edit bay.
 *
 * Posture and gesture come from backend state only:
 *   lifecycle PAUSED / SUSPENDED / TERMINATED -> asleep, head down
 *   runtime_state WORKING / EXECUTING / RUNNING -> typing
 *   runtime_state THINKING / PLANNING          -> hand to chin, idea bubble
 *   anything else                              -> idle: breathing, blinking, an occasional sip
 *
 * Idle motions are cosmetic and never imply that work is happening.
 */

import { PixelGrid, cachedSprite, drawSprite, glow, contactShadow } from './pixel_sprites.js';
import { SKIN, HAIR, CLOTH, UI, AMBIENT, withAlpha, ramp } from './office_palette.js';
import { partsReady, compositeParts } from './office_atlas.js';

const TAU = Math.PI * 2;

function hash32(input) {
  const str = String(input);
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a += 0x6d2b79f5;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pick = (list, rnd) => list[Math.floor(rnd() * list.length) % list.length];

/* ============================================================================
   Templates. One character per world pixel. Letters map to ramp tones:

     z s S Z  skin: deep, shade, base, light      w e  eye white, eye dark
     a A @    hair: shade, base, light            m    mouth
     D c C B  garment: deep, shade, base, light   X x  second garment colour, its shade
     N n      shirt/undershirt light, shade       K k  accessory (headset, glasses) light/dark
   ========================================================================== */

/** Seated body, front view, 26 wide. Rows 0-12 head, 13 neck, 14+ torso to the waist. */
const BODY = [
  '........SSSSSSSSSS........',
  '.......SSSSSSSSSSSS.......',
  '......ZSSSSSSSSSSSSs......',
  '......ZSSSSSSSSSSSSs......',
  '.....SZSSSSSSSSSSSSss.....',
  '.....SZSSSSSSSSSSSSss.....',
  '.....SZSSSSSSSSSSSSss.....',
  '......ZSSSSSSSSSSSSs......',
  '......sSSSSSSSSSSSSs......',
  '......sSSSSSSSSSSSSs......',
  '.......sSSSSSSSSSSs.......',
  '........ssSSSSSSss........',
  '..........ssSSss..........',
  '...........sSSs...........',
  '.......CCCCsSSsCCCC.......',
  '.....CCCCCCCXXXXCCCCCCC...',
  '....CCCCCCCCCXXCCCCCCCCc..',
  '...CCCCCCCCCCCCCCCCCCCCc..',
  '...cCCCCCCCCCCCCCCCCCCCc..',
  '..cCCCCCCCCCCCCCCCCCCCCcc.',
  '..cCCCCCCCCCCCCCCCCCCCCcc.',
  '..cCCcCCCCCCCCCCCCCCcCCcc.',
  '..cCC.cCCCCCCCCCCCCc.CCcc.',
  '..ccc.cCCCCCCCCCCCCc.ccc..',
  '..ccc..cCCCCCCCCCCc..ccc..',
  '..ccc..ccCCCCCCCCcc..ccc..',
  '.......cccCCCCCCccc.......',
  '........ccccccccccc.......',
];

/**
 * Light comes from the top-left: the two right-most garment columns of every torso row fall
 * one tone into shade, so the body reads as a cylinder instead of a flat card.
 */
function shadeTorso(rows) {
  return rows.map((row, i) => {
    if (i < 14) return row;
    let out = row;
    let shaded = 0;
    for (let x = row.length - 1; x >= 0 && shaded < 2; x -= 1) {
      if (row[x] === 'C') {
        out = `${out.slice(0, x)}c${out.slice(x + 1)}`;
        shaded += 1;
      } else if (row[x] !== '.' && row[x] !== 'c') {
        break;
      }
    }
    return out;
  });
}
const BODY_SHADED = shadeTorso(BODY);

/** Face features, blitted over the head at the sprite origin. */
const FACE_OPEN = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '........we......we........',
  '........ee......ee........',
  '............s.............',
  '..........................',
  '..........mmmm............',
];
const FACE_BLINK = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '........ee......ee........',
  '............s.............',
  '..........................',
  '..........mmmm............',
];
const FACE_SLEEP = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '........ee......ee........',
  '............s.............',
  '..........................',
  '...........mm.............',
];
const FACE_LOOK = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '........ew......ew........',
  '........ee......ee........',
  '............s.............',
  '..........................',
  '..........mmmm............',
];
const FACE_TALK = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '........we......we........',
  '........ee......ee........',
  '............s.............',
  '..........mmmm............',
  '..........mmmm............',
];

/** Hair styles drawn over the head. dy is the row offset from the sprite's top. */
const HAIR_STYLES = {
  short: {
    dy: -2,
    rows: [
      '.........AAAAAAAA.........',
      '.......AAAAAAAAAA@A.......',
      '......AAAAAAAAAAAAAA......',
      '......aAAAAAAAAAAAAa......',
      '......aA............a.....',
      '......a..............a....',
    ],
  },
  crop: {
    dy: -1,
    rows: [
      '........AAAAAAAAAA........',
      '.......AAAAAAAAAA@A.......',
      '.......aAAAAAAAAAAa.......',
      '.......a..........a.......',
    ],
  },
  bob: {
    dy: -2,
    rows: [
      '.........AAAAAAAA.........',
      '.......AAAAAAAAAA@A.......',
      '......AAAAAAAAAAAAAA......',
      '......AAAAAAAAAAAAAA......',
      '......AAA........AAA......',
      '......AAa........aAA......',
      '......AAa........aAA......',
      '......AAa........aAA......',
      '......AAa........aAA......',
      '......aaa........aaa......',
    ],
  },
  long: {
    dy: -2,
    rows: [
      '.........AAAAAAAA.........',
      '.......AAAAAAAAAA@A.......',
      '......AAAAAAAAAAAAAA......',
      '.....AAAAAAAAAAAAAAAA.....',
      '.....AAA..........AAA.....',
      '.....AAa..........aAA.....',
      '.....AAa..........aAA.....',
      '.....AAa..........aAA.....',
      '.....AAa..........aAA.....',
      '.....AAa..........aAA.....',
      '.....AAa..........aAA.....',
      '.....AAa..........aAA.....',
      '.....aaa..........aaa.....',
    ],
  },
  bun: {
    dy: -6,
    rows: [
      '...........AAAA...........',
      '..........AA@AAA..........',
      '..........AAAAAA..........',
      '...........aaaa...........',
      '.........AAAAAAAA.........',
      '.......AAAAAAAAAA@A.......',
      '......AAAAAAAAAAAAAA......',
      '......aAAAAAAAAAAAAa......',
      '......a............a......',
    ],
  },
  curly: {
    dy: -4,
    rows: [
      '.........AA@AAAA..........',
      '.......AAAAAAAAAAAA.......',
      '......AAAAAAAAAAAAAA......',
      '.....AAAAAAAAAAAAAAAA.....',
      '.....AAAAAAAAAAAAAAAA.....',
      '.....aAAAAAAAAAAAAAAa.....',
      '.....aAA..........AAa.....',
      '......aa..........aa......',
    ],
  },
  fade: {
    dy: -1,
    rows: [
      '........AAAAAAAAAA........',
      '.......AAAAAAAAAA@A.......',
      '.......aaaAAAAAAaaa.......',
      '.......a..........a.......',
    ],
  },
  ponytail: {
    dy: -2,
    rows: [
      '.........AAAAAAAA.........',
      '.......AAAAAAAAAA@A.......',
      '......AAAAAAAAAAAAAA......',
      '......aAAAAAAAAAAAAaA.....',
      '......a............aAA....',
      '....................aA....',
      '....................aA....',
      '....................aA....',
      '.....................a....',
    ],
  },
  bald: {
    dy: 0,
    rows: ['........ZZZZZZZZZZ........'],
  },
  undercut: {
    dy: -3,
    rows: [
      '.........AAAAAAA..........',
      '........AAAAAAAAA@........',
      '.......AAAAAAAAAAAA.......',
      '......aaAAAAAAAAAAaa......',
      '......aa..........aa......',
    ],
  },
};

/** Accessories. */
const GLASSES = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '.......KKKK.KK.KKKK.......',
  '.......K..K....K..K.......',
  '.......KKKK....KKKK.......',
];
const GLASSES_ROUND = [
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '..........................',
  '.......kKKk.kk.kKKk.......',
  '.......K..K....K..K.......',
  '.......kKKk....kKKk.......',
];
const HEADSET = {
  dy: -3,
  rows: [
    '........kkkkkkkkkk........',
    '.......kk........kk.......',
    '......kk..........kk......',
    '......k............k......',
    '......k............k......',
    '......k............k......',
    '.....KK............KK.....',
    '.....KK............KK.....',
    '.....kk............kk.....',
  ],
};

/** Cuffs and hands resting on the desk edge, drawn in front of the desk. */
const HANDS_REST = [
  '.ccc.............ccc.',
  '.ccc.............ccc.',
  'sSSSs...........sSSSs',
  'sSSSs...........sSSSs',
  '.sss.............sss.',
];
const HANDS_TYPE_A = [
  '.ccc.............ccc.',
  'sSSSs............ccc.',
  'sSSSs...........sSSSs',
  '.sss............sSSSs',
  '.................sss.',
];
const HANDS_TYPE_B = [
  '.ccc.............ccc.',
  '.ccc............sSSSs',
  'sSSSs...........sSSSs',
  'sSSSs............sss.',
  '.sss.................',
];

/* ============================================================================
   Looks: who this person is (stable per agent) and what they wear (per role).
   ========================================================================== */

const COSTUMES = {
  Director:     { garment: 'navy',     second: 'white',   trim: 'mustard' },
  Researcher:   { garment: 'white',    second: 'teal',    trim: 'teal' },
  FactChecker:  { garment: 'olive',    second: 'cream',   trim: 'olive' },
  ScriptWriter: { garment: 'rust',     second: 'cream',   trim: 'rust' },
  VoiceArtist:  { garment: 'plum',     second: 'wine',    trim: 'plum', headset: true },
  VideoEditor:  { garment: 'charcoal', second: 'sky',     trim: 'sky' },
  Publisher:    { garment: 'mustard',  second: 'navy',    trim: 'mustard' },
  Analyst:      { garment: 'denim',    second: 'cream',   trim: 'denim' },
};

const GARMENT_KEYS = Object.keys(CLOTH);

/* ============================================================================
   Character Bible. The backend's `character_bible` records (GET /api/v1/media/character-bible)
   are the canonical description of each recurring employee: hair, glasses, headset, outfit
   colours. When an agent has a bible entry, its look follows the bible; the deterministic
   hash below only fills what the bible does not say (skin tone, idle timing).
   ========================================================================== */

const HONORIFICS = new Set(['dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.', 'prof', 'prof.']);

function firstName(name) {
  const words = String(name || '').toLowerCase().split(/[\s()]+/).filter(Boolean);
  return words.find((w) => !HONORIFICS.has(w)) || '';
}

/**
 * The bible entry for an agent: an explicit employee link wins; otherwise the first name of
 * the canonical name and of the agent's display name must agree. Null when nothing matches.
 */
export function matchBible(agent, bibles) {
  if (!agent || !Array.isArray(bibles) || !bibles.length) return null;
  const id = agent.id || agent.agent_id;
  const linked = bibles.find((b) => b && b.employee_id && b.employee_id === id);
  if (linked) return linked;
  const name = firstName(agent.display_name || agent.name);
  if (!name) return null;
  return bibles.find((b) => b && firstName(b.canonical_name) === name) || null;
}

const HEX = /^#[0-9a-f]{6}$/i;
const GARMENT_WORDS = ['suit', 'coat', 'blazer', 'jacket', 'vest', 'hoodie', 'sweater', 'shirt', 'blouse'];
const SECOND_WORDS = ['tie', 'shirt', 'blouse', 'tee', 'scarf', 'badge'];
const TRIM_WORDS = ['tie', 'headphones', 'headset', 'badge', 'glasses', 'scarf'];

function hairStyleFrom(text, fallback) {
  /** @type {Array<[RegExp, string]>} */
  const rules = [
    [/\bbun\b/, 'bun'], [/\bbob\b/, 'bob'], [/ponytail/, 'ponytail'], [/spiky|spiked/, 'undercut'],
    [/curly|wavy|tousled/, 'curly'], [/\blong\b|sleek/, 'long'], [/\bbald\b|shaved/, 'bald'],
    [/\bshort\b|\bcrop/, 'crop'],
  ];
  for (const [re, style] of rules) if (re.test(text)) return style;
  return fallback;
}

/**
 * Look overrides read from a bible entry. Pure: exported for tests. Colours come from
 * `palette_json` (hex only), styles and accessories from the descriptions.
 */
export function lookFromBible(entry) {
  if (!entry) return {};
  const pal = entry.palette_json && typeof entry.palette_json === 'object' ? entry.palette_json : {};
  const text = `${entry.face_hair_desc || ''} ${entry.outfit_desc || ''}`.toLowerCase();
  const color = (key) => (typeof pal[key] === 'string' && HEX.test(pal[key]) ? pal[key] : null);
  const firstColor = (words, skip = null) => {
    for (const w of words) if (w !== skip && color(w)) return [w, color(w)];
    return null;
  };
  const out = {};
  const hair = color('hair') || color('bun');
  if (hair) out.hair = ramp(hair, { dark: 0.55, light: 0.35 });
  out.hairStyle = hairStyleFrom(text, null);
  if (!out.hairStyle) delete out.hairStyle;
  const garment = firstColor(GARMENT_WORDS);
  if (garment) out.garment = ramp(garment[1]);
  const second = firstColor(SECOND_WORDS, garment ? garment[0] : null);
  if (second) out.second = ramp(second[1]);
  const trim = firstColor(TRIM_WORDS);
  if (trim) out.trim = ramp(trim[1]);
  if (/spectacles|glasses/.test(text)) out.glasses = /circular|round/.test(text) ? 'round' : 'square';
  if (/headset|headphones/.test(text)) out.headset = true;
  return out;
}

/** Stable, deterministic appearance for an agent; a bible entry overrides what it specifies. */
export function agentLook(agentId, roleName, bible = null) {
  const rnd = mulberry32(hash32(`${agentId}|${roleName || ''}`));
  const role = String(roleName || '').replace(/[^A-Za-z]/g, '');
  const costume = COSTUMES[role] || {
    garment: pick(GARMENT_KEYS, rnd),
    second: pick(GARMENT_KEYS, rnd),
    trim: pick(GARMENT_KEYS, rnd),
  };
  const hairStyle = pick(Object.keys(HAIR_STYLES), rnd);
  const base = {
    key: `${agentId}|${role}`,
    skin: pick(SKIN, rnd),
    hair: pick(HAIR, rnd),
    hairStyle,
    garment: CLOTH[costume.garment] || CLOTH.charcoal,
    second: CLOTH[costume.second] || CLOTH.cream,
    trim: CLOTH[costume.trim] || CLOTH.teal,
    glasses: rnd() > 0.6 ? (rnd() > 0.5 ? 'square' : 'round') : null,
    headset: Boolean(costume.headset) || rnd() > 0.85,
    phase: rnd() * TAU,
    blinkOffset: rnd() * 6,
    fidget: rnd(),
  };
  if (!bible) return base;
  return { ...base, ...lookFromBible(bible), key: `${base.key}|bible${bible.version || 1}|${bible.id || bible.canonical_name || ''}` };
}

function letterMap(look) {
  const [z, s, S, Z] = look.skin;
  const [a, A, , , at] = [look.hair[1], look.hair[2], look.hair[3], look.hair[4], look.hair[3]];
  const [D, c, C, B] = look.garment;
  return {
    z, s, S, Z,
    a, A, '@': at,
    D, c, C, B,
    X: look.second[2], x: look.second[1],
    N: CLOTH.white[3], n: CLOTH.white[1],
    K: '#dfe6f0', k: '#3a3a52',
    w: '#f6f2ea', e: AMBIENT.shadow, m: look.skin[1], b: look.hair[1],
  };
}

/** Sprite geometry: where the head and shoulders sit inside the compiled bitmap. */
const SPRITE_W = 26;
const HEAD_ROWS = 13;
const HAIR_MARGIN = 6;   // room above the head for the tallest hair
const OUTLINE = 1;

/**
 * Compile a body sprite for a look and a face state.
 * @param {'open'|'blink'|'sleep'|'talk'|'look'} face
 * @param {'up'|'down'} head  'down' lowers the head onto the chest (asleep)
 */
function bodySprite(look, face, head = 'up') {
  return cachedSprite(`body|${look.key}|${face}|${head}`, () => {
    const map = letterMap(look);
    const hairStyle = HAIR_STYLES[look.hairStyle] || HAIR_STYLES.short;
    const grid = new PixelGrid(SPRITE_W + OUTLINE * 2, BODY.length + HAIR_MARGIN + OUTLINE * 2);
    const ox = OUTLINE;
    const oy = HAIR_MARGIN + OUTLINE;
    const headDrop = head === 'down' ? 3 : 0;

    // Torso first, then the head over it (a lowered head must cover the collar).
    grid.blit(BODY_SHADED.slice(HEAD_ROWS), map, ox, oy + HEAD_ROWS);
    grid.blit(BODY.slice(0, HEAD_ROWS), map, ox, oy + headDrop);
    // Head volume: a lit forehead at the top-left, a shadow under the chin and along the jaw.
    grid.plot(ox + 8, oy + headDrop + 1, map.Z);
    grid.plot(ox + 9, oy + headDrop + 1, map.Z);
    grid.plot(ox + 7, oy + headDrop + 2, map.Z);
    for (let x = 9; x <= 16; x += 1) grid.plot(ox + x, oy + headDrop + 11, map.s);
    for (let x = 10; x <= 15; x += 1) grid.plot(ox + x, oy + headDrop + 12, map.s);
    grid.plot(ox + 18, oy + headDrop + 9, map.s);
    grid.plot(ox + 18, oy + headDrop + 10, map.s);

    // Garment details: a placket or lapels, always in the second colour.
    const detail = map.X;
    const shade = map.x;
    for (let y = 16; y < 24; y += 1) {
      grid.plot(ox + 12, oy + y, y % 2 ? detail : shade);
      grid.plot(ox + 13, oy + y, y % 2 ? shade : detail);
    }
    // Sleeve and shoulder highlights that mark the light from above.
    grid.plot(ox + 5, oy + 17, map.B);
    grid.plot(ox + 6, oy + 16, map.B);
    grid.plot(ox + 7, oy + 15, map.B);
    grid.plot(ox + 8, oy + 15, map.B);
    grid.plot(ox + 18, oy + 15, map.B);
    grid.plot(ox + 19, oy + 15, map.B);
    grid.plot(ox + 20, oy + 16, map.B);

    const faceRows = face === 'blink' ? FACE_BLINK : face === 'sleep' ? FACE_SLEEP : face === 'talk' ? FACE_TALK : face === 'look' ? FACE_LOOK : FACE_OPEN;
    grid.blit(faceRows, map, ox, oy + headDrop);
    // Brows.
    grid.plot(ox + 8, oy + headDrop + 4, map.b);
    grid.plot(ox + 9, oy + headDrop + 4, map.b);
    grid.plot(ox + 16, oy + headDrop + 4, map.b);
    grid.plot(ox + 17, oy + headDrop + 4, map.b);
    // Cheek warmth.
    grid.plot(ox + 7, oy + headDrop + 8, look.skin[1]);
    grid.plot(ox + 18, oy + headDrop + 8, look.skin[1]);

    grid.blit(hairStyle.rows, map, ox, oy + headDrop + hairStyle.dy);
    if (look.hairStyle !== 'bald') {
      // A second highlight next to the template's '@' so the hair reads as glossy, not flat.
      const hy = oy + headDrop + hairStyle.dy + 1;
      if (grid.at(ox + 9, hy) === map.A) grid.plot(ox + 9, hy, map['@']);
      if (grid.at(ox + 10, hy) === map.A) grid.plot(ox + 10, hy, map['@']);
    }
    if (look.glasses) grid.blit(look.glasses === 'round' ? GLASSES_ROUND : GLASSES, map, ox, oy + headDrop);
    if (look.headset) grid.blit(HEADSET.rows, map, ox, oy + headDrop + HEADSET.dy);

    grid.outline(AMBIENT.shadow);
    return grid.toCanvas();
  });
}

function handsSprite(look, frame) {
  return cachedSprite(`hands|${look.key}|${frame}`, () => {
    const map = letterMap(look);
    const rows = frame === 1 ? HANDS_TYPE_A : frame === 2 ? HANDS_TYPE_B : HANDS_REST;
    const grid = new PixelGrid(HANDS_REST[0].length + 2, rows.length + 2);
    grid.blit(rows, map, 1, 1);
    grid.outline(AMBIENT.shadow);
    return grid.toCanvas();
  });
}

function chinHandSprite(look) {
  return cachedSprite(`chin|${look.key}`, () => {
    const map = letterMap(look);
    const grid = new PixelGrid(9, 14);
    grid.blit(['..SSS..', '.SSSSs.', '.SSSSs.', '..sSs..', '..cCc..', '..cCc..', '..cCc..', '..cCc..', '..cCc..', '..ccc..'], map, 1, 1);
    grid.outline(AMBIENT.shadow);
    return grid.toCanvas();
  });
}

/* ---------------------------------------------------------------------------
   Atlas characters: the Blender-rendered parts (art-source/blender/characters.py), composited
   and recoloured per look. Used for zones drawn from the sprite atlas; the procedural sprites
   above remain the fallback and the art for every other floor.
   ------------------------------------------------------------------------- */

function atlasBodySprite(look, face, head = 'up') {
  return cachedSprite(`abody|${look.key}|${face}|${head}`, () => {
    const dy = head === 'down' ? 3 : 0;
    const list = [{ name: `body_${face}` }, { name: `hair_${look.hairStyle}`, dy }];
    if (look.glasses) list.push({ name: look.glasses === 'round' ? 'glasses_round' : 'glasses_square', dy });
    if (look.headset) list.push({ name: 'headset', dy });
    return compositeParts(list, look, AMBIENT.shadow);
  });
}

function atlasHandsSprite(look, pose) {
  return cachedSprite(`ahands|${look.key}|${pose}`, () => compositeParts([{ name: `hands_${pose}` }], look, AMBIENT.shadow));
}

const NEUTRAL_LOOK = { skin: SKIN[0], hair: HAIR[0], garment: CLOTH.charcoal, second: CLOTH.white, trim: CLOTH.white };

function atlasMugSprite() {
  return cachedSprite('amug', () => compositeParts([{ name: 'mug' }], NEUTRAL_LOOK, AMBIENT.shadow));
}

/** Head geometry of the atlas body: 14 x 13 px head whose top sits 30 px above the desk plane. */
const ATLAS_HEAD_TOP = 30;
const ATLAS_SHOULDERS = 16;

function mugSprite(color) {
  return cachedSprite(`mug|${color}`, () => {
    const grid = new PixelGrid(10, 8);
    grid.blit(['.MMMMM..', '.MMMMMh.', '.MMMMMh.', '.MMMMM..', '.mmmmm..'], { M: color, m: color, h: color }, 1, 1);
    grid.rect(2, 2, 5, 1, '#fff3d6');
    grid.outline(AMBIENT.shadow);
    return grid.toCanvas();
  });
}

/* ============================================================================
   Drawing
   ========================================================================== */

export const STATE_MODE = {
  WORKING: 'work',
  EXECUTING: 'work',
  RUNNING: 'work',
  THINKING: 'think',
  PLANNING: 'think',
  WAITING: 'idle',
  IDLE: 'idle',
};

export function modeForAgent(agent) {
  const lifecycle = String(agent.lifecycle || '').toUpperCase();
  if (lifecycle === 'PAUSED' || lifecycle === 'SUSPENDED' || lifecycle === 'TERMINATED') return 'sleep';
  const rs = String(agent.runtime_state || 'IDLE').toUpperCase();
  return STATE_MODE[rs] || 'idle';
}

/**
 * Where a seated character's parts land relative to the desk it sits at.
 *
 * deskTop is the y of the desk's top edge (its far edge, the one against the character).
 * The body sprite is anchored so the waist sits just below the desk plane and is hidden by it.
 */
export function characterMetrics(deskTop) {
  const waist = deskTop - 2;                // the desk plane hides everything below it
  const spriteBottom = waist;
  const bodyTop = spriteBottom - BODY.length;   // head row 0
  return { waist, bodyTop, headTop: bodyTop, headBottom: bodyTop + HEAD_ROWS, shoulders: bodyTop + 14 };
}

/**
 * Draw the seated body (everything above the desk). Hands are drawn separately with
 * drawCharacterHands after the desk so they rest on it.
 *
 * @param mode 'work' | 'think' | 'sleep' | 'idle' | 'talk'
 * @returns {{headX:number, headY:number, headW:number, headH:number, shoulders:number}}
 */
export function drawCharacterBody(ctx, cx, deskTop, look, mode, time, selected, talking = false, premium = false, screenLight = null) {
  const m = characterMetrics(deskTop);
  const sleeping = mode === 'sleep';
  const breathe = sleeping ? 0 : Math.round(Math.sin(time * 1.6 + look.phase) * 0.5 + 0.5) - 0;
  const blinkT = (time + look.blinkOffset) % 4.4;
  // Idle glance: every few seconds the eyes drift to the side for a moment.
  const glanceT = (time * 0.13 + look.fidget * 7) % 1;
  const glancing = mode === 'idle' && glanceT > 0.62 && glanceT < 0.74;
  const face = sleeping ? 'sleep' : blinkT < 0.12 ? 'blink' : talking && Math.sin(time * 9) > 0 ? 'talk' : glancing ? 'look' : 'open';

  if (premium && partsReady()) {
    const atlasSprite = atlasBodySprite(look, face, sleeping ? 'down' : 'up');
    if (atlasSprite) {
      const tilt = mode === 'think' ? 1 : 0;
      if (selected) glow(ctx, cx, m.headBottom, 44, 'rgba(255,207,122,0.55)', 0.8);
      drawSprite(ctx, atlasSprite.canvas, cx - atlasSprite.ax + tilt, deskTop - atlasSprite.ay - breathe);
      const headY = deskTop - ATLAS_HEAD_TOP + (sleeping ? 3 : 0) - breathe;
      return { headX: cx - 7 + tilt, headY, headW: 14, headH: HEAD_ROWS, shoulders: deskTop - ATLAS_SHOULDERS - breathe };
    }
  }
  const sprite = bodySprite(look, face, sleeping ? 'down' : 'up');

  // Idle fidget: a slow head tilt while thinking, a slight lean while sipping.
  const tilt = mode === 'think' ? 1 : 0;
  const x = cx - Math.round(sprite.width / 2) + tilt;
  const y = m.bodyTop - HAIR_MARGIN - OUTLINE - breathe;

  if (selected) {
    glow(ctx, cx, m.headBottom, 44, 'rgba(255,207,122,0.55)', 0.8);
  }
  drawSprite(ctx, sprite, x, y);
  if (screenLight && !sleeping) {
    // The monitor sits to the left of the seat: its light catches the near cheek and shoulder.
    ctx.save();
    ctx.globalAlpha = 0.22 + Math.sin(time * 5.3 + look.phase) * 0.05;
    ctx.fillStyle = screenLight;
    ctx.fillRect(cx - 7 + tilt, m.headTop + 4 - breathe, 1, 6);
    ctx.fillRect(cx - 6 + tilt, m.headTop + 9 - breathe, 1, 2);
    ctx.fillRect(cx - 11 + tilt, m.shoulders + 1 - breathe, 2, 5);
    ctx.restore();
  }

  return {
    headX: cx - 7 + tilt,
    headY: m.headTop - breathe + (sleeping ? 3 : 0),
    headW: 14,
    headH: HEAD_ROWS,
    shoulders: m.shoulders - breathe,
  };
}

/** Cuffs and hands on the desk edge; typing frames only when mode is 'work'. */
export function drawCharacterHands(ctx, cx, deskTop, look, mode, time, premium = false) {
  if (premium && partsReady() && drawAtlasHands(ctx, cx, deskTop, look, mode, time)) return;
  const map = letterMap(look);
  if (mode === 'sleep') {
    // Arms folded on the desk under the head.
    ctx.fillStyle = AMBIENT.shadow;
    ctx.fillRect(cx - 12, deskTop - 5, 24, 7);
    ctx.fillStyle = map.C;
    ctx.fillRect(cx - 11, deskTop - 4, 22, 5);
    ctx.fillStyle = map.B;
    ctx.fillRect(cx - 11, deskTop - 4, 22, 1);
    ctx.fillStyle = map.S;
    ctx.fillRect(cx - 3, deskTop - 3, 5, 3);
    return;
  }
  if (mode === 'think') {
    const hand = chinHandSprite(look);
    drawSprite(ctx, hand, cx + 4, deskTop - 22);
    // Only the far hand rests on the desk.
    const rest = handsSprite(look, 0);
    ctx.save();
    ctx.beginPath();
    ctx.rect(cx - 13, deskTop - 6, 12, 10);
    ctx.clip();
    drawSprite(ctx, rest, cx - 12, deskTop - 3);
    ctx.restore();
    return;
  }
  let frame = 0;
  if (mode === 'work') {
    const tick = Math.floor(time * 10 + look.phase * 3);
    frame = tick % 2 === 0 ? 1 : 2;
  } else {
    // Idle sip: the near hand lifts a mug every so often.
    const cycle = (time * 0.16 + look.fidget * 3) % 3;
    if (cycle > 1.1 && cycle < 1.7) {
      const lift = Math.sin(((cycle - 1.1) / 0.6) * Math.PI);
      const rest = handsSprite(look, 0);
      ctx.save();
      ctx.beginPath();
      ctx.rect(cx - 13, deskTop - 6, 12, 10);
      ctx.clip();
      drawSprite(ctx, rest, cx - 12, deskTop - 3);
      ctx.restore();
      const mug = mugSprite('#c9573f');
      const lifted = Math.round(lift * 12);
      drawSprite(ctx, mug, cx + 5, deskTop - 6 - lifted);
      ctx.fillStyle = map.S;
      ctx.fillRect(cx + 4, deskTop - 3 - lifted, 4, 3);
      // Steam curling off the coffee while the mug is up.
      for (let i = 0; i < 2; i += 1) {
        const t = (time * 0.9 + i * 0.5) % 1;
        ctx.globalAlpha = (1 - t) * 0.45 * lift;
        ctx.fillStyle = '#f2ece0';
        ctx.fillRect(cx + 7 + Math.round(Math.sin(t * 7 + i * 2) * 1.5), deskTop - 9 - lifted - Math.round(t * 7), 1, 1);
      }
      ctx.globalAlpha = 1;
      return;
    }
  }
  drawSprite(ctx, handsSprite(look, frame), cx - 12, deskTop - 3);
}

/** Atlas hands: same poses and timing as the procedural hands. Returns false if a part is missing. */
function drawAtlasHands(ctx, cx, deskTop, look, mode, time) {
  let pose = 'rest';
  if (mode === 'sleep') pose = 'sleep';
  else if (mode === 'think') pose = 'chin';
  else if (mode === 'work') pose = Math.floor(time * 10 + look.phase * 3) % 2 === 0 ? 'type_a' : 'type_b';
  else {
    const cycle = (time * 0.16 + look.fidget * 3) % 3;
    if (cycle > 1.1 && cycle < 1.7) {
      const lift = Math.sin(((cycle - 1.1) / 0.6) * Math.PI);
      const rest = atlasHandsSprite(look, 'rest');
      const mug = atlasMugSprite();
      if (!rest || !mug) return false;
      ctx.save();
      ctx.beginPath();
      ctx.rect(cx - 14, deskTop - 8, 13, 12);
      ctx.clip();
      drawSprite(ctx, rest.canvas, cx - rest.ax, deskTop - rest.ay);
      ctx.restore();
      const lifted = Math.round(lift * 12);
      drawSprite(ctx, mug.canvas, cx + 5 - mug.ax, deskTop - lifted - mug.ay);
      ctx.fillStyle = look.skin[2];
      ctx.fillRect(cx + 4, deskTop - 3 - lifted, 4, 3);
      return true;
    }
  }
  const s = atlasHandsSprite(look, pose);
  if (!s) return false;
  drawSprite(ctx, s.canvas, cx - s.ax, deskTop - s.ay);
  return true;
}

/** Status marks above the head: only for states the backend reports. */
export function drawStateMark(ctx, cx, headTop, mode, time) {
  if (mode === 'think') {
    const bob = Math.round(Math.sin(time * 2.2) * 1.5);
    const bx = cx + 12;
    const by = headTop - 16 + bob;
    // Thought bubble with a small pixel bulb.
    const bubble = cachedSprite('mark|think', () => {
      const g = new PixelGrid(18, 16);
      g.blit(
        [
          '....PPPPPPPP....',
          '..PPPPPPPPPPPP..',
          '.PPPPPPPPPPPPPP.',
          '.PPPPPYYYYPPPPP.',
          '.PPPPYYYYYYPPPP.',
          '.PPPPYYyYYYPPPP.',
          '.PPPPPYYYYPPPPP.',
          '.PPPPPPggPPPPPP.',
          '..PPPPPPPPPPPP..',
          '....PPPPPPPP....',
          '.....PP.........',
          '...PP...........',
        ],
        { P: UI.paper, Y: UI.thinking, y: '#fff6d0', g: '#8a6a3a' },
        1,
        1,
      );
      g.outline(AMBIENT.shadow);
      return g.toCanvas();
    });
    drawSprite(ctx, bubble, bx - 4, by - 10);
    glow(ctx, bx + 5, by - 3, 16, 'rgba(255,211,106,0.55)', 0.6);
  } else if (mode === 'sleep') {
    for (let i = 0; i < 3; i += 1) {
      const t = (time * 0.6 + i * 0.33) % 1;
      const zx = cx + 8 + t * 12;
      const zy = headTop - 8 - t * 16;
      const size = t < 0.5 ? 1 : 2;
      ctx.save();
      ctx.globalAlpha = 1 - t;
      drawZ(ctx, zx, zy, size, UI.paused);
      ctx.restore();
    }
  }
}

function drawZ(ctx, x, y, s, color) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), 3 * s, s);
  ctx.fillRect(Math.round(x) + 2 * s, Math.round(y) + s, s, s);
  ctx.fillRect(Math.round(x) + s, Math.round(y) + 2 * s, s, s);
  ctx.fillRect(Math.round(x), Math.round(y) + 3 * s, 3 * s, s);
}

/** The chair the character sits on: drawn before the body so the backrest shows behind it. */
export function drawChair(ctx, cx, deskTop, trim, seatColor) {
  const [d0, d1, d2, d3] = seatColor;
  // High back: 30 wide, rising behind the shoulders to the middle of the head, so the chair
  // reads around the seated figure; a headrest on top, lit edges top-left, shade right.
  const backTop = deskTop - 34;
  const backH = 32;
  ctx.fillStyle = AMBIENT.shadow;
  ctx.fillRect(cx - 14, backTop - 1, 28, backH + 2);
  ctx.fillRect(cx - 15, backTop + 1, 30, backH - 2);
  ctx.fillRect(cx - 9, backTop - 7, 18, 7);
  ctx.fillRect(cx - 10, backTop - 6, 20, 5);
  ctx.fillStyle = d2;
  ctx.fillRect(cx - 13, backTop, 26, backH);
  ctx.fillRect(cx - 14, backTop + 2, 28, backH - 4);
  ctx.fillRect(cx - 8, backTop - 6, 16, 6);
  ctx.fillRect(cx - 9, backTop - 5, 18, 4);
  ctx.fillStyle = d3;
  ctx.fillRect(cx - 12, backTop, 24, 1);
  ctx.fillRect(cx - 14, backTop + 2, 1, backH - 6);
  ctx.fillRect(cx - 7, backTop - 6, 14, 1);
  ctx.fillRect(cx - 9, backTop - 5, 1, 3);
  ctx.fillStyle = d1;
  ctx.fillRect(cx + 12, backTop + 3, 2, backH - 7);
  ctx.fillRect(cx + 8, backTop - 5, 1, 4);
  ctx.fillRect(cx - 13, backTop + backH - 2, 26, 2);
  // Stitch lines across the back and the headrest.
  ctx.fillRect(cx - 8, backTop + 9, 16, 1);
  ctx.fillRect(cx - 8, backTop + 19, 16, 1);
  ctx.fillStyle = d0;
  ctx.fillRect(cx - 14, backTop + backH - 3, 28, 1);
  // Post between headrest and back.
  ctx.fillStyle = trim[1];
  ctx.fillRect(cx - 2, backTop - 1, 4, 2);
  // Armrests.
  ctx.fillStyle = AMBIENT.shadow;
  ctx.fillRect(cx - 17, deskTop - 9, 6, 4);
  ctx.fillRect(cx + 11, deskTop - 9, 6, 4);
  ctx.fillStyle = trim[2];
  ctx.fillRect(cx - 16, deskTop - 8, 4, 2);
  ctx.fillRect(cx + 12, deskTop - 8, 4, 2);
  ctx.fillStyle = trim[4];
  ctx.fillRect(cx - 16, deskTop - 8, 4, 1);
  ctx.fillRect(cx + 12, deskTop - 8, 4, 1);
}

export { BODY as CHARACTER_BODY_ROWS, HAIR_STYLES, SPRITE_W as CHARACTER_SPRITE_W, contactShadow };
