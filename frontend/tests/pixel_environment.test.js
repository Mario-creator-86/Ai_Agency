import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeWeather } from '../src/hq_weather.js';
import { OUTDOORS, outdoorWeather, outdoorMoment, outdoorsAt, outdoorReadout, weatherMoves } from '../src/pixel_environment.js';

const now = Date.parse('2026-10-08T12:00:00Z');
const rain = normalizeWeather({ available: true, condition: 'rain', intensity: 0.6, temperature_c: 14.2 });
const live = { live: true, reduced: false, replay: false, parked: false, hidden: false };

test('weather uses observation UTC rather than the computer timezone', () => {
  assert.equal(outdoorWeather(rain, now, now, '2026-10-08T14:45:00+03:00').condition, 'rain');
  assert.equal(outdoorWeather(rain, now, now, '2026-10-08T11:00:00Z').available, false);
  assert.equal(outdoorWeather(rain, now, now, '2026-10-08T12:10:00Z').available, false);
});

test('unavailable, aged or replay data draws no invented precipitation', () => {
  assert.equal(outdoorWeather(rain, now, now + OUTDOORS.weather_max_age_ms + 1).available, false);
  assert.equal(outdoorWeather(rain, 0, now).available, false);
  assert.equal(outdoorWeather(null, now, now).available, false);
  assert.equal(outdoorWeather(rain, now, now, null, true).available, false);
  assert.equal(outdoorWeather(rain, now, now).available, true, 'compatible providers without UTC expire by receipt');
});

test('weather motion obeys every lifecycle guard', () => {
  assert.equal(weatherMoves(rain, live), true);
  for (const key of ['reduced', 'replay', 'parked', 'hidden']) assert.equal(weatherMoves(rain, { ...live, [key]: true }), false);
  assert.equal(weatherMoves(rain, { ...live, live: false }), false);
  for (const condition of ['fog', 'snow', 'drizzle', 'storm']) assert.equal(weatherMoves(normalizeWeather({ available: true, condition }), live), true);
  assert.equal(weatherMoves(normalizeWeather({ available: true, condition: 'clear' }), live), false);
});

test('solar lighting and clock use actual Bucharest dates including daylight saving', () => {
  const day = outdoorMoment(new Date(now));
  const night = outdoorMoment(new Date('2026-10-08T23:00:00Z'));
  assert.equal(day.phase, 'day'); assert.equal(day.text, '15:00');
  assert.equal(night.phase, 'night'); assert.equal(night.daylight, 0);
  assert.equal(outdoorMoment(new Date('2026-12-08T12:00:00Z')).text, '14:00');
  assert.equal(outdoorMoment(new Date(now + 42000)).elevation, day.elevation, 'minute precision avoids constant relighting');
});

test('weather stays outside the furnished rooms', () => {
  for (const [x, y] of [[212, 254], [700, 430], [300, 450], [267, 190]]) assert.equal(outdoorsAt(x, y), false);
  for (const [x, y] of [[100, 100], [902, 477], [450, 600]]) assert.equal(outdoorsAt(x, y), true);
});

test('readout names unavailable and historical weather without made up temperatures', () => {
  assert.match(outdoorReadout('15:00', rain), /15:00.*14°C/);
  assert.match(outdoorReadout('15:00', normalizeWeather(null)), /indisponibil/);
  assert.match(outdoorReadout('15:00', rain, true), /atunci: necunoscută/);
});
