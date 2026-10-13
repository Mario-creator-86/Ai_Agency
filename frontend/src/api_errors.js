// PAGE_SETTINGS_ERRORS (PAGE-11): what the page says when a request to the studio does not
// succeed. Every kind of failure has its own sentence: a value the studio refused (422, whose
// detail is a list), the studio's own fault (5xx), a request that never got an answer, one that
// took too long, and a state that changed under him (409). Pure: no DOM, so node --test loads it.

export const KEY_WORDS = 'Cheia Proprietarului nu este valabilă.';
export const NETWORK_WORDS = 'Conexiunea nu este disponibilă. Ce se vede nu mai este la zi.';
export const TIMEOUT_WORDS =
  'Studioul nu a răspuns la timp. Comanda poate fi încă în lucru pe server: reîncarcă pagina și privește starea înainte să repeți.';
// A 5xx does not say whether anything changed (a paid step can fail after paying), so the
// sentence does not promise that nothing did; it sends him to look first.
export const SERVER_WORDS =
  'Studioul a avut o eroare internă. Detaliile sunt în jurnalul serverului; reîncarcă pagina și privește starea înainte să repeți.';
export const CONFLICT_WORDS =
  'Starea s-a schimbat între timp. Reîncarcă pagina și privește din nou înainte să repeți.';
export const VALUE_REFUSED = 'Valoarea trimisă nu este acceptată';

/** The studio's catch-all 500 detail (app.main), never shown as it is. */
const GENERIC_DETAILS = new Set(['Internal error', 'Internal Server Error']);

/** Field names the Owner meets in the page's forms, in his words. */
const FIELD_WORDS = /** @type {Record<string, string>} */ ({
  limit_usd: 'limita',
  period: 'perioada',
  expected_version: 'versiunea citită',
  expected_policy_version: 'versiunea politicii citită',
  autonomous_privacy: 'vizibilitatea',
  public_publish_enabled: 'publicul permis',
  publish_delay_minutes: 'întârzierea publicării',
  amount_usd: 'suma',
  note: 'nota',
  price_usd: 'prețul',
  threshold_usd: 'pragul',
});

/** @param {unknown} loc a pydantic location: ['body', 'limit_usd'], ['query', 'limit'], ... */
export function fieldName(loc) {
  const parts = (Array.isArray(loc) ? loc : [])
    .filter((part) => !['body', 'query', 'path', 'header'].includes(String(part)))
    .map(String);
  if (!parts.length) return '';
  const last = parts[parts.length - 1];
  return FIELD_WORDS[last] || parts.join('.');
}

/** The first number in an English bound message: «greater than or equal to 0» gives '0'. */
function bound(msg) {
  const match = /(-?\d+(?:\.\d+)?)/.exec(String(msg || ''));
  return match ? match[1] : '';
}

/** @param {{type?: string, msg?: string}} item */
function problemWords(item) {
  const type = String(item.type || '');
  const msg = String(item.msg || '');
  if (type === 'value_error' || type === 'assertion_error') {
    // The studio's own validators speak Romanian; pydantic only prefixes them.
    return msg.replace(/^(Value error|Assertion failed),\s*/, '').trim();
  }
  if (type === 'missing') return 'lipsește';
  if (type === 'greater_than') return `trebuie să fie mai mare decât ${bound(msg)}`;
  if (type === 'greater_than_equal') return `trebuie să fie cel puțin ${bound(msg)}`;
  if (type === 'less_than') return `trebuie să fie mai mic decât ${bound(msg)}`;
  if (type === 'less_than_equal') return `trebuie să fie cel mult ${bound(msg)}`;
  if (type === 'int_parsing' || type === 'int_from_float' || type === 'int_type') return 'trebuie să fie un număr întreg';
  if (/^(float|decimal)_/.test(type)) return 'trebuie să fie un număr';
  if (type === 'bool_parsing' || type === 'bool_type') return 'trebuie să fie da sau nu';
  if (type === 'uuid_parsing' || type === 'uuid_type') return 'nu este un identificator valid';
  if (type === 'string_too_short') return 'este prea scurt';
  if (type === 'string_too_long') return 'este prea lung';
  if (type === 'string_pattern_mismatch') return 'nu are forma cerută';
  if (type === 'literal_error' || type === 'enum') return 'nu este una dintre valorile permise';
  if (type === 'extra_forbidden') return 'nu este un câmp cunoscut';
  if (type === 'json_invalid') return 'nu este un JSON valid';
  return 'nu este acceptată';
}

/** @param {unknown} detail FastAPI's 422 list: [{type, loc, msg}, ...] */
export function validationWords(detail) {
  const items = Array.isArray(detail) ? detail : [];
  const parts = items
    .filter((item) => item && typeof item === 'object')
    .map((item) => {
      const field = fieldName(item.loc);
      const why = problemWords(item);
      return field ? `${field} — ${why}` : why;
    })
    .filter(Boolean);
  return parts.length ? `${VALUE_REFUSED}: ${parts.join('; ')}.`.replace(/\.\.$/, '.') : `${VALUE_REFUSED}.`;
}

/** The backend's own words in a detail, when it wrote some. */
function ownWords(detail) {
  if (typeof detail === 'string') return detail.trim();
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    for (const key of ['message', 'reason_ro', 'error']) {
      if (typeof detail[key] === 'string' && detail[key].trim()) return detail[key].trim();
    }
  }
  return '';
}

/**
 * The sentence for a response that did not succeed.
 * @param {number} status
 * @param {any} body the parsed JSON body, or {} when there was none
 */
export function apiErrorMessage(status, body) {
  const detail = body ? body.detail : undefined;
  if (status === 401) return KEY_WORDS;
  if (status === 422 && Array.isArray(detail)) return validationWords(detail);
  const own = ownWords(detail);
  if (status >= 500) {
    if (own && !GENERIC_DETAILS.has(own)) return own;
    const code = body && typeof body.correlation_id === 'string' ? body.correlation_id.slice(0, 8) : '';
    return code ? `${SERVER_WORDS} (cod: ${code})` : SERVER_WORDS;
  }
  if (own) return own;
  if (status === 409) return CONFLICT_WORDS;
  if (status === 422) return `${VALUE_REFUSED}.`;
  return `Studioul a refuzat cererea (cod ${status}).`;
}

/**
 * What a fetch that never got an answer means. Both kinds stay marked `network`, which the
 * shooting sheet reads as «the purchase may still be running» (NETWORK_STEP_WORDS).
 * @param {any} error what fetch threw
 */
export function fetchFailure(error) {
  const name = error && error.name;
  const timeout = name === 'TimeoutError' || name === 'AbortError';
  return Object.assign(new Error(timeout ? TIMEOUT_WORDS : NETWORK_WORDS), { network: true, timeout });
}
