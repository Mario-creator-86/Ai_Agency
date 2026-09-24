import { MODE_LABEL } from './governance.js';

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
  owner: 'owner',
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
  ['all', 'Toate'],
  ['speech', 'Discuții'],
  ['production', 'Producție'],
  ['work', 'Angajați'],
  ['money', 'Bani'],
  ['owner', 'Proprietar'],
];

/**
 * How many entries the register holds, said the way Romanian says it: one is an `intrare`,
 * twenty and above take the `de` a Romanian speaker cannot leave out («400 de intrări»).
 *
 * @param {number} count
 */
export function entryCountLabel(count) {
  const n = Number(count) || 0;
  if (n === 1) return '1 intrare';
  // Romanian takes «de» when the last two digits are 00 or 20 to 99: «20 de intrări»,
  // «101 intrări», «120 de intrări» (the same rule main.js's countLabel follows).
  const rest = Math.abs(n) % 100;
  return `${n} ${Math.abs(n) >= 20 && (rest === 0 || rest >= 20) ? 'de intrări' : 'intrări'}`;
}

/**
 * Jobs the scheduler runs on its own clock that make nothing: they read, check and tidy.
 * A restart creates several in one second, and calling them "production started" told the
 * Owner films were being made when none was (measured 2026-09-18). A job not named here -
 * the daily run above all - still reads as production.
 */
const ROUTINE_JOB = {
  WATCHDOG: 'watchdog',
  MODEL_REVIEW: 'revizuirea modelelor',
  MODEL_RESEARCH: 'cercetare de modele',
  DIRECTOR_LOOP: 'bucla Directoarei',
  TRENDS_REFRESH: 'tendințe',
  WEEKLY_REVIEW: 'analiza săptămânală',
};

const STAGE_LABEL = {
  DISCOVERY: 'Descoperire',
  IDEA_SELECTION: 'Alegerea ideii',
  RESEARCH: 'Cercetare',
  FACT_CHECK: 'Verificarea faptelor',
  RESEARCHED: 'Cercetat',
  SCRIPTING: 'Scenariu',
  SCRIPT_READY: 'Scenariu gata',
  HOOK_OPTIMIZATION: 'Optimizarea deschiderii',
  STORYBOARD: 'Storyboard',
  MEDIA_GENERATION: 'Generare media',
  VOICE_GENERATION: 'Generarea vocii',
  ASSET_GENERATION: 'Generarea materialelor',
  VIDEO_GENERATION: 'Generarea imaginilor',
  EDITING: 'Montaj',
  RENDERING: 'Randare',
  QUALITY_CONTROL: 'Controlul calității',
  READY_TO_PUBLISH: 'Gata de publicare',
  PUBLISHING: 'Publicare',
  PUBLISHED: 'Publicat',
  ANALYTICS: 'Analitice',
  LEARNING: 'Învățare',
};

/** The stages of the daily runbook, as the Owner reads them in the panel. */
const RUN_STAGE_LABEL = {
  preflight: 'verificarea preliminară',
  performance_intake: 'preluarea performanței',
  idea_generation: 'generarea de idei',
  research_and_verification: 'documentare și verificare',
  selection: 'alegerea subiectului',
  script_and_storyboard: 'scenariu și storyboard',
  media: 'producție media',
  edit_and_qc: 'montaj și controlul calității',
  publish: 'publicare',
  post_run: 'raportare și închiderea zilei',
  daily_log: 'jurnalul zilei',
  serial_queue: 'episodul din serial',
  serial_next: 'scenariul de mâine',
};

/** What each kind of letter is, as the Owner would name it. */
const MAIL_INTENT = {
  REQUEST_INFO: 'întrebare',
  REQUEST_REVIEW: 'cerere de verificare',
  CHALLENGE: 'obiecție',
  HANDOFF: 'îndrumare',
  STATUS: 'raport',
  ESCALATE: 'escaladare',
};

/**
 * A status as it is read after a feminine noun — `sarcină`, `etapă`, `rularea zilei` — because
 * that is where every one of them is used. The one masculine host, `controlul calității`,
 * takes a colon instead of an agreement, so nothing here has to be said twice.
 */
