/**
 * Escaping for text that ends up inside markup.
 *
 * Forty-six places in the interface build HTML from template literals, and every value that
 * reaches one of them passes through here first. Much of that text is written by someone other
 * than the Owner — a language model's script title, a research source's headline, an error
 * message quoting a name the Owner typed — so it is untrusted by default.
 *
 * The page's Content-Security-Policy already forbids inline scripts and inline event handlers,
 * so an injected `onerror=` would not run. That is a second line of defence, not a reason to
 * skip the first: a header can be relaxed, and injected markup can mislead a reader without
 * executing anything at all — a forged "verified" badge needs no JavaScript.
 *
 * It lives in its own module so it can be tested. It used to be a private function in the
 * application's entry point, which meant the one guard protecting every injection site had no
 * test of its own.
 */

/** Characters that change the meaning of markup, and their entities. */
const ENTITIES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

/**
 * Render any value as text that is safe to place in element content or in a quoted attribute.
 *
 * `null` and `undefined` become an empty string rather than the words "null" and "undefined",
 * because a missing value should read as missing.
 *
 * @param {unknown} value
 * @returns {string}
 */
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ENTITIES[character]);
}
