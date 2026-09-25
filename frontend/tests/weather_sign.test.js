// W25 «the weather's sign at night»: at 03:00 the glass read «☀ Senin 17°C», a sun over a night
// with none. The sign follows the observation's own day or night (is_day), and when the studio does
// not say, the real sun over Bucharest. The words stay the glossary's.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { weatherSign } from '../src/hq_weather.js';

const ENGINE = fs.readFileSync(new URL('../src/office_engine.js', import.meta.url), 'utf8');

test('a clear night shows a moon, a clear day a sun', () => {
  assert.equal(weatherSign('clear', true, 40), '☀');
  assert.equal(weatherSign('clear', false, -40), '☾');
});

test('the signs with a sun in them lose it at night', () => {
  assert.equal(weatherSign('partly_cloudy', true, 30), '⛅');
  assert.equal(weatherSign('partly_cloudy', false, -30), '☁');
  assert.equal(weatherSign('drizzle', true, 30), '🌦');
  assert.equal(weatherSign('drizzle', false, -30), '🌧');
});

test('the signs without a sun stay what they are, day or night', () => {
  for (const c of ['cloudy', 'fog', 'rain', 'snow', 'storm']) assert.equal(weatherSign(c, true, 30), weatherSign(c, false, -30));
  assert.equal(weatherSign('rain', false, -30), '🌧');
});

test('the observation says day or night; the sun decides only when it does not', () => {
  // is_day wins over the computed sun (the service observes the sky)
  assert.equal(weatherSign('clear', true, -3), '☀');
  assert.equal(weatherSign('clear', false, 3), '☾');
  // not said: the sun above or below the horizon (refraction, -0.833 deg)
  assert.equal(weatherSign('clear', null, 5), '☀');
  assert.equal(weatherSign('clear', null, -5), '☾');
  assert.equal(weatherSign('clear', null, Number.NaN), '☀');
});

test('an unknown weather has no sign at all', () => {
  assert.equal(weatherSign('unknown', true, 30), '');
  assert.equal(weatherSign('nonsense', false, -30), '');
});

// the glass keeps the live hour even over a replay, so the sun is the real one now, not the world's
test('the glass takes its sign from weatherSign, with the observation and the real sun now', () => {
  assert.match(ENGINE, /weatherSign\(weather\.state\.condition, weather\.state\.isDay, timeOfDay\(new Date\(\)\)\.elevation\)/);
  assert.doesNotMatch(ENGINE, /WEATHER_ICONS/);
});
