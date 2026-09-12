/**
 * Model output, read by a person.
 *
 * Structured pipelines consume the model's answer as JSON — the pages it proposes to read,
 * the claims it extracted, the scenes it wrote — and that raw JSON is exactly what the run
 * history used to show the Owner. A person should never have to read it: this module turns
 * the known shapes into plain Romanian sentences and lists. Everything else passes through
 * as ordinary text, and for a structured answer the model's exact output stays one click
 * away in a collapsed block, because the history is an audit trail.
 *
 * Pure and testable: `friendlyAnswer` returns HTML with every dynamic value escaped.
 */

import { escapeHtml } from './html.js';

/** Fenced code blocks are the most common wrapper a model puts around JSON. */
function stripFences(text) {
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenced ? fenced[1] : text;
}

/**
 * The JSON inside an answer, or null when the answer is ordinary text.
 *
 * A direct parse is tried first; failing that, the substring from the first bracket to the
 * last one, because models sometimes write one sentence before the list. Anything that still
 * does not parse is not JSON — treating it as text is the honest outcome.
 */
export function extractJson(text) {
  const cleaned = stripFences(String(text ?? '').trim());
  const first = cleaned.search(/[{[]/);
  if (first === -1) return null;
  const attempts = [cleaned];
  const lastBrace = cleaned.lastIndexOf('}');
  const lastBracket = cleaned.lastIndexOf(']');
  const last = Math.max(lastBrace, lastBracket);
  if (first > 0 && last > first) attempts.push(cleaned.slice(first, last + 1));
  for (const candidate of attempts) {
    try {
      const value = JSON.parse(candidate);
      return value && typeof value === 'object' ? value : null;
    } catch {
      // next candidate, or null
    }
  }
  return null;
}

const VERDICT_LABEL = {
  SUPPORTED: 'supported by the source',
  REFUTED: 'refuted by the source',
  UNCERTAIN: 'the source does not say',
  DISPUTED: 'disputed',
  UNVERIFIED: 'unverified',
};

/**
 * Complete objects salvaged from a truncated structured answer.
 *
 * A reasoning model that hits its token budget mid-list leaves broken JSON in the run's
 * output. The pipeline keeps the complete items; the raw text stays broken, and it used to
 * be printed as-is. This walks the text with a string-aware depth counter and parses every
 * object that actually closed, dropping only the dangling partial one — exactly what the
 * backend's own salvager does, so what the Owner sees matches what was stored.
 *
 * @param {string} text
 * @returns {any[]|null}
 */
export function salvageItems(text) {
  const cleaned = stripFences(String(text ?? '').trim());
  const start = cleaned.search(/[[{]/);
  if (start === -1) return null;
  // Inside a top-level array the objects sit at depth 1; inside {"claims": [ … ]} at 2.
  const baseDepth = cleaned[start] === '{' ? 1 : 0;
  const items = [];
  let depth = 0;
  let inString = false;
  let escape = false;
  let begin = -1;
  for (let i = start; i < cleaned.length; i += 1) {
    const ch = cleaned[i];
    if (inString) {
      if (escape) escape = false;
      else if (ch === '\\') escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
    } else if (ch === '{') {
      if (depth === baseDepth) begin = i;
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
      if (depth === baseDepth && begin !== -1) {
        try {
          items.push(JSON.parse(cleaned.slice(begin, i + 1)));
        } catch {
          // a block that cannot stand alone is dropped, never guessed at
        }
        begin = -1;
      }
    }
  }
  return items.length ? items : null;
}

/** A safe external link: only a real http(s) address becomes one. */
function link(url) {
  const value = String(url || '').trim();
  if (!/^https?:\/\//i.test(value)) return escapeHtml(value);
  return `<a href="${escapeHtml(value)}" target="_blank" rel="noopener noreferrer">${escapeHtml(value)}</a>`;
}

function list(items) {
  return `<ul class="friendly-list">${items.join('')}</ul>`;
}

/** One level of a structure nobody has a dedicated sentence for. */
function genericObject(value, depth) {
  const entries = Object.entries(value).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!entries.length) return '';
  const rows = [];
  for (const [key, item] of entries) {
    const label = escapeHtml(String(key).replace(/_/g, ' '));
    if (Array.isArray(item)) {
      const parts = item
        .slice(0, 12)
        .map((one) =>
          typeof one === 'object' && one !== null
            ? `<li>${renderValue(one, depth + 1)}</li>`
            : `<li>${escapeHtml(String(one))}</li>`,
        );
      rows.push(`<div class="friendly-head">${label}:</div>${list(parts)}`);
    } else if (typeof item === 'object') {
      const inner = genericObject(item, depth + 1);
      if (inner) rows.push(`<div class="friendly-head">${label}:</div>${inner}`);
    } else {
      rows.push(`<div class="friendly-row"><span class="friendly-key">${label}:</span> ${escapeHtml(String(item))}</div>`);
    }
  }
  return rows.join('');
}

/** Pages proposed for reading, as a titled list: {"urls": [{"url", "why"}]} — or salvaged ones. */
function urlsBlock(pages) {
  const shown = pages.slice(0, 12);
  const items = shown.map(
    (page) =>
      `<li>${link(page && page.url)}${page && page.why ? `<div class="friendly-why">${escapeHtml(page.why)}</div>` : ''}</li>`,
  );
  return `<div class="friendly-head">I suggest ${shown.length} ${shown.length === 1 ? 'page to read' : 'pages to read'}:</div>${list(items)}`;
}

/** Atomic claims, as numbered sentences: [{"claim_text", ...}] — or salvaged ones. */
function claimsBlock(claims) {
  const items = claims.slice(0, 20).map((one) => {
    const meta = [
      one.importance ? String(one.importance).toLowerCase() : '',
      typeof one.confidence === 'number' ? `confidence ${Math.round(one.confidence * 100)}%` : '',
    ]
      .filter(Boolean)
      .join(' · ');
    return `<li>${escapeHtml(one.claim_text || one.text)}${meta ? `<div class="friendly-why">${escapeHtml(meta)}</div>` : ''}</li>`;
  });
  return `<div class="friendly-head">I extracted ${claims.length} ${claims.length === 1 ? 'claim' : 'claims'}:</div>${list(items)}`;
}

/** Salvaged items that match no known shape still read as labelled rows, never as braces. */
function itemsBlock(items) {
  return list(items.slice(0, 20).map((one) => `<li>${renderValue(one, 2) || genericObject(one, 2)}</li>`));
}

/** A parsed JSON answer, as a person reads it. Depth caps the recursion; the raw block below
 *  always carries the whole thing. */
function renderValue(value, depth = 0) {
  if (Array.isArray(value)) {
    if (!value.length) return '<p class="friendly-empty">The list received is empty.</p>';
    if (value.every((one) => typeof one === 'string' || typeof one === 'number')) {
      return list(value.map((one) => `<li>${escapeHtml(String(one))}</li>`));
    }
    return list(value.slice(0, 20).map((one) => `<li>${renderValue(one, depth + 1)}</li>`));
  }

  // Pages the researcher proposes to read: {"urls": [{"url", "why"}]}
  if (Array.isArray(value.urls)) return urlsBlock(value.urls);

  // Atomic claims: {"claims": [{"claim_text", ...}]} or a bare list of them.
  const claims = Array.isArray(value.claims)
    ? value.claims
    : Array.isArray(value)
      ? value
      : [];
  if (claims.length && claims.every((one) => one && typeof one === 'object' && (one.claim_text || one.text))) {
    return claimsBlock(claims);
  }

  // Topics: {"topics": [{"title", "topic", "angle", ...}]}
  if (Array.isArray(value.topics)) {
    const topics = value.topics.slice(0, 12);
    const items = topics.map((one) => {
      const detail = [one && one.topic, one && one.angle].filter(Boolean).map(escapeHtml).join(' — ');
      return `<li><strong>${escapeHtml((one && one.title) || '')}</strong>${detail ? `<div class="friendly-why">${detail}</div>` : ''}</li>`;
    });
    return `<div class="friendly-head">I suggest ${topics.length} ${topics.length === 1 ? 'topic' : 'topics'}:</div>${list(items)}`;
  }

  // A script draft: {"title", "scenes": [{"narration", ...}]}
  if (Array.isArray(value.scenes) && (value.title || value.scenes.length)) {
    const scenes = value.scenes.slice(0, 30);
    const items = scenes.map((scene) =>
      `<li><div>${escapeHtml((scene && scene.narration) || '')}</div>${
        scene && scene.visual ? `<div class="friendly-why">Picture: ${escapeHtml(scene.visual)}</div>` : ''
      }</li>`,
    );
    const title = value.title ? `"${escapeHtml(value.title)}" — ` : '';
    return `<div class="friendly-head">${title}${scenes.length} ${scenes.length === 1 ? 'scene' : 'scenes'}:</div>${list(items)}`;
  }

  // A claim verdict: {"status", "confidence", "evidence_quote", "verifier_notes"}
  if (value.status && VERDICT_LABEL[String(value.status).toUpperCase()]) {
    const status = String(value.status).toUpperCase();
    const confidence =
      typeof value.confidence === 'number' ? ` · confidence ${Math.round(value.confidence * 100)}%` : '';
    const quote = value.evidence_quote
      ? `<blockquote class="friendly-quote">"${escapeHtml(value.evidence_quote)}"</blockquote>`
      : '';
    const notes = value.verifier_notes ? `<div class="friendly-why">${escapeHtml(value.verifier_notes)}</div>` : '';
    return `<div class="friendly-head">Verdict: ${escapeHtml(VERDICT_LABEL[status])}${confidence}</div>${quote}${notes}`;
  }

  if (depth >= 2) return '';
  return genericObject(value, depth);
}

/**
 * An answer as the interface shows it: ordinary text stays ordinary text; a structured
 * answer becomes sentences and lists, with the model's exact output collapsed underneath.
 * A structured answer cut off by the token limit still reads as its items — the complete
 * ones — with a note saying the list was interrupted; the raw text stays collapsed below.
 *
 * @param {unknown} raw the run's stored output text
 * @returns {string} HTML, every dynamic value escaped
 */
export function friendlyAnswer(raw) {
  const text = String(raw ?? '');
  const value = extractJson(text);
  if (value) {
    const body = renderValue(value);
    if (body) {
      return `${body}<details class="chat-raw"><summary>The model's exact answer</summary><pre>${escapeHtml(text)}</pre></details>`;
    }
  } else {
    const startsStructured = /^[{[]/.test(text.trim());
    const salvaged = salvageItems(text);
    if (salvaged || startsStructured) {
      const shaped = salvaged
        ? salvaged.every((one) => one && typeof one === 'object' && (one.claim_text || one.text))
          ? claimsBlock(salvaged)
          : salvaged.every((one) => one && typeof one === 'object' && one.url)
            ? urlsBlock(salvaged)
            : itemsBlock(salvaged)
        : '';
      const note = salvaged
        ? '<p class="friendly-note">The list from the model was cut off at the token limit; only the complete items are shown.</p>'
        : '<p class="friendly-note">The answer was cut off at the token limit, before the first complete item.</p>';
      const empty = salvaged ? '' : '<p class="friendly-empty">No complete item to show.</p>';
      return `${note}${empty}${shaped}<details class="chat-raw"><summary>The model's exact answer</summary><pre>${escapeHtml(text)}</pre></details>`;
    }
  }
  if (value) {
    return '<p class="friendly-empty">Structured answer with no displayable content.</p>' +
      `<details class="chat-raw"><summary>The model's exact answer</summary><pre>${escapeHtml(text)}</pre></details>`;
  }
  return escapeHtml(text);
}