const STATUS_LABEL = {
  COMPLETED: 'încheiată',
  PARTIAL: 'parțială',
  FAILED: 'eșuată',
  BLOCKED: 'blocată',
  SKIPPED: 'sărită',
  SUCCEEDED: 'reușită',
  PASSED: 'trecută',
  PUBLISHED: 'publicată',
  PUBLISHED_SIMULATED: 'publicare simulată',
};

/**
 * A stage of one film, as the Owner reads it. Exported because the scene draws the same word
 * over the project token that walks the building, and the two must not disagree: the office
 * used to letter the token with the raw code (`MEDIA GENERATION`) while the register beside it
 * said the stage in words.
 *
 * @param {string} stage
 */
export function stageLabel(stage) {
  return STAGE_LABEL[stage] || String(stage || '').replace(/_/g, ' ').toLowerCase();
}

function runStageLabel(stage) {
  return RUN_STAGE_LABEL[stage] || String(stage || '').replace(/_/g, ' ');
}

/**
 * A status after a feminine noun (`sarcină reușită`). Exported for the scene's speech bubble,
 * which says a finished task in the same words as the register row beside it.
 * @param {string} status
 */
export function statusLabel(status) {
  return STATUS_LABEL[status] || String(status || '').toLowerCase();
}

/** Task types as the Owner would name them. Unknown types read as their own words. */
const TASK_LABEL = {
  propose_topics: 'idei de subiect',
  gather_sources: 'căutarea surselor',
  extract_claims: 'extragerea afirmațiilor',
  verify_claim: 'verificarea faptelor',
  choose_topic: 'alegerea subiectului',
  write_script: 'scenariu',
  write_episode: 'episodul serialului',
  review_narration: 'revizuirea narațiunii',
  review_failed_render: 'diagnoza randării',
  prepare_publication: 'pregătirea publicării',
  director_review: 'revizuirea Directorului',
  reconcile_day: 'închiderea zilei',
  direct_task: 'sarcină directă',
  TEST_CONNECTIVITY: 'test de conexiune',
  // W12: the task types the studio's own runs record (agent_run.task_type on the Owner's data),
  // which the name tags now read from the snapshot and which had no word yet
  answer_mail: 'răspunsul la corespondență',
  research_models: 'cercetarea modelelor',
  direct_company: 'conducerea companiei',
  editorial_review: 'revizuirea editorială',
  story_review: 'citirea episodului',
  episode_review: 'citirea episodului',
  shot_prompts: 'descrierea cadrelor',
  visual_bible: 'ghidul vizual',
  picture_qc: 'controlul imaginii',
  owner_chat: 'discuția cu Proprietarul',
  WEEKLY_REVIEW: 'bilanțul săptămânii',
  DAILY_RUN: 'rularea zilei',
};

/** What a state change says in the register; IDLE and anything unlisted is «a terminat». @type {Record<string, string>} */
const STATE_CHANGE_LABEL = {
  WORKING: 'lucrează',
  EXECUTING: 'lucrează',
  RUNNING: 'lucrează',
  THINKING: 'lucrează',
  PLANNING: 'lucrează',
  REVIEWING: 'verifică',
  ERROR: 'stare: eroare',
  FAILED: 'stare: eroare',
  BLOCKED: 'stare: blocaj',
};

/**
 * A task type in words. It lived in main.js for the inspector's timeline; the scene needs the
 * same words, so it lives here with the register's other labels.
 * @param {string} type
 */
export function taskLabel(type) {
  if (TASK_LABEL[type]) return TASK_LABEL[type];
  // a step of a task («direct_company:critique») is said as its task
  const base = String(type || '').split(':')[0];
  return TASK_LABEL[base] || String(type || '').replace(/_/g, ' ');
}

/**
 * What an employee is doing, in the words the scene prints on a name tag and on the render bay's
 * wall display. The enum stays the enum everywhere it is data (the inspector's grid, the sprite
 * chooser); only the words drawn into the picture are Romanian. Each is invariable (a noun
 * phrase or «în …»), because the tag follows names of either gender and the display's own
 * heading, «RANDARE», is feminine.
 */
