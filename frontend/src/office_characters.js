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
import { SKIN, HAIR, CLOTH, UI, AMBIENT, withAlpha } from './office_palette.js';

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

/** Stable, deterministic appearance for an agent. */
export function agentLook(agentId, roleName) {
  const rnd = mulberry32(hash32(`${agentId}|${roleName || ''}`));
  const role = String(roleName || '').replace(/[^A-Za-z]/g, '');
  const costume = COSTUMES[role] || {
    garment: pick(GARMENT_KEYS, rnd),
    second: pick(GARMENT_KEYS, rnd),
    trim: pick(GARMENT_KEYS, rnd),
  };
  const hairStyle = pick(Object.keys(HAIR_STYLES), rnd);
  return {
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
 * @param {'open'|'blink'|'sleep'|'talk'} face
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
    grid.blit(BODY.slice(HEAD_ROWS), map, ox, oy + HEAD_ROWS);
    grid.blit(BODY.slice(0, HEAD_ROWS), map, ox, oy + headDrop);

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

    const faceRows = face === 'blink' ? FACE_BLINK : face === 'sleep' ? FACE_SLEEP : face === 'talk' ? FACE_TALK : FACE_OPEN;
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
export function drawCharacterBody(ctx, cx, deskTop, look, mode, time, selected, talking = false) {
  const m = characterMetrics(deskTop);
  const sleeping = mode === 'sleep';
  const breathe = sleeping ? 0 : Math.round(Math.sin(time * 1.6 + look.phase) * 0.5 + 0.5) - 0;
  const blinkT = (time + look.blinkOffset) % 4.4;
  const face = sleeping ? 'sleep' : blinkT < 0.12 ? 'blink' : talking && Math.sin(time * 9) > 0 ? 'talk' : 'open';
  const sprite = bodySprite(look, face, sleeping ? 'down' : 'up');

  // Idle fidget: a slow head tilt while thinking, a slight lean while sipping.
  const tilt = mode === 'think' ? 1 : 0;
  const x = cx - Math.round(sprite.width / 2) + tilt;
  const y = m.bodyTop - HAIR_MARGIN - OUTLINE - breathe;

  if (selected) {
    glow(ctx, cx, m.headBottom, 44, 'rgba(255,207,122,0.55)', 0.8);
  }
  drawSprite(ctx, sprite, x, y);

  return {
    headX: cx - 7 + tilt,
    headY: m.headTop - breathe + (sleeping ? 3 : 0),
    headW: 14,
    headH: HEAD_ROWS,
    shoulders: m.shoulders - breathe,
  };
}

/** Cuffs and hands on the desk edge; typing frames only when mode is 'work'. */
export function drawCharacterHands(ctx, cx, deskTop, look, mode, time) {
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
      drawSprite(ctx, mug, cx + 5, deskTop - 6 - Math.round(lift * 12));
      ctx.fillStyle = map.S;
      ctx.fillRect(cx + 4, deskTop - 3 - Math.round(lift * 12), 4, 3);
      return;
    }
  }
  drawSprite(ctx, handsSprite(look, frame), cx - 12, deskTop - 3);
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
  const backTop = deskTop - 22;
  const [d0, d1, d2, d3] = seatColor;
  // Backrest: a rounded upholstered panel, lit along its top edge.
  ctx.fillStyle = AMBIENT.shadow;
  ctx.fillRect(cx - 12, backTop - 1, 24, 22);
  ctx.fillRect(cx - 13, backTop + 1, 26, 18);
  ctx.fillStyle = d2;
  ctx.fillRect(cx - 11, backTop, 22, 20);
  ctx.fillRect(cx - 12, backTop + 2, 24, 16);
  ctx.fillStyle = d3;
  ctx.fillRect(cx - 10, backTop, 20, 1);
  ctx.fillRect(cx - 12, backTop + 2, 1, 14);
  ctx.fillStyle = d1;
  ctx.fillRect(cx - 11, backTop + 18, 22, 2);
  ctx.fillRect(cx + 10, backTop + 3, 2, 14);
  // Stitch line.
  ctx.fillRect(cx - 7, backTop + 7, 14, 1);
  ctx.fillStyle = d0;
  ctx.fillRect(cx - 12, backTop + 17, 24, 1);
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
