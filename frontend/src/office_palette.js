/**
 * Office palette — the single colour source for the 2D scene.
 *
 * Modern pixel art lives or dies on its ramps: every material is a short run of tones whose
 * hue shifts as it darkens (shadows lean towards the ambient blue-violet, highlights towards
 * the warm lamp light). Nothing in the scene may pick a colour outside these ramps, which is
 * what keeps a walnut desk, a cotton shirt and a concrete floor looking like they share one
 * room and one light.
 *
 * Ramps are indexed darkest -> lightest:  [0] deep shadow · [1] shadow · [2] base · [3] light · [4] highlight
 *
 * Nothing here reads backend state. Colours never encode data.
 */

/* ------------------------------------------------------------------ helpers */

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function rgbToHex([r, g, b]) {
  const c = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** Linear mix of two hex colours; t in [0,1]. */
export function mix(a, b, t) {
  const A = hexToRgb(a);
  const B = hexToRgb(b);
  return rgbToHex([A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t]);
}

/** Hex colour with an alpha byte appended, alpha in [0,1]. */
export function withAlpha(hex, alpha) {
  const a = Math.max(0, Math.min(255, Math.round(alpha * 255))).toString(16).padStart(2, '0');
  return `${hex.slice(0, 7)}${a}`;
}

/** rgba() string for gradients, alpha in [0,1]. */
export function rgba(hex, alpha) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** The ambient colours every ramp bends towards. */
export const AMBIENT = {
  shadow: '#1a1630',   // deep violet-navy: night, corners, outlines
  light: '#ffe6b0',    // warm tungsten: lamps, screens' edge light, highlights
};

/**
 * Build a five-tone ramp around a base colour with hue-shifted ends: the dark end mixes
 * into the ambient shadow, the light end into the ambient light.
 */
export function ramp(base, { dark = 0.62, light = 0.42 } = {}) {
  return [
    mix(base, AMBIENT.shadow, dark),
    mix(base, AMBIENT.shadow, dark * 0.5),
    base,
    mix(base, AMBIENT.light, light * 0.5),
    mix(base, AMBIENT.light, light),
  ];
}

/* ------------------------------------------------------------------ exterior */

export const SKY = {
  zenith: '#0b1020',
  upper: '#14203a',
  band: '#243a58',
  dusk: '#5c4a58',
  horizon: '#a8735a',
  star: '#f4ecd6',
  moon: '#f5ecd2',
  moonSea: '#d8cbaa',
  // daytime counterparts, mixed in by the street clock's daylight value
  dayZenith: '#5d8fc9',
  dayUpper: '#8fb8dc',
  dayBand: '#bcd6e2',
  dayHorizon: '#eadfb9',
};

export const CITY = {
  far: '#1a2140',
  farTop: '#28305a',
  mid: '#131a30',
  midTop: '#1f2848',
  near: '#0e1224',
  windowWarm: '#f4c77a',
  windowCool: '#9fd0e8',
  windowDim: '#5a5468',
  beacon: '#ff6a5a',
};

export const STREET = {
  asphalt: ramp('#262a3a', { dark: 0.5, light: 0.25 }),
  pavement: ramp('#3a3f52', { dark: 0.5, light: 0.3 }),
  kerb: ramp('#565a6e', { dark: 0.5, light: 0.3 }),
  plinth: ramp('#463a44', { dark: 0.5, light: 0.3 }),
  line: '#d8c07a',
  crossing: '#8a8ca0',
  lampPost: ramp('#3a3f52'),
  lampGlow: '#ffcf8a',
  trunk: ramp('#4a3528'),
  leaf: ['#16352c', '#22513c', '#33734f', '#4f9560', '#86bd78'],
  planter: ramp('#5a4a44'),
};

/* ------------------------------------------------------------------ building */

/** Warm limestone piers and slabs, the frame the cutaway sits in. */
export const FACADE = {
  stone: ['#2e2536', '#4d3e4a', '#7a6560', '#a88c78', '#d3b898'],
  slab: ['#2a2130', '#4a3c44', '#6e5c5a', '#9c8676', '#cfb69a'],
  mullion: ['#1a1630', '#2e2a44', '#4a4660', '#6b6784', '#8f8aa8'],
  glass: ['#101a2c', '#182a44', '#244060', '#3a6a88', '#7fb6cc'],
  roof: ['#1c1826', '#2c283a', '#40394e', '#5a5268', '#7c7490'],
  neon: '#ffcf7a',
  neonCore: '#fff3d6',
  signBoard: ['#120f1e', '#1e1a30', '#2c2744', '#3f3a5c', '#5a5478'],
};

/* ------------------------------------------------------------------ interior */

/** Shared interior materials: the same wood, metal and fabric appear on every floor. */
export const MAT = {
  walnut: ['#2a1a18', '#4a2c26', '#6e4434', '#96634a', '#c48f6a'],
  oak: ['#3a2a1a', '#6a4a2c', '#9a6d40', '#c09258', '#e2bd82'],
  ash: ['#3f3a3c', '#6e6360', '#a49386', '#c9b9a5', '#e9dcc4'],
  steel: ['#1c1a2c', '#343348', '#545468', '#7e7e94', '#b0b0c2'],
  chrome: ['#2a2a3c', '#5a5c72', '#8d90a8', '#c1c4d6', '#f0f2f8'],
  black: ['#0f0d1a', '#1c1a2c', '#2a2840', '#3d3a56', '#56526e'],
  paper: ['#8a8474', '#b8b19c', '#e2dbc4', '#f2ecd8', '#fffaea'],
  screen: ['#0a1018', '#0f1c28', '#132a3a', '#1c3f52', '#2a5a70'],
  glass: ['#1a2c3a', '#2a4a5c', '#3f6c80', '#6a9cae', '#a6d2dc'],
  felt: ['#1d2a26', '#2c4038', '#3d5a4c', '#527663', '#6f9a80'],
  fabricBlue: ['#1d2438', '#2c3654', '#3d4c74', '#56689a', '#7d8fc0'],
  fabricRed: ['#3a1c22', '#5c2c34', '#864050', '#ab5c6a', '#d0838c'],
  fabricOlive: ['#2a2c1c', '#42462a', '#5e6438', '#7e864c', '#a4ac6a'],
  leather: ['#231816', '#3c2620', '#5a3a2e', '#7a5240', '#9c6f58'],
  terracotta: ['#4a2a22', '#7a4030', '#a85a3e', '#cd7a55', '#e9a37c'],
  brass: ['#4a3618', '#7a5a22', '#b48a34', '#dcb054', '#f4d98a'],
  ceramic: ['#5a5a66', '#8c8c98', '#c2c2cc', '#e2e2ea', '#f8f8fc'],
  plant: ['#173226', '#20503a', '#2f7a50', '#4aa063', '#83c47c'],
  concrete: ['#2a2a3a', '#3f3f52', '#5a5a70', '#7c7c92', '#a0a0b4'],
  carpet: ['#22203a', '#302c4a', '#3f3a5c', '#524c72', '#6a6488'],
  foam: ['#1e1630', '#2c2244', '#3a2e58', '#4c3e70', '#5f5088'],
  tileWhite: ['#5a5c6c', '#8c8e9c', '#bfc1cc', '#dcdde4', '#f4f4f8'],
  tileMint: ['#2f4a44', '#4c6e64', '#6e9488', '#94b8aa', '#bcd8cc'],
};

/** Skin, hair and clothing ramps for characters. All hue-shifted, none grey. */
export const SKIN = [
  ['#7a4a3e', '#b07c60', '#e8b48c', '#f6cfae', '#fde5cc'],
  ['#6a3e30', '#9c6446', '#d19a72', '#e6b48c', '#f2caa6'],
  ['#4e2c22', '#7e4c36', '#b07852', '#c99268', '#dcab84'],
  ['#3a2018', '#5e3826', '#8a5a3c', '#a67450', '#bd8c66'],
  ['#2a160f', '#472a1c', '#6a4430', '#845a42', '#9e7258'],
  ['#1e100a', '#331e14', '#4e3224', '#644432', '#7a5844'],
];

export const HAIR = [
  ['#120c14', '#1e1420', '#2c1c2e', '#3e2a40', '#56405a'],   // black
  ['#2a160e', '#43241a', '#5e3626', '#7a4c36', '#9a6a50'],   // dark brown
  ['#4a2a12', '#6e4220', '#946034', '#b8804c', '#d8a26a'],   // chestnut
  ['#6a4a1c', '#9a7030', '#c89a48', '#e0bc6a', '#f2d68e'],   // blonde
  ['#4a1c18', '#7a2e26', '#a8443a', '#c8604e', '#e08470'],   // auburn
  ['#2c2c3a', '#4c4c5c', '#7a7a8c', '#a4a4b4', '#d0d0dc'],   // silver
  ['#1a2438', '#243a58', '#345680', '#4c7aa8', '#6aa0cc'],   // blue dye
  ['#3a1a34', '#5c2a56', '#864080', '#a85ca4', '#cc82c8'],   // violet dye
];

export const CLOTH = {
  navy: ['#151a30', '#222a4c', '#303c68', '#465490', '#6a7ab0'],
  charcoal: ['#16141f', '#25222f', '#37333f', '#4d4858', '#6a6478'],
  cream: ['#7a6c58', '#b3a284', '#e0cfa8', '#f0e2c2', '#fbf2dc'],
  teal: ['#0e2e30', '#174a4a', '#22696a', '#3a8e8c', '#63b2ad'],
  rust: ['#3a1a12', '#5e2a1a', '#8c4028', '#b45a3a', '#d8805a'],
  olive: ['#242a14', '#3b4420', '#556232', '#748448', '#98a866'],
  plum: ['#2a1630', '#44244c', '#63366c', '#844e8c', '#a86eaf'],
  mustard: ['#4a3a10', '#7a5c18', '#b08a28', '#d0ac48', '#e8c86e'],
  sky: ['#1c3446', '#2c5470', '#3f7a9a', '#5ea0c0', '#8cc4dc'],
  wine: ['#2c1018', '#4c1a28', '#722840', '#943a58', '#b85a78'],
  white: ['#8a8898', '#b8b6c4', '#e4e2ea', '#f2f0f6', '#fcfbff'],
  denim: ['#182034', '#243050', '#324470', '#465e90', '#6a82b0'],
  brown: ['#2c1c12', '#4a3020', '#6c4830', '#8c6444', '#ac8460'],
};

/* ------------------------------------------------------------ departments */

/**
 * Each department is one material story: a wall finish, a floor finish, an accent that
 * lights its screens and labels, and a signature colour for its people's work-wear.
 * The names are display labels only; the backend zone_type is the key.
 */
export const DEPARTMENTS = {
  DIRECTOR: {
    name: 'EXECUTIVE',
    accent: '#f0c46a',
    wall: ['#1c2a2a', '#25403c', '#2f5650', '#3f6c64', '#5a8a80'],
    wallStyle: 'panelled',
    floor: MAT.walnut,
    floorStyle: 'planks',
    trim: MAT.brass,
    lamp: '#ffd89a',
  },
  RESEARCH: {
    name: 'RESEARCH',
    accent: '#5ee0c8',
    wall: ['#1f2438', '#2c3452', '#3a4568', '#4c5a86', '#6a7aa8'],
    wallStyle: 'plaster',
    floor: MAT.tileMint,
    floorStyle: 'tiles',
    trim: MAT.ash,
    lamp: '#e8f4ff',
  },
  SCRIPT: {
    name: 'WRITING',
    accent: '#ffb35c',
    wall: ['#3a2a1c', '#5a4028', '#7a5836', '#9a7448', '#c0955e'],
    wallStyle: 'plaster',
    floor: MAT.oak,
    floorStyle: 'planks',
    trim: MAT.walnut,
    lamp: '#ffd08a',
  },
  AUDIO: {
    name: 'AUDIO',
    accent: '#e08ae4',
    wall: ['#1e1630', '#2c2044', '#3c2c5c', '#4e3c74', '#66528e'],
    wallStyle: 'foam',
    floor: MAT.carpet,
    floorStyle: 'carpet',
    trim: MAT.black,
    lamp: '#e8b8ff',
  },
  VIDEO: {
    name: 'VIDEO',
    accent: '#6cc0ff',
    wall: ['#151a28', '#1f2740', '#2a3656', '#3a4a70', '#526890'],
    wallStyle: 'panelled',
    floor: MAT.concrete,
    floorStyle: 'rubber',
    trim: MAT.steel,
    lamp: '#cfe6ff',
  },
  SERVER: {
    name: 'INFRA',
    accent: '#7ff08a',
    wall: ['#121a22', '#1a2632', '#233444', '#2f4658', '#446078'],
    wallStyle: 'steel',
    floor: MAT.tileWhite,
    floorStyle: 'raised',
    trim: MAT.steel,
    lamp: '#d8ffe8',
  },
  LOUNGE: {
    name: 'COMMONS',
    accent: '#ff9a76',
    wall: ['#3a2422', '#5a3a34', '#7a5044', '#9c6a5a', '#c08c74'],
    wallStyle: 'brick',
    floor: MAT.oak,
    floorStyle: 'herringbone',
    trim: MAT.walnut,
    lamp: '#ffcf9a',
  },
  PUBLISH: {
    name: 'DISTRIBUTION',
    accent: '#ff7e5c',
    wall: ['#2a1e1c', '#403030', '#584444', '#725a58', '#907670'],
    wallStyle: 'panelled',
    floor: MAT.concrete,
    floorStyle: 'concrete',
    trim: MAT.steel,
    lamp: '#ffd8b8',
  },
  SHOP: {
    name: 'AD SPACE',
    accent: '#ffcf5c',
    wall: ['#241a12', '#3a2c1c', '#4e3c28', '#664f36', '#846848'],
    wallStyle: 'plaster',
    floor: MAT.tileWhite,
    floorStyle: 'checker',
    trim: MAT.brass,
    lamp: '#ffe2a0',
  },
  DEFAULT: {
    name: 'STUDIO',
    accent: '#bfc8d8',
    wall: ['#1e2230', '#2c3244', '#3c4458', '#505a72', '#6c7890'],
    wallStyle: 'plaster',
    floor: MAT.concrete,
    floorStyle: 'concrete',
    trim: MAT.steel,
    lamp: '#f0f0ff',
  },
};

export const department = (zoneType) => DEPARTMENTS[zoneType] || DEPARTMENTS.DEFAULT;

/** Status and signage colours shared by chips, bubbles and marks. */
export const UI = {
  ink: '#1a1630',
  paper: '#fbf6e6',
  paperShade: '#d9d0b6',
  chip: '#15122a',
  chipEdge: '#3a3560',
  chipText: '#f3eee0',
  working: '#7ff08a',
  thinking: '#ffd36a',
  idle: '#a7b6c8',
  paused: '#8a86a8',
  selected: '#ffcf7a',
  red: '#ff6a5a',
  amber: '#ffb35c',
  green: '#7ff08a',
};