const RUNTIME_LABEL = {
  IDLE: 'în așteptare',
  WORKING: 'în lucru',
  EXECUTING: 'în lucru',
  RUNNING: 'în lucru',
  THINKING: 'se gândește',
  PLANNING: 'se gândește',
  REVIEWING: 'verifică',
  PAUSED: 'în pauză',
  SUSPENDED: 'în pauză',
  BLOCKED: 'blocaj',
  ERROR: 'eroare',
  FAILED: 'eroare',
};

/** @param {string} state a runtime state (or PAUSED from the lifecycle) */
export function runtimeLabel(state) {
  const key = String(state || 'IDLE').toUpperCase();
  return RUNTIME_LABEL[/** @type {keyof typeof RUNTIME_LABEL} */ (key)] || key.replace(/_/g, ' ').toLowerCase();
}

/**
 * The speech bubble when a run ends, from the run's own status and task type: the same words as
 * the register row «sarcină reușită · gather_sources», set as one sentence
 * («Sarcină reușită: căutarea surselor»). It used to say `Completed: gather_sources ✓` in
 * English, and uppercase made it `COMPLETED: GATHER_SOURCES ✓`.
 * @param {{status?: string, task_type?: string}} payload
 */
export function runDoneLine(payload) {
  const status = statusLabel(String(payload?.status || 'SUCCEEDED'));
  const task = payload?.task_type ? `: ${taskLabel(payload.task_type)}` : '';
  return `Sarcină ${status}${task}`;
}

