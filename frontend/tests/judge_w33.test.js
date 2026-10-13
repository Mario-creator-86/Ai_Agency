// W33, THE RELEASE JUDGE'S SMALL FIXES. A stranger over the real stream, on a fresh copy of the
// Owner's studio, met three things that read as unfinished: a failed site said its reason twice
// (the page's label, then the backend's Romanian sentence saying the same thing, and on one site
// the two disagreed); a connection the studio added itself was titled «settings», a machine word;
// and the Character Bible's place chips were cut mid-word at the card's edge.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { connectionTitle, hostFailureWords } from '../src/dialog_words.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const SETTINGS = fs.readFileSync(new URL('../src/settings.js', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

const LABELS = { HTTP_403: 'a refuzat studioul (403)', OTHER: 'nu a răspuns cu nimic utilizabil' };

test('a failed site says why once: the backend\'s sentence when it wrote one, the label otherwise', () => {
  const said = 'Site-ul a refuzat cererea studioului (HTTP 403); cât timp o refuză, nu poate fi sursă.';
  assert.equal(hostFailureWords('HTTP_403', said, LABELS), said);
  assert.equal(hostFailureWords('HTTP_403', '', LABELS), 'a refuzat studioul (403)');
  assert.equal(hostFailureWords('HTTP_403', '   ', LABELS), 'a refuzat studioul (403)');
  // no reason and no sentence: the state's own word, never a guessed cause
  assert.equal(hostFailureWords(null, '', LABELS), 'nu poate fi citit');
  // a reason the page does not know passes through as words, not guessed into a known one
  assert.equal(hostFailureWords('TLS_PINNED', '', LABELS), 'tls pinned');
});

test('the Research door prints the failure through hostFailureWords, not label and sentence together', () => {
  assert.match(MAIN, /hostFailureWords\(r\.last_test_reason, r\.last_test_detail, HOST_REASON_LABEL\)/);
  assert.ok(!/HOST_REASON_LABEL\[r\.last_test_reason\][^\n]*last_test_detail \? ` · /.test(MAIN));
});

test('a connection stored under a machine name is titled by its service, the stored name kept', () => {
  const id = 'settings:7d1f0c2a-9b3e-4c55-8a10-2f6e5d4c3b2a';
  assert.deepEqual(connectionTitle(id, 'Ollama · ollama.com'), { title: 'Ollama · ollama.com', identifier: id });
  assert.deepEqual(connectionTitle('7d1f0c2a-9b3e-4c55-8a10-2f6e5d4c3b2a', 'Runway'), { title: 'Runway', identifier: '7d1f0c2a-9b3e-4c55-8a10-2f6e5d4c3b2a' });
  // the Owner's own names stay his, with or without an identifier after them
  assert.deepEqual(connectionTitle('local-ollama', 'Ollama'), { title: 'local-ollama', identifier: '' });
  assert.deepEqual(connectionTitle('Ollama Cloud', 'Ollama'), { title: 'Ollama Cloud', identifier: '' });
  assert.deepEqual(connectionTitle('Canal principal 7d1f0c2a-9b3e-4c55-8a10-2f6e5d4c3b2a', 'YouTube'), { title: 'Canal principal', identifier: 'Canal principal 7d1f0c2a-9b3e-4c55-8a10-2f6e5d4c3b2a' });
  assert.deepEqual(connectionTitle('', 'Ollama'), { title: 'Ollama', identifier: '' });
});

test('Setări titles every card through connectionTitle, with the service as the fallback', () => {
  assert.ok(!/function splitIdentifier/.test(SETTINGS));
  assert.match(SETTINGS, /connectionTitle\(provider\.name, /);
  assert.match(SETTINGS, /connectionTitle\(item\.name, spec\.label\)/);
});

test('a Character Bible place chip moves under the name and never cuts a word silently', () => {
  const tail = STYLE.slice(STYLE.lastIndexOf('W33'));
  assert.match(tail, /\.char-header\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.match(tail, /\.char-archetype\s*\{[^}]*text-overflow:\s*ellipsis/);
  assert.match(tail, /\.char-archetype\s*\{[^}]*max-width:\s*100%/);
  assert.match(MAIN, /class="char-archetype" title="\$\{escapeHtml\(/);
});

test('a site with no search address keeps its empty field behind a key, one with an address shows it', () => {
  assert.match(MAIN, /<details class="host-search-edit"><summary class="host-search-key">Adaugă adresa de căutare<\/summary>\$\{editor\}<\/details>/);
  assert.match(MAIN, /r\.search_template\s*\n?\s*\? editor/);
  assert.match(STYLE.slice(STYLE.indexOf('/* W33')), /\.host-search-edit > \.host-search-key\s*\{[^}]*cursor:\s*pointer/);
});
