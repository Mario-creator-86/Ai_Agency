import { paneMode, roomOccupancy, screenLight } from './hq_screens.js';
import { keptDay } from './stream_keep.js';

/**
 * «RELUAREA ZILEI» IN THE UNREAL BUILDING (W22).
 *
 * With the stream configured, the replay used to play in the page's own renderer: a visitor saw
 * the Unreal building live, then a different, graded building for the replay, then Unreal again.
 * The replay now plays over a still of the real Unreal building — the live video's frame taken at
 * the replay's door, else the frame this browser kept (stream_keep.js) — graded as the replay's
 * look, with the replay's own layers drawn over it where the photograph shows their objects:
 * the rooms' light rising and falling over the photograph's rooms, the monitors' state as glows
 * over the desks, the world's tags and captions at the figures, the shelter's clock under ATUNCI,
 * and (in the page, stream_plaques.js) the plaques with the books as they stood.
 *
 * A photograph cannot carry everything the record says. Its light and its weather are those of the
 * hour it was taken, not of the replayed moment: the page says so in words under ATUNCI
 * (stillLine) instead of repainting the sky. Its figures are the ones seated now; what each one did
 * then is said by the tags and captions, as in the page's own replay.
 *
 * Every anchor below was measured on a raw frame of the live stream (1920x1008, laid exactly over
 * the world's 1600x840 px, game_frame.js streamTransform), 2026-09-25 00:47, scratchpad
 * ui/w22/probe/raw.png with measure_anchors.py: the rooms' lit interiors (the strongest luminance
 * step within 14 px of the manifest's edges; where the step was weak, the manifest's edge, which
 * the Unreal building was built to), the lit face of each desk's monitor, and the shelter clock's
 * dark panel.
 */

/**
 * The rooms of the Unreal building, world px [x, y, w, h]. The upper floors keep the manifest's
 * walls (measured steps 6-46, the decoration bars stood nearer) with the measured floor and
 * ceiling; the ground floor is measured whole (steps 65-163), under its name band.
 * @type {Record<string, [number, number, number, number]>}
 */
export const STREAM_ROOMS = {
  director_suite: [517, 86, 688, 94],
  research_lab: [517, 195, 345, 90],
  factcheck_room: [868, 195, 337, 90],
  script_room: [517, 297, 345, 98],
  publish_desk: [868, 297, 337, 98],
  audio_booth: [517, 410, 345, 92],
  video_studio: [867, 410, 338, 92],
  server_corner: [448, 520, 196, 138],
  lobby: [642, 520, 256, 138],
  accounting_office: [895, 520, 137, 138],
  ad_shop: [1042, 520, 159, 138],
};

/**
 * The lit face of each desk's monitor in the Unreal building, world px (centre), by desk: the
 * centroid of the brightest 4 % of a 32 px window around the manifest's monitor.
 * @type {Record<string, [number, number]>}
 */
export const STREAM_MONITORS = {
  desk_director: [821.3, 147.5],
  desk_research_1: [680.2, 258.6],
  desk_research_2: [917.7, 251.1],
  desk_script: [813.1, 368.2],
  desk_publish: [1009.1, 368.4],
  desk_audio: [677.8, 474.8],
  desk_video: [1008.5, 469.9],
  desk_accounting: [956.5, 623.7],
};

/** The bus shelter's clock panel in the photograph, world px: it shows the live hour (00:47). */
export const STREAM_SHELTER_CLOCK = /** @type {[number, number, number, number]} */ ([1408.5, 619, 72, 37.5]);

/** How long a room's light takes to rise or fall most of the way to the replayed occupancy. */
export const ROOM_EASE_MS = 420;

/**
 * How far a room of the photograph is lowered for its replayed occupancy (0 = as photographed).
 * Deeper than the plates' own ROOM_SHADE for a room where someone sits: the photograph was taken
 * live, with every room Unreal lights on, and the replay's rooms must read as the record's.
 */
export const STILL_SHADE = { night: { working: 0, present: 0.32, empty: 0.5 }, day: { working: 0, present: 0.08, empty: 0.16 } };

/**
 * A room's light over the photograph for its replayed occupancy, at the photograph's own daylight:
 * `shade` is the dark laid over the room, `lift` the warm light poured down a room where someone
 * works (softer by day, when the rooms are lit already).
 * @param {'working'|'present'|'empty'} occupancy @param {number} daylight 0 night .. 1 day
 */
export function roomLight(occupancy, daylight) {
  const d = Math.max(0, Math.min(1, Number(daylight) || 0));
  const night = STILL_SHADE.night[occupancy] ?? 0;
  const day = STILL_SHADE.day[occupancy] ?? 0;
  const shade = Math.round((night + (day - night) * d) * 1000) / 1000;
  const lift = occupancy === 'working' ? Math.round((0.26 - 0.14 * d) * 1000) / 1000 : 0;
  return { shade, lift };
}

/**
 * One step of a light toward its target: most of the way in ROOM_EASE_MS, time-corrected; at once
 * under reduced motion (the same frames, without the animation).
 * @param {number} current @param {number} target @param {number} dtMs @param {boolean} reduced
 */
