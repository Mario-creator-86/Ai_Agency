# Internal audit — 2026-09-11

Commissioned by the Owner: check everything, fix and test every defect found, verify the logic
and the whole pipeline.

Scope: 29,000 lines of Python across `backend/`, `tests/` and `scripts/`, 8,800 lines of
JavaScript in `frontend/src/`, eighteen migrations, and the eleven checks the CI workflow runs.

Nine defects were found and fixed, each with a test that fails without the fix. Five areas were
checked and found sound; they now carry tests so that the finding is repeated on every run rather
than remembered. One structural gap is recorded as the next piece of work rather than a defect.

---

## How the defects were found

Not by reading code for style. Three lenses did nearly all the work, and each one is worth
reusing:

**What happens when a question fails?** Most code is written for the answer arriving. Searching
for `except Exception` and asking "what does the caller conclude from this?" produced the two most
serious findings.

**What does the fallback claim?** A branch that runs when nothing else matched tends to inherit an
optimistic message from the branch beside it. The factual gate's fallback said "verified factual
provenance" about assets it had never traced.

**What does the CI configuration actually check?** Two of its eleven checks had been failing since
Phase 11 without anyone running them locally.

---

## Defects found and fixed

### 1. A duplicate upload could not be ruled out, so it was ruled out

`YouTubeProvider.get_video_status` returned `exists=False` whenever the request raised.
`reconcile_upload` returned `None` — meaning "no previous upload found" — for the same reason. A
rate limit, an expired token or a dropped connection therefore became *evidence that a video was
absent*, and the caller's next step after that evidence is to upload.

Two callers acted on it. The retry path in `execute_publication` uploads when reconciliation finds
nothing, so a failed reconciliation produced a second copy of a video that may already have been
live. `reconcile_publication` wrote `FAILED_RETRYABLE` with the message "Video not found on remote
channel after timeout; safe to retry" — a statement nobody had established.

Both now raise `RemoteStateUnavailable`. The retry stops before uploading and records that a
duplicate cannot be ruled out; reconciliation stays `REMOTE_UNKNOWN`. An unconfigured provider
raises too, because a provider with no credentials knows nothing about a channel, including
whether a video is on it.

`tests/test_remote_state_honesty.py` — five tests, including one that counts upload attempts.

### 2. The factual gate passed assets whose provenance it never established

The gate walks asset → render job → storyboard → script to learn which claims a video makes. If
any link was missing, the walk produced nothing and execution fell through to a check that read
**"Asset has verified factual provenance"** and passed.

This is the same defect the 2026-09-09 external audit found elsewhere: a verification asserted,
never performed. `../architecture/50_CONTENT_GATE_MATRIX.md` gives `NOT_APPLICABLE` its own outcome — "record
reason" — and it is not a synonym for PASS.

An unresolvable chain now fails the gate and names the missing link. A script that genuinely
references no claims still passes, and says so plainly instead of claiming a verification.

### 3. A claim referenced but absent counted as supported

The same gate loaded the claim rows that existed and compared only those. A script citing three
claims of which two had no rows passed as "All 1 referenced claims are SUPPORTED". Dangling
references now fail the gate and are named in the reason.

Both gate defects: `tests/test_truthfulness_gates.py`.

### 4. Owner funding was not idempotent

`command_id` reached `record_owner_funding` only as a correlation id. A retried request — a double
submit, a proxy replaying a POST, a client that never saw the response — recorded a second funding
event and posted a second ledger transaction. The Owner's money doubled.

The Phase 11 decision log claimed unique external references made every money-creating operation
idempotent. That holds for revenue evidence and provider invoices, which carry a reference. Owner
funding carries none.

Funding now honours the command id through the existing `CommandRecord` table, remembered inside
the same transaction that posts, so the record cannot survive without the posting or the posting
without the record. The key is the command, not the amount: two deliberate contributions of the
same size are both recorded. The same id with different input is a 409.

### 5. The studio could not find its own encoder

FFmpeg was installed and configured, and the studio kept saying it was not.

Three parts of the codebase resolved the toolchain three different ways. The renderer read
`STUDIO_FFMPEG_PATH` from the environment and then PATH. Quality control and the preflight check
read PATH alone. Only the media router passed the Owner's configured `ffmpeg_path`, and only to
the renderer.

The Owner's FFmpeg comes from WinGet: `ffmpeg.exe` on PATH, `ffprobe.exe` beside it in the package
folder, and the encoder path in `.env`. So the preflight reported media inspection unavailable
with ffprobe one directory away from an encoder it had already found — and five media tests
skipped themselves on a machine with a working encoder.

