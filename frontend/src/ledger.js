/**
 * The live ledger: everything the studio does and says, in the order it happened.
 *
 * The activity log listed event type names with an id; the Owner could see that "an agent
 * answered" but not what it said, and that "a workflow was created" but not where the work
 * stands. The ledger reads the same events and tells the story: who did it (the employee's
 * name when the event belongs to one), what it was in plain words, and the text that was
 * said or decided, taken from the event's payload. It also keeps one line at the top that
 * says where production is right now.
 *
 * Two sources feed it, both events already recorded by the backend: the live socket, for the
 * handful of event types the outbox streams, and the events endpoint, polled after each
 * snapshot for everything else. Entries are deduplicated by event id and ordered by sequence,
 * so the two sources never produce a double or a jump backwards.
 *
 * `describeEvent` and `productionStatus` are pure, so what the ledger says is testable.
 */

const FAMILY_KIND = {
  agent: 'work',
  director: 'work',
  role: 'work',
  workforce: 'work',
  workflow: 'production',
  factual: 'production',
  media: 'production',
  research: 'production',
  story: 'production',
  runbook: 'production',
  publishing: 'production',
  channel: 'production',
  economy: 'money',
  strategy: 'money',
  analytics: 'money',
  autonomy: 'owner',
  settings: 'owner',
  provider: 'owner',
  youtube: 'owner',
  character: 'owner',
  studio: 'system',
  office: 'system',
  experiment: 'system',
};

/** Kinds the filter chips offer, in display order. */
export const KINDS = [
  ['all', 'Tot'],
  ['speech', 'Vorbe'],
  ['production', 'Producție'],
  ['work', 'Personal'],
  ['money', 'Bani'],
  ['owner', 'Owner'],
];

const STAGE_LABEL = {
  RESEARCH: 'Cercetare',
  RESEARCHED: 'Cercetat',
  SCRIPTING: 'Scenariu',
  SCRIPT_READY: 'Scenariu gata',
  STORYBOARD: 'Storyboard',
  MEDIA_GENERATION: 'Generare media',
  RENDERING: 'Randare',
  QUALITY_CONTROL: 'Control calitate',
  READY_TO_PUBLISH: 'Gata de publicare',
  PUBLISHING: 'Publicare',
  PUBLISHED: 'Publicat',
  ANALYTICS: 'Analiză',
  LEARNING: 'Învățare',
};

/** The stages of the daily runbook, as the Owner reads them in the panel. */
const RUN_STAGE_LABEL = {
  preflight: 'verificarea de dinainte',
  performance_intake: 'preluarea performanței',
  idea_generation: 'generarea de idei',
  research_and_verification: 'cercetare și verificare',
  selection: 'selecția subiectului',
  script_and_storyboard: 'scenariu și storyboard',
  media: 'producția media',
  edit_and_qc: 'montaj și control calitate',
  publish: 'publicare',
  post_run: 'raportare și închiderea zilei',
  daily_log: 'jurnalul zilei',
  serial_queue: 'episodul serialului',
};

/** What each kind of letter is, as the Owner would name it. */
const MAIL_INTENT = {
  REQUEST_INFO: 'întrebare',
  REQUEST_REVIEW: 'cerere de revizuire',
  CHALLENGE: 'contestare',
  HANDOFF: 'indicație',
  STATUS: 'raport',
  ESCALATE: 'escaladare',
};

const STATUS_LABEL = {
  COMPLETED: 'finalizată',
  PARTIAL: 'parțială',
  FAILED: 'eșuată',
  BLOCKED: 'blocată',
  SKIPPED: 'sărită',
  SUCCEEDED: 'reușită',
  PASSED: 'trecut',
  PUBLISHED: 'publicat',
  PUBLISHED_SIMULATED: 'publicare simulată',
};

function stageLabel(stage) {
  return STAGE_LABEL[stage] || String(stage || '').replace(/_/g, ' ').toLowerCase();
}

function runStageLabel(stage) {
  return RUN_STAGE_LABEL[stage] || String(stage || '').replace(/_/g, ' ');
}

function statusLabel(status) {
  return STATUS_LABEL[status] || String(status || '').toLowerCase();
}

