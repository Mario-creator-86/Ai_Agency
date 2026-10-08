import { runtimeLabel } from './ledger.js';
import { studioPlace } from './office_clock.js';
import { WeatherManager } from './hq_weather.js';
import { OUTDOORS, outdoorWeather, outdoorMoment, drawOutdoorLight, drawOutdoorClock, drawOutdoorWeather, outdoorReadout, weatherMoves } from './pixel_environment.js';

import { PIXEL_LAYOUT, staffPositions, restoreFurniture } from './pixel_desks.js';
import { identitySeed, characterProfile, characterMotion, drawSeatedPerson, drawDeskGesture } from './pixel_people.js';
import { bubblePages, bubbleFrame } from './speech_bubble.js';
import { sceneFrame } from './pixel_navigation.js';
import { drawOutdoorSky } from './pixel_sky.js';
import { ambientMoves, drawOutdoorLife } from './pixel_life.js';
import { loadActorAtlases } from './pixel_actor_atlas.js';
export { staffPositions, identitySeed, characterMotion };

export const WORLD_W = PIXEL_LAYOUT.world.width;
export const WORLD_H = PIXEL_LAYOUT.world.height;
export const BUILDING = PIXEL_LAYOUT.building;
export const PIXEL_BACKGROUND = PIXEL_LAYOUT.background;
const ZERO = { left: 0, right: 0, top: 0, bottom: 0 };

export function acting(agent, live, reduced) {
  return Boolean(live && !reduced && agent.lifecycle === 'ACTIVE' && ['WORKING', 'THINKING'].includes(agent.runtime_state));
}

