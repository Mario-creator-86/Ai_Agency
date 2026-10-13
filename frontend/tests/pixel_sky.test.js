import test from 'node:test';
import assert from 'node:assert/strict';
import { outdoorMoment } from '../src/pixel_environment.js';
import { normalizeWeather } from '../src/hq_weather.js';
import { skyAppearance, skyPixel } from '../src/pixel_sky.js';

const clear = normalizeWeather({ available: true, condition: 'clear' });
const night = outdoorMoment(new Date('2026-10-08T17:10:00Z'));

test('at the reported Bucharest 20:10 the sun is down and the moon/stars are visible', () => {
  assert.equal(night.text, '20:10'); assert.equal(night.phase, 'night');
  const sky = skyAppearance(night, clear);
  assert.equal(sky.sun, 0); assert.ok(sky.moon > 0.9); assert.ok(sky.stars > 0.9);
  assert.notEqual(sky.colours[0], sky.colours[2], 'sky has depth rather than a flat grey wash');
});

test('daytime hides night bodies and twilight blends the warm sunset palette', () => {
  const day = skyAppearance(outdoorMoment(new Date('2026-10-08T10:00:00Z')), clear);
  assert.equal(day.moon, 0); assert.equal(day.stars, 0); assert.ok(day.sun > 0.9);
  const dusk = outdoorMoment(new Date('2026-10-08T15:35:00Z'));
  assert.equal(dusk.phase, 'dusk');
  assert.notDeepEqual(skyAppearance(dusk, clear).colours, skyAppearance(night, clear).colours);
});

test('real cloud/fog observations soften celestial lights; missing weather invents no clouds', () => {
  const bright = skyAppearance(night, clear);
  const storm = skyAppearance(night, normalizeWeather({ available: true, condition: 'storm' }));
  const fog = skyAppearance(night, normalizeWeather({ available: true, condition: 'fog', intensity: 1 }));
  assert.ok(storm.moon < bright.moon); assert.ok(fog.stars < bright.stars);
  assert.equal(skyAppearance(night, normalizeWeather(null)).cloudiness, 0);
});

test('sky mask covers the edge above the sloped roof while excluding rooms and plants', () => {
  assert.equal(skyPixel(152, 78, 240, 148, 117), true, 'no rectangular orange seam above plants');
  assert.equal(skyPixel(137, 158, 240, 148, 117), true, 'no triangular seam along the roof');
  assert.equal(skyPixel(792, 95, 240, 148, 117), true, 'sky reaches behind the right roof foliage');
  assert.equal(skyPixel(798, 150, 240, 148, 117), false, 'warm indoor pixels cannot enter the sky mask');
  assert.equal(skyPixel(400, 200, 240, 148, 117), false);
  assert.equal(skyPixel(400, 70, 47, 45, 59), false, 'roof stays intact');
  assert.equal(skyPixel(150, 50, 62, 108, 53), false, 'foliage stays intact');
});