function short(text, max = 160) {
  const clean = String(text ?? '').replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/**
 * The second line of a row, when it has something to add.
 *
 * A letter's excerpt is very often the whole of its subject after the colon, so the
 * register printed the same sentence twice — once in the row's own headline and once in
 * the grey line under it — on ten consecutive rows. Nothing here rewords anything: when
 * the detail is already the end of (or the whole of) the headline, the copy is dropped
 * and the row says it once. Case and surrounding space are ignored, because a subject
 * ends in a full stop as often as it does not.
 *
 * @param {string|undefined|null} headline what the row already says
 * @param {string|undefined|null} detail what it was going to say again
 * @returns {string} the detail, or '' when it is an echo
 */
export function withoutEcho(headline, detail) {
  const tail = String(detail || '').trim();
  if (!tail) return '';
  const head = String(headline || '').trim();
  if (!head) return tail;
  const a = head.toLowerCase();
  const b = tail.toLowerCase();
  return a === b || a.endsWith(b) ? '' : tail;
}

/**
 * Describe one event for the Owner.
 *
 * @param {{event_type: string, aggregate_id?: string, payload?: any}} event
 * @param {Record<string, string>} [names] agent id → display name
 * @returns {{who: string, label: string, text: string, kind: string, to?: string, thread?: string|null, forOwner?: boolean, subject?: string, excerpt?: string}}
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
      text = [payload.subject, withoutEcho(payload.subject, payload.excerpt)]
        .filter(Boolean)
        .join(' — ');
      kind = 'speech';
      // A letter: the ledger names both ends and opens the thread it belongs to. One
      // addressed to the Owner is the Owner's business: it files under the Owner chip and
      // is drawn in red until it is answered.
      return {
        who: who || payload.from_name || 'Proprietar',
        label: payload.for_owner ? `${label} · PENTRU TINE` : label,
        text,
        kind: payload.for_owner ? 'owner' : kind,
        to: payload.to_name || 'Director',
        thread: payload.thread_id || event.aggregate_id || null,
        forOwner: Boolean(payload.for_owner),
        subject: payload.subject || '',
        excerpt: withoutEcho(payload.subject, payload.excerpt),
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
      // WORKING is production without a model — a voice being recorded, a shot generated. It
      // used to read "a terminat" (finished) while the work was only starting.
      // An error or a block is not a finish (W9): it says the state in the name tag's words.
      label = STATE_CHANGE_LABEL[payload.runtime_state] || 'a terminat';
      text = payload.detail || (payload.task_type ? `sarcina: ${taskLabel(payload.task_type)}` : '');
      break;
    case 'agent.run_completed':
      label = `sarcină ${statusLabel(payload.status)}`;
      text = [payload.task_type ? taskLabel(payload.task_type) : '', payload.model_name].filter(Boolean).join(' · ');
      break;
    case 'agent.paused':
      label = 'a intrat în pauză';
      break;
    case 'agent.resumed':
      label = 'a reluat lucrul';
      break;
    case 'agent.hired':
      label = 'a intrat în companie';
      text = [payload.display_name, payload.role].filter(Boolean).join(' · ');
      break;
    case 'director.review_completed':
      label = 'Directoarea a trecut ziua în revistă';
      text = `${payload.reviewed ?? 0} mesaje, ${payload.applied ?? 0} decizii`;
      break;
    case 'workflow.created':
    case 'workflow.job_scheduled':
    case 'workflow.job_activated':
      if (type === 'workflow.created' && !payload.current_stage && ROUTINE_JOB[payload.workflow_type]) {
        label = 'sarcină de rutină pornită';
        text = ROUTINE_JOB[payload.workflow_type];
        kind = 'system';
        break;
      }
      label = type === 'workflow.created' ? 'a început o producție' : 'producție programată';
      text = payload.current_stage ? `etapa: ${stageLabel(payload.current_stage)}` : '';
      break;
    case 'factual.topic_proposed':
      label = 'subiect propus';
      text = payload.title || '';
      break;
    case 'factual.topic_selected':
      label = 'subiect ales pentru producție';
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
      label = 'scenariu aprobat de Proprietar';
      text = payload.title || '';
      break;
    case 'factual.script_blocked_by_gate':
      label = 'scenariu blocat de poartă';
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
      label = `controlul calității: ${statusLabel(payload.status)}`;
      text = Array.isArray(payload.failures) ? payload.failures.join('; ') : '';
      break;
    case 'publishing.started':
      label = 'încărcare începută';
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
      label = 'model alocat';
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
      label = 'conexiune ștearsă';
      text = payload.kind || '';
      break;
    case 'youtube.authorization_started':
      label = 'autorizare YouTube începută';
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
      label = 'înregistrare contabilă';
      text = [payload.kind, payload.memo, payload.amount_vr ? `${payload.amount_vr} VR$` : '']
        .filter(Boolean)
        .join(' · ');
      break;
    case 'research.host_revoked':
      label = 'site retras din listă';
      text = payload.host || '';
      break;
    case 'studio.renamed':
      label = 'studioul a fost redenumit';
      text = [payload.previous_name, payload.name].filter(Boolean).join(' → ');
      break;
    case 'trends.snapshot_recorded':
      label = 'tendințe citite';
      text = `${payload.count ?? 0} noi din ${payload.seen ?? 0} (${payload.geo || ''})${Array.isArray(payload.top) && payload.top.length ? ` · ${payload.top.slice(0, 3).join(', ')}` : ''}`;
      break;
    case 'trends.unavailable':
      label = 'tendințele nu au putut fi citite';
      text = payload.reason || '';
      break;
    case 'media.model_research_recorded':
      label = `cercetare de modele · ${payload.purpose || ''}`;
      text = `${payload.steward ? `${payload.steward}: ` : ''}${payload.annotated ?? 0} modele judecate din ${payload.pages ?? 0} pagini${payload.recommended ? ` · recomandat ${payload.recommended}` : ''}${payload.changed ? ' · pus ca implicit' : ''}`;
      kind = 'production';
      break;
    case 'provider.resource_metadata_updated':
      label = 'fișa modelului actualizată';
      text = payload.source || '';
      break;
    case 'media.production_configured':
      label = 'setări implicite de producție';
      text = [payload.model_id ? `model ${payload.model_id}` : '', payload.voice_id ? `voce ${payload.voice_id}` : '', payload.image_model_id ? `imagine ${payload.image_model_id}` : '']
        .filter(Boolean)
        .join(' · ');
      break;
    case 'media.editorial_reviewed':
      label = payload.verdict === 'APPROVE' ? 'vizionat și aprobat' : 'vizionat și respins';
      text = [payload.title, payload.story, Array.isArray(payload.reasons) ? payload.reasons.join('; ') : '']
        .filter(Boolean)
        .join(' — ');
      kind = 'production';
      break;
    case 'studio.history_reset':
      label = 'istoric șters';
      text = `de la zero · ${payload.events || 0} evenimente, ${payload.messages || 0} mesaje, ${payload.runs || 0} rulări șterse`;
      kind = 'owner';
      break;
    case 'runbook.daily_run_started':
      label = 'ziua a început';
      text = `${payload.stages || ''} etape · verificare preliminară ${payload.preflight || ''}`.trim();
      break;
    case 'runbook.stage_started':
      label = 'etapă începută';
      text = `${runStageLabel(payload.stage)}${payload.index ? ` (${payload.index}/${payload.total})` : ''}`;
      break;
    case 'runbook.stage_finished':
      label = `etapă ${statusLabel(payload.status)}`;
      text = [runStageLabel(payload.stage), payload.reason].filter(Boolean).join(' — ');
      break;
    case 'runbook.daily_run_finished':
      label = `rularea zilei ${statusLabel(payload.status)}`;
      // The backend's sentence of what the day made, when the event carries one: a status
      // alone read COMPLETED for a rehearsal day that produced nothing.
      text = payload.summary || (payload.preflight ? `verificare preliminară ${payload.preflight}` : '');
      break;
    case 'runbook.safe_mode_entered':
      label = 'MOD SIGUR';
      text = payload.reason || '';
      break;
    case 'story.daily_log_closed':
      label = 'jurnalul zilei s-a închis';
      break;
    case 'story.episode_drafted':
      label = 'episod scris';
      text = payload.title || (payload.episode_number ? `episodul ${payload.episode_number}` : '');
      break;
    case 'story.episode_approved':
      label = 'episod aprobat';
      text = payload.reviewed_by === 'director' ? 'de Directoare' : payload.reviewed_by === 'owner' ? 'de Proprietar' : '';
      break;
    case 'story.episode_rejected':
      label = 'episod respins';
      text = payload.reviewed_by === 'owner' ? 'de Proprietar' : '';
      break;
    case 'governance.approval_requested':
      label = 'cerere de aprobare pentru Proprietar';
      text = [payload.subject, payload.risk_tier].filter(Boolean).join(' · ');
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
      label = 'VR$ emis din dovezi';
      text = payload.vr ? `${payload.vr} VR$` : '';
      break;
    case 'economy.owner_funding_recorded':
      label = 'finanțare de la Proprietar';
      text = payload.vr ? `${payload.vr} VR$` : '';
      break;
    case 'strategy.version_promoted':
      label = 'strategie promovată';
      text = `v${payload.new_version ?? ''}`;
      break;
    case 'autonomy.stopped':
      label = 'Proprietarul a oprit autonomia';
      break;
    case 'autonomy.stop_cleared':
      label = 'Proprietarul a pornit autonomia';
      break;
    // W17: the Owner's own switches, seen in the register of 24.09 as raw keys
    // («autonomy mode changed · autonomy_mode: AUTONOMOUS_CEO · …»); the modes in the words the
    // governance drawer gives them (governance.js MODE_LABEL), the environment as the banner says it.
    case 'owner.autonomy_mode_changed': {
      const mode = (/** @type {unknown} */ m) => (typeof m === 'string' && m ? /** @type {Record<string, string>} */ (MODE_LABEL)[m] || m : '');
      label = 'Proprietarul a schimbat modul de autonomie';
      text = [mode(payload.previous_autonomy_mode), mode(payload.autonomy_mode)].filter(Boolean).join(' → ');
      break;
    }
    case 'owner.environment_changed':
      label = 'Proprietarul a schimbat mediul';
      text = payload.environment ? `MEDIU ${payload.environment}` : '';
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
      label = 'birou creat';
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
 * How long the register may go without a single new event before «Acum» stops claiming that a
 * stage is under way: one hour, the worker's task lease (backend/app/workflows/worker.py,
 * TASK_LEASE_SECONDS = 3600). Past it the backend itself treats a task that has said nothing as
 * lapsed and lets the queue claim it again, so the page does not go on saying "now" for longer
 * than the studio would.
 */
