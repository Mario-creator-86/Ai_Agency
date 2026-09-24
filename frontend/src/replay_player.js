/**
 * «RELUAREA ZILEI» ON THE PAGE (W13): the controls on the slate, the clock beside the live
 * clock, the letterbox, the prompt when live news arrives, and the world fed from the record.
 *
 * The logic is day_replay.js (pure, node-tested); this is its hands. The record is read once when
 * the replay starts (readRecord: a bisection to the run's start, then pages of 300), and kept for
 * the run while the page is open. Nothing is fetched per frame: the frame loop advances the
 * clock, and only when the record's next event is crossed does the world change.
 *
 * While it plays, the world is the replay's alone: the page stops handing the engine its live
 * agents, speech and facts (main.js asks `active`), and gives them back when it ends. The
 * drawers, the register and the readouts outside the world keep saying live values.
 */

import {
  LIVE_WINS_MS, REPLAY_BUBBLE_MS, REPLAY_SPEEDS, REPLAY_STEP_MS, ReplayClock, acceptFigures, agentsAt, buildTimeline, crossed, figuresQuery,
  figuresAt, frameAt, captionLines, indexAt, nextStageTime, prevStageTime, quietSpans, readRecord, replayBubble, replayWords, replayableRun,
  stageTicks,
} from './day_replay.js';
import { latestFilm } from './hq_screens.js';
import { fromKeyboard, replayFocus } from './replay_invite.js';
import { describeEvent } from './ledger.js';

/**
 * @typedef {{
 *   api: (path: string) => Promise<any>,
 *   engine: () => any,
 *   agents: () => any[],
 *   known: () => any[],
 *   cursor: () => number,
 *   timeZone: () => string|undefined,
 *   today: () => string|null,
 *   reduced: () => boolean,
 *   names: () => Record<string, string>,
 *   poster?: (assetId: string) => Promise<HTMLCanvasElement|null>,
 *   onEnter: () => void,
 *   onExit: (liveEvents: any[]) => void,
 *   onChange: () => void,
 *   onOffer: (offered: boolean) => void,
 * }} ReplayDeps
 */

/** The record's moment at a fraction of the replay, without moving the clock. @param {ReplayClock} clock @param {number} f */
function recordFraction(clock, f) {
  const p = clock.p;
  const t = clock.seekFraction(f);
  clock.p = p;
  return t;
}

const $ = (/** @type {string} */ id) => /** @type {HTMLElement} */ (document.getElementById(id));

export class DayReplayPlayer {
  /** @param {ReplayDeps} deps */
  constructor(deps) {
    this.deps = deps;
    /** @type {any|null} the run a replay would play */
    this.run = null;
    /** @type {import('./day_replay.js').Timeline|null} */
    this.timeline = null;
    /** @type {ReplayClock|null} */
    this.clock = null;
    /** @type {import('./day_replay.js').ReplayFrame|null} */
    this.frame = null;
    this.active = false;
    this.loading = false;
    /** @type {any[]} the replay's captions on the page */
    this.bubbles = [];
    this.raf = 0;
    this.last = 0;
    this.stepWait = 0;
    this.lastIndex = -1;
    this.lastSecond = -1;
    this.lastStage = '';
    this.lastPermille = '';
    this.lastRate = '';
    /** The requests the last read of the record took (bisection and pages), for QA. */
    this.requests = 0;
    /** @type {any[]} live events that arrived while the replay played */
    this.liveEvents = [];
    this.liveTimer = 0;
    this.liveTick = 0;
    this.liveUntil = 0;
    /** @type {HTMLElement|null} */
    this.returnFocus = null;
    /** Whether this replay was started from the keyboard (W17): only then does the page move focus. */
    this.byKeyboard = false;
    this.film = /** @type {{assetId: string, date: string|null, canvas: HTMLCanvasElement}|null} */ (null);
    this.filmRead = 'none';
    /** How the record was read the last time: one read by time, or bisection (an older studio). */
    this.readMethod = '';
    /**
     * The books at the moments the run crossed (/economy/as-of, W15), sorted; null when the studio
     * cannot answer them (an older studio), and the Treasury and the tokens plate then say «—».
     * @type {any[]|null}
     */
    this.figures = null;
    this.figuresRun = '';
    /** The first moment the books were not asked about (ms), or null (W17). @type {number|null} */
    this.figuresUntil = null;
    this.el = {
      toggle: /** @type {HTMLButtonElement} */ ($('replay-toggle')),
      viewport: $('scene-viewport'),
      bar: $('replay-bar'),
      play: /** @type {HTMLButtonElement} */ ($('replay-play')),
      prev: /** @type {HTMLButtonElement} */ ($('replay-prev')),
      next: /** @type {HTMLButtonElement} */ ($('replay-next')),
      scrub: /** @type {HTMLInputElement} */ ($('replay-scrub')),
      ticks: $('replay-ticks'),
      track: $('replay-track'),
      time: $('replay-time'),
      stage: $('replay-stage'),
      progress: $('replay-progress'),
      rate: $('replay-rate'),
      exit: /** @type {HTMLButtonElement} */ ($('replay-exit')),
      back: /** @type {HTMLButtonElement} */ ($('replay-back')),
      then: $('replay-then'),
      thenTime: $('replay-then-time'),
      live: $('replay-live'),
      liveWhat: $('replay-live-what'),
      liveGo: /** @type {HTMLButtonElement} */ ($('replay-live-go')),
      liveCount: $('replay-live-count'),
      announce: $('replay-announce'),
      weather: $('replay-weather'),
      note: $('register-replay-note'),
      speeds: /** @type {HTMLButtonElement[]} */ (Array.from(document.querySelectorAll('#replay-bar .replay-speed'))),
    };
    this._loop = this._loop.bind(this);
    this._bind();
  }

