# YouTube channel connections — OAuth, not typing

**Date:** 2026-09-11 · **Scope:** frontend, `backend/app/youtube/`, migration `0017_youtube_connections`

## What the Owner asked for

Stop asking a human to paste a refresh token and a channel id. Keep four manual fields — a name,
a Google OAuth client id, a client secret, a redirect URI — then one button that performs the
Authorization Code flow with offline access, stores the refresh token server-side, reads the
channel back from the API and shows which channel was connected. Several channels must be able to
coexist, and nothing about any of them may be hardcoded.

## Why the old shape was wrong

A refresh token typed into a form is a credential travelling through a clipboard, a browser field
and an HTTP body, with no proof that whoever pasted it controls the channel it belongs to. A
channel id typed beside it is worse: it is an unverified claim about which account the token
opens. The two fields together let a connection be *described* correctly and *be* wrong, and the
publishing pipeline would have no way to tell.

The flow now closes that gap. The refresh token is issued by Google directly to the studio, and
the channel identity is read back with that token, so the row cannot describe an account the
grant does not actually open.

## The shape of it

**Two tables** (`0017_youtube_connections`):

`youtube_connection` holds one authorised channel, or one waiting to be authorised. The client
secret and the refresh token are not columns: both live inside `encrypted_secrets`, a Fernet blob
written by the same vault the rest of the studio uses, and `secret_fields` names which of them
exist so a view can answer "is this connected?" without decrypting anything. Everything about the
channel — id, title, custom URL, thumbnail, counts, uploads playlist, granted scopes — is written
only from a `channels.list` answer.

`youtube_oauth_state` holds one pending authorisation. The callback arrives through the user's
browser, where the Owner credential is not present, so the random `state` is the entire CSRF
defence: 43 characters from `secrets`, single-use (stamped `used_at` the moment it is accepted),
and dead after ten minutes.

**Eight Owner-only routes** under `/api/v1/youtube/`, plus one public route. The public one is
`GET /auth/youtube/callback`, which must be public because Google redirects a browser to it; it
is protected by the state, and it renders an unstyled HTML page because the studio's CSP forbids
inline styles.

**The consent URL** carries `access_type=offline`, `response_type=code`,
`include_granted_scopes=true`, the two scopes the studio needs (`youtube.readonly`,
`youtube.upload`), and `prompt=consent` — but only when there is no refresh token stored, or when
the Owner explicitly pressed Reconnect. Sending it unconditionally would re-prompt a working
connection for no reason; never sending it means a second authorisation returns no refresh token
at all.

## Decisions worth recording

**Failure states are written in their own transaction.** The first version set `status = ERROR`
inside the transaction that then raised, so the rollback erased the very record of the failure. A
test caught it. `complete_authorization` is now three transactions — claim the state, exchange and
fetch, then write the result — and `_record_failure` opens its own.

**Disconnect forgets locally first, then revokes.** The revocation call to Google happens outside
any transaction, after the row is already clean. If Google is unreachable the token is still gone
from the studio, which is the half the studio controls.

**Changing the client drops the refresh token.** A refresh token is issued to one OAuth client; if
the Owner edits the client id, the stored token is meaningless and keeping it would leave a
connection that reports CONNECTED and cannot mint an access token. The status returns to
AUTH_REQUIRED and the card asks to connect again.

**Nothing is special-cased per channel.** AMN-AI runs two channels today, and the code contains
neither of their names. A test greps the module for hardcoded channel ids, client ids, secrets,
tokens and account names; it caught a channel name sitting in a comment, which was removed.

## Verification

Backend: `tests/test_youtube_connections.py`, 30 tests against a stubbed Google — the token
exchange, the channel read, single-use state, expiry, replay, an unknown state, the ERROR path
surviving its own rollback, the client-change rule, multiple independent connections, and the
no-hardcoding grep. Full suite 368 passed, 6 skipped (ffmpeg and Ollama absent). `ruff`, `mypy`,
`tsc` and the frontend's 43 tests clean.

Browser: `scripts/demo_youtube.py` builds a throwaway studio in a temporary directory — never the
Owner's books — and drives the *real* service functions with only the HTTP transport to Google
replaced, producing two CONNECTED channels and one AUTH_REQUIRED. `scripts/verify_youtube_ui.mjs`
then drives that studio in Chromium with every request to `accounts.google.com` aborted at the
network layer, and asserts against what the page actually renders:

- the three cards, their statuses, the channel identities read back from the API;
- that the add form asks for exactly four fields, the secret one masked, the redirect URI
  prefilled from the page's own origin;
- that no secret-shaped text appears anywhere in the DOM;
- that the consent URL carries `access_type=offline`, `prompt=consent` and a long random state;
- that pressing Connect opens a second tab instead of navigating the studio away.

Screenshots: `output/playwright/youtube-panel.png`, `output/playwright/youtube-form.png`.

That last assertion was written because the check failed: `window.open('', '_blank', 'noopener')`
returns `null` in Chromium, so the code fell through to its fallback and sent the Owner's own tab
to Google, losing the panel. The handle is needed precisely because the tab must be opened
synchronously on the click, before the authorisation URL arrives, or the browser blocks it as an
unrequested popup. `noopener` is gone and the opener link is cut by hand while the new tab is
still blank and same-origin.

The visual pass also found that the CSS class `.secondary` — the affirmative button in roughly
fifteen places across the admin surface, including the top bar's Settings control — had never been
defined in any stylesheet, so all of them rendered as the browser's default box. It is defined
now.

## What this does not do

It connects channels. It does not upload. The publishing pipeline still holds the Phase 6
correction recorded in `13_ROADMAP_TODO.md`: no upload has reached YouTube, and a connection being
CONNECTED here is not evidence that one has.
