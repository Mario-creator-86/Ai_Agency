/**
 * Where the studio stands and what time it is there.
 *
 * The place comes from the studio's own settings (STUDIO_TIMEZONE, STUDIO_OFFICE_LATITUDE,
 * STUDIO_OFFICE_LONGITUDE, STUDIO_OFFICE_CITY, STUDIO_HOLIDAY_COUNTRY), served in the snapshot
 * as `studio.location` and handed here by main.js once it has read it (setStudioPlace). Until
 * then, and for any value the snapshot does not carry or carries broken, the place is
 * Bucharest: the first studio's own, kept only as the fallback (SELL-08, PAGE-13). The time
 * uses the browser's timezone database, including seasonal DST.
 */

/** @typedef {{timeZone: string, lat: number, lon: number, city: string, holidayCountry: string, studioName: string}} StudioPlace */

/** @type {Readonly<StudioPlace>} */
export const DEFAULT_PLACE = Object.freeze({
  timeZone: 'Europe/Bucharest',
  lat: 44.4268,
  lon: 26.1025,
  city: 'București',
  holidayCountry: 'RO',
  studioName: 'AMN-AI',
});

/** @type {Readonly<StudioPlace>} */
let current = DEFAULT_PLACE;

/** @type {Map<string, Intl.DateTimeFormat>} */
const formatters = new Map();

/** @param {string} timeZone */
function formatterFor(timeZone) {
  let formatter = formatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    formatters.set(timeZone, formatter);
  }
  return formatter;
}

/** @param {unknown} zone */
function validZone(zone) {
  if (typeof zone !== 'string' || !zone) return false;
  try {
    formatterFor(zone);
    return true;
  } catch {
    return false;
  }
}

/** @param {unknown} value @param {number} limit */
function inRange(value, limit) {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= limit;
}

/** @param {unknown} value */
function words(value) {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, 80) : null;
}

/**
 * Sets the studio's place from what the snapshot says. A value missing or out of range keeps the
 * fallback's, one by one, so a half-configured studio is never drawn at 0°N 0°E.
 * @param {{timeZone?: unknown, timezone?: unknown, latitude?: unknown, longitude?: unknown, lat?: unknown, lon?: unknown,
 *          city?: unknown, holiday_country?: unknown, holidayCountry?: unknown, studioName?: unknown}|null|undefined} place
 * @returns {Readonly<StudioPlace>}
 */
export function setStudioPlace(place) {
  current = placeFrom(place);
  // Kept in this browser for the next visit's title, which is drawn before the Owner signs in
  // and so before any snapshot (a per-viewer convenience: it may be refused, and then the
  // title falls back as before).
  try {
    if (place) globalThis.localStorage?.setItem(PLACE_KEY, JSON.stringify(current));
    else globalThis.localStorage?.removeItem(PLACE_KEY);
  } catch {
    // storage refused (a private window, blocked site data): nothing is kept
  }
  return current;
}

/** The key the last place is kept under in this browser. */
const PLACE_KEY = 'amn.studioPlace';

/**
 * @param {Parameters<typeof setStudioPlace>[0]} place
 * @returns {Readonly<StudioPlace>}
 */
function placeFrom(place) {
  const p = place || {};
  const zone = p.timeZone ?? p.timezone;
  const lat = p.lat ?? p.latitude;
  const lon = p.lon ?? p.longitude;
  const country = p.holidayCountry ?? p.holiday_country;
  return Object.freeze({
    timeZone: validZone(zone) ? /** @type {string} */ (zone) : DEFAULT_PLACE.timeZone,
    lat: inRange(lat, 90) ? /** @type {number} */ (lat) : DEFAULT_PLACE.lat,
    lon: inRange(lon, 180) ? /** @type {number} */ (lon) : DEFAULT_PLACE.lon,
    city: words(p.city) ?? DEFAULT_PLACE.city,
    // none named: the fallback's; named but not a country code: no holidays at all, never Romania's
    holidayCountry: country == null ? DEFAULT_PLACE.holidayCountry
      : typeof country === 'string' && /^[A-Za-z]{2}$/.test(country) ? country.toUpperCase() : '',
    studioName: words(p.studioName) ?? DEFAULT_PLACE.studioName,
  });
}

// The place an earlier visit of this browser read from the snapshot, if any.
try {
  const kept = globalThis.localStorage?.getItem(PLACE_KEY);
  if (kept) current = placeFrom(JSON.parse(kept));
} catch {
  // nothing kept, or storage refused: the fallback stands
}

/** The place the page currently draws: the studio's, or the Bucharest fallback. */
export function studioPlace() {
  return current;
}

/**
 * The time in the studio's zone (or the zone given).
 * @param {Date} [date] @param {string} [timeZone]
 */
export function studioTime(date = new Date(), timeZone = current.timeZone) {
  const zone = validZone(timeZone) ? timeZone : DEFAULT_PLACE.timeZone;
  const parts = Object.fromEntries(formatterFor(zone).formatToParts(date).map((p) => [p.type, p.value]));
  return {
    text: parts.hour + ':' + parts.minute,
    hour: Number(parts.hour) + Number(parts.minute) / 60 + Number(parts.second) / 3600,
    day: new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day))).getUTCDay(),
    // The calendar date in the studio's zone, for what depends on it (a public holiday empties the street).
    ymd: /** @type {[number,number,number]} */ ([Number(parts.year), Number(parts.month), Number(parts.day)]),
  };
}

/**
 * The time in Bucharest, whatever the studio's place: the fixed reading older callers and tests use.
 * @param {Date} [date]
 */
export function bucharestTime(date = new Date()) {
  return studioTime(date, DEFAULT_PLACE.timeZone);
}

const DIGITS=['abcedf','bc','abged','abgcd','fgbc','afgcd','afgecd','abc','abcdefg','abfgcd'];
/** Seven-segment LED display, rasterized with whole pixels. Purely a clock, never a status badge. */
export function drawDigitalTime(ctx,x,y,text) {
 const segments={a:[2,0,7,2],b:[9,2,2,6],c:[9,10,2,6],d:[2,16,7,2],e:[0,10,2,6],f:[0,2,2,6],g:[2,8,7,2]};
 let cursor=Math.round(x);
 for(const char of text) {
  if(char===':') {ctx.fillStyle='#b5f0c4';ctx.fillRect(cursor+2,y+5,2,2);ctx.fillRect(cursor+2,y+12,2,2);cursor+=7;continue;}
  for(const [key,[dx,dy,w,h]] of Object.entries(segments)) {
   ctx.fillStyle=DIGITS[Number(char)]?.includes(key)?'#b5f0c4':'#20382f';
   ctx.fillRect(cursor+dx,Math.round(y)+dy,w,h);
  }
  cursor+=14;
 }
}