/** A small canvas view: one background, real staff, actual state badges, pointer/keyboard input. */
export class OfficeEngine {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.options = /** @type {any} */ (options);
    this.ctx = canvas.getContext('2d');
    this.worldW = WORLD_W;
    this.worldH = WORLD_H;
    this.building = BUILDING;
    this.dpr = 1;
    this.agents = [];
    this.bubbles = [];
    this.positions = [];
    this.pixelLayout = PIXEL_LAYOUT;
    this.characters = new Map();
    this.page = 0;
    this.tickTimer = 0;
    this.environmentTimer = 0;
    this.weatherReceivedAt = 0;
    this.weatherEpoch = 0;
    this.weatherObservedUtc = null;
    this.weatherElapsed = 0;
    this.weatherFrameAt = null;
    this.lifeElapsed = 0;
    this.lifeFrameAt = null;
    this.weather = new WeatherManager(async () => {
      const epoch = this.weatherEpoch;
      const data = await this.options.fetchWeather?.();
      if (epoch !== this.weatherEpoch) return { available: false, reason: 'changed_context' };
      this.weatherReceivedAt = Date.now();
      this.weatherObservedUtc = data?.observed_at_utc || null;
      this.weatherSource = data?.source || 'serviciul meteo';
      return data;
    }, { refreshMs: OUTDOORS.weather_refresh_ms });
    this.selected = null;
    this.hover = null;
    this.insets = { ...ZERO };
    this.zoom = 1;
    this.pan = { x: 0, y: 0 };
    this.drag = null;
    this.suppressClick = false;
    this.parked = Boolean(this.options.parked);
    this.replay = false;
    this.replayStill = null;
    this.hitsOnly = false;
    this.raf = 0;
    this.last = 0;
    this.assets = { manifest: null };
    this.renderer = {
      hits: [], captionBoxes: [], m: { seats: {} },
      drawPortrait: (ctx, agent, _win = null, _frame = null) => {
        ctx.imageSmoothingEnabled = false;
        ctx.fillStyle = '#353346';
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        const px = Math.max(1, ctx.canvas.width / 26);
        const profile = this.profileFor(agent);
        const motion = characterMotion(agent);
        drawSeatedPerson(ctx, profile, motion, ctx.canvas.width / 2, 39 * px, px, true);
        return true;
      },
    };
    this.viewport = {
      zoom: 1, panX: 0, panY: 0, insets: { ...ZERO }, floor: { ...ZERO },
      worldToScreen: (x, y) => ({ x: x * this.viewport.zoom + this.viewport.panX, y: y * this.viewport.zoom + this.viewport.panY }),
      screenToWorld: (x, y) => ({ x: (x - this.viewport.panX) / this.viewport.zoom, y: (y - this.viewport.panY) / this.viewport.zoom }),
    };
    this.background = new Image();
    const backgroundReady = new Promise((resolve) => {
      this.background.onload = () => { this.draw(); resolve(true); };
      this.background.onerror = () => { this.draw(); resolve(false); };
      this.background.src = PIXEL_BACKGROUND;
    });
    this.ready=Promise.all([backgroundReady,loadActorAtlases()]).then(([background])=>{this.draw();return background;});
    this.themeReady = this.ready;
    this.warmed = false;
    this.bindInput();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.stop();
      else if (!this.parked) { this.startEnvironment(); this.schedule(); }
    });
    this.resize();
  }

  view() { return { cw: this.canvas.width, ch: this.canvas.height, dpr: this.dpr, worldW: WORLD_W, worldH: WORLD_H, ...this.viewport }; }
  frameBox() {
    const v = this.viewport;
    const a = v.worldToScreen(BUILDING.x, BUILDING.y);
    return { room: { left: this.insets.left, right: this.canvas.width / this.dpr - this.insets.right, top: this.insets.top, bottom: this.canvas.height / this.dpr - this.insets.bottom }, building: { x: a.x / this.dpr, y: a.y / this.dpr, w: BUILDING.width * v.zoom / this.dpr, h: BUILDING.height * v.zoom / this.dpr } };
  }
  resize() {
    const box = this.canvas.getBoundingClientRect();
    if (!box.width || !box.height) return;
    this.prewarm(box.width, box.height);
  }
  prewarm(w, h) {
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);
    this.plan();
    this.warmed = true;
  }
  plan() {
    const d = this.dpr;
    const w = this.canvas.width / d - this.insets.left - this.insets.right;
    const h = this.canvas.height / d - this.insets.top - this.insets.bottom;
    const frame = sceneFrame({ width: w, height: h, worldWidth: WORLD_W, worldHeight: WORLD_H, zoom: this.zoom, panX: this.pan.x, panY: this.pan.y });
    this.pan = { x: frame.panX, y: frame.panY }; this.movable = frame.movable;
    const k = frame.scale * d;
    Object.assign(this.viewport, { zoom: k, panX: (this.insets.left + (w - WORLD_W * frame.scale) / 2 + this.pan.x) * d, panY: (this.insets.top + (h - WORLD_H * frame.scale) / 2 + this.pan.y) * d, insets: Object.fromEntries(Object.entries(this.insets).map(([key, n]) => [key, n * d])) });
    this.canvas.style.touchAction = this.movable ? 'none' : 'pan-y';
    this.canvas.style.cursor = this.drag?.moved ? 'grabbing' : this.hover ? 'pointer' : this.movable ? 'grab' : 'default';
    this.options.onView?.(this.view());
    this.draw();
  }
  setInsets(insets, _options = {}) {
    this.insets = { ...ZERO, ...insets };
    const roster = document.getElementById('pixel-roster');
    if (roster) { roster.style.left = `${this.insets.left + 12}px`; roster.style.right = `${this.insets.right + 12}px`; }
    this.plan();
  }
  zoomBy(factor) { this.zoomTo(this.zoom * factor); }
  zoomTo(zoom, anchor = null) {
    if (!Number.isFinite(zoom)) return;
    const world = anchor && this.viewport.screenToWorld(anchor.x * this.dpr, anchor.y * this.dpr);
    this.zoom = Math.max(0.65, Math.min(2.5, zoom));
    if (this.zoom <= 1) this.pan = { x: 0, y: 0 };
    this.plan();
    if (world) {
      const screen = this.viewport.worldToScreen(world.x, world.y);
      this.panBy(anchor.x - screen.x / this.dpr, anchor.y - screen.y / this.dpr);
    }
  }
  panBy(x, y) {
    if (!this.movable || !Number.isFinite(x) || !Number.isFinite(y)) return false;
    const before = this.pan;
    this.pan = { x: before.x + x, y: before.y + y }; this.plan();
    return this.pan.x !== before.x || this.pan.y !== before.y;
  }
  fitView(_options = {}) { this.pan = { x: 0, y: 0 }; this.zoomTo(1); }
  park() { this.parked = true; this.resetWeather(); this.stop(); }
  resetWeather() {
    this.weatherEpoch++; this.weatherReceivedAt = 0; this.weatherObservedUtc = null;
    this.weather._last = -Infinity;
  }
  unpark() { this.parked = false; this.resize(); this.startEnvironment(); this.schedule(); }
  stop() {
    cancelAnimationFrame(this.raf); clearTimeout(this.tickTimer); clearTimeout(this.environmentTimer);
    this.raf = 0; this.tickTimer = 0; this.environmentTimer = 0; this.weatherFrameAt = null;
    this.lifeFrameAt = null;
  }
  async refreshWeather() {
    if (this.parked || document.hidden || this.replay || this.weather._pending) return;
    await this.weather.first(Date.now());
    if (!this.parked && !document.hidden) { this.draw(); this.schedule(); }
  }
  startEnvironment() {
    if (this.parked || document.hidden || this.environmentTimer) return;
    if (!this.replay) this.weather.update(Date.now());
    this.environmentTimer = window.setTimeout(() => {
      this.environmentTimer = 0;
      if (this.parked || document.hidden) return;
      if (!this.raf && !this.tickTimer) this.draw();
      this.schedule(); this.startEnvironment();
    }, OUTDOORS.clock_refresh_ms);
  }
  currentWeather(now = Date.now()) {
    return outdoorWeather(this.weather.state, this.weatherReceivedAt, now, this.weatherObservedUtc, this.replay);
  }
  weatherAnimating(weather = this.currentWeather()) {
    return weatherMoves(weather, { live: this.options.dataLive?.(), reduced: this.options.reducedMotion?.(), replay: this.replay, parked: this.parked, hidden: document.hidden });
  }
  ambientAnimating() {
    return ambientMoves({ live: this.options.dataLive?.(), reduced: this.options.reducedMotion?.(), replay: this.replay, parked: this.parked, hidden: document.hidden });
  }
  motionFor(agent, at = this.lifeElapsed) {
    return characterMotion(agent, at, this.options.dataLive?.(), this.options.reducedMotion?.(), this.replay);
  }
  profileFor(agent) { return characterProfile(agent, this.characters.get(String(agent.id || agent.agent_id))); }
  visiblePositions() { return this.positions.filter(p => p.page === this.page); }
  schedule() {
    if (this.raf || this.tickTimer || this.parked || document.hidden) return;
    const moving = this.visiblePositions().some(p => this.motionFor(p.agent).animate);
    const speaking = this.bubbles.some(b => b.expiresAt > Date.now()) && (this.replay || this.options.dataLive?.());
    if (!moving && !speaking && !this.weatherAnimating() && !this.ambientAnimating()) return;
    // At most twelve paints per second, no busy RAF loop between paints or while hidden.
    this.tickTimer = window.setTimeout(() => {
      this.tickTimer = 0;
      if (this.parked || document.hidden) return;
      this.raf = requestAnimationFrame(at => { this.raf = 0; this.draw(at); this.schedule(); });
    }, Math.ceil(1000 / PIXEL_LAYOUT.life.frame_rate));
  }
  setLayout(layout) {
    this.layout = layout;
    // Existing inspectors use department/desk names; visual coordinates belong to this scene.
    this.assets.manifest = { ...layout };
    this.pixelLayout = layout.pixel_office || PIXEL_LAYOUT;
    this.draw();
  }
  setCharacterBible(characters) {
    this.characters = new Map(characters.filter(c => c.employee_id).map(c => [String(c.employee_id), c]));
    this.draw();
  }
  setAgents(agents) {
    this.agents = [...agents];
    this.positions = staffPositions(agents, this.pixelLayout);
    const pages = this.positions.map(p => p.page);
    if (!pages.includes(this.page)) this.page = pages[0] || 0;
    this.syncHits();
    this.renderPages();
    this.draw();
    this.schedule();
    this.renderRoster();
  }
  syncHits() {
    this.renderer.hits = this.visiblePositions().map(p => ({ x: p.x - 32, y: p.y - 70, w: 64, h: 86, x0: p.x - 32, y0: p.y - 70, x1: p.x + 32, y1: p.y + 16, agent: p.agent }));
  }
  showPage(page) { this.page = page; this.syncHits(); this.renderPages(); this.draw(); this.schedule(); }
  setSelectedAgent(id) {
    this.selected = id;
    const person = this.positions.find(p => p.id === id);
    if (person && person.page !== this.page) this.showPage(person.page);
    this.draw(); this.renderRoster();
  }
  renderPages() {
    const host = document.getElementById('pixel-office-pages');
    if (!host) return;
    const pages = [...new Set(this.positions.map(p => p.page))].sort((a, b) => a - b);
    host.hidden = pages.length <= 1;
    const key = `${pages}:${this.page}`;
    if (key === this.pagesKey) return;
    this.pagesKey = key; host.replaceChildren();
    for (const page of pages) {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = page === 0 ? 'Birouri principale' : `Birouri suplimentare ${page}`;
      button.setAttribute('aria-pressed', String(page === this.page));
      button.addEventListener('click', () => this.showPage(page)); host.append(button);
    }
  }
  setSpeechBubbles(bubbles) { this.bubbles = [...bubbles]; this.draw(); this.schedule(); }
  setProjectTokens(_tokens) { /* Workflow progress is displayed by the existing truthful day track. */ }
  setFacts(facts) {
    this.facts = facts;
    const place = studioPlace(), key = `${place.lat}:${place.lon}:${place.timeZone}`;
    if (this.weatherPlace && this.weatherPlace !== key) this.resetWeather();
    this.weatherPlace = key;
    this.draw();
  }
  setReplay(on) { this.replay = on; this.draw(); this.schedule(); }
  setReplayMoment(at) { this.replayAt = at; this.draw(); }
  async prepareMoment(_at) { return true; }
  setReplayStill(_image, _at) { return false; }
  clearArrivals() { this.bubbles = []; this.draw(); }
  quietRoomChips() { this.draw(); }
  resetGlints() { this.draw(); }
  offerArrival(_event, _live) { this.draw(); }
  offerReplayArrival(_event) { this.draw(); }
  setCovered(_covered) { this.draw(); }

  draw(at = performance.now()) {
    const ctx = this.ctx;
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#222538';
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const v = this.viewport;
    ctx.setTransform(v.zoom, 0, 0, v.zoom, v.panX, v.panY);
    ctx.imageSmoothingEnabled = false;
    if (this.background.complete && this.background.naturalWidth) ctx.drawImage(this.background, 0, 0, WORLD_W, WORLD_H);
    else { ctx.fillStyle = '#4b3556'; ctx.fillRect(0, 0, WORLD_W, WORLD_H); }
    const now = new Date();
    const historical = this.replay && this.replayAt ? new Date(this.replayAt) : now;
    const moment = outdoorMoment(Number.isFinite(historical.getTime()) ? historical : now, studioPlace());
    const weather = this.currentWeather(now.getTime());
    const animate = this.weatherAnimating(weather);
    const ambient = this.ambientAnimating();
    if (ambient && this.lifeFrameAt !== null) this.lifeElapsed += Math.max(0, Math.min(250, at - this.lifeFrameAt));
    this.lifeFrameAt = ambient ? at : null;
    if (animate && this.weatherFrameAt !== null) this.weatherElapsed += Math.max(0, Math.min(250, at - this.weatherFrameAt));
    this.weatherFrameAt = animate ? at : null;
    drawOutdoorLight(ctx, moment, weather);
    const sky = drawOutdoorSky(ctx, this.background, moment, weather, this.lifeElapsed);
    this.street = drawOutdoorLife(ctx, weather, this.lifeElapsed, moment);
    drawOutdoorWeather(ctx, weather, this.weatherElapsed);
    for (const p of this.visiblePositions()) {
      const selected = p.id === this.selected || p.id === this.hover;
      const profile = this.profileFor(p.agent);
      const motion = this.motionFor(p.agent);
      drawSeatedPerson(ctx, profile, motion, p.x, p.y, p.scale || 1.5, false, p.orientation);
      restoreFurniture(ctx, this.background, p, this.pixelLayout);
      drawDeskGesture(ctx, profile, motion, p.x, p.y, p.scale || 1.5);
      // A tiny real-state indicator keeps the detailed furniture and room readable.
      ctx.fillStyle = '#222538'; ctx.fillRect(p.x + 17, p.y - 61, 5, 5);
      ctx.fillStyle = motion.color; ctx.fillRect(p.x + 18, p.y - 60, 3, 3);
      const bubble = this.bubbles.find(b => b.agentId === p.id && b.expiresAt > Date.now());
      if (bubble && selected) this.speech(ctx, bubble, p);
    }
    this.bubbles = this.bubbles.filter(b => b.expiresAt > Date.now());
    const clock = drawOutdoorClock(ctx, now, this.facts?.timeZone);
    if (this.options.infoElement) {
      this.options.infoElement.textContent = outdoorReadout(clock, weather, this.replay);
      this.options.infoElement.title = weather.available ? `${studioPlace().city} · ${weather.observedAt || 'observație curentă'} · ${this.weatherSource}` : 'Ora studioului; datele meteo nu sunt disponibile.';
    }
    this.environment = { clock, phase: moment.phase, daylight: moment.daylight, moon: sky.moon, sun: sky.sun, stars: sky.stars, weather: weather.condition, available: weather.available, animating: animate, ambientAnimating: ambient };
    this.clockAt = now.getTime();
  }
  speech(ctx, bubble, person) {
    const pages = bubble.pages || bubblePages(bubble.text);
    const frame = bubbleFrame(pages, (Date.now() - bubble.createdAt) / 1000);
    const lines = this.options.reducedMotion?.() ? pages[frame.pageIndex] || [] : frame.lines;
    const left = Math.max(4, Math.min(WORLD_W - 188, person.x - 92));
    const top = person.y - 132;
    ctx.fillStyle = '#222538'; ctx.fillRect(left, top, 184, 54);
    ctx.strokeStyle = '#d5b28a'; ctx.lineWidth = 1; ctx.strokeRect(left, top, 184, 54);
    ctx.font = '10px monospace'; ctx.fillStyle = '#f4dfb4';
    lines.forEach((line, i) => ctx.fillText(line, left + 8, top + 13 + i * 12));
    if (frame.pageCount > 1) { ctx.font = '8px monospace'; ctx.fillStyle = '#c3b9bb'; ctx.fillText(`${frame.pageIndex + 1}/${frame.pageCount}`, left + 151, top + 48); }
  }
  renderRoster() {
    const host = document.getElementById('pixel-roster');
    if (!host) return;
    const key = JSON.stringify(this.agents.map(a => [a.id || a.agent_id, a.display_name, a.runtime_state, a.lifecycle, this.selected]));
    if (key === this.rosterKey) return;
    this.rosterKey = key;
    // Reconcile in place so live updates preserve the keyboard focus and scroll position.
    const ids = new Set(this.positions.map(p => p.id));
    for (const child of Array.from(host.children)) if (!ids.has(child.getAttribute('data-agent'))) child.remove();
    for (const p of this.positions) {
      let button = /** @type {HTMLButtonElement} */ (Array.from(host.children).find(el => el.getAttribute('data-agent') === p.id));
      if (!button) {
        button = document.createElement('button'); button.type = 'button'; button.dataset.agent = p.id;
        button.addEventListener('click', () => this.select(button.dataset.agent));
        host.append(button);
      }
      button.textContent = `${p.agent.display_name || p.agent.name || p.id} · ${['PAUSED', 'SUSPENDED'].includes(p.agent.lifecycle) ? 'în pauză' : runtimeLabel(p.agent.runtime_state || 'UNKNOWN')}`;
      button.setAttribute('aria-pressed', String(p.id === this.selected));
      button.dataset.state = this.motionFor(p.agent).mode;
      button.title = `Birou personal: ${p.agent.display_name || p.id}. ${runtimeLabel(p.agent.runtime_state || 'UNKNOWN')}`;
    }
  }
  select(id) {
    const p = this.positions.find(p => p.id === id);
    if (!p) return;
    this.setSelectedAgent(id);
    this.options.onSelectAgent?.(p.agent);
  }
  bindInput() {
    this.canvas.addEventListener('wheel', event => {
      const rect = this.canvas.getBoundingClientRect();
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        this.zoomTo(this.zoom * Math.exp(-event.deltaY * 0.002), { x: event.clientX - rect.left, y: event.clientY - rect.top });
      } else {
        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1;
        const moved = event.shiftKey ? this.panBy(-event.deltaY * unit, -event.deltaX * unit) : this.panBy(-event.deltaX * unit, -event.deltaY * unit);
        if (moved) event.preventDefault();
      }
    }, { passive: false });
    this.canvas.addEventListener('pointerdown', event => {
      if (event.button === 0) this.suppressClick = false;
      if (event.button !== 0 || !this.movable) return;
      this.drag = { id: event.pointerId, x: event.clientX, y: event.clientY, originX: event.clientX, originY: event.clientY, moved: false };
      this.canvas.setPointerCapture(event.pointerId);
    });
    this.canvas.addEventListener('pointermove', event => {
      if (this.drag?.id === event.pointerId) {
        const drag = this.drag;
        if (drag.moved || Math.hypot(event.clientX - drag.originX, event.clientY - drag.originY) > 4) {
          drag.moved = true; this.suppressClick = true; this.hover = null;
          this.panBy(event.clientX - drag.x, event.clientY - drag.y);
          drag.x = event.clientX; drag.y = event.clientY; return;
        }
      }
      const rect = this.canvas.getBoundingClientRect();
      const p = this.viewport.screenToWorld((event.clientX - rect.left) * this.dpr, (event.clientY - rect.top) * this.dpr);
      const hit = this.renderer.hits.find(h => p.x >= h.x && p.x <= h.x + h.w && p.y >= h.y && p.y <= h.y + h.h);
      this.hover = hit ? String(hit.agent.id || hit.agent.agent_id) : null;
      this.canvas.style.cursor = hit ? 'pointer' : this.movable ? 'grab' : 'default';
      this.canvas.title = hit ? `${hit.agent.display_name || hit.agent.id}: ${runtimeLabel(this.motionFor(hit.agent).mode === 'PAUSED' ? 'PAUSED' : hit.agent.runtime_state || 'UNKNOWN')}` : 'Birourile agenților · Ctrl + rotiță: zoom · scena mărită: scroll sau tragere · Încadrează: vedere completă';
      this.draw();
    });
    const endDrag = event => {
      if (this.drag?.id !== event.pointerId) return;
      this.drag = null;
      if (this.canvas.hasPointerCapture(event.pointerId)) this.canvas.releasePointerCapture(event.pointerId);
      this.canvas.style.cursor = this.movable ? 'grab' : 'default';
    };
    this.canvas.addEventListener('pointerup', endDrag);
    this.canvas.addEventListener('pointercancel', endDrag);
    this.canvas.addEventListener('lostpointercapture', endDrag);
    this.canvas.addEventListener('pointerleave', () => { this.hover = null; this.draw(); });
    this.canvas.addEventListener('click', event => {
      if (this.suppressClick) { this.suppressClick = false; return; }
      const rect = this.canvas.getBoundingClientRect();
      const p = this.viewport.screenToWorld((event.clientX - rect.left) * this.dpr, (event.clientY - rect.top) * this.dpr);
      const hit = this.renderer.hits.find(h => p.x >= h.x && p.x <= h.x + h.w && p.y >= h.y && p.y <= h.y + h.h);
      if (hit) this.select(String(hit.agent.id || hit.agent.agent_id));
    });
    this.canvas.addEventListener('keydown', event => {
      if (!this.positions.length) return;
      const index = this.positions.findIndex(p => p.id === (this.hover || this.selected));
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        event.preventDefault();
        const direction = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1;
        this.hover = this.positions[(index + direction + this.positions.length) % this.positions.length].id;
        const p = this.positions.find(p => p.id === this.hover);
        if (p.page !== this.page) this.showPage(p.page);
        this.canvas.setAttribute('aria-label', `${p.agent.display_name || p.id}: ${runtimeLabel(p.agent.runtime_state)}. Enter deschide angajatul.`);
        this.draw();
      } else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); this.select(this.hover || this.positions[0].id); }
    });
  }
}

export class PixelTitle {
  constructor({ stage, caption }) { this.stage = stage; this.caption = caption; this.visible = true; }
  start() { this.caption.textContent = 'AMN-AI · studioul creativ'; }
  show() { this.visible = true; this.stage.hidden = false; document.body.classList.add('is-title'); }
  hide() { this.visible = false; this.stage.hidden = true; document.body.classList.remove('is-title', 'is-entering'); }
  async enter(_landing = null) { this.hide(); return true; }
}