  /* ----------------------------------------------------------------- offer -- */

  /**
   * The runbook's record was read: the newest finished run is what a replay plays. With none on
   * record, the button is not offered.
   * @param {any[]|null|undefined} runs
   */
  setRuns(runs) {
    const run = replayableRun(runs);
    if (run && this.run && run.id !== this.run.id && !this.active) this.timeline = null;
    this.run = run;
    this.el.toggle.hidden = !run;
    this.deps.onOffer(Boolean(run));
  }

  /** Sign-out: nothing is kept. */
  reset() {
    if (this.active) this.exit({ silent: true });
    this.run = null;
    this.timeline = null;
    this.el.toggle.hidden = true;
  }

  /* ------------------------------------------------------------ the words -- */

  /** What the chip, the clock and the slate say now, or null outside a replay. */
  words() {
    if (!this.active || !this.timeline || !this.clock) return null;
    const segment = this.clock.segment;
    return replayWords(this.timeline, this.clock.t, { timeZone: this.deps.timeZone(), stage: this.frame ? this.frame.stage : null, rate: this.clock.rate, staff: this.deps.agents().length, quiet: segment && segment.quiet ? segment : null });
  }

  /** The people and the facts of the world at the replay's moment, for the glass readout. */
  world() {
    if (!this.active || !this.frame) return null;
    return { agents: agentsAt(this.deps.agents(), this.frame), facts: this.facts(this.frame), now: this.frame.t };
  }

  /* --------------------------------------------------------- start / exit -- */