function short(text, max = 160) {
  const clean = String(text ?? '').replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/**
 * Describe one event for the Owner.
 *
 * @param {{event_type: string, aggregate_id?: string, payload?: any}} event
 * @param {Record<string, string>} [names] agent id → display name
 * @returns {{who: string, label: string, text: string, kind: string, to?: string, thread?: string|null, forOwner?: boolean}}
 */
export function describeEvent(event, names = {}) {
  const type = String(event.event_type || '');
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const family = type.split('.')[0];
  const agentId = payload.agent_id || (family === 'agent' ? event.aggregate_id : null);
  const who = (agentId && names[agentId]) || payload.from_name || '';
  let label = '';
  let text = '';
  let kind = FAMILY_KIND[family] || 'system';

  switch (type) {
    case 'agent.message_sent':
      label = 'a spus';
      text = payload.text || payload.content || '';
      kind = 'speech';
      break;
    case 'agent.message_posted':
      label = `${payload.in_reply_to ? 'răspunde' : 'scrie'} · ${MAIL_INTENT[payload.intent] || payload.intent || 'mesaj'}`;
      text = [payload.subject, payload.excerpt].filter(Boolean).join(' — ');
      kind = 'speech';
      // A letter: the ledger names both ends and opens the thread it belongs to. One
      // addressed to the Owner is the Owner's business: it files under the Owner chip and
      // is drawn in red until it is answered.
      return {
        who: who || payload.from_name || 'Owner',
        label: payload.for_owner ? `${label} · CĂTRE TINE` : label,
        text,
        kind: payload.for_owner ? 'owner' : kind,
        to: payload.to_name || 'Director',
        thread: payload.thread_id || event.aggregate_id || null,
        forOwner: Boolean(payload.for_owner),
      };
    case 'agent.message_answered':
      label = 'a răspuns la un mesaj';
      text = payload.subject || '';
      kind = 'speech';
      break;
    case 'agent.message_resolved':
      label = `a închis un mesaj (${payload.resolved_by || ''})`;
      text = payload.subject || '';
      kind = 'speech';
      break;
    case 'agent.state_changed':
      label = payload.runtime_state === 'THINKING' ? 'lucrează' : 'a terminat';
      text = payload.task_type ? `sarcina ${payload.task_type}` : '';
      break;
    case 'agent.run_completed':
      label = `sarcină ${statusLabel(payload.status)}`;
      text = [payload.task_type, payload.model_name].filter(Boolean).join(' · ');
      break;
    case 'agent.paused':
      label = 'pus pe pauză';
      break;
    case 'agent.resumed':
      label = 'reactivat';
      break;
    case 'agent.hired':
      label = 'angajat';
      text = [payload.display_name, payload.role].filter(Boolean).join(' · ');
      break;
    case 'director.review_completed':
      label = 'Directorul a revizuit ziua';
      text = `${payload.reviewed ?? 0} mesaje, ${payload.applied ?? 0} decizii`;
      break;
    case 'workflow.created':
    case 'workflow.job_scheduled':
    case 'workflow.job_activated':
      label = type === 'workflow.created' ? 'producție pornită' : 'flux programat';
      text = payload.current_stage ? `etapa: ${stageLabel(payload.current_stage)}` : '';
      break;
    case 'factual.topic_proposed':
      label = 'temă propusă';
      text = payload.title || '';
      break;
    case 'factual.topic_selected':
      label = 'temă aleasă pentru producție';
      text = payload.title || '';
      break;
    case 'factual.source_ingested':
      label = 'sursă citită';
      text = payload.title || payload.url || '';
      break;
    case 'factual.claim_extracted':
      label = 'afirmație extrasă';
      text = payload.claim_text || '';
      break;
    case 'factual.claim_verified':
      label = `verdict ${payload.status || ''}`.trim();
      text = payload.claim_text || payload.evidence_quote || '';
      break;
    case 'factual.script_verified_pass':
      label = 'scenariu verificat';
      text = payload.title || '';
      break;
    case 'factual.script_approved':
      label = 'scenariu aprobat de Owner';
      text = payload.title || '';
      break;
    case 'factual.script_blocked_by_gate':
      label = 'scenariu blocat de gate';
      text = payload.reason || '';
      break;
    case 'media.storyboard_created':
      label = 'storyboard creat';
      text = payload.title || '';
      break;
    case 'media.video_rendered':
      label = 'video randat';
      text = payload.provider_name || '';
      break;
    case 'media.render_failed':
      label = 'randare eșuată';
      text = payload.reason || '';
      break;
    case 'media.qc_evaluated':
      label = `control de calitate ${statusLabel(payload.status)}`;
      text = Array.isArray(payload.failures) ? payload.failures.join('; ') : '';
      break;
    case 'publishing.started':
      label = 'încărcare pornită';
      break;
    case 'publishing.video_published_simulated':
      label = 'publicare simulată (nimic pe YouTube)';
      break;
    case 'publishing.reconciled_published':
      label = 'publicat, confirmat de YouTube';
      text = payload.remote_video_id || '';
      break;
    case 'publishing.failed':
      label = 'publicare eșuată';
      text = payload.reason || payload.error || '';
      break;
    case 'provider.model_discovered':
      label = 'model găsit la furnizor';
      text = payload.model_name || '';
      break;
    case 'provider.registered':
      label = 'furnizor înregistrat';
      text = [payload.name, payload.provider_type].filter(Boolean).join(' · ');
      break;
    case 'agent.model_assigned':
      label = 'model atribuit';
      break;
    case 'role.created':
      label = 'rol creat';
      text = [payload.name, payload.mission].filter(Boolean).join(' — ');
      break;
    case 'role.contract_seeded':
      label = 'contract de muncă scris';
      text = payload.name || '';
      break;
    case 'settings.service_selected':
      label = 'serviciu ales pentru o sarcină';
      break;
    case 'settings.integration_deleted':
      label = 'integrare ștearsă';
      text = payload.kind || '';
      break;
    case 'youtube.authorization_started':
      label = 'autorizare YouTube pornită';
      break;
    case 'youtube.connection_created':
      label = 'conexiune YouTube creată';
      text = payload.name || '';
      break;
    case 'youtube.verified':
      label = 'canal YouTube verificat';
      text = payload.channel_title || payload.channel_id || '';
      break;
    case 'channel.created':
      label = 'canal creat';
      text = [payload.channel_name, payload.channel_type].filter(Boolean).join(' · ');
      break;
    case 'publishing.intent_created':
      label = 'publicare pregătită';
      text = payload.title || '';
      break;
    case 'publishing.video_published':
      label = 'video publicat';
      text = payload.title || payload.remote_url || '';
      break;
    case 'economy.transaction_posted':
      label = 'înregistrare în registrul contabil';
      text = [payload.kind, payload.memo, payload.amount_vr ? `${payload.amount_vr} VR$` : '']
        .filter(Boolean)
        .join(' · ');
      break;
    case 'research.host_revoked':
      label = 'sursă interzisă';
      text = payload.host || '';
      break;
    case 'studio.renamed':
      label = 'studioul a fost redenumit';
      text = [payload.previous_name, payload.name].filter(Boolean).join(' → ');
      break;
    case 'runbook.daily_run_started':
      label = 'ziua a început';
      text = `${payload.stages || ''} etape · preflight ${payload.preflight || ''}`.trim();
      break;
    case 'runbook.stage_started':
      label = 'etapă pornită';
      text = `${runStageLabel(payload.stage)}${payload.index ? ` (${payload.index}/${payload.total})` : ''}`;
      break;
    case 'runbook.stage_finished':
      label = `etapă ${statusLabel(payload.status)}`;
      text = [runStageLabel(payload.stage), payload.reason].filter(Boolean).join(' — ');
      break;
    case 'runbook.daily_run_finished':
      label = `rulare zilnică ${statusLabel(payload.status)}`;
      text = payload.preflight ? `preflight ${payload.preflight}` : '';
      break;
    case 'runbook.safe_mode_entered':
      label = 'SAFE MODE';
      text = payload.reason || '';
      break;
    case 'story.daily_log_closed':
      label = 'jurnalul zilei închis';
      break;
    case 'story.episode_drafted':
      label = 'episod scris';
      text = payload.title || '';
      break;
    case 'economy.provider_cost_recorded':
      label = `cost ${payload.status === 'BILLED' ? 'facturat' : 'estimat'}`;
      text = [payload.provider, payload.vr ? `${payload.vr} VR$` : ''].filter(Boolean).join(' · ');
      break;
    case 'economy.budget_set':
      label = 'buget stabilit';
      text = `${payload.period || ''} ${payload.limit_usd || ''} USD`.trim();
      break;
    case 'economy.budget_retired':
      label = 'buget retras';
      text = payload.period || '';
      break;
    case 'economy.vr_minted':
      label = 'VR$ emise din dovadă';
      text = payload.vr ? `${payload.vr} VR$` : '';
      break;
    case 'economy.owner_funding_recorded':
      label = 'finanțare de la Owner';
      text = payload.vr ? `${payload.vr} VR$` : '';
      break;
    case 'strategy.version_promoted':
      label = 'strategie promovată';
      text = `v${payload.new_version ?? ''}`;
      break;
    case 'autonomy.stopped':
      label = 'Owner a oprit autonomia';
      break;
    case 'autonomy.stop_cleared':
      label = 'Owner a pornit autonomia';
      break;
    case 'research.host_tested':
      label = `site testat: ${payload.status || ''}`.trim();
      text = payload.host || '';
      break;
    case 'research.host_authorised':
      label = 'site autorizat';
      text = payload.host || '';
      break;
    case 'settings.integration_saved':
      label = 'conexiune salvată';
      text = payload.kind || '';
      break;
    case 'settings.integration_checked':
      label = `conexiune verificată: ${payload.status || ''}`.trim();
      break;
    case 'provider.catalog_refreshed':
      label = 'catalog actualizat';
      text = [payload.models != null ? `${payload.models} modele` : '', payload.voices != null ? `${payload.voices} voci` : '']
        .filter(Boolean)
        .join(', ');
      break;
    case 'youtube.connected':
      label = 'cont YouTube conectat';
      text = payload.channel_title || '';
      break;
    case 'channel.credentials_bound':
      label = 'slot de canal legat de un cont';
      break;
    case 'character.identity_locks_set':
      label = 'identitate blocată';
      break;
    case 'studio.created':
      label = 'studioul a fost creat';
      break;
    case 'office.room_created':
      label = 'spațiu de lucru creat';
      break;
    default: {
      label = type.split('.').slice(1).join(' ').replace(/_/g, ' ') || type;
      const bits = Object.entries(payload)
        .filter(([, v]) => typeof v === 'string' || typeof v === 'number')
        .slice(0, 3)
        .map(([k, v]) => `${k}: ${v}`);
      text = bits.join(' · ');
    }
  }
  return { who, label, text: short(text), kind };
}

/**
 * Where production stands, from the newest events that say so.
 *
 * @param {Array<{event_type: string, payload?: any, sequence?: number}>} events newest first
 * @returns {{stage: string|null, run: string|null, running: string|null, text: string}}
 */
export function productionStatus(events) {
  let stage = null;
  let run = null;
  let running = null;
  for (const event of events) {
    const payload = event.payload || {};
    const type = String(event.event_type);
    // A stage that started and has not been seen finishing is where the day is right now;
    // it is newer than anything the workflow can say, so it is read first and wins.
    if (running === null && (type === 'runbook.stage_started' || type === 'runbook.stage_finished')) {
      running = type === 'runbook.stage_started' ? payload.stage || null : false;
    }
    if (!stage && type.startsWith('workflow.') && payload.current_stage) {
      stage = payload.current_stage;
    }
    if (!run && type === 'runbook.daily_run_finished') {
      run = payload.status || null;
    }
    if (stage && run && running !== null) break;
  }
  const parts = [];
  if (running) parts.push(`Acum: ${runStageLabel(running)}`);
  if (stage) parts.push(`producția: ${stageLabel(stage)}`);
  if (run) parts.push(`ultima rulare zilnică ${statusLabel(run)}`);
  if (!parts.length) return { stage, run, running: null, text: 'Nicio producție în curs.' };
  const text = parts.join(' · ');
  return { stage, run, running: running || null, text: text[0].toUpperCase() + text.slice(1) };
}

/** How many entries the ledger keeps on screen. Older ones are in the events endpoint. */
export const LEDGER_CAPACITY = 400;

export class Ledger {
  /**
   * @param {{list: HTMLElement, now: HTMLElement, filters: HTMLElement, escape: (s: string) => string,
   *          onEvents?: (events: any[]) => void, onThread?: (threadId: string) => void}} parts
   */
  constructor(parts) {
    this.list = parts.list;
    this.now = parts.now;
    this.filters = parts.filters;
    this.escape = parts.escape;
    // Called once per add() with the events that were actually new, whichever source they
    // came from — the socket, the snapshot or the events endpoint. The live agent windows
    // hang off this: they must see the same stream the ledger renders, without a second
    // subscription that could drift from it.
    this.onEvents = typeof parts.onEvents === 'function' ? parts.onEvents : null;
    // A letter in the ledger opens its thread; the page decides in which window.
    this.onThread = typeof parts.onThread === 'function' ? parts.onThread : null;
    this.list.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target.closest('[data-thread]') : null;
      if (target && this.onThread) this.onThread(target.getAttribute('data-thread'));
    });
    /** @type {Map<string, any>} */
    this.events = new Map();
    this.names = {};
    this.cursor = 0;
    this.backfilled = false;
    this.kind = 'all';
    this.timezone = undefined;
    this.renderFilters();
  }

  /** Names arrive after the first events (the office layout loads later); re-render then. */
  setNames(names) {
    const next = names || {};
    const changed = JSON.stringify(next) !== JSON.stringify(this.names);
    this.names = next;
    if (changed) this.render();
  }

  clear() {
    this.events.clear();
    this.cursor = 0;
    this.backfilled = false;
    this.render();
  }

  /** Add events from any source; duplicates are ignored, order comes from the sequence. */
  add(events) {
    const fresh = [];
    for (const event of Array.isArray(events) ? events : [events]) {
      if (!event || !event.event_id || this.events.has(event.event_id)) continue;
      this.events.set(event.event_id, event);
      fresh.push(event);
      if (Number.isFinite(event.sequence)) this.cursor = Math.max(this.cursor, event.sequence);
    }
    if (this.events.size > LEDGER_CAPACITY) {
      const sorted = this.sorted();
      for (const old of sorted.slice(LEDGER_CAPACITY)) this.events.delete(old.event_id);
    }
    if (fresh.length) {
      this.render();
      if (this.onEvents) this.onEvents(fresh);
    }
    return fresh.length > 0;
  }

  /** Newest first. */
  sorted() {
    return [...this.events.values()].sort(
      (a, b) => (b.sequence ?? 0) - (a.sequence ?? 0) || String(b.timestamp).localeCompare(String(a.timestamp)),
    );
  }

  /**
   * Pull everything recorded after the ledger's cursor. On first use, start a page back so
   * the Owner sees history, not only what happens from now on.
   */
  async sync(api, snapshotCursor) {
    if (!this.backfilled && Number.isFinite(snapshotCursor)) {
      // The snapshot's twenty events already set the cursor near the end; the first sync
      // looks a page further back so the day's history is on screen, not only its tail.
      this.cursor = Math.max(0, snapshotCursor - 200);
      this.backfilled = true;
    }
    for (let page = 0; page < 3; page += 1) {
      const data = await api(`/events?after=${this.cursor}&limit=200`);
      this.add(data.events || []);
      if (Number.isFinite(data.next_cursor)) this.cursor = Math.max(this.cursor, data.next_cursor);
      if (!data.has_more) break;
    }
  }

  renderFilters() {
    this.filters.replaceChildren();
    for (const [kind, label] of KINDS) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `ledger-chip${kind === this.kind ? ' is-active' : ''}`;
      chip.textContent = label;
      chip.addEventListener('click', () => {
        this.kind = kind;
        this.renderFilters();
        this.render();
      });
      this.filters.append(chip);
    }
  }

  render() {
    const events = this.sorted();
    this.now.textContent = productionStatus(events).text;
    // A letter the Owner has answered is no longer red: the answer's event names it.
    const answered = new Set(
      events
        .filter((e) => e.event_type === 'agent.message_answered' || e.event_type === 'agent.message_resolved')
        .map((e) => e.aggregate_id),
    );
    const rows = [];
    for (const event of events) {
      const item = describeEvent(event, this.names);
      if (this.kind !== 'all' && item.kind !== this.kind) continue;
      const time = new Date(event.timestamp || Date.now()).toLocaleTimeString('ro-RO', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: this.timezone,
      });
      const mail = item.thread
        ? `${item.forOwner ? ` ledger-owner-mail${answered.has(event.aggregate_id) ? ' is-answered' : ''}` : ''} ledger-mail" data-thread="${this.escape(item.thread)}" title="Deschide firul de corespondență`
        : '';
      const route = item.thread
        ? `<strong>${this.escape(item.who)}</strong> <span class="ledger-arrow">→</span> <strong>${this.escape(item.to)}</strong> · ${this.escape(item.label)}`
        : `${item.who ? `<strong>${this.escape(item.who)}</strong> ` : ''}${this.escape(item.label)}`;
      rows.push(
        `<li class="ledger-item ledger-${item.kind}${mail}"><time>${this.escape(time)}</time><div>` +
          `<div class="ledger-head">${route}</div>` +
          (item.text ? `<div class="ledger-text">${this.escape(item.text)}</div>` : '') +
          (item.thread ? '<div class="ledger-open">Deschide firul ↗</div>' : '') +
          `</div></li>`,
      );
      if (rows.length >= 150) break;
    }
    this.list.innerHTML = rows.length
      ? rows.join('')
      : '<li class="ledger-empty">Nimic înregistrat încă pentru acest filtru.</li>';
  }
}