export function easeToward(current, target, dtMs, reduced) {
  if (reduced || !Number.isFinite(current)) return target;
  const k = 1 - Math.exp(-Math.max(0, dtMs) / (ROOM_EASE_MS / 3));
  const next = current + (target - current) * k;
  return Math.abs(target - next) < 0.002 ? target : next;
}

/**
 * The glow a desk's monitor casts for its employee's state: none on a dark desk, red for an error,
 * brightest while the employee works (the page renderer's own strengths, drawDeskMonitors).
 * @param {'work'|'think'|'error'|'idle'|'dark'|string} mode hq_screens.js paneMode
 * @returns {{rgb: string, strength: number}|null}
 */
export function monitorGlow(mode) {
  if (mode === 'dark') return null;
  if (mode === 'error') return { rgb: '239,68,68', strength: 0.34 };
  if (mode === 'work') return { rgb: '120,170,255', strength: 0.42 };
  if (mode === 'think') return { rgb: '120,170,255', strength: 0.28 };
  return { rgb: '120,170,255', strength: 0.12 };
}

/**
 * The room levels the photograph is lit by at this frame, eased toward the replayed occupancy.
 * Pure: `levels` is the previous frame's, and a new object is returned.
 * @param {Record<string, {shade: number, lift: number}>} levels
 * @param {any[]} agents the replayed employees @param {(agent: any) => string|null} zoneOf
 * @param {number} daylight the photograph's @param {number} dtMs @param {boolean} reduced
 */
export function roomLevels(levels, agents, zoneOf, daylight, dtMs, reduced) {
  /** @type {Record<string, {shade: number, lift: number, occupancy: string}>} */
  const out = {};
  const seated = new Set(Object.values(STREAM_SEATED));
  for (const zone of Object.keys(STREAM_ROOMS)) {
    if (!seated.has(zone)) continue;
    const occupancy = roomOccupancy((agents || []).filter((a) => zoneOf(a) === zone));
    const target = roomLight(occupancy, daylight);
    const was = levels[zone];
    out[zone] = {
      occupancy,
      shade: was ? easeToward(was.shade, target.shade, dtMs, reduced) : target.shade,
      lift: was ? easeToward(was.lift, target.lift, dtMs, reduced) : target.lift,
    };
  }
  return out;
}

/** Which room each desk is in (the manifest's seats; a room without a desk takes no light). */
export const STREAM_SEATED = {
  desk_director: 'director_suite',
  desk_research_1: 'research_lab',
  desk_research_2: 'factcheck_room',
  desk_script: 'script_room',
  desk_publish: 'publish_desk',
  desk_audio: 'audio_booth',
  desk_video: 'video_studio',
  desk_accounting: 'accounting_office',
};

/**
 * The monitors' glows for the replayed employees: one per occupied desk, where the photograph's
 * monitor is.
 * @param {any[]} agents
 * @returns {Array<{desk: string, x: number, y: number, rgb: string, strength: number}>}
 */
export function monitorGlows(agents) {
  const out = [];
  for (const agent of agents || []) {
    const at = agent && STREAM_MONITORS[agent.desk_id];
    if (!at) continue;
    const glow = monitorGlow(paneMode(agent));
    if (glow) out.push({ desk: agent.desk_id, x: at[0], y: at[1], ...glow });
  }
  return out;
}

/** How brightly a monitor's glow reads in the photograph's light (by day the sun washes it). @param {number} daylight */
export function glowBloom(daylight) {
  return Math.round((0.45 + 0.55 * screenLight(daylight).bloom) * 1000) / 1000;
}

/**
 * «de azi, 00:47», «de ieri, 21:05», «de sâmbătă, 12:30», «din 12.09, 23:59».
 * @param {number} at @param {number} now @param {string} [timeZone]
 */
function frameWhen(at, now, timeZone) {
  const when = keptDay(at, now, timeZone);
  if (!when) return '';
  return `${when.dated ? 'din' : 'de'} ${when.day}, ${when.hm}`;
}

/**
 * The replay's line under ATUNCI over the photograph (glossary W22): what the picture is, and that
 * its light and weather are not the replayed moment's.
 * @param {number} at when the photograph was taken @param {number} now @param {string} [timeZone]
 */
export function stillLine(at, now, timeZone) {
  const when = frameWhen(at, now, timeZone);
  return when ? `cadru live ${when} · lumina și vremea nu sunt cele de atunci` : '';
}

/**
 * The same, said once to a screen reader when the replay starts.
 * @param {number} at @param {number} now @param {string} [timeZone]
 */
export function stillSentence(at, now, timeZone) {
  const when = frameWhen(at, now, timeZone);
  return when ? `Clădirea este cadrul live ${when}; lumina și vremea lui nu sunt cele de atunci.` : '';
}

/**
 * Whether the replay can play in the Unreal building: a stream is configured and the page holds a
 * real picture of it (the live video, a frozen frame, or the kept one).
 * @param {{configured: boolean, picture: {width: number, height: number}|null|undefined}} s
 */
export function replayInUnreal(s) {
  return Boolean(s.configured && s.picture && s.picture.width > 0 && s.picture.height > 0);
}
