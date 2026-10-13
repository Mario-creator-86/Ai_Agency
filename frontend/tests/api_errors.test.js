// PAGE_SETTINGS_ERRORS (PAGE-11): the page's api() showed a refused budget (a 422 whose detail
// is a list) and a studio fault (500) as «Conexiunea nu a putut fi verificată», and its 409
// fallback told him to repeat the command, on money paths too. Each kind of answer now has its
// own Romanian sentence, decided by a pure module the tests can load.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CONFLICT_WORDS,
  KEY_WORDS,
  NETWORK_WORDS,
  SERVER_WORDS,
  TIMEOUT_WORDS,
  apiErrorMessage,
  fetchFailure,
  validationWords,
} from '../src/api_errors.js';

const OLD_CONNECTION = /Conexiunea nu a putut fi verificată/;

test('a 422 list detail names the field and why, in Romanian', () => {
  const body = {
    detail: [{ type: 'missing', loc: ['body', 'limit_usd'], msg: 'Field required' }],
  };
  const words = apiErrorMessage(422, body);
  assert.match(words, /^Valoarea trimisă nu este acceptată: /);
  assert.match(words, /limita/);
  assert.match(words, /lipsește/);
  assert.doesNotMatch(words, OLD_CONNECTION);
  assert.doesNotMatch(words, /Field required/);
});

test('the studio\'s own Romanian validator message is kept, without pydantic\'s prefix', () => {
  const words = validationWords([
    { type: 'value_error', loc: ['body'], msg: 'Value error, Scrie o limită mai mare decât zero sau retrage bugetul.' },
  ]);
  assert.equal(words, 'Valoarea trimisă nu este acceptată: Scrie o limită mai mare decât zero sau retrage bugetul.');
});

test('bounds, numbers, patterns and choices are each said in Romanian', () => {
  const said = (type, msg) => validationWords([{ type, loc: ['body', 'publish_delay_minutes'], msg }]);
  assert.match(said('greater_than_equal', 'Input should be greater than or equal to 0'), /cel puțin 0/);
  assert.match(said('less_than_equal', 'Input should be less than or equal to 1440'), /cel mult 1440/);
  assert.match(said('int_parsing', 'Input should be a valid integer'), /număr întreg/);
  assert.match(said('string_pattern_mismatch', "String should match pattern '^x$'"), /forma cerută/);
  assert.match(said('literal_error', "Input should be 'private' or 'public'"), /valorile permise/);
  assert.match(said('something_new', 'Some English sentence'), /nu este acceptată/);
  assert.doesNotMatch(said('something_new', 'Some English sentence'), /English/);
  // two problems are both said
  const two = validationWords([
    { type: 'missing', loc: ['body', 'command_id'], msg: 'Field required' },
    { type: 'int_parsing', loc: ['body', 'expected_version'], msg: 'Input should be a valid integer' },
  ]);
  assert.match(two, /command_id — lipsește; versiunea citită — trebuie să fie un număr întreg/);
});

test('a 5xx is the studio\'s fault, never a connection problem', () => {
  for (const status of [500, 502, 504]) {
    const words = apiErrorMessage(status, { detail: 'Internal error', correlation_id: 'abcdef12-3456' });
    assert.match(words, new RegExp('^' + SERVER_WORDS.slice(0, 30)));
    assert.match(words, /abcdef12/);
    assert.doesNotMatch(words, OLD_CONNECTION);
    assert.doesNotMatch(words, /Internal error/);
  }
  assert.equal(apiErrorMessage(500, {}), SERVER_WORDS);
  // a 503 that explains itself in Romanian is shown as it is (no FFmpeg, a vault that cannot be read)
  assert.equal(apiErrorMessage(503, { detail: { error: 'RenderEngineUnavailable', message: 'FFmpeg nu a putut porni.' } }), 'FFmpeg nu a putut porni.');
});

test('a 409 without words of its own never asks him to repeat blindly', () => {
  assert.equal(apiErrorMessage(409, {}), CONFLICT_WORDS);
  assert.doesNotMatch(CONFLICT_WORDS, /repetă comanda/);
  assert.match(CONFLICT_WORDS, /înainte să repeți/);
  // the backend's own refusal wins
  assert.equal(apiErrorMessage(409, { detail: 'Politica s-a schimbat între timp.' }), 'Politica s-a schimbat între timp.');
  assert.equal(apiErrorMessage(409, { detail: { status: 'FILM_BUSY', message: 'Filmul este deja în lucru.' } }), 'Filmul este deja în lucru.');
});

test('the key and the plain refusals keep their words', () => {
  assert.equal(apiErrorMessage(401, {}), KEY_WORDS);
  assert.equal(apiErrorMessage(404, { detail: 'Filmul nu există.' }), 'Filmul nu există.');
  assert.match(apiErrorMessage(404, {}), /404/);
  assert.doesNotMatch(apiErrorMessage(404, {}), OLD_CONNECTION);
});

test('a network failure and a timeout each have their own sentence and stay marked as network', () => {
  const network = fetchFailure(new TypeError('Failed to fetch'));
  assert.equal(network.message, NETWORK_WORDS);
  assert.equal(network.network, true);
  assert.equal(network.timeout, false);
  const late = fetchFailure(Object.assign(new Error('signal timed out'), { name: 'TimeoutError' }));
  assert.equal(late.message, TIMEOUT_WORDS);
  assert.equal(late.network, true);
  assert.equal(late.timeout, true);
  const aborted = fetchFailure(Object.assign(new Error('aborted'), { name: 'AbortError' }));
  assert.equal(aborted.timeout, true);
  assert.notEqual(TIMEOUT_WORDS, NETWORK_WORDS);
  assert.match(TIMEOUT_WORDS, /încă în lucru/);
});

test('main.js reads its errors from api_errors.js and has no alert()', async () => {
  const { readFileSync } = await import('node:fs');
  const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  assert.match(main, /from '\.\/api_errors\.js'/);
  assert.doesNotMatch(main, /Conexiunea nu a putut fi verificată/);
  assert.doesNotMatch(main, /repetă comanda/);
  assert.doesNotMatch(main, /\balert\(/);
});