export const RUN_QUIET_MS = 60 * 60 * 1000;

/**
 * The calendar day an instant falls on in the studio's time zone, as YYYY-MM-DD.
 * @param {number} ms @param {string} [timeZone]
 */
export function studioDay(ms, timeZone) {
  // en-CA writes dates as YYYY-MM-DD, which sorts and compares as text
  return new Date(ms).toLocaleDateString('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' });
}

/**
 * The words over a day's rows in the register. A row's time alone would let a day twelve days
 * old read as this morning under a heading that says «acum», so every day is named: «Azi»,
 * «Ieri», or its date («vineri, 12 septembrie»).
 * @param {string|number} timestamp @param {number} now @param {string} [timeZone]
 */
export function dayLabel(timestamp, now, timeZone) {
  const at = typeof timestamp === 'number' ? timestamp : Date.parse(String(timestamp || ''));
  if (!Number.isFinite(at)) return '';
  const day = studioDay(at, timeZone);
  if (day === studioDay(now, timeZone)) return 'Azi';
  // noon of the studio day before, so a clock change never skips or repeats a day
  const [y, m, d] = studioDay(now, timeZone).split('-').map(Number);
  if (day === studioDay(Date.UTC(y, m - 1, d - 1, 12), timeZone)) return 'Ieri';
  const sameYear = day.slice(0, 4) === studioDay(now, timeZone).slice(0, 4);
  return new Date(at).toLocaleDateString('ro-RO', { timeZone, weekday: 'long', day: 'numeric', month: 'long', ...(sameYear ? {} : { year: 'numeric' }) });
}

