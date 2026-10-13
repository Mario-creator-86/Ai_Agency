import { mixHex, skyStops } from './hq_time.js';

/**
 * The sky and the weather over the headquarters: gradient, clouds, stars, sun and moon, rain,
 * snow, fog and lightning, and the sky events (aircraft, birds).
 *
 * The drawings of the balloon, the fireworks, the helicopter, the drone, the shooting star and
 * the UFO are kept, but those events never start: hq_events.js REMOVED_EVENTS took them off
 * the real street on 2026-09-24. Taking an id out of that set is all it takes to bring one back.
 *
 * Everything that moves is drawn from state the managers own; the only randomness is the world's
 * seeded source, used once to lay out stars and cloud shapes.
 */

/** @param {() => number} rng @param {number} w @param {number} h */
function cloudCanvas(rng, w, h) {
  if (typeof document === 'undefined') return null;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  if (!ctx) return null;
  const puffs = 14 + Math.floor(rng() * 10);
  for (let i = 0; i < puffs; i += 1) {
    const x = w * (0.15 + rng() * 0.7);
    const y = h * (0.45 + (rng() - 0.5) * 0.35);
    const r = h * (0.18 + rng() * 0.28);
    const g = ctx.createRadialGradient(x, y, r * 0.1, x, y, r);
    g.addColorStop(0, 'rgba(255,255,255,0.55)');
    g.addColorStop(0.6, 'rgba(255,255,255,0.25)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  return c;
}

/**
 * How much of each painted cloud layer to show: dusk when the sun is near the horizon, day when it
 * is up, night otherwise. The weights always add up to one.
 * @param {{daylight:number, dusk:number}} time
 * @returns {{dusk:number, day:number, night:number}}
 */
export function cloudLayerWeights(time) {
  const dusk = Math.max(0, Math.min(1, time.dusk));
  const light = Math.max(0, Math.min(1, time.daylight));
  const day = light * (1 - dusk);
  const night = (1 - light) * (1 - dusk);
  const sum = dusk + day + night || 1;
  return { dusk: dusk / sum, day: day / sum, night: night / sum };
}

/**
 * How much cloud the sky shows, from the real cover the backend reads and nothing else: the
 * painted banks and the drifting clouds both scale with it. A clear sky is clear; an unknown
 * sky (no weather service, or it could not be reached) shows no cloud at all, because a cloud
 * drawn there would be weather the studio made up. The banks reach full strength at 0.6 cover,
 * where the weather says "partly cloudy" turns into "cloudy".
 * @param {{cloudiness:number, fog:number}} fx
 * @returns {{banks:number, drift:number}}
 */
export function cloudCover(fx) {
  const cover = Math.max(0, Math.min(1, fx.cloudiness || 0));
  return {
    banks: Math.min(1, cover / 0.6) * (1 - Math.min(0.6, (fx.fog || 0) * 0.6)),
    drift: cover,
  };
}

export class SkyRenderer {
  /**
   * @param {{worldWidth:number, worldHeight:number, horizonRow:number, rng:() => number, assets?: any}} options
   */
  constructor(options) {
    /** painted cloud layers come from the assets (sheets sky:dusk, sky:day, sky:night) */
    this.assets = options.assets || null;
    this.w = options.worldWidth;
    this.h = options.worldHeight;
    this.horizon = options.horizonRow;
    this.rng = options.rng;
    this.stars = Array.from({ length: 140 }, () => ({
      x: this.rng() * this.w,
      y: this.rng() * this.horizon * 0.9,
      r: 0.4 + this.rng() * 0.9,
      p: this.rng() * Math.PI * 2,
    }));
    this.cloudShapes = Array.from({ length: 6 }, () => cloudCanvas(this.rng, 360, 120));
    this.clouds = Array.from({ length: 12 }, (_, i) => ({
      shape: i % 6,
      x: this.rng() * (this.w + 400) - 200,
      y: 20 + this.rng() * (this.horizon - 60),
      scale: 0.6 + this.rng() * 0.9,
      speed: 3 + this.rng() * 6,
      layer: this.rng(),
    }));
    this.drops = Array.from({ length: 260 }, () => ({ x: this.rng() * this.w, y: this.rng() * this.h, s: 0.6 + this.rng() * 0.8 }));
    this.flakes = Array.from({ length: 180 }, () => ({ x: this.rng() * this.w, y: this.rng() * this.h, s: 0.5 + this.rng(), p: this.rng() * 6 }));
    this.flash = 0;
    this._nextFlash = 6;
    /** How far above the world's top edge the canvas shows sky (world units, 0 or negative). */
    this.top = 0;
    this.clock = 0;
    /** @type {any} */
    this._gradient = null;
    this._gradientKey = '';
    this.fireworks = [];
  }

  /**
   * @param {number} dt
   * @param {any} time TimeOfDayManager state
   * @param {any} fx weather effects
   */
  update(dt, time, fx) {
    this.clock += dt;
    const wind = 1 + fx.wind * 3;
    for (const c of this.clouds) {
      c.x += c.speed * wind * dt * (0.6 + c.layer * 0.8);
      if (c.x > this.w + 220) c.x = -380 * c.scale;
    }
    if (fx.rain > 0) {
      for (const d of this.drops) {
        d.y += 900 * d.s * dt;
        d.x += (60 + fx.wind * 220) * dt;
        if (d.y > this.h) {
          d.y = this.top - 20;
          d.x = this.rng() * this.w;
        }
      }
    }
    if (fx.snow > 0) {
      for (const f of this.flakes) {
        f.y += 38 * f.s * dt;
        f.x += Math.sin(this.clock * 0.9 + f.p) * 12 * dt + fx.wind * 30 * dt;
        if (f.y > this.h) {
          f.y = this.top - 6;
          f.x = this.rng() * this.w;
        }
      }
    }
    if (fx.storm) {
      this._nextFlash -= dt;
      if (this._nextFlash <= 0) {
        this.flash = 1;
        this._nextFlash = 7 + this.rng() * 18;
      }
    }
    this.flash = Math.max(0, this.flash - dt * 3.5);
  }

  /**
   * The sky from `top` down to the world's floor. Above the world's top edge (a negative `top`,
   * where the frame keeps a row of sky over the roof) the gradient runs on in its own top colour,
   * as a canvas gradient pads past its ends, and the stars of the band under the edge repeat
   * there, so the row is the same sky, not a strip of another colour.
   * @param {CanvasRenderingContext2D} ctx
   * @param {any} time
   * @param {any} fx
   * @param {number} [top] the canvas's top in world units, 0 or negative
   */
  drawSky(ctx, time, fx, top = 0) {
    const above = Math.min(0, top);
    this.top = above;
    const key = `${time.daylight.toFixed(2)}|${time.dusk.toFixed(2)}|${fx.cloudiness.toFixed(2)}|${fx.fog.toFixed(2)}`;
    if (key !== this._gradientKey) {
      const g = ctx.createLinearGradient(0, 0, 0, this.h);
      for (const [pos, color] of skyStops(time, fx)) g.addColorStop(Number(pos), String(color));
      this._gradient = g;
      this._gradientKey = key;
    }
    ctx.fillStyle = this._gradient;
    ctx.fillRect(0, above, this.w, this.h - above);
    if (time.dusk > 0.05) this.drawAfterglow(ctx, time, fx);
    const night = 1 - time.daylight;
    if (night > 0.05 && fx.cloudiness < 0.9) {
      ctx.fillStyle = '#ffffff';
      for (const s of this.stars) {
        ctx.globalAlpha = night * (1 - fx.cloudiness) * (0.35 + 0.35 * Math.sin(this.clock * 1.3 + s.p));
        ctx.fillRect(s.x, s.y, s.r, s.r);
        if (s.y < -above) ctx.fillRect(s.x, s.y + above, s.r, s.r);
      }
      ctx.globalAlpha = 1;
    }
    if (time.daylight > 0.25 && fx.cloudiness < 0.7) {
      const t = Math.min(1, Math.max(0, (time.hour - 6) / 14));
      // The camera looks north: the sun rises on the right and sets on the left, where the
      // reference's sunset glows.
      const sx = this.w * (0.92 - 0.84 * t);
      const sy = this.horizon - Math.max(0, time.elevation) * 5.5;
      const glow = ctx.createRadialGradient(sx, sy, 2, sx, sy, 90);
      glow.addColorStop(0, `rgba(255,248,220,${0.9 * (1 - fx.cloudiness)})`);
      glow.addColorStop(0.15, `rgba(255,236,190,${0.35 * (1 - fx.cloudiness)})`);
      glow.addColorStop(1, 'rgba(255,236,190,0)');
      ctx.fillStyle = glow;
      ctx.fillRect(sx - 90, sy - 90, 180, 180);
    } else if (night > 0.6 && fx.cloudiness < 0.8) {
      ctx.fillStyle = `rgba(236,240,255,${0.85 * (1 - fx.cloudiness)})`;
      ctx.beginPath();
      ctx.arc(this.w * 0.72, 70, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = this._gradient;
      ctx.beginPath();
      ctx.arc(this.w * 0.72 + 4, 67, 8, 0, Math.PI * 2);
      ctx.fill();
    }
    this.drawCloudLayers(ctx, time, fx);
    this.drawClouds(ctx, time, fx);
  }

  /**
   * The painted cloud banks, as in the Owner's picture: warm undersides at dusk, white by day, dim at
   * night, crossfaded with the time of day, and only as much of them as the real cover (cloudCover).
   * @param {CanvasRenderingContext2D} ctx
   * @param {{daylight:number, dusk:number}} time
   * @param {{cloudiness:number, fog:number}} fx
   */
  drawCloudLayers(ctx, time, fx) {
    if (!this.assets) return;
    const weights = cloudLayerWeights(time);
    const opacity = cloudCover(fx).banks;
    if (opacity < 0.01) return;
    for (const look of /** @type {Array<'dusk'|'day'|'night'>} */ (['night', 'day', 'dusk'])) {
      const img = this.assets.sheet(`sky:${look}`);
      if (!img || weights[look] < 0.01) continue;
      ctx.globalAlpha = weights[look] * opacity;
      ctx.drawImage(img, 0, 0, this.w, (img.height * this.w) / img.width);
    }
    ctx.globalAlpha = 1;
  }

  /**
   * Around sunrise and sunset the sky is not level: warm low on the side the sun went down (or
   * is coming up), a lighter blue high on the side across from it.
   * @param {CanvasRenderingContext2D} ctx
   * @param {{dusk:number, hour:number}} time
   * @param {{cloudiness:number, fog:number}} fx
   */
  drawAfterglow(ctx, time, fx) {
    const a = time.dusk * (1 - Math.min(0.85, fx.cloudiness * 0.75 + fx.fog * 0.5));
    if (a <= 0.02) return;
    const sunSide = time.hour < 12 ? this.w : 0;
    // both glows are ellipses, flattened so the warmth stays on the horizon and the blue up high
    ctx.save();
    ctx.translate(sunSide, this.horizon);
    ctx.scale(1, 0.28);
    const warm = ctx.createRadialGradient(0, 0, 10, 0, 0, this.w * 0.5);
    warm.addColorStop(0, `rgba(250,160,110,${0.5 * a})`);
    warm.addColorStop(0.5, `rgba(214,120,110,${0.22 * a})`);
    warm.addColorStop(1, 'rgba(214,120,110,0)');
    ctx.fillStyle = warm;
    ctx.fillRect(-this.w, -this.horizon / 0.28, this.w * 2, (this.h / 0.28) * 2);
    ctx.restore();
    const across = time.hour < 12 ? this.w * 0.14 : this.w * 0.86;
    ctx.save();
    ctx.translate(across, 20);
    ctx.scale(1, 0.55);
    const cool = ctx.createRadialGradient(0, 0, 10, 0, 0, this.w * 0.26);
    cool.addColorStop(0, `rgba(100,146,220,${0.7 * a})`);
    cool.addColorStop(1, 'rgba(100,146,220,0)');
    ctx.fillStyle = cool;
    ctx.fillRect(-this.w * 0.3, -60, this.w * 0.6, this.w * 0.6);
    ctx.restore();
  }

  /**
   * A cloud shape recoloured to the light, cached per colour (the colour changes by the minute).
   * @param {number} index @param {string} colour
   */
  tinted(index, colour) {
    const shape = this.cloudShapes[index];
    if (!shape || typeof document === 'undefined') return shape;
    if (!this._tints) this._tints = new Map();
    const key = `${index}|${colour}`;
    let canvas = this._tints.get(key);
    if (!canvas) {
      if (this._tints.size > 48) this._tints.clear();
      canvas = document.createElement('canvas');
      canvas.width = shape.width;
      canvas.height = shape.height;
      const c = canvas.getContext('2d');
      if (c) {
        c.drawImage(shape, 0, 0);
        c.globalCompositeOperation = 'source-atop';
        c.fillStyle = colour;
        c.fillRect(0, 0, canvas.width, canvas.height);
      }
      this._tints.set(key, canvas);
    }
    return canvas;
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time @param {any} fx */
  drawClouds(ctx, time, fx) {
    const amount = cloudCover(fx).drift;
    const count = Math.round(this.clouds.length * amount);
    // Clouds take the colour of the light: lit pink-orange at dusk, white by day, blue-grey at night.
    const lit = mixHex(mixHex('#2a3350', '#f4f6fa', time.daylight), '#e9a48c', time.dusk * 0.55);
    for (let i = 0; i < count; i += 1) {
      const c = this.clouds[i];
      const shape = this.tinted(c.shape, i % 3 === 0 ? mixHex(lit, '#1a2138', 0.35) : lit);
      if (!shape) continue;
      ctx.globalAlpha = (0.3 + fx.cloudiness * 0.55) * (0.45 + c.layer * 0.55);
      ctx.drawImage(shape, c.x, c.y, shape.width * c.scale, shape.height * c.scale);
    }
    ctx.globalAlpha = 1;
    if (fx.cloudiness > 0.55) {
      ctx.fillStyle = mixHex('#0c1020', '#9aa3b2', time.daylight);
      ctx.globalAlpha = (fx.cloudiness - 0.55) * 0.9;
      ctx.fillRect(0, 0, this.w, this.horizon + 40);
      ctx.globalAlpha = 1;
    }
  }

  /**
   * Far events (airliners, birds, shooting stars) pass behind the skyline; near ones (helicopter,
   * drone, balloon, fireworks, the UFO) are drawn over the building so they are never hidden.
   * @param {CanvasRenderingContext2D} ctx @param {any} manager RandomEventManager @param {any} time
   * @param {'far'|'near'} [depth]
   */
  drawSkyEvents(ctx, manager, time, depth = 'far') {
    const far = new Set(['airplane_cross', 'bird_flock', 'shooting_star']);
    for (const event of manager.active) {
      const p = manager.progress(event);
      const id = event.def.eventId;
      if (far.has(id) !== (depth === 'far')) continue;
      const rnd = (/** @type {number} */ k) => ((Math.sin(event.seed * 0.001 + k * 12.9898) * 43758.5453) % 1 + 1) % 1;
      const ltr = rnd(1) < 0.5;
      const x = ltr ? -80 + (this.w + 160) * p : this.w + 80 - (this.w + 160) * p;
      if (id === 'airplane_cross') drawAirplane(ctx, x, 70 + rnd(2) * 160, ltr ? 1 : -1, this.clock, time);
      else if (id === 'helicopter_pass') drawHelicopter(ctx, x, 150 + rnd(3) * 120, ltr ? 1 : -1, this.clock);
      else if (id === 'bird_flock') drawBirds(ctx, x, 120 + rnd(4) * 150, ltr ? 1 : -1, this.clock, time);
      else if (id === 'delivery_drone') drawDrone(ctx, x, 260 + rnd(5) * 90, this.clock);
      else if (id === 'hot_air_balloon') drawBalloon(ctx, this.w * (0.08 + 0.2 * rnd(6)) + p * 180, 260 - p * 140, rnd(7));
      else if (id === 'shooting_star') drawShootingStar(ctx, this.w * (0.2 + rnd(8) * 0.6), 40 + rnd(9) * 80, p);
      else if (id === 'ufo_flyover') drawUfo(ctx, x, 110 + Math.sin(p * Math.PI * 3) * 30, this.clock, p);
      else if (id === 'fireworks') this.drawFireworks(ctx, event, p);
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} event @param {number} p */
  drawFireworks(ctx, event, p) {
    const bursts = 9;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (let b = 0; b < bursts; b += 1) {
      const start = b / bursts;
      const local = (p - start) * bursts * 0.6;
      if (local < 0 || local > 1) continue;
      const seed = event.seed + b * 97;
      const bx = (seed % 700) + 120 + (b % 2 ? 900 : 0);
      const by = 120 + ((seed >> 3) % 160);
      const hue = (seed * 37) % 360;
      const r = 8 + local * 55;
      ctx.globalAlpha = Math.max(0, 1 - local);
      ctx.fillStyle = `hsl(${hue},95%,65%)`;
      for (let i = 0; i < 28; i += 1) {
        const a = (i / 28) * Math.PI * 2;
        ctx.fillRect(bx + Math.cos(a) * r, by + Math.sin(a) * r + local * local * 12, 2, 2);
      }
    }
    ctx.restore();
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time @param {any} fx */
  drawWeather(ctx, time, fx, top = 0) {
    const above = Math.min(0, top);
    if (fx.fog > 0) {
      const g = ctx.createLinearGradient(0, this.h * 0.3, 0, this.h);
      const c = time.daylight > 0.5 ? '210,216,224' : '90,98,120';
      g.addColorStop(0, `rgba(${c},0)`);
      g.addColorStop(0.5, `rgba(${c},${0.35 * fx.fog})`);
      g.addColorStop(1, `rgba(${c},${0.55 * fx.fog})`);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, this.w, this.h);
    }
    if (fx.rain > 0) {
      ctx.strokeStyle = time.daylight > 0.5 ? 'rgba(210,220,235,0.35)' : 'rgba(170,190,230,0.3)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      const n = Math.round(this.drops.length * fx.rain);
      for (let i = 0; i < n; i += 1) {
        const d = this.drops[i];
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x - 3 - fx.wind * 6, d.y - 16 * d.s);
      }
      ctx.stroke();
    }
    if (fx.snow > 0) {
      ctx.fillStyle = 'rgba(248,250,255,0.85)';
      const n = Math.round(this.flakes.length * fx.snow);
      for (let i = 0; i < n; i += 1) {
        const f = this.flakes[i];
        ctx.fillRect(f.x, f.y, 1.6 * f.s, 1.6 * f.s);
      }
    }
    if (this.flash > 0) {
      ctx.fillStyle = `rgba(230,236,255,${0.45 * this.flash})`;
      ctx.fillRect(0, above, this.w, this.h - above);
    }
  }
}

/** @param {CanvasRenderingContext2D} ctx */
function drawAirplane(ctx, x, y, dir, clock, time) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(dir, 1);
  const trail = ctx.createLinearGradient(-160, 0, 0, 0);
  trail.addColorStop(0, 'rgba(255,255,255,0)');
  trail.addColorStop(1, `rgba(255,255,255,${0.25 + 0.25 * time.daylight})`);
  ctx.fillStyle = trail;
  ctx.fillRect(-160, -1, 150, 2);
  ctx.fillStyle = time.daylight > 0.4 ? '#e5e7eb' : '#1f2433';
  ctx.beginPath();
  ctx.moveTo(-14, -1.5);
  ctx.lineTo(12, -1.2);
  ctx.lineTo(15, 0);
  ctx.lineTo(12, 1.2);
  ctx.lineTo(-14, 1.5);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(-2, 0);
  ctx.lineTo(-7, -9);
  ctx.lineTo(-3, -9);
  ctx.lineTo(4, 0);
  ctx.moveTo(-2, 0);
  ctx.lineTo(-6, 7);
  ctx.lineTo(-3, 7);
  ctx.lineTo(4, 0);
  ctx.moveTo(-14, 0);
  ctx.lineTo(-17, -5);
  ctx.lineTo(-13, -1);
  ctx.fill();
  if (Math.sin(clock * 6) > 0.6) {
    ctx.fillStyle = '#ff3b3b';
    ctx.fillRect(-5, -9, 2, 2);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(-16, -1, 2, 2);
  }
  ctx.restore();
}

/** @param {CanvasRenderingContext2D} ctx */
function drawHelicopter(ctx, x, y, dir, clock) {
  ctx.save();
  ctx.translate(x, y + Math.sin(clock * 2) * 2);
  ctx.scale(dir, 1);
  ctx.fillStyle = '#1c2230';
  ctx.beginPath();
  ctx.ellipse(0, 0, 9, 5, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillRect(-22, -1, 14, 2);
  ctx.fillRect(-23, -4, 2, 6);
  ctx.fillStyle = 'rgba(40,48,64,0.8)';
  const blade = 16 * Math.abs(Math.sin(clock * 25));
  ctx.fillRect(-blade, -7, blade * 2, 1.2);
  ctx.fillStyle = Math.sin(clock * 5) > 0.3 ? '#ff3b3b' : '#48202a';
  ctx.fillRect(-2, 4, 2, 2);
  ctx.fillStyle = 'rgba(160,210,255,0.8)';
  ctx.fillRect(3, -2, 4, 3);
  ctx.restore();
}

/** @param {CanvasRenderingContext2D} ctx */
function drawBirds(ctx, x, y, dir, clock, time) {
  ctx.strokeStyle = time.daylight > 0.4 ? 'rgba(30,34,44,0.8)' : 'rgba(10,12,20,0.8)';
  ctx.lineWidth = 1.2;
  for (let i = 0; i < 9; i += 1) {
    const bx = x - dir * (Math.abs(i - 4) * 14);
    const by = y + i * 4 + Math.sin(clock * 3 + i) * 2;
    const flap = Math.sin(clock * 9 + i) * 3;
    ctx.beginPath();
    ctx.moveTo(bx - 4, by - flap);
    ctx.lineTo(bx, by);
    ctx.lineTo(bx + 4, by - flap);
    ctx.stroke();
  }
}

/** @param {CanvasRenderingContext2D} ctx */
function drawDrone(ctx, x, y, clock) {
  ctx.fillStyle = '#20242e';
  ctx.fillRect(x - 6, y - 1.5, 12, 3);
  ctx.fillRect(x - 3, y + 1.5, 6, 3);
  ctx.fillStyle = 'rgba(80,90,110,0.7)';
  ctx.fillRect(x - 9, y - 3, 5, 1);
  ctx.fillRect(x + 4, y - 3, 5, 1);
  ctx.fillStyle = Math.sin(clock * 8) > 0 ? '#34d399' : '#ef4444';
  ctx.fillRect(x - 1, y - 1, 2, 2);
}

/** @param {CanvasRenderingContext2D} ctx */
function drawBalloon(ctx, x, y, seed) {
  const colors = [['#ef4444', '#f59e0b'], ['#2563eb', '#f8fafc'], ['#10b981', '#fbbf24']][Math.floor(seed * 3) % 3];
  ctx.save();
  ctx.translate(x, y);
  for (let i = 0; i < 6; i += 1) {
    ctx.fillStyle = colors[i % 2];
    ctx.beginPath();
    ctx.ellipse(0, 0, 16 - i * 2.4, 20, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.strokeStyle = '#3f2a1a';
  ctx.beginPath();
  ctx.moveTo(-6, 17);
  ctx.lineTo(-3, 28);
  ctx.moveTo(6, 17);
  ctx.lineTo(3, 28);
  ctx.stroke();
  ctx.fillStyle = '#6b4a2a';
  ctx.fillRect(-4, 28, 8, 6);
  ctx.restore();
}

/** @param {CanvasRenderingContext2D} ctx */
function drawShootingStar(ctx, x, y, p) {
  const len = 90;
  const px = x + p * 220;
  const py = y + p * 70;
  const g = ctx.createLinearGradient(px - len, py - len * 0.32, px, py);
  g.addColorStop(0, 'rgba(255,255,255,0)');
  g.addColorStop(1, `rgba(255,255,255,${1 - p})`);
  ctx.strokeStyle = g;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(px - len, py - len * 0.32);
  ctx.lineTo(px, py);
  ctx.stroke();
}

/** @param {CanvasRenderingContext2D} ctx */
function drawUfo(ctx, x, y, clock, p) {
  ctx.save();
  ctx.translate(x, y);
  const beam = ctx.createLinearGradient(0, 6, 0, 120);
  beam.addColorStop(0, `rgba(160,255,210,${0.35 * Math.sin(p * Math.PI)})`);
  beam.addColorStop(1, 'rgba(160,255,210,0)');
  ctx.fillStyle = beam;
  ctx.beginPath();
  ctx.moveTo(-6, 6);
  ctx.lineTo(6, 6);
  ctx.lineTo(28, 120);
  ctx.lineTo(-28, 120);
  ctx.fill();
  const halo = ctx.createRadialGradient(0, 0, 4, 0, 0, 46);
  halo.addColorStop(0, 'rgba(140,255,200,0.45)');
  halo.addColorStop(1, 'rgba(140,255,200,0)');
  ctx.fillStyle = halo;
  ctx.fillRect(-46, -46, 92, 92);
  ctx.fillStyle = '#9aa4b8';
  ctx.beginPath();
  ctx.ellipse(0, 2, 22, 6, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = 'rgba(170,240,255,0.9)';
  ctx.beginPath();
  ctx.ellipse(0, -2, 9, 6, 0, Math.PI, 0);
  ctx.fill();
  for (let i = 0; i < 6; i += 1) {
    ctx.fillStyle = Math.sin(clock * 8 + i) > 0 ? '#fde047' : '#22d3ee';
    ctx.fillRect(-18 + i * 7, 3, 2, 2);
  }
  ctx.restore();
}