One resolver now, `backend/app/media/toolchain.py`: an explicit setting, then PATH, then beside the
resolved ffmpeg. Unskipping those five tests was the point, and they pass. The suite went from
391 passed / 6 skipped to **402 passed / 1 skipped**, the remaining skip being a real Ollama server.

### 6. Verifying a media provider always failed

The integration check route branched `llm` → `stored` → *else*, and the *else* built a
`YouTubeProvider`. The `media` kinds — ElevenLabs and OpenAI media — have no `client_id`, so
verifying one raised on a missing key, was swallowed by a bare `except`, and reported FAILED every
time. Media and stored now share the vendor probe that always covered both.

### 7. Two audited writes left no trace

An exchange rate decides how a foreign payout converts to USD, and that figure is what mints VR$;
a rate arriving with no event left the books unable to say where it came from. A scheduled job
decides that a workflow runs again and again without being asked, which is an autonomy decision.

Both now append and link their event. Migration `0018_audit_gaps` adds a nullable `event_id` to
each table; rows written earlier keep NULL, which is the truth about them.

### 8. The preflight described a claim it had not checked

The publishing check passed on either an OAuth connection or credentials in the server
environment, and reported "channel connected by OAuth" in both cases. It now says which, and names
the channel when there is one.

### 9. CI had been red since Phase 11

`ruff format --check` wanted eleven files. The secret scan reported five findings, all of them the
keyword heuristic firing on field names and obviously invented test values. Formatted; each
scanner finding annotated with the tool's own line-scoped pragma, so a real credential anywhere
else still fails the scan.

A red check that everyone has learned to ignore is worse than no check.

---

## Checked and found sound

Each of these is now covered by a test, so the finding is repeated rather than remembered.

| Claim | How it was checked | Result |
| --- | --- | --- |
| Every API route is Owner-only | Called every operation in the OpenAPI surface with no credential | 3 public routes, all deliberate |
| Migrations match the models | Alembic `compare_metadata` against the declared metadata | No drift |
| One dollar mints one VR$ | Six threads minting one payout at once | One accepted, five refused, books balanced |
| One payout records once | Six threads recording one reference at once | One accepted |
| A chargeback reverses once | Six threads reversing one transaction | One accepted |
| No unescaped text reaches innerHTML | Scanned all 46 interpolation sites | None found |
| A claim cannot be supported by invented evidence | Read the verification path | The quote must appear verbatim in the source |
| Analytics cannot measure a video that does not exist | Read the ingestion guard | Refuses a simulated or remote-less publication |

The three public routes are the two health probes, which must answer a load balancer, and the
OAuth callback, which Google redirects a browser to and which therefore cannot carry the Owner
credential. Its protection is the single-use state.

`escapeHtml` guarded all 46 of those sites and had no test of its own, because it was a private
function inside the application's entry point. It now lives in `frontend/src/html.js` with five
tests.

---

## Not a defect: the runbook has no work wired into it

`execute_daily_run` walks twelve stages and asks `app.state.stage_runners` for the work of each.
Nothing in the application ever sets that attribute. A daily run in production therefore records
`preflight` and then eleven stages as SKIPPED, each with its reason.

This is honest — the runbook was built to report SKIPPED rather than omit a stage — but it means
the studio does not yet run a day end to end. The work exists in Phases 4 to 7 and is not
connected to the orchestrator that would call it.

That is the next piece of implementation, not a defect to fix in an audit.

---

## What the Owner's own studio reports now

Read from `data/studio.db` after the fixes, not from a test fixture:

```
STATUS: DEGRADED
  stop_autonomy        ok
  llm_provider         ok
  agents               ok    7 activi
  render_engine        ok    ...ffmpeg-9.0.1-full_build\bin\ffmpeg.exe
  media_inspection     ok
  research_sources     FAIL
  image_provider       FAIL
  voice_provider       FAIL
  publishing           ok    Canal conectat: NEXUS CURIOSITY.
```

`media_inspection` was FAIL before this audit and is now ok, with no change to the machine. The
three remaining failures are honest and need external accounts the Owner has not added: no
research sources ingested, no image provider, no voice provider.

The publishing line is worth noting on its own. A real YouTube channel was connected through the
OAuth flow built the day before, by the Owner, against the real Google — the connection row exists
in the production database with a channel id read back from the API.