/**
 * «de o oră», «de 5 ore», «de 20 de ore», «de 3 zile»: how long the register has been quiet.
 * @param {number} ms
 */
export function quietFor(ms) {
  const count = (/** @type {number} */ n, /** @type {string} */ one, /** @type {string} */ many) => {
    if (n === 1) return one;
    const tail = n % 100;
    return `${n}${n >= 20 && (tail === 0 || tail >= 20) ? ' de' : ''} ${many}`;
  };
  const hours = Math.max(1, Math.floor(ms / 3600000));
  if (hours < 48) return `de ${count(hours, 'o oră', 'ore')}`;
  return `de ${count(Math.floor(hours / 24), 'o zi', 'zile')}`;
}

/**
 * Where production stands, from the newest events that say so.
 *
 * `running` is the stage that started and has not been seen finishing — and the day's own
 * end (`runbook.daily_run_finished`) closes any stage still open before it. `live` is whether
 * the register may say «Acum» with a pulse: a stage is running AND something was recorded in
 * the last RUN_QUIET_MS. Without `now` the clock is not consulted (the tests of the wording).
 *
 * `closedAt` is when the runbook's own record says its newest day finished (`/runbook/runs`): the
 * register keeps only its newest 400 events, so the finish of a day can have scrolled out of it
 * while the start of one of its stages is still there. A stage that started before the recorded
 * finish is not running, whatever the register lost.
 *
 * @param {Array<{event_type: string, payload?: any, sequence?: number, timestamp?: string}>} events newest first
 * @param {number|null} [now] epoch ms
 * @param {number|null} [closedAt] epoch ms of the newest recorded finished day
 * @returns {{stage: string|null, run: string|null, running: string|null, live: boolean, text: string}}
 */
