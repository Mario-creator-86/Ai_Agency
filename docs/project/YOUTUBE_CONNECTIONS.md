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

### Avatar repair — live check, 2026-09-11

Both existing rows held valid Google thumbnail URLs, but the app sent `img-src 'self' data:`, so
the browser blocked the images. The image policy now allows the two YouTube avatar origins
`https://yt3.ggpht.com` and `https://yt3.googleusercontent.com`. Scripts, styles and connections
remain same-origin. Images use `no-referrer` and a 44px circular cover layout.

`_channel_snapshot` selects high → medium → default by nonempty URL, not by whether the size
object exists. The selected URL is persisted unchanged in `channel_snapshot.thumbnail_url`.
Verify and the completed Reconnect callback both replace that snapshot, including clearing a
stale URL when YouTube returns no thumbnail. Only that missing-thumbnail case gets a neutral
CSS silhouette. The existing request includes `snippet,statistics` and preserves its additional
`id,contentDetails` parts for uploads-playlist metadata.

`scripts/verify_youtube_avatars.mjs` was run against the real local studio with the Owner token
passed privately through the environment. It clicked Verify for **Nexus Curiosity** and
**Inside The Nexus**, re-read the saved connections, and confirmed each image decoded to
**800×800**, with no image CSP violations. Evidence lives in
`output/playwright/youtube-avatars-live.json` and `youtube-avatars-live.png`. Its separate
browser-only missing-thumbnail fixture passed without changing the database. A real Google
re-consent was not initiated; Reconnect callback refresh/isolation is covered by the automated
stubbed-Google tests. The 62 targeted backend tests and 52 frontend tests passed, as did types
and the frontend build.

Official schema: [channels.list](https://developers.google.com/youtube/v3/docs/channels/list)
and [channel thumbnails](https://developers.google.com/youtube/v3/docs/channels#snippet.thumbnails).

### Original OAuth verification

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

The same check also asserts that the catalog picker no longer offers YouTube and that no label
anywhere in the section reads *Refresh token* or *ID canal*.

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

## The old form had to go, not just be joined

The first pass added the OAuth section beside the existing settings catalog, which still carried a
`youtube` entry asking for a client id, a client secret, **a refresh token, an ID canal YouTube**
and a redirect URI. Two forms, one of them still demanding exactly what the flow exists to remove.
The Owner found it immediately.

The catalog entry is now deleted, and every consumer of it reads the OAuth connection instead:

| Consumer | Before | Now |
| --- | --- | --- |
| `selected_youtube` (publishing credentials) | a `VERIFIED` catalog row chosen by a purpose selection | the bound connection, or the only connected one |
| channel binding (`PUT /settings/channels/{id}`) | `integration_id`, channel id copied from the typed field | `connection_id`, channel id copied from the grant |
| analytics provider | first `VERIFIED` youtube row | the only connected channel, or none |
| runbook preflight | a `VERIFIED` youtube row exists | a `CONNECTED` channel exists |
| purpose selections | a "YouTube" row in *Conturile alese* | gone; the backend refuses the purpose |

Two consequences worth stating plainly.

**Ambiguity is refused, not guessed.** With two channels connected and no binding, `selected_youtube`
raises instead of returning the first row. Publishing to the wrong channel is not a recoverable
mistake, and AMN-AI runs more than one channel, so a channel record must name its connection.

**A media verification bug fell out with it.** The check route branched `llm` → `stored` → *else*,
and the *else* built a YouTube provider. The `media` kinds — ElevenLabs and OpenAI media — have no
`client_id`, so verifying one raised, was swallowed by a bare `except`, and reported FAILED every
time. With the YouTube branch gone, media and stored both verify through the vendor probe that was
always meant to serve them.

## The form used to empty itself

Filling this form means leaving the window: the client id and the secret are copied out of the
Google console one at a time. The first version refreshed the list whenever the window regained
focus, which rebuilt the whole section — including the open form — so every trip away cleared
what had been typed. Three fields, three trips, and the Owner could never finish.

Two independent fixes, because either alone would have left the form fragile:

- the refresh now happens only after the Owner has actually been sent to Google, and never while
  a form is open, which is the condition the listener was always meant to express;
- whatever is typed is mirrored into a `draft` held outside the DOM and restored when the form is
  rebuilt, so no redraw from any cause can empty it. The draft is dropped on Renunță and after a
  successful save, and it is keyed to the connection being edited so it cannot appear in the
  wrong form.

The browser check covers it: it types into the form, leaves the window and returns, and compares.
Removing either protection alone still passes; removing both reproduces the original report
exactly, with three fields emptied and only the prefilled redirect URI left standing. That
negative control is how the check was shown to be worth anything.

## What this does not do

It connects channels. It does not upload. A connection being CONNECTED here is not evidence
that an upload has happened; that evidence is `publication_record`, which since 2026-09-12 holds
two PUBLISHED private uploads to Main Channel A (`98JltCPoOKs`, `sDEtt-WQGh8`) made by the
publish stage through a bound connection. The Phase 6 correction of 2026-09-09 recorded in
`13_ROADMAP_TODO.md` ("no upload has reached YouTube") is superseded (corrected 2026-09-18).