  /**
   * @param {HTMLElement|null} [origin] where the keyboard was, to return it there
   * @param {{keyboard?: boolean}} [how] started from the keyboard (W17): only then is focus moved
   */
  async start(origin = null, how = {}) {
    if (this.active || this.loading || !this.run) return;
    const run = this.run;
    this.loading = true;
    this.el.toggle.setAttribute('aria-busy', 'true');
    this.say('Se încarcă reluarea zilei din registrul studioului…');
    try {
      if (!this.timeline || this.timeline.runId !== String(run.id)) {
        const record = await readRecord((after, limit) => this.deps.api(`/events?after=${after}&limit=${limit}`), run, {
          cursor: this.deps.cursor(),
          known: this.deps.known(),
          // one read by time where the studio has it (W15); an older one is bisected as before
          since: (iso, limit) => this.deps.api(`/events?since=${encodeURIComponent(iso)}&limit=${limit}`),
        });
        this.timeline = buildTimeline(run, record.events, { complete: record.complete });
        this.requests = record.requests;
        this.readMethod = record.method;
      }
      // the world will be lit by the run's own hour: its plates are composed while this is read
      const engine = this.deps.engine();
      const lit = engine && engine.prepareMoment && this.timeline ? engine.prepareMoment(this.timeline.start).catch(() => false) : Promise.resolve(false);
      await Promise.all([this._readFilm(run), this._readFigures(this.timeline), lit]);
    } catch {
      this.timeline = null;
      this.say('Registrul rulării nu a putut fi citit. Clădirea rămâne live.');
      return;
    } finally {
      this.loading = false;
      this.el.toggle.removeAttribute('aria-busy');
    }
    const timeline = this.timeline;
    if (!timeline || !timeline.events.length) {
      this.say('Registrul nu mai are evenimentele acestei rulări. Clădirea rămâne live.');
      return;
    }
    const engine = this.deps.engine();
    if (!engine) return;
    this.returnFocus = origin || /** @type {HTMLElement|null} */ (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    this.byKeyboard = Boolean(how.keyboard);
    this.active = true;
    this.clock = new ReplayClock(timeline);
    this.clock.play();
    this.stepWait = 0;
    this.lastIndex = -1;
    this.lastSecond = -1;
    this.lastStage = '';
    this.bubbles = [];
    this.liveEvents = [];
    engine.setReplay(true);
    this.deps.onEnter();
    this._paintTicks();
    this.el.viewport.dataset.replay = 'on';
    this.el.bar.hidden = false;
    this.el.then.hidden = false;
    this.el.weather.hidden = false;
    const day = timeline.date ? timeline.date.slice(8, 10) + '.' + timeline.date.slice(5, 7) : '';
    this.el.note.textContent = `Clădirea redă ${day || 'ultima rulare încheiată'} · registrul rămâne live`;
    this.el.note.hidden = false;
    this.el.toggle.setAttribute('aria-pressed', 'true');
    this.el.toggle.title = 'Ieși din reluare (Esc)';
    this._speed(1);
    this._render(true);
    this.last = performance.now();
    this.raf = requestAnimationFrame(this._loop);
    const w = this.words();
    if (w) this.say(`Reluarea zilei a început: rularea din ${w.chip.replace(/^RELUARE · /, '').replace(' · ', ', ora ')}. Nu este live; vremea de atunci nu e cunoscută. Registrul rămâne live. Esc iese.`);
    if (replayFocus({ keyboard: this.byKeyboard, inControls: false }).onStart) this.el.play.focus({ preventScroll: true });
  }

  /**
   * Back to live. The page gives the world its live state again (onExit), with the live events
   * that arrived during the replay, so a fresh arrival is still seen.
   * @param {{silent?: boolean, focus?: boolean}} [options]
   */
  exit(options = {}) {
    if (!this.active) return;
    // where the keyboard is, read before the controls go (W17)
    const focused = document.activeElement;
    const inControls = Boolean(focused && (this.el.bar.contains(focused) || this.el.live.contains(focused)));
    this.active = false;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    window.clearInterval(this.liveTick);
    window.clearTimeout(this.liveTimer);
    this.el.live.hidden = true;
    this.el.bar.hidden = true;
    this.el.back.hidden = true;
    this.el.exit.hidden = false;
    this.el.then.hidden = true;
    this.el.weather.hidden = true;
    this.el.note.hidden = true;
    delete this.el.viewport.dataset.replay;
    this.el.toggle.setAttribute('aria-pressed', 'false');
    this.el.toggle.title = 'Reluarea zilei: ultima rulare încheiată, redată din registrul studioului';
    this.bubbles = [];
    this.frame = null;
    const engine = this.deps.engine();
    if (engine) engine.setReplay(false);
    const live = this.liveEvents;
    this.liveEvents = [];
    this.deps.onExit(live);
    if (!options.silent) this.say('Înapoi la live.');
    const moveFocus = replayFocus({ keyboard: this.byKeyboard, inControls }).onExit;
    if (options.focus !== false && moveFocus && this.returnFocus && document.contains(this.returnFocus)) this.returnFocus.focus({ preventScroll: true });
    this.returnFocus = null;
    this.byKeyboard = false;
  }

  /**
   * LIVE WINS: a live event that changes the world, while the day is replayed. A prompt says what
   * is happening now, in the register's own words, and the page returns to live on a click or by
   * itself after LIVE_WINS_MS. The world is never live and replayed at once.
   * @param {any} event
   */
  liveArrived(event) {
    if (!this.active) return;
    this.liveEvents.push(event);
    const d = describeEvent(event, this.deps.names());
    const what = [d.who, d.label].filter(Boolean).join(' · ') + (d.text ? ` · ${d.text}` : '');
    this.el.liveWhat.textContent = what || 'Studioul lucrează acum.';
    if (!this.el.live.hidden) return;
    this.el.live.hidden = false;
    this.liveUntil = performance.now() + LIVE_WINS_MS;
    const tick = () => {
      const left = Math.max(0, Math.ceil((this.liveUntil - performance.now()) / 1000));
      this.el.liveCount.textContent = String(left);
    };
    tick();
    this.liveTick = window.setInterval(tick, 250);
    this.liveTimer = window.setTimeout(() => {
      // Back to live by itself (W15): the keyboard that was on the replay's controls lands on the
      // dock's «Reluare» key, which is still there, rather than on nothing.
      const active = document.activeElement;
      const onControls = Boolean(active && (this.el.bar.contains(active) || this.el.live.contains(active)));
      this.exit({ focus: false });
      if (onControls && !this.el.toggle.hidden) this.el.toggle.focus({ preventScroll: true });
    }, LIVE_WINS_MS);
  }

  /* ---------------------------------------------------------- the frames -- */

  /** @param {number} now */
  _loop(now) {
    if (!this.active || !this.clock || !this.timeline) return;
    const dt = Math.min(100, Math.max(0, now - this.last));
    this.last = now;
    const clock = this.clock;
    if (this.deps.reduced()) {
      // Reduced motion: nothing animates. The replay steps from one stage to the next.
      if (clock.playing) {
        this.stepWait += dt;
        if (this.stepWait >= REPLAY_STEP_MS / clock.speed) {
          this.stepWait = 0;
          clock.seek(nextStageTime(this.timeline, clock.t));
          if (clock.ended) clock.pause();
        }
      }
    } else {
      const from = clock.t;
      const to = clock.advance(dt);
      // what the record did between the two moments says itself in the world, as it happened
      const engine = this.deps.engine();
      for (const event of crossed(this.timeline, from, to)) {
        if (engine) engine.offerReplayArrival(event);
        this._caption(event);
      }
    }
    this._render(false);
    this.raf = requestAnimationFrame(this._loop);
  }

  /** @param {any} event */
  _caption(event) {
    const said = replayBubble(event, { timeZone: this.deps.timeZone() });
    if (!said) return;
    const now = Date.now();
    this.bubbles = this.bubbles.filter((b) => b.agentId !== said.agentId);
    // the words as written, whole lines, no typing: a caption of the replay is read at a glance
    this.bubbles.push({ id: `replay_${event.sequence}`, agentId: said.agentId, text: said.text, label: said.label, lines: captionLines(said.text), x: 0, y: 0, createdAt: now, expiresAt: now + REPLAY_BUBBLE_MS });
    this._pushBubbles();
  }

  _pushBubbles() {
    const engine = this.deps.engine();
    if (engine) engine.setSpeechBubbles(this.bubbles);
  }

  /**
   * The facts the building's faces are drawn from, at the frame: what the record carries at that
   * moment, and «—» for what it does not (the treasury, the budget, the serial, the schedule).
   * @param {import('./day_replay.js').ReplayFrame} frame
   */
  facts(frame) {
    // the books as they stood at the moment (/economy/as-of): the newest reading at or before it
    const reading = /** @type {any} */ (figuresAt(this.figures, frame.t, this.figuresUntil));
    const film = latestFilm([frame.run]);
    const shown = film && this.film && this.film.assetId === film.assetId ? { ...film, canvas: this.film.canvas } : null;
    return {
      run: frame.run,
      track: frame.track,
      today: this.deps.today(),
      live: true,
      treasury: reading ? reading.treasury : null,
      budget: reading ? reading.budget : null,
      episodes: null,
      topics: frame.topics,
      film: shown,
      jobs: null,
      tasks: frame.tasks,
      nextRun: '',
      stopped: null,
      timeZone: this.deps.timeZone(),
      replay: true,
      reads: { runs: 'ok', episodes: 'pending', figures: reading ? 'ok' : 'pending', ledger: frame.topics.titles.length ? 'ok' : 'pending', film: film ? (shown ? 'ok' : this.filmRead === 'failed' ? 'failed' : 'pending') : 'pending' },
    };
  }

  /**
   * The books at every moment the run can have moved a figure (day_replay.js figureMoments), in
   * one request, once per run. A studio without /economy/as-of answers 404: the walls say «—».
   * @param {import('./day_replay.js').Timeline|null} timeline
   */
  async _readFigures(timeline) {
    if (!timeline) return;
    if (this.figuresRun === timeline.runId && this.figures) return;
    // a studio that could not read its log by time predates the books' read too (W16): not asked
    const query = figuresQuery(timeline, this.readMethod);
    if (!query) {
      this.figures = null;
      this.figuresUntil = null;
      this.figuresRun = '';
      return;
    }
    // one read per 240 moments, one after the other, all now: nothing is read while it plays (W17)
    /** @type {any[]|null} */
    let readings = [];
    for (const read of query.reads) {
      const answer = await this.deps.api(read.path).catch(() => null);
      const part = acceptFigures(answer, read.moments);
      if (!part) {
        readings = null;
        break;
      }
      readings.push(...part);
    }
    this.figures = readings && readings.length ? readings : null;
    this.figuresUntil = this.figures ? query.until : null;
    this.figuresRun = this.figures ? timeline.runId : '';
  }

  /** @param {any} run */
  async _readFilm(run) {
    const film = latestFilm([run]);
    if (!film || !this.deps.poster) {
      this.film = null;
      this.filmRead = 'none';
      return;
    }
    if (this.film && this.film.assetId === film.assetId) return;
    // the same decode the render bay uses, cached per film (film_poster.js PosterCache)
    const canvas = await this.deps.poster(film.assetId).catch(() => null);
    this.film = canvas ? { ...film, canvas } : null;
    this.filmRead = canvas ? 'ok' : 'failed';
  }

  /** @param {boolean} force */
  _render(force) {
    const timeline = this.timeline;
    const clock = this.clock;
    if (!timeline || !clock) return;
    const engine = this.deps.engine();
    // the world is lit by the replayed moment's own sun (the world re-reads it once a second)
    if (engine) engine.setReplayMoment(clock.t);
    const index = indexAt(timeline, clock.t);
    if (force || index !== this.lastIndex) {
      this.lastIndex = index;
      this.frame = frameAt(timeline, clock.t);
      if (engine) {
        engine.setAgents(agentsAt(this.deps.agents(), this.frame));
        engine.setProjectTokens([]);
        engine.setFacts(this.facts(this.frame));
      }
      this.deps.onChange();
    }
    const now = Date.now();
    const kept = this.bubbles.filter((b) => b.expiresAt > now);
    if (kept.length !== this.bubbles.length || force) {
      this.bubbles = kept;
      this._pushBubbles();
    }
    const w = this.words();
    if (!w) return;
    const second = Math.floor(clock.t / 1000);
    if (force || second !== this.lastSecond) {
      this.lastSecond = second;
      this.el.time.textContent = w.clock;
      this.el.thenTime.textContent = w.clock;
      this.el.progress.textContent = w.progress;
      this.el.scrub.setAttribute('aria-valuetext', `${w.clock}, ${w.stage}`);
      this.deps.onChange();
    }
    if (force || w.rate !== this.lastRate) {
      // the rate changes in a quiet stretch of the record, and says so
      this.lastRate = w.rate;
      this.el.rate.textContent = w.rate;
    }
    if (force || w.stage !== this.lastStage) {
      this.lastStage = w.stage;
      this.el.stage.textContent = w.stage;
      // a stage change is said once; a second's tick is not
      if (!force) this.say(w.sentence);
    }
    // the scrubber's knob and its played run: written only when they move a pixel's worth
    const permille = String(Math.round(clock.fraction * 1000));
    if (force || permille !== this.lastPermille) {
      this.lastPermille = permille;
      this.el.scrub.value = permille;
      this.el.track.style.setProperty('--replay-p', `${Number(permille) / 10}%`);
    }
    const playing = clock.playing;
    // W17: at the end, paused on the whole run, the way back to live is offered beside it
    const over = clock.ended && !playing;
    if (this.el.back.hidden === over) {
      const hadExit = document.activeElement === this.el.exit;
      const hadBack = document.activeElement === this.el.back;
      this.el.back.hidden = !over;
      this.el.exit.hidden = over;
      if (over && hadExit) this.el.back.focus({ preventScroll: true });
      if (!over && hadBack) this.el.exit.focus({ preventScroll: true });
    }
    if (this.el.play.dataset.state !== (playing ? 'playing' : 'paused')) {
      this.el.play.dataset.state = playing ? 'playing' : 'paused';
      const label = playing ? 'Pauză' : clock.ended ? 'Redă din nou' : 'Redă';
      this.el.play.setAttribute('aria-label', label);
      this.el.play.title = `${label} (Spațiu)`;
    }
  }

  _paintTicks() {
    if (!this.timeline || !this.clock) return;
    const schedule = this.clock.schedule;
    const quiet = quietSpans(schedule).map((q) => {
      const span = document.createElement('span');
      span.className = 'replay-quiet';
      span.style.left = `${q.from * 100}%`;
      span.style.width = `${(q.to - q.from) * 100}%`;
      return span;
    });
    const ticks = stageTicks(this.timeline, schedule).map((t) => {
      const mark = document.createElement('span');
      mark.className = 'replay-tick';
      mark.style.left = `${t.p * 100}%`;
      return mark;
    });
    this.el.ticks.replaceChildren(...quiet, ...ticks);
  }

  /* --------------------------------------------------------- the controls -- */

  toggle() {
    if (!this.clock) return;
    if (this.clock.playing) this.clock.pause();
    else this.clock.play();
    this.stepWait = 0;
    this._render(true);
  }

  /** @param {number} t */
  seek(t) {
    if (!this.clock) return;
    this.clock.seek(t);
    // what was arriving belongs to the moment left
    const engine = this.deps.engine();
    if (engine) engine.clearArrivals();
    this.bubbles = [];
    this.stepWait = 0;
    this._render(true);
    if (this.frame) this.say(/** @type {any} */ (this.words()).sentence);
  }

  /** @param {number} speed */
  _speed(speed) {
    if (!this.clock || !REPLAY_SPEEDS.includes(speed)) return;
    this.clock.setSpeed(speed);
    for (const b of this.el.speeds) b.setAttribute('aria-pressed', String(Number(b.dataset.speed) === speed));
    const w = this.words();
    if (w) {
      this.lastRate = w.rate;
      this.el.rate.textContent = w.rate;
      this.el.bar.title = w.title;
    }
  }

  /** @param {string} text */
  say(text) {
    this.el.announce.textContent = text;
  }

  _bind() {
    const el = this.el;
    el.toggle.addEventListener('click', (e) => (this.active ? this.exit() : this.start(el.toggle, { keyboard: fromKeyboard(e) })));
    el.play.addEventListener('click', () => this.toggle());
    el.prev.addEventListener('click', () => this.timeline && this.clock && this.seek(prevStageTime(this.timeline, this.clock.t)));
    el.next.addEventListener('click', () => this.timeline && this.clock && this.seek(nextStageTime(this.timeline, this.clock.t)));
    el.exit.addEventListener('click', () => this.exit());
    el.back.addEventListener('click', () => this.exit());
    el.liveGo.addEventListener('click', () => this.exit());
    el.scrub.addEventListener('input', () => {
      if (!this.clock) return;
      // the scrubber's axis is the replay's own time (a quiet stretch is as short on it as on the page)
      this.seek(recordFraction(this.clock, Number(el.scrub.value) / 1000));
    });
    el.scrub.addEventListener('keydown', (e) => {
      // Page Up / Page Down walk the stages; the arrows move the moment
      if (!this.timeline || !this.clock) return;
      if (e.key === 'PageDown' || e.key === 'PageUp') {
        e.preventDefault();
        this.seek(e.key === 'PageDown' ? nextStageTime(this.timeline, this.clock.t) : prevStageTime(this.timeline, this.clock.t));
      }
    });
    for (const b of el.speeds) b.addEventListener('click', () => this._speed(Number(b.dataset.speed)));
    window.addEventListener('keydown', (e) => {
      if (!this.active || e.defaultPrevented) return;
      if (e.key === 'Escape') {
        // a dialog open over the replay closes first, as dialogs do
        if (document.querySelector('dialog[open]')) return;
        e.preventDefault();
        this.exit();
        return;
      }
      const target = /** @type {HTMLElement|null} */ (e.target instanceof HTMLElement ? e.target : null);
      const typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(target.tagName) || target.id === 'office-canvas');
      if ((e.key === ' ' || e.key === 'Spacebar') && !typing && !document.querySelector('dialog[open]')) {
        e.preventDefault();
        this.toggle();
      }
    });
  }
}