export function productionStatus(events, now = null, closedAt = null) {
  let stage = null;
  let run = null;
  let running = null;
  /** @type {number | null} */
  let runningSince = null;
  /** @type {number | null} */
  let productive = null;
  /** @type {number | null} */
  let newest = null;
  for (const event of events) {
    const payload = event.payload || {};
    const type = String(event.event_type);
    if (newest === null) {
      const at = Date.parse(String(event.timestamp || ''));
      if (Number.isFinite(at)) newest = at;
    }
    // A stage that started and has not been seen finishing is where the day is right now;
    // it is newer than anything the workflow can say, so it is read first and wins. The end of
    // the day, newer than the start of a stage, means that stage is not running any more.
    if (
      running === null &&
      (type === 'runbook.stage_started' || type === 'runbook.stage_finished' || type === 'runbook.daily_run_finished')
    ) {
      running = type === 'runbook.stage_started' ? payload.stage || null : false;
      const since = Date.parse(String(event.timestamp || ''));
      runningSince = Number.isFinite(since) ? since : null;
    }
    if (!stage && type.startsWith('workflow.') && payload.current_stage) {
      stage = payload.current_stage;
    }
    if (!run && type === 'runbook.daily_run_finished') {
      run = payload.status || null;
      productive = typeof payload.stages_productive === 'number' ? payload.stages_productive : null;
    }
    if (stage && run && running !== null && newest !== null) break;
  }
  if (running && closedAt !== null && Number.isFinite(closedAt) && runningSince !== null && runningSince < closedAt) {
    running = false;
  }
  const quiet = Boolean(running) && now !== null && newest !== null && now - newest > RUN_QUIET_MS;
  const parts = [];
  if (running) {
    parts.push(
      quiet
        ? `ultima etapă începută: ${runStageLabel(running)} · nimic nou ${quietFor(/** @type {number} */ (now) - /** @type {number} */ (newest))}`
        : `Acum: ${runStageLabel(running)}`,
    );
  }
  if (stage) parts.push(`producție: ${stageLabel(stage)}`);
  // How many stages made something, beside the status: "completed" alone is what a day that
  // made nothing looked like. An event without the count says only its status.
  if (run) {
    parts.push(
      `ultima rulare a zilei ${statusLabel(run)}${productive === null ? '' : ` · ${productive} etape au produs ceva`}`,
    );
  }
  if (!parts.length) return { stage, run, running: null, live: false, text: 'Nicio producție în lucru.' };
  const text = parts.join(' · ');
  return { stage, run, running: running || null, live: Boolean(running) && !quiet, text: text[0].toUpperCase() + text.slice(1) };
}

/** How many entries the ledger keeps on screen. Older ones are in the events endpoint. */
export const LEDGER_CAPACITY = 400;

/** How long after the page opens the ledger stops treating an arrival as history. */
export const LEDGER_SETTLE_MS = 4000;

/**
 * Which of the events that just arrived should be lit as NEW.
 *
 * A row is lit only when it arrived while the Owner was watching. The first
 * seconds after the page opens are the snapshot and the backfill — seventy
 * rows of the day's history — and lighting those would be a flash of the whole
 * column saying nothing. After the settle, anything fresh is genuinely news.
 *
 * @param {{event_id?: string}[]} fresh events add() has just accepted
 * @param {number} openedAt when the ledger was constructed
 * @param {number} now
 * @param {number} [settleMs]
 * @returns {Set<string>} the ids to mark, empty during the settle
 */
export function arrivingIds(fresh, openedAt, now, settleMs = LEDGER_SETTLE_MS) {
  const ids = new Set();
  if (!Array.isArray(fresh) || now - openedAt <= settleMs) return ids;
  for (const event of fresh) {
    if (event && event.event_id) ids.add(event.event_id);
  }
  return ids;
}

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
    /** @type {number|null} when the runbook recorded its newest day finished (productionStatus) */
    this.closedAt = null;
    /** @type {string} the studio day the list was last drawn on (dayTurned) */
    this.renderedDay = '';
    // When this column started showing history, and the ids lit on the next render.
    this.openedAt = Date.now();
    /** @type {Set<string>} */
    this.arrived = new Set();
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
      for (const id of arrivingIds(fresh, this.openedAt, Date.now())) this.arrived.add(id);
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

  /**
   * The head line alone. The page calls it on a timer as well, so «Acum» goes quiet when the
   * register has been silent for RUN_QUIET_MS even though no event arrives to say so.
   * @param {any[]} [events] newest first
   */
  renderNow(events = this.sorted()) {
    const status = productionStatus(events, Date.now(), this.closedAt);
    this.now.textContent = status.text;
    // The pulse is the stylesheet's, and it runs only on .is-live.
    if (this.now.classList) this.now.classList.toggle('is-live', status.live);
  }

  /** True once midnight has passed since the list was drawn: «Azi» and «Ieri» must be re-read. */
  dayTurned() {
    return Boolean(this.renderedDay) && this.renderedDay !== studioDay(Date.now(), this.timezone);
  }

  render() {
    const events = this.sorted();
    this.renderNow(events);
    // A letter the Owner has answered is no longer red: the answer's event names it.
    const answered = new Set(
      events
        .filter((e) => e.event_type === 'agent.message_answered' || e.event_type === 'agent.message_resolved')
        .map((e) => e.aggregate_id),
    );
    // How long each thread is, so a letter says whether it is the first word or the fifth.
    const threadLength = new Map();
    for (const e of events) {
      if (e.event_type !== 'agent.message_posted') continue;
      const id = (e.payload && e.payload.thread_id) || e.aggregate_id;
      threadLength.set(id, (threadLength.get(id) || 0) + 1);
    }
    // A routine that ran ten times is one fact, not ten. Consecutive entries that
    // say exactly the same thing are folded into the row they would each have
    // drawn: the newest time, the count, and the span the run covers. Nothing is
    // reworded and nothing is dropped — correspondence never folds, because every
    // letter is its own event with its own thread.
    const rows = [];
    const now = Date.now();
    this.renderedDay = studioDay(now, this.timezone);
    let lastDay = '';
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
      const letters = item.thread ? threadLength.get(item.thread) || 1 : 0;
      const body = item.thread
        ? `<div class="ledger-subject">${this.escape(item.subject || item.text)}</div>` +
          (item.excerpt ? `<div class="ledger-text">${this.escape(item.excerpt)}</div>` : '') +
          `<div class="ledger-open">Deschide firul${letters > 1 ? ` · ${letters} scrisori` : ''} ↗</div>`
        : (() => {
            const detail = withoutEcho(`${item.who} ${item.label}`, item.text);
            return detail ? `<div class="ledger-text">${this.escape(detail)}</div>` : '';
          })();
      const at = Date.parse(String(event.timestamp || ''));
      const day = Number.isFinite(at) ? studioDay(at, this.timezone) : lastDay;
      const last = rows[rows.length - 1];
      const key = item.thread ? null : `${item.kind}\u0000${route}\u0000${body}`;
      // a fold never crosses midnight: each day keeps its own count
      if (key && last && last.key === key && day === lastDay) {
        last.count += 1;
        last.oldest = time;
        continue;
      }
      if (day !== lastDay) {
        rows.push({ day: dayLabel(at, now, this.timezone) });
        lastDay = day;
      }
      rows.push({ key, kind: item.kind, mail, route, body, time, oldest: time, count: 1, id: event.event_id });
      if (rows.length >= 150) break;
    }
    this.list.innerHTML = rows.length
      ? rows
          .map((row) => {
            if (row.day !== undefined) return `<li class="ledger-day">${this.escape(row.day)}</li>`;
            return (
              `<li class="ledger-item ledger-${row.kind}${row.count > 1 ? ' is-repeat' : ''}${this.arrived.has(row.id) ? ' is-new' : ''}${row.mail}">` +
              `<time>${this.escape(row.time)}</time><div>` +
              `<div class="ledger-head">${row.route}${row.count > 1 ? `<span class="ledger-repeat">×${row.count}</span>` : ''}</div>` +
              row.body +
              (row.count > 1 ? `<span class="ledger-span">${this.escape(row.oldest)} – ${this.escape(row.time)}</span>` : '') +
              `</div></li>`
            );
          })
          .join('')
      : '<li class="ledger-empty">Nimic înregistrat pentru acest filtru.</li>';
    // The highlight plays once. A later render — a filter change, the office
    // layout arriving with its names — must not replay it on the same rows.
    this.arrived.clear();
  }
}
