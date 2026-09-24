# CURRENT STATUS — Phases 0-2 complete; Phases 4-6 partially implemented

Last verified: 2026-09-09 by an independent audit (`AUDIT_2026-09-09_EXTERNAL.md`) and the
remediation that followed it. Active edit claim: Codex, 2026-09-11 — ElevenLabs authentication,
database resource discovery/refresh, separate production choices, UI and regression tests.

> **Correction notice (2026-09-09).** An earlier revision of this document declared Phases 4, 5 An earlier revision of this document declared Phases 4, 5
> and 6 "complete — verified". That was not supported by the code. The audit found fabricated
> channel configuration, simulated uploads recorded as real YouTube publications, a
> non-playable file written with an `.mp4` name, a QC gate that verified its own metadata
> instead of the file, and a demo endpoint that inserted a self-authored "SUPPORTED" claim.
> Those defects are fixed; the phases they belonged to are now marked partial, because the
> providers their acceptance criteria require still do not exist. Sections below state what is
> actually true.

## The serial in one click: today's episode and tomorrow's script (2026-09-24)

The Owner's condition (2026-09-24): «Poti spune ca este gata cand pot da un click si serialul
zilnic este creat cat si scriptul pentru a doua zi de serial.» Six readers first found that one
click did neither: the serial only ever told yesterday, and yesterday was empty on his data; an
episode he approved by hand was never filmed; the writer saw the day's chronological tail as
template sentences; dialogue was one free-text block read by one voice with the speaker labels;
and nothing wrote tomorrow's script. Seven steps closed it, test first, with every provider
faked, and an adversary verified it: **READY**.

**What one click now does, proven by `tests/test_autonomous_day_end_to_end.py::test_one_click_films_one_episode_and_writes_the_next`
with the real stage runners and faked vendors:** the serial stage tells the newest real day,
writes it through the showrunner brief v3, has the Director read it on a six-point rubric,
approves it under the Owner's policy, storyboards it and the media stage films it; after the
day's log closes, the new stage **«Scenariul de mâine» (`serial_next`)** writes and reviews the
next episode from today's events and plans it, with no storyboard, so no media is spent. The
next day's run films that planned episode without writing it again.

**What it needs from the Owner.** On his data the Director may not approve episodes
(`director_may_approve_episodes = 0` on OFFICE_SERIAL). Without that leave the path is click,
approve, click — the episode waits for him at each step. Granting it is his act. And only his own
paid click proves the brief v3, the rubric and the plan with real models and vendors.

- 2026-09-24, serial S0+S1 (tested with every provider faked, no real run). The 2026-09-19 metadata guard is finished: an office-serial episode cannot go out under another channel's title and tags from the last 24 hours, nor under a title that shares no word with its own episode. It is checked by the Publisher (HOLD) and again on the upload road (BLOCKED_GATE). The dead end is closed: a HOLD the Director lifted no longer hands its refused title to the upload, because the Publisher is asked again, and a BLOCKED_GATE row no longer keeps a film out of later runs. The serial stage now resumes before it skips. In order it takes up an APPROVED episode with no storyboard (readied without a model), a DRAFT the Director never read (read again, with the day's rewrite budget counted over all runs), and a DRAFT passed and waiting for the Owner (named by title; no new episode is written beside it). Only then does it tell a new closed day, looking back at most 7 days. The Owner's approve route builds the storyboard of the episode he approves. Tests: test_publication_metadata_per_film 12/12, test_serial_pipeline 43/43, neighbours 117 + 95 + 104 passed, mypy clean. Still open: S2 (the missing days and the newest real day), S3-S5 (the writer's input, schema and review) and S6 (tomorrow's script in the same click).

- 2026-09-24, serial S2+S3 (tested with every provider faked, no real run, live DB never opened). The run's start now closes every unclosed past date of the last 7 days, never before the studio's first event, then yesterday in full. The serial tells the newest closed day with public-safe events that comes after the newest day already told, and its reason names that day and the quiet days it passed over. Dry rehearsal on a copy of the readers' copy: 2026-09-17..23 are closed, 2026-09-19 is told with 15 lines, and 2026-09-20..23 are quiet. The writer now gets the day's story, not its tail. The projection keeps a computed selection: routine dropped, repeats collapsed with their count, ranked by narrative weight, 8-15 lines in the order they happened. Each line is in English and carries the title, the first reason of a verdict, the refuted claim's text and the actor. The writer is told how many public events it does not see. Model names on record, and the families seedream, seedance, kimi, minimax and others, are redacted. Answered letters no longer leak their subject. Tests: test_serial_pipeline 66/66 (22 new tests, 30 cases), neighbours 104 + 95 + 62 passed, mypy clean. Still open: S4 (showrunner prompt and schema v3, which must also render the Romanian letter subjects in English), S5 (review v2) and S6 (tomorrow's script in the same click).

- 2026-09-24, serial S4 (tested with every provider faked, no real run, live DB never opened). The showrunner's brief is v3 ('episode-v3') and in English. It names the day it tells and asks for hook, situation, turn, payoff and button, and 2-4 speakers who act in the cited events (everyone else is background). It asks for 8-22 spoken words a beat (115-170 in all), English dialogue and title, one of the studio's 12 rooms per beat (11 in the headquarters, plus 'Studio principal' from the room table) and no written text in a scene. It gives the allowed names as a JSON array and each character's voice from their bible, and it keeps the day's events (with who acts in each), the serial's memory and any refused draft inside inert boundaries. The answer is structured lines {speaker, text, direction?}: names, colons and stage directions never reach the spoken text, and 'dialogue' now stores the spoken words only. Names are normalised ('Sarah' becomes 'Sarah (Director)'). A refused answer (stranger, invented citation, placeholder, unknown thread id, not the schema) now spends one of the day's two drafts, and the retry is told why and shown the refused answer. A rewrite after a Director FAIL is shown the refused draft. The Director's computed checks gain the v3 cast rule and a structure check. The storyboard reads the lines and binds the first speaker's voice, and old v2 episodes are still filmable without their labels. Tests: test_serial_pipeline 85/85 (19 new cases, 14 functions), neighbours 147 + 256 + 96 passed, mypy clean. Still open: S5 (review v2), S6 (tomorrow's script), S7 (one voice per speaker), and S13, the only proof that a real model follows the v3 schema.

- 2026-09-24, serial S5 (tested with every provider faked, no real run, live DB never opened). The Director's episode review is v2 ('episode-review-v2'). She now reads each beat with the events it cites (id, the record's public words, who acts), the speakers' voices from their bibles, and canon's last summaries and open threads. Her facts are fitted to a 14,000-character budget by shedding the least needed parts first, never cut mid-JSON. Her English brief FAILs any outcome a beat shows that its cited event does not hold, and she scores hook, situation, turn, payoff, voices and button 1-5. A PASS without the whole rubric is no verdict and is read again next run; a PASS her own scores put below 3 is a FAIL. New computed checks, run before any model: words per beat (8-22 spoken), concentration (no event in more than half the beats unless it is the day's only event), and language (title and every line in English). No check passes by absence: an episode that cites nothing now fails grounding. A dry rehearsal on a copy of the readers' copy shows 'Day One' failing concentration (8 of 8 beats on one event), and its review facts (16,890 characters) fitted whole into 13,530. Tests: test_serial_pipeline 99/99 (12 new functions, 14 cases, the last the contract test), neighbours 68 + 152 passed, test_agent_identity included, mypy clean. Still open: S6 (tomorrow's script in the same click), S7 (one voice per speaker), and S13, the only proof that a real model returns the rubric.

- 2026-09-24, serial S6 (tested with every provider faked; no real run; live DB never opened; the daily job untouched). One click now films one episode and writes the next. The run ends with a new stage, serial_next, after today's log is closed. It writes, reviews and, under the channel's policy, approves the episode of today from today's log (closed at the run's hour), and builds no storyboard, so nothing of an unfinished day is filmed or bought. The next run readies that approved episode (S1's first case) and its media stage films it. The media stage now films a serial episode only once its day is over, so a same-day re-run films nothing of today, even an episode the Owner approved that afternoon. serial_next writes nothing when today's log is not closed (it is blocked by daily_log), when today already has an episode, or when an earlier episode waits for his approval or the Director's reading. Every episode now carries a required plan for the next one (premise, cold-open line, open question, threads to pay off), stored as PLANNED. The next writer is given it inside a data boundary, keeps it only if the events support it, and says so. On approval, the plan is closed as KEPT, DROPPED or UNSAID. 39_DAILY_AUTONOMOUS_RUNBOOK §7 and its index hash are updated, and check_docs passes. Proof: tests/test_autonomous_day_end_to_end.py::test_one_click_films_one_episode_and_writes_the_next. Day D films D-1's episode and writes, reads and approves D's with no storyboard; a second click on D writes and films nothing of D; day D+1 films D's episode without asking any model to write it again. Tests: 24 new (red first), test_serial_pipeline 118/118, neighbours 245 + 171 passed (1 opt-in skip), end-to-end 7/7, mypy clean. Still open: the frontend labels for serial_next and the plan, the full-day log, S7 (one voice per speaker), and S13 (a real model answering the plan fields). With director_may_approve_episodes off, as on his data, tomorrow's script is written only on the first run after he approves the waiting episode.

## The page amazes a first-time visitor — wave 1 (2026-09-24)

The Owner asked on 2026-09-24 for a premium interface «ca un joc demn de anul 2026», one that
amazes whoever opens the page. Six readers first mapped the page and the serial read-only; four
parts then built this wave in frontend/ (plus the modules map in backend/app/services.py and the
delivery headers in backend/app/main.py), and a stranger judged it cold. **Verdict: ALMOST** — the
title screen and the entry amaze; the workspace is a well-made dark dashboard, not yet a 2026
game frame. What is left for YES is listed at the end of this section.

- 2026-09-24, W1 «every live claim true» (frontend/**, backend/app/services.py modules map, backend/app/main.py cache headers). Every 'live' the page prints is now decided in one place, frontend/src/live_claims.js, from states the page actually reads: the Unreal stream's status, the events socket's status and the last snapshot read.
- The corner readout says 'Live · Unreal Nfps' only while the Pixel Streaming video plays, and the figure is the inbound video frame rate from the library's statsReceived event.
- Over a frozen last frame it says 'Se reconectează · cadru înghețat'. Before any frame it is hidden behind the viewport's own 'Pornește sediul live…' plate.
- With no stream it says 'Live · randarea paginii Nfps' only while the backend's events reach the page. Otherwise it says 'Se conectează' or 'Se reconectează', 'Deconectat' on a refused key, and 'Date neactualizate' after a failed snapshot.
- The dot pulses only in the live state, and the slate caption and the canvas label drop ', live' when it is not true.
- The events socket reconnects (EventsLink): 1, 2, 4, 8, 16 then 30 s; a replay from the newest sequence held, in 500-event pages; the snapshot re-read after a drop; a 25 s ping with a 60 s silence limit; code 1008 is final. The masthead chip follows it.
- The register's «Acum» pulses only while a stage is running and something was recorded in the last hour (RUN_QUIET_MS = the worker's 3600 s task lease). After that it reads 'Ultima etapă începută: … · nimic nou de N zile' on the quiet chip. A daily_run_finished newer than a stage_started now closes that stage.
Tested: 188/188 frontend tests, tsc, build, shoot.mjs at 1920/1280/2560 with 0 missing and 0 errors, and frame sequences in scratchpad ui/shots_w1_scene.

- the canvas fallback follows the real Bucharest sun and weather. The reference_dusk light mode was removed from hq_time.js and hq_world.js, and scene.json now says light 'live'. The painted and drifting clouds scale with the real cloud cover from /office/weather (hq_sky.js cloudCover): no weather service means no cloud drawn. Photographed on 2026-09-24 at 12:00, 19:15 and 23:30, and under cloudy, clear and rain answers (scratchpad ui/shots_w1_scene/montage_instants.png). The Unreal level itself is still dusk until W2. The canvas street's random traffic, pedestrians and sky events are still simulated and await the Owner's call.

- delivery. backend/app/main.py serves frontend/dist through PageFiles:
- Vite's content-hashed /assets/<name>-<hash>.<ext> files are 'public, max-age=31536000, immutable';
- every other built file (index.html, icons, /assets/hq art, scene.json) is 'no-cache', revalidated with a 304;
- every /api/* answer, and anything else that set no policy, stays 'no-store'.
Tested in tests/test_delivery_cache.py. Effective after the backend restarts.

- the modules map in snapshot() was read against the code. story is now PARTIAL (it was NOT_IMPLEMENTED): the day closes, a grounded episode is written, reviewed and decided, and the runbook's serial stage takes an approved episode to a storyboard. It is not end to end: an Owner-approved episode is not storyboarded, drafts are not resumed, and there is no tomorrow's script. financing is now PARTIAL (it was NOT_IMPLEMENTED): Owner capital and Owner loans are recorded end to end, while the CEO financing flow and accruing interest are not built. procurement stays NOT_IMPLEMENTED. tests/test_foundation.py asserts both corrections.

- 2026-09-24, W3 «the first ten seconds» (frontend only). The sign-in is now a title screen standing in the studio's own world (frontend/src/title_screen.js, title_frame.js, index.html #title-stage):
- The sky is the office's own SkyRenderer at the real Bucharest sun. The Blender plates form six depth layers, composed as key art: the headquarters on the right with a band of sky above its roof, the brand and the key on the left over a veil.
- The light is the real hour. The day and night plates are crossfaded by the renderer's plateDayMix, and deep night gets its multiply grade. The sun is re-read every minute, and only the variant being shown is downloaded.
- Before the key there is no weather (the route requires the Owner), so none is drawn.
- What moves: mouse parallax of at most 14 px by depth, and the light. Nothing moves under reduced motion.
- The only controls are the key and its button. The masthead and the footer arrive with the workspace.
- A caption states the claim: 'Sediul AMN-AI, București · 19:15 · amurg, în lumina reală a orei'.
- On a key the backend accepted, and only then, the camera pushes into the building (700 ms) and the workspace arrives staggered (masthead, register, render, modules, governance, footer). 820 ms in all.
- A refused key moves nothing. Under reduced motion the workspace opens at once.
Tested:
- 208/208 frontend tests (title_frame.test.js new);
- title_w3.mjs at 1920, 1440, 1280, 2560 and 390, at 12:00, 19:15 and 23:30, with every word at 4.71:1 or better measured from pixels;
- the entry as scrubbed frames and as a real-time screencast (scratchpad ui/shots_w3);
- shoot.mjs at three sizes with 0 missing and 0 errors.

- W9 in part: type, texture and key light.
- The display face Oxanium (SIL OFL 1.1, self-hosted in frontend/public/fonts/oxanium with OFL.txt; ș ț with the comma below checked in the cmap) sets the title, the panel and dialog titles, and the hero figures. It has a metric-matched Arial fallback, and figures are tabular by default.
- The page ground has a still SVG grain (3.5%) and an edge vignette.
- The key light (--key-cool) is sampled every 2 s from the top band of the frame being shown: the stream's kept still, otherwise the page's renderer. It is clamped so --ink-3 keeps 4.5:1 over the lit ground (key_light.js, key_light.test.js).
- Plates and sprite sheets are now decoded off the main thread (hq_assets.js loadBitmap). The longest task after sign-in fell from 222 ms to 97 ms.

- 2026-09-24, W6 «data you can read at a glance» (frontend only). Four instruments draw answers the backend already gives, and nothing else (frontend/src/hud_charts.js).
- The render's slate carries the newest daily run: one segment per stage, placed by the index on runbook.stage_started, coloured green/warm/red/gold/faint. When the register has lost a finished day's events, the run record from /runbook/runs is used instead. Words beside it: 'Rularea din 12.09 · 12/12 · încheiată', or '12.09 · 12/12' on a narrower page.
- The daily-run dialog's «Flux» is six bars on one scale from company-state pipeline.stages, with waiting work in gold and losses in red. It is not drawn as a tapering funnel, because the data is not one.
- Each treasury budget has a ring: spent, then held, against the limit, with the warning tick at warn_ratio.
- Each distribution channel has one column per published film from /analytics/performance. A measured zero is a tick; an unmeasured film has no height.
- An empty series is said in words. Geometry is attributes and classes, never inline style (CSP). Nothing animates on arrival; a tracker segment recolours in 240 ms only when a real stage event changes it.
- «Acum» now agrees with the run record: a stage that started before the day's recorded finish is not running. On the copy of the database it had said 'nimic nou de 4 zile' about a finished day.
Tested: 233/233 frontend tests (hud_charts.test.js new), tsc, build, shoot.mjs at 1920/1280/2560 with 0 missing and 0 errors, and scene_w6.mjs recordings in scratchpad ui/shots_w6_scene.

- W8 «moments» (frontend/src/moments.js, film_poster.js).
- A moment plays only for an event the socket sent as it happened ({type:'event'}; EventsLink now passes the flag), whose own timestamp is under 10 minutes old, and at most once per event_id. The page-open replay, the REST backfill and a reconnect's catch-up play nothing; proven with three fresh milestones sent as replay_event.
- An episode drafted or approved puts a chapter card in the render's lower left: 'Inside The Nexus · Ep 1', the episode's title from /story/episodes, and who decided.
- A film rendered puts a toast in the lower right carrying a real frame of the film. The page streams the start of the +faststart MP4, finds a key frame at 20% of the film by parsing the MP4 index, stops reading, and decodes that one frame with WebCodecs; no <video> and no blob:. Measured about 250-290 ms after the event.
- A film published puts up a toast with its title.
- A request for the Owner re-reads the approvals, and the register's gold mark ('N cereri așteaptă decizia ta', a button to the approvals) glows once for 1.2 s. The mark itself stays up while requests wait.
- Every moment arrives in 320 ms, leaves in 240 ms and is gone within 3 s. One is up at a time. Pointer or focus holds it; the close button and Escape dismiss it; the text goes to a polite live region.
- Under reduced motion the same words stay up for the same time, with no movement.
- The register also gained words for story.episode_approved/rejected and governance.approval_requested, which it had printed as raw English keys.

- the workspace read as a whole at 1920. The masthead's Settings button was a filled green slab, the loudest object above the render. It is now the quiet outlined plate its neighbours wear, in the studio green (9.3:1). Letter subjects in the register drop from 600 to 500 weight so the column no longer reads as a wall of bold. The chapter card has no backdrop blur, because it would be recomputed every frame over the moving picture. Frame timing at 1920 with no screenshots: median 6.9 ms, no long tasks. One 42 ms frame when a chapter card appears, and up to 28 ms while a poster is decoded.

**Measured.** 236 frontend tests pass (165 before this wave), `tsc` clean, the build succeeds; the backend files of this wave pass tests/test_foundation.py and tests/test_delivery_cache.py (29 passed). Every view was photographed at 1280, 1920 and 2560 with 0 missing fixtures and 0 console errors.

**What is left for YES, from the judge.** The Unreal real-sky level on the live stream (the one
game-grade object); the render as the full-bleed hero with the register and approvals as glass
drawers; Unreal stills to replace the 2026-09-13 Blender plates, whose windows are lit at noon;
portraits of the eight employees; the canvas words in Romanian; `media-src 'self' blob:` in the
page's CSP; and the Owner's call on the canvas street's random life (traffic, pedestrians, sky
events come from a seeded generator, not from the backend).

## One icon family, and the two readouts beside the render (2026-09-23)

Active edit claim: Claude, 2026-09-23 — the product's icons, the frame-rate figure on the glass
and the heading band above the render. Done and tested.

**Why.** The seven room links under the render carried seven icons from seven places: a
two-stroke magnifier whose handle floated clear of its lens, a filled badge with a solid play
triangle, a circle crossed by a diagonal that read as *forbidden*, a person, a page, a **house**
for the daily run and a classical bank with seven strokes — twice the ink of anything beside it.
Everywhere else an icon's work was being done by a typographic character: a font's multiplication
sign for every close button, a font's arrow for refresh, a plus and a minus set at `--fs-h3`,
a filled ▶ on the play control. Three drawing systems on one page, at three weights.

**One family.** Every icon in the product is now drawn on one 24×24 grid, inside 4..20 of it, at
`--icon-stroke` (1.7 user units — 1.06 device px at the console's `--scene-icon`, 1.13 at
`--icon`), with round caps and round joins, no fill but the one dot a shape needs, and
`stroke: currentColor`, so an icon never states an ink of its own and always takes the ink of the
control it sits in — its hover, its disabled state, the alert triple on «Ieși din ecran complet».
The family is `.ui-icon` in `style.css`; the seven rooms are inline in `index.html`, the four a
script draws are in `src/icons.js` (new). Twenty-two icons, one grid.

**Two of the seven said the wrong thing.**
- **Rularea zilei** was a *house*. A daily run is a day of work, so it is the sun over the
  horizon. Not the play-in-a-circle the brief offered as the alternative: a play mark already
  means «a film» two buttons to its left, and on a dialog that only *reports* what each run did
  it would read as a Start the Owner must never press by accident.
- **Distribuție** was a compass rose inside a circle, which at 15px reads as a prohibition sign.
  It is now the film leaving the studio: the arrow rising out of the tray. The share glyph was
  built and photographed first; its three nodes turn to mush at the size it is actually drawn.

**Beside the render, two measured changes.**
1. *The frame rate is not a heading.* It was set at `--fs-meta` in `--scene-chrome-ink` — the
   same size and the same ink as the word **Live** next to it — so a figure that ticks every
   second was leading a readout whose subject is that the render is live. It keeps every word and
   takes the chrome's quiet meta treatment: `--fs-micro`, `--scene-chrome-muted`, still mono and
   still tabular. Scoped to the live readout, so the clock in the opposite corner is untouched.
   Measured at 1920×1080: the figure 11.5px/600/`#dfe7f5` → 10px/500/`#8496b8`, 40.4px wide →
   35.2px, and the readout 169px → 163.7px.
2. *The band above the render.* It carried the live badge at its right end until the badge was
   let into the glass, and what was left was a heading alone in an 83px band 1422px wide. Nothing
   was brought back to fill it: every readout this panel owns is already on the bezel — the
   clock, the weather, the live state, and on the slate the employee count and the moment it was
   read — and a second copy up here would be the page saying the same sentence twice. So the band
   was tightened instead. Its two lines were leaded for running prose (`--lh-body` gave the 10px
   eyebrow a 16px line and the 20px title a 30px one) inside 32px of padding; both now take
   `--lh-tight`, the token the type scale already names for titles and figures, and the padding
   comes to the page's own rhythm. Measured at 1920×1080: **83px → 65px**, which is where the
   register's heading and the approvals heading have always been (62px), so the page has one
   section-heading band instead of two; the render begins 18px higher.

**Nothing else changed**: no word, no behaviour, no data flow, no API call, no gate, no test
contract, no id, class, data attribute, `aria` role or test hook. The only literal added to
`style.css` is `--icon: 16px`, inside the `:root` block; a literal was *removed* from
`office_scene.css` (`stroke-width: 1.7` became the token).

**Tested.** `npm test --prefix frontend`: **164 tests, 164 pass, 0 fail** — the same 164, none
added, none changed, because no test named a glyph. `npm run check --prefix frontend`: clean.
`npm run build --prefix frontend`: succeeds. Photographed at 1920×1080 and 1280×800 against the
254 captured answers — login, workspace, the eight dialogs, the inspector, the mail window and
the seventeen deeper dialog states — **0 missing fixtures, 0 console errors** in every run, and
every icon was read at 4× and 8×. At 1280 the seven rooms still use 767.6px of a 791.6px row, to
the pixel what they used before.

**One glyph deliberately left.** The five publishing gates keep their `✓`: it is a status mark
inside a sentence, in `--ok-ink` like every other verdict on the page, not a control's icon, and
a 16px family icon set inline in 13px running text would need a third measure and a baseline
shim to sit on. Five lines to change if the Owner disagrees. The trailing `↗`, `↻` and `↓` after
a label («Deschide firul ↗», «Citește tendințele ↻», «Preia sursa ↓») are punctuation in the
studio's own voice, not icons, and were left as they are.

## The interface speaks Romanian (2026-09-23)

Active edit claim: Claude, 2026-09-23 — the frontend's user-facing strings, in two parts
(the page and the scene; then the eight dialogs, the agent inspector and the mail window).
Both parts are done and tested.

**Why.** The studio already spoke Romanian everywhere it computed a sentence: the preflight's
reasons, the day's summary, the approvals, the governance panel, the refusals. The interface's
older static text was still English, so one row read «Automatizare» above «Fact research», a
button «Randare 9:16» sat beside «Check QC», and the treasury labelled six tiles in two
languages. An independent critic called it the loudest unfinished signal on the screen: a
stranger does not read that as a bilingual product, they read it as a product where nobody
decided. The Owner's own convention decided it: **the interface speaks Romanian.**

**What changed.** Every user-facing string the frontend owns is Romanian, with full diacritics
(ă â î ș ț, comma-below), in the studio's own voice — plain, exact, short, matching the words
the backend already writes. `<html lang>` went from `en` to `ro`; the meta and og descriptions
follow. A glossary was written before the work and followed throughout
(`<scratchpad>/ui/GLOSSARY.md`): the pairs, the loanwords kept and why, and every place the
translator hesitated, with the measurement rather than the guess.

- **The page**: masthead, sign-in, the live register (including the ~90 sentences
  `describeEvent` writes and the ledger's gender-invariable verbs), the module panel, the scene
  panel and its readouts, both toolbars, the footer, the separate per-agent live window, the
  model's answer as a person reads it, and the signage the canvas draws.
- **The dialogs**: every header, one-line purpose, section heading, rail link, field label,
  placeholder, button, tab, table header and `title`/`aria-label` inside the eight dialogs, plus
  every status, intent, empty line, confirmation and error fallback that `main.js`,
  `settings.js`, `youtube_connections.js`, `mail_thread.js`, `agent_details.js` and
  `provider_production.js` write themselves.

**Two things the critic named, both now answered.**
1. The research form had three inputs described only by a placeholder — which disappears the
   moment a word is typed — and a fourth box holding the word `general` with nothing above it.
   The four controls now carry visible Romanian labels taken from what each control already
   said: **Titlul episodului · Subiectul factual · Unghiul · Publicul**. The markup reuses
   `.yt-field` / `.yt-field-label`, the field-label pair the stylesheet already defines for the
   YouTube form, so no rule and no literal was added.
2. The publishing gate card quoted an internal architecture filename. It now says the same
   thing without naming a file the Owner does not open: «Aceste verificări nu sunt încă
   implementate: drepturile pe pachetul final, politica platformei, …».

**What was deliberately left alone.** Values are not labels: the brand, the employees' names and
role names as the data gives them, units and codes (`VR$`, `USD`, `fps`, `9:16`, `QC`, `UUID`,
`API`, `OAuth`), enum values (`IDLE`, `SUPPORTED`, `PASSED`, `SINGLE`, `PRODUCTION`), Google's own
field names on the YouTube form, and every sentence that arrives from the backend — those are
already Romanian and are not the interface's to reword. Loanwords Romanian technical speech
actually uses were kept and are listed in the glossary (`live`, `storyboard`, `prompt`, `token`,
`slot`, `watchdog`, `showrunner`, `analytics`).

**A defect found by reading the photographs, not the code.** The panels printed the plural
against every figure, so the closed day of 2026-09-12 read «1 evenimente de povestit» beside
«92 evenimente». `main.js` now has `countLabel(count, one, many)`: one is singular, and a
numeral takes «de» when its last two digits are 00 or 20 and above — «19 evenimente», «92 de
evenimente», «101 evenimente». It is applied to the day's counts, the episode's beats and cited
events, a script's claims and scenes, an employee's runs and a provider's ledger records.

**Nothing else changed**: no behaviour, no data flow, no API call, no gate, no test contract,
and `style.css` was not touched — no colour, size, radius, shadow or duration literal was added
anywhere.

**Tested.** `npm test --prefix frontend`: **164 tests, 164 pass, 0 fail** — the same 164 as
before; no test was added or removed, and forty-four assertions that named an English word were
updated in the same breath (`ledger`, `ledger_fold`, `live_window`, `friendly_text`,
`day_outcome`, `hq_world`, `hq_stream_lifecycle`, `mail_thread`, `agent_details`).
`npm run check --prefix frontend`: clean. `npm run build --prefix frontend`: succeeds.
Every view was photographed at 1920×1080 and 1280×800 against the 254 captured answers and read
back — login, workspace, the eight dialogs, the agent inspector, the mail window, and the dialog
states the plain shooter cannot reach (the second tab of Settings and of Media, every rail
section of Research, the daily run and the Treasury): **0 missing fixtures, 0 console errors**
in every run, and no Romanian word overflowed the button, tab row or table header it was put in.

**Still English, and not the frontend's to fix.** The rendered city backdrop and the HQ building
plate carry baked-in signage (`BUCHAREST AI DISTRICT`, the floor plates `L4 EXECUTIVE` … `S3 AI
SPACE`): pixels in the art, an `art-source/blender/hq` job and a re-bake, not started. The
bus-shelter posters in `hq_world.js` were kept in English as the studio's own brand and channel
advertising inside the depicted world — one line each to change if the Owner wants them
Romanian. And the backend's own Romanian sentences still point at «Settings» by its English
name while the page's button now says «Setări»; that is one line in the backend's own pass.

## The interface, brought to a finish (2026-09-22/23)

The Owner asked for the interface to be finished «la un nivel extrem de bun cu detalii și
polisare, realism și profesionalism, ca jocurile moderne din 2026 AAA». What stood before: a
light, warm-paper administration page with a black-green top bar, a photoreal night render pasted
in the middle of it, and eight dialogs that were white sheets of dense prose. Nothing about the
studio's behaviour changed in this work: no user-facing string, no Romanian wording, no data flow,
no API call and no gate.

**How the interface was seen at all.** The Owner's studio was not running, so a harness was built
that opens the real page without it (`<scratchpad>/ui/`): `capture_fixtures.py` copies
`data/studio.db` (plus `-wal` and `-shm`), blanks every encrypted column in the copy under a key
made for it, builds the application against the copy with the worker and the catalogue refresh off
behind a loopback-only network guard, and writes **254 captured answers** — one JSON per read-only
route, including the detail views. `shoot.mjs` then serves the built page, answers every
`/api/v1` request from those files, replays his real events over a stubbed websocket, and
photographs eleven views (login, workspace, the eight dialogs, the agent inspector) plus the mail
thread at any width. No provider, no network, no cost, and the live database is never opened.

**Three directions were built, not one.** Three designers each restyled the real code in their own
worktree and photographed it: A, one continuous dark ground with the render as the only heavy
object; B, a warm broadcast charcoal; C, the best possible light room. A judge looked at every
picture and chose **A**, with named grafts from C (the wide page spread, the two-tier scene
console, the chip scale, the figure treatment, the section-head rule) and from B (the dialog rail,
the row rhythm, the storyboard card header), and wrote the specification the build followed
(`<scratchpad>/ui/SPEC.md`).

**What the Owner will see.**
- **One dark ground, and the render is the hero.** The page is a single near-black surface with a
  fixed key light where the 3D window sits; the render carries the only deep well shadow on the
  page. The top bar is a deep green band with the brand on a pale plate.
- **The ledger reads at a glance.** A 54 px time rail in tabular mono figures, the subject in ink
  and the detail beneath it, a colour rail at the row edge for the kind, correspondence on its own
  rail with its way into the thread — and **seventeen identical watchdog rows folded into one**,
  carrying ×17 and the span they cover. Nothing is dropped and correspondence never folds.
- **The daily run is a dashboard**, not six stacked bars: small-caps label, one promoted figure,
  supporting lines in tabular figures, and the tiles of a row close on one edge.
- **Every dialog has one shell**: a header that does not move, a body that scrolls on its own, a
  104-character measure on prose; the three long ones (media, daily run, treasury) have a sticky
  rail of section links that follows the reading (`frontend/src/dialog_rail.js`).
- **The page has no dead area** at 1280, 1440, 1920 or 2560: above 1560 px the register stands
  full height on the left with the render and the two panels beside it, and between 1051 and
  1559 px the same cure with one column fewer.
- **The detail**: one type scale of eight sizes, tabular figures everywhere by default, four
  visibly different button states, one tag system, one shape for every empty, loading and error
  state (keeping the product's own words), dialogs that arrive and leave in 160–200 ms, a new
  ledger row lit once, and exactly one looping animation on the page (the live dot).

**Measured, by the parts that measured them.**
- The architecture part: no horizontal overflow at 1024, 1280, 1440, 1920 or 2560; the register
  equals the grid's height exactly; the filter chips sit on one line with a true 32 px hit box.
- The dialog part: the header's y is identical before and after the body is scrolled on all eight
  dialogs at 1920 and 1440; zero controls under 32 px; worst contrast pair 4.86:1.
- The finishing part: exactly eight font sizes in use at four widths; 308 places with shifting
  figures before, 0 after; 0 heading widows; one infinite animation; `--ink-3` lifted to `#8a98b2`
  after it measured 4.47:1 on the ground a hovered ledger row wears.
- The adversarial part: **655 contrast pairs per width** measured from the running page at 1280,
  1920 and 2560 — 4 failures before it started, **0 after**; worst pair now 5.59:1. A real Tab walk
  over 10 + 34 + 12×8 stops: no invisible focus, no trap, Escape closes all eight dialogs and
  returns focus to the button that opened each. `report.json`: **0 missing fixtures and 0 console
  errors** on every view at every width.
- Tests: **143 frontend tests pass** (125 before), `tsc` clean, the build succeeds. Seven of the
  new tests are the ledger fold, which changes *what* is on screen and had none.

**Not finished, honestly.**
- *Corrected 2026-09-23 by the polishing pass:* the research dialog has the rail. What stood
  here: it was the longest in the product and the only long one without one.
- The login page's gold line breaks the rule that gold is rationed to what is live or waiting for
  the Owner; it is the only accent on that screen and the call is the Owner's.
- The ledger's internal scroll always ends on a clipped half-row.
- The Governance panel carries 180–250 px of empty ground at 1920 and above.
- The thin scrollbar the stylesheet asks for is unverified: this harness's browser hides
  scrollbars entirely, so no photograph in any pass shows one.
- Everything was photographed over the page's own canvas renderer. **The interface has not been
  seen over the live Unreal stream**, which by this project's standard leaves that a guess.
- *Corrected 2026-09-23 by the polishing pass:* the «Live window» is on the new palette, with a
  test that catches a token drift. What stood here: it still carried the old light palette,
  written into the file as literals.
- `frontend/dist` in the repository is rebuilt, but the Owner still has to restart his studio to
  serve it.

### The polishing pass — 2026-09-23

Four of the five gaps the section above left open are closed, and an adversary measured the result
twice by two independent methods.

- **The per-agent «Live window» is on the new palette.** `frontend/src/live_window.js` builds a
  separate popup document and cannot import the page's stylesheet, so its token block is a copy of
  the one in `style.css`, with a comment saying why it is duplicated and that the two must move
  together — and a test (`frontend/tests/hq_palette.test.js`) that fails when a token drifts,
  because a drift is invisible in a browser.
- **The research dialog has the section rail** the other three long dialogs have: five links that
  repeat its own headings, on the wrappers that already existed.
- **The sign-in screen** stands in the product's own world: the headquarters plate behind the card
  under four named veils, the brand artwork on a deliberate printed badge, the gold eyebrow removed
  (gold is rationed to what is live or waits for the Owner), and the Settings button hidden until
  the key is accepted, by reading the `hidden` attribute the page already keeps.
- **The chrome around the render is one instrument family.** Three readouts (clock and weather, the
  live state, the slate) are let into the bezel — square where they meet the frame, rounded only
  towards the picture — and the console's two tiers now start and end on the same margins, with the
  camera as one grouped instrument. Every word each readout said, it still says.
- **The scene answers the pointer and the keyboard.** Selection and hover marks are drawn at a
  constant size *on screen*, so they read at fit zoom as at 4×, in the page's own focus colour and
  geometry; the canvas takes focus, the arrows walk the seats in the renderer's own order, Enter
  selects and Escape clears. The renderer's interface colours come from the page's tokens
  (`frontend/src/hq_palette.js`, new); the art is untouched.
- **What the scene says when it has nothing** — loading, failure, reconnecting, starting — uses the
  product's own sentences in the page's empty/loading/error shapes, as elements with `role=status`
  rather than grey text painted on the canvas.

**Measured on the final build.** 2 853 text/ground pairs read from the *real pixels* of 22 views at
1280, 1920 and 2560 — 0 below threshold, worst 5.28:1 — and the cascade-based sweep agreeing at
671 pairs per width. 84 pairs over the render and 14 in the popup, all passing. A real Tab walk at
1920 and 1280 over the sign-in screen, the workspace and all eight dialogs: no invisible focus, no
trap, no ring under 3:1. `report.json`: 0 missing fixtures and 0 console errors at four widths.
**146 frontend tests pass**, `tsc` clean, the build succeeds.

**Seven defects the adversary found and fixed**, each measured before it was touched: the autonomy
mode the studio is *in* was painted darker and fainter than the modes it is not in (1.05:1 plate,
now the studio's green at 6.54:1); the page's key light had never once reached the screen, because
`body` repainted the ground over it; four fields' placeholder sentences were written and invisible
(1.1:1); the «NICIUNA» tag floated in the middle of the approvals heading; the Governance panel
carried 175px of dead ground; the storyboard's text well cut its seventh line through the middle of
the letters, in five cards at once; and the Settings dialog was the only one whose head rule was
drawn between the title and its own sentence.

**Still not finished, honestly.** 447 of 574 control borders measure under 3:1 — the ghost-control
language the scene pass introduced deliberately, and a whole-surface decision rather than a small
fix (WCAG does not require a boundary for a control whose label is visible). Moving the live badge
onto the glass left the «Studio Office» heading alone in a wide empty band, and what belongs there
must be a word the product already owns — the Owner's call. The two corner readouts cover 440px of
the render's top edge that was whole before. At 1280×800 the sign-in card leaves no room for the
footer on the first screen. The research rail's column is empty below its five links. And the
interface has still never been photographed over the live Unreal stream.

### Closing the critic's list — 2026-09-23

A stranger read the thirteen views at four widths and ranked twenty findings. Eleven are closed in
the view layer and the stylesheet; nine are refused, and the reason for each is written below so the
Owner can check it rather than take it. **Not one user-facing word was added, removed or reworded,
and the 3D art was not touched.**

**Closed.**

- **A row printed its own sentence twice.** Ten consecutive ledger rows read
  `publish: COMPLETED — <sentence>` in bold and `<sentence>` again in grey beneath, because a
  letter's excerpt is usually the whole of its subject after the colon. `withoutEcho()` in
  `frontend/src/ledger.js` drops a detail that is already the end of the headline; the mail window
  does the same for a letter's body (`mail_thread.js`), and because the rule lives in
  `describeEvent`, the per-agent Live window stopped joining the two copies with an em dash as
  well. A letter with genuinely no text still says so; only an echo is dropped. The ×17 fold is
  untouched.
- **The Daily Run tiles.** `align-items` on `#company-state` is back to `start`. This is the second
  time the line has moved and the stylesheet now records both measurements: filling the row bought
  a flush bottom edge with 168px of empty ground *inside* the AGENTS tile at 1920 and 120px inside
  AUTONOMY IS ON at 1280, because the row took its height from a third tile whose data repeats a
  paragraph. Empty ground inside a card reads as an unfinished card; a ragged edge between cards of
  different length reads as cards of different length.
- **The agent inspector's two columns never matched** — the right one stopped 220px short of the
  left at 1920 and left a wholly empty column beside the last block at 2560. `.identity-grid` flows
  the six blocks as CSS columns with `break-inside: avoid`, so a short block is followed by the next
  block. Three columns above 1900px. Nothing is reordered.
- **The long dialogs' rails** painted a 208px column of lit ground the full height of the report —
  in Media, two links above 780px of it. The ground and the hairline move onto `.dialog-rail`
  itself, which is `align-self: start` and sticky: the rail is now a card as tall as its links.
- **The module-status meters read backwards.** Each row is its own grid, so the longest status word
  pulled its own meter left and the modules that are *not* built drew a bar further along than the
  ones half built. `--module-state-w` fixes the status column, so all three states draw one track at
  one x and one width, filled 100 / 50 / 0.
- **The eight dialogs did not share a top edge** — Story opened 60px lower, Settings 230px and Mail
  245px, so the close button moved halfway down the screen depending on the door. Every dialog is
  pinned to `--dialog-top` (5vh), the offset the other seven already used. Settings also gives up
  its own 1000px cap and joins the family width.
- **A wide screen bought margin, not content.** `--dialog-w` steps from 1180px to 1440px above
  1900px and the inspector's contract flows in three columns there. The treasury's six tiles are
  capped at three columns so the most finished component in the product stays three and three
  rather than four and two.
- **Inner scrollers ended by slicing a line of type through the middle of its letters.** The
  ledger, the topic lists, the agent list and the chat history fade over one line-height at the
  bottom lip, driven by the scroller's own position: no fade on a list that does not scroll, and
  none once the reader reaches the end. Measured: ledger 21px of fade at rest, 0px at
  `scrollTop === max`, 0px on every list whose `scrollHeight === clientHeight`. Where a browser has
  no scroll timeline the rule does not apply at all.
- **A connection card was titled with a machine identifier** — `settings:9298e62d-…-64120311942a`
  wrapping to two lines in the biggest type on the card, beside two cards titled `local-ollama` and
  `Ollama Cloud`. Every character is kept: the word before the identifier takes the title, the whole
  string is printed as the card's meta line in the mono face every identifier wears, and the
  untruncated value is on hover.
- **The live badge claimed a picture that was not there.** While the viewport shows its loading or
  error plate, the badge in the opposite corner went on reading `Live Renderer 68fps` over a frame
  whose only other content was "The headquarters art could not be loaded." One `:has()` rule hides
  it for exactly as long as a plate is up.
- **«Fullscreen» did not look like a control at rest** beside a bordered, filled group of four. It
  is the last key of the same instrument and now wears the same plate. The slate's stamp also joins
  the bezel's other figures on a fixed advance.
- **The per-agent Live window** pinned its caption to the floor 430px under three entries. The
  window is a column now and the caption follows the content. Its palette was already the page's
  (`--ink-2` body, `--ink-3` rail, measured 6.39:1); the "cyan" the critic read is an artefact of a
  downscaled capture.

**Refused, and why.**

- **Two display languages in one row** (Module status, the publishing channel row, the six treasury
  captions, the inspector's fourth caption). Every candidate fix is a string change. It is the
  loudest unfinished signal on the screen and it needs one decision from the Owner about which
  language the interface speaks; presentation must not paper over it by inventing words.
- **The `.md` filename, the `.env` sentence, the three unlabelled research fields and the box
  pre-filled with `general`.** All four want words the form does not own as labels (the only names
  those fields have are placeholder *examples*). Owner's call.
- **The Governance dead ground.** The empty plate is centred in its region on purpose, recorded in
  the sheet with the alternative already tried and rejected. The panel is stretched to Module
  status beside it, so pinning the plate under the head rule would not remove the emptiness — it
  would gather all ~200px of it under the note instead of splitting it. Moving a void is not
  closing it.
- **The storyboard prompt well.** A fade mask there was tried in an earlier pass and rejected by a
  judge; the well is sized so the cut lands *between* lines rather than through letters, and an
  "expand" affordance would be a new control with a new word.
- **The numeric fps.** Hiding the badge over a failed frame is a fault fixed. Hiding the figure
  itself is not: it is the Owner's own measurement of his renderer, and the studio's standing rule
  is that nothing in the office view is decoration. Collected for him.
- **The seven room icons.** Two of them do mean the wrong thing (a house for Daily Run, a slashed
  circle for Distribution) and two are drawn at a different weight. Redrawing them is new art.
- **The three-weight button system and Pause/Resume.** The ghost-control language is a whole-surface
  decision the record already names; hiding whichever of Pause/Resume does not apply is a change in
  behaviour, not in presentation.
- **The sign-in brand plate and the «Not connected» chip.** `--plate` is a named token and the mark
  is dark-on-light by design; dulling it is brand. The chip is a true state readout.
- **The «Studio Office» band and the three clocks.** Both need a word the product must already own,
  in a place the Owner chooses.

**Measured on this build.** `report.json`: 0 missing fixtures and 0 console errors at 1280×800,
1440×900, 1920×1080 and 2560×1440. 673 text/ground pairs read from the real pixels of 20 views —
**0 below threshold**, worst 5.73:1. **146 frontend tests pass**, `tsc` clean, the build succeeds.
Pictures: `scratchpad/ui/shots_p7_final/` (four widths), `shots_live_p7/`, `shots_scene_p7/`.

## The rehearsal on the Owner's data (2026-09-18)

The suite was green and the studio had never been tried on the one database that matters. On
2026-09-18 a rehearsal ran one whole scheduled day on a **copy** of the Owner's own studio, through
the real scheduler, worker and runbook (`set_job_active`, `scheduler_tick`, `worker_pass`,
`execute_daily_run` with `build_stage_runners`), with every paid vendor faked and every outside
connection refused; an independent audit then read its report, re-ran it on a fresh copy and named
what it had missed. The audit's verdict was **FIX_FIRST**. This section records what the rehearsal
ran on and why nothing could be spent, every finding of the report and of the audit in their four
classes, and what the four parts that followed fixed. The report and the audit are
`rehearsal_report.txt` and `rehearsal_audit.txt` in the session's scratchpad; the repeatable harness
is `tests/test_rehearsal_on_a_copy.py`, skipped unless `STUDIO_REHEARSAL_DB` names a copy.

**What it ran on.** `data/studio.db` (11,902,976 B), its `-wal` (263,712 B) and its `-shm`
(32,768 B) were copied together with `shutil.copy2` into the scratchpad at about 19:44 UTC, and
sqlite was opened on the copy only (`wal_checkpoint(TRUNCATE)`, `integrity_check` ok). The
credential key was copied beside each copy, because the preflight's media description and the
analytics adapter decrypt integration rows; no key or secret was printed. The copy was already at
`0045_reconciliation`, not at the 0035 the brief assumed: the Owner had restarted his studio himself
at 22:42 local, and `start.py` runs `bootstrap.py` first, so step 1 of his checklist was done by his
own hand before the copy was taken. What the copy holds: eight employees, all on Ollama Cloud; three
VERIFIED integrations (ollama, elevenlabs, runway); both channel slots bound to his CONNECTED
accounts — *Nexus Curiosity* → MAIN_FACTUAL (`youtube_connection` 69cb4598) and *Inside The Nexus*
→ OFFICE_SERIAL (241dfcf5); 98 SUPPORTED, 11 UNVERIFIED and 1 REFUTED claims; 18 daily runs, all of
2026-09-12; a DAILY budget of 15 USD; TEST, AUTONOMOUS_CEO, the stop off, `daily_main` inactive.

**Why nothing could be spent.** Three measures, and the second held where the first did not.
Every paid vendor was faked in the process at the boundaries the whole-day test fakes — one
stand-in model registered under all three provider ids of the copy, the local picture and voice
adapters, the plain render plan, and a recording publisher in place of `stages.selected_youtube`. A
network guard was installed before any studio code was imported and proved itself first; it refused
`connect`, `connect_ex`, `getaddrinfo`, `gethostbyname(_ex)` and asyncio's proactor and selector
`sock_connect` for anything but loopback. And the settings were built with `_env_file=None`, every
`STUDIO_*` variable removed, the worker, the catalogue refresh and trends off, and render storage
moved into the scratchpad. What the rehearsal changed, it changed on copies only and with the
Owner's own commands: `daily_main` activated through `set_job_active` with its `next_run_at` moved
into the past, and `director_may_approve_episodes` granted on OFFICE_SERIAL through
`change_publish_policy` (policy version 1 → 2). The guard's record is the proof: no refusal through
migration, start-up and preflight — the preflight really calls nothing; 4 in pass 1, all
`getaddrinfo 'oauth2.googleapis.com'`; 109 in pass 1b, where the analytics adapter was faked as well
— `api.dev.runwayml.com` ×24, `api.elevenlabs.io` ×12, 33 authorised hosts once each, and
`en.wikipedia.org` and `ro.wikipedia.org` ×20 each. **The only paid path the guard stopped was
Runway's text-to-video in pass 1b, four shots** — about 0.88 USD at catalogue prices, at most
1.20 USD; everything else it refused was a free read. The audit confirmed both halves on its own:
nothing left the machine, and the live files were not touched by the rehearsal — they changed at
22:55:14, when the Owner restarted his studio again from a PyCharm terminal; its read-only copy of
them holds no rehearsal artefact (no run of 2026-09-18, no `sim:` publication, the serial's leave and
the clock unchanged); and the harness, pointed at `data/studio.db`, refused at setup in 0.09 s with
the live files' sizes and times identical before and after.

**What the day said, stage by stage.** Pass 1 used only the whole-day test's fakes; pass 1b faked the
analytics adapter as well, on a fresh copy of the migrated state. The reasons are the studio's own.

| Stage | Pass 1 | Pass 1b |
|---|---|---|
| preflight | COMPLETED, DEGRADED: «Studioul poate rula, dar unele etape vor fi sărite sau vor produce rezultate nepublicabile.» | the same |
| performance_intake | FAILED after 4 attempts over 140.1 s: «URLError: <urlopen error [Errno 11001] rehearsal guard: DNS for 'oauth2.googleapis.com' refused>» | «0 publicări măsurate pe 2 canale. 2 fără date.» |
| idea_generation | BLOCKED: «Rularea s-a oprit la etapa «performance_intake».» | «Propunerile au fost respinse: Propunerile nu respectă schema; nimic nu a fost salvat» |
| research_and_verification | BLOCKED, the same reason | «0 pagini preluate, 0 surse citite, 0 afirmații verificate, 11 verdicte respinse. 33 site-uri retestate (0 citibile).» |
| selection | BLOCKED, the same reason | «Subiect selectat: Why Nepal Is Being Handed a Climate Bill It Cannot Pay.» |
| script_and_storyboard | BLOCKED, the same reason | «1 scenarii scrise în 1 schimburi, 1 aprobate de Director, 1 storyboard-uri generate. 4 cadre descrise complet. Recenzia poveștii: PASS. Un scenariu așteaptă aprobarea ta înainte de storyboard.» |
| serial_queue | BLOCKED, the same reason | «Episodul pentru 2026-09-17 a fost scris, citit, aprobat și pregătit de filmare.» |
| media | BLOCKED, the same reason | «2 videoclipuri randate. Episodul serialului a fost filmat.» |
| edit_and_qc | BLOCKED, the same reason | «2 au trecut QC, 0 au picat.» |
| publish | BLOCKED, the same reason | «Publicat pe Main Channel A - Factual Shorts: PUBLISHED_SIMULATED (private). Publicat pe Channel B - Office Serial: PUBLISHED_SIMULATED (private).» |
| post_run | BLOCKED, the same reason | «10 rapoarte depuse; revizuirea Directorului a fost respinsă: modelul kimi-k3 a scris 184 caractere de analiză și nu a ajuns la decizii; a doua încercare, 184 caractere, tot fără obiect.» |
| daily_log | «Jurnalul zilei 2026-09-18 a fost închis.» | the same |
| the run | FAILED, 2 of 12, a re-attempt queued for 20:24 UTC | COMPLETED 12/12 (run 96b08fd8) |

**Found: two defects.** *One statistics read stopped the day before anything was filmed.* The Google
token refresh in the analytics adapter (`providers/youtube_analytics.py:124`, a `urlopen` outside
the `try` its report had) raised a `URLError`, the stage caught only `MetricsUnavailable`
(`analytics/services.py:296-300`), and the runbook blocked every stage after any failed one; the
re-attempt queued thirty minutes on would have met the same wall. The audit found it worse than
reported: `classify_fault` reads an HTTP 4xx from Google — `invalid_grant`, or a 403 from the
Analytics API — as HARD (measured on both), and a HARD fault in any stage opened safe mode and set
AUTONOMIE OPRITĂ, so **one expired read-only token would have halted the studio until he cleared
it**. His MAIN_FACTUAL slot has two PUBLISHED films with remote ids, so every real day asks Google
first; the whole-day test never met this, because its publications are simulated and carry none.
*The books charged motion that was never generated.* Pass 1b wrote four Runway cost rows, ESTIMATED
and `failed=0` — 0.204 + 0.306 + 0.372 + 0.558 = **1.44 USD** — for shots whose render record says
«api.dev.runwayml.com could not be reached (after 3 attempts)», with no bytes and no credits, and
settled both films' holds (1.30472 and 1.36104 USD) against them. `_priced_scene_costs`
(`economy/accountant.py:184-193`) priced every motion record by its `asked_seconds` whatever became
of the shot, and the price gate's own refusals (`media/assembler.py:1197-1223`) have the same shape,
so on a paid day every shot refused by the 0.60 USD film ceiling or the 0.12 USD-per-second ceiling
would also have been charged against the 15 USD budget.

**Found: the limits of the fakes.** *Two boundaries were not faked:* with the whole-day test's fakes
only, the media stage chose Runway `seedance2_mini` (HERO) and `seedance2_fast` for scenes 1-2 of
each film and made four paid `text_to_video` attempts, three tries each, which only the guard stopped
(four `model_outcome` rows, accepted=0, TECHNICAL, were written on the copy); and the analytics
adapter was not faked, so the harness as first written never went past stage 2 on his data. *Free
vendor reads were refused, not faked:* the Runway and ElevenLabs balance reads
(`economy/credits.py:29`), the host retests (`research/service.py:281`), the Wikipedia searches
(`:543`) and the watchdog's own publisher resolver (`workflows/watchdog.py:175`, which imports
`selected_youtube` from `integrations.services` and is not reached by the stages fake). All were best
effort; on the copy, 34 of the 36 hosts now read FAILED (16 before) purely because of the guard.
*The stand-in's content passed every reviewer:* selection chose his real Nepal topic, and the
stand-in's JWST script «The light your eyes were not built for», citing the Nepal claim 0be61855,
passed the factual gate, the story review, the Director and editorial review; the serial's upload
carried the factual film's metadata («Infrared light and what it shows», tags space/astronomy).
*The picture and character gates were not exercised:* both read NOT_APPLICABLE — «Kael (Video
Editor) gave no usable verdict on the pictures (SUCCEEDED)» — and quality control still scored 1.0
PASSED; if his real vision model answers in prose, films pass that gate unseen. *Stages reported
COMPLETED that did no work* — the audit's finding, which the report had not counted: ideas refused
on schema, research that verified nothing, a Director review with no decisions and the Accountant's
line SKIPPED («books: SKIPPED — Raportul contabil nu respectă schema»), under a run that read
COMPLETED 12/12. *Whether his real refresh tokens still work is unknown:* a rehearsal cannot refresh
a token without leaving the machine.

**Found: what only the Owner can change.** Both YouTube connections read green in the preflight
(«2 sloturi de canal legate de conturi YouTube conectate.», «Canal YouTube conectat prin OAuth.»)
from their stored status alone; their `granted_scopes` hold `youtube.readonly` and `youtube.upload`
and not the `yt-analytics.readonly` the analytics adapter names; and both were connected on
2026-09-11, so if his Google OAuth app is in Testing mode their seven-day refresh tokens end about
now. Six Ollama Cloud models have no token price («Modele fără preț pe jetoane la: ollama. …»), the
only DEGRADING failure of his preflight, so every employee's run is booked without a cost. The voice
is priced at the DOCUMENTED Creator-plan figure for every model («*», 0.22 USD per 1k characters)
while his model is `eleven_flash_v2`, which the same price list bills at half — the audit's
finding. No character has a reference picture («8 personaje fără imagine de referință: …»); a set is
40 images, about 0.80 USD, a cost the preflight's message does not name. The Director may not
approve serial episodes («Canalul serialului este legat, dar Directoarea nu are dreptul să aprobe
episoade: …») and the daily clock is off, both still so on the live data. The mode (AUTONOMOUS_CEO)
and the environment (TEST) are the values the migrations wrote — 0043's and 0031's defaults — and
the rehearsal found no choice of his behind either; the preflight states the mode as a fact without
saying it was a default. 29 scripts of 2026-09-12 stand
VERIFIED_PASS and wait for his approval, and every day repeats «Un scenariu așteaptă aprobarea ta
înainte de storyboard.» about them. In PRODUCTION his 15 USD daily budget and the 12 USD per-film
motion hold leave room for one film, not two — the audit's finding: after the first film settles at
X, the second is refused whenever X + 12.1 > 15, that is whenever X is above about 2.9 USD. Each of
these is now a dated line in «Ce are Owner-ul de făcut» below, in the step it belongs to.

**Found: what worked as designed.** The migration and the seeds are clean on his data. On a copy of
his own backup of 2026-09-12 (at `0029_editorial_review`) the chain ran one revision at a time, 0036
to 0045 in 0.04-0.06 s each, with no warning, no pre-existing cell changed in any table and
`foreign_key_check` empty; bootstrap run again on the live copy changed zero rows; the only change
of meaning is the one 0043 documents, the mode. The app started through its lifespan in 0.317 s,
`/health/ready` answered 200 and the preflight read DEGRADED. With analytics faked too, the day ran
to its end: a factual short and a serial episode grounded in 3 of the 79 events of his real
2026-09-17 log (episode 0b81435e, 52.8 s; grounding, privacy, length and cast passed; approved by
the Director), rendered at 38.4 s and 54.6 s, 1080×1920, captions burnt in, quality control PASSED,
both uploaded private to the simulator, each to its own slot, with no video on any platform; and the
11 re-verdicts on his UNVERIFIED claims were refused because the stand-in's quote is not in their
sources, which is the gate working on real sources.

**Fixed: a failed stage costs its dependants and nothing else.** `YouTubeAnalyticsProvider` turns a
transport or authentication failure — on the token refresh or on the report — into
`MetricsUnavailable` (moved into `providers/youtube_analytics.py`, re-exported by
`analytics.services`), which carries `during`, `auth_refused`, `error_class`, `http_status` and
Google's short `oauth_error` word and never a token. `measure_channel_publications` then records
every publication left as «fără date» with one reason instead of asking Google again, names the
account and the slot and says to press Reconectează, and writes one `youtube.token_refresh_failed`
or `youtube.analytics_refused` ledger event for the preflight. The runbook has `STAGE_PREREQUISITES`
beside `STAGES` (the table, and where each edge comes from, are in `39_DAILY_AUTONOMOUS_RUNBOOK`
§*Abort behavior* and in the decision log): a stage is BLOCKED only when every prerequisite it lists
was lost, with «Nu a fost încercată: etapa de care depinde, «X», a eșuat.» and the root fault named;
the Owner's stop and a blocked preflight still block everything. Safe mode opens only for a P0 as
`21_FAILURE_RECOVERY_PLAYBOOK` defines it — a HARD fault in media, publish or the day's log, or a
database integrity error anywhere (`SAFE_MODE_STAGES`); any other HARD fault costs its stage, its
dependants and one letter from the Director. The same-day re-attempt follows only a transient fault
that cost the day's films (`PRODUCTION_STAGES`), and a day whose films went through while another
stage failed is PARTIAL, which the clock reads as done. Every stage record carries `produced`,
counted from the artefacts its runner already returns, and the run returns a Romanian `summary` and
`stages_productive` — «10 din 10 etape au rulat până la capăt; 7 au produs ceva. Fără rezultat:
«…». Filme publicate: 2.», or «Ziua nu a produs nimic.» — so 12/12 no longer stands for a day that
made nothing. **Fixed: the books charge what was bought.** `motion_was_bought` — `bytes` or
`paid_but_lost`, the only two shapes in which the assembler also records credits — decides whether a
shot is charged, in the finished-render and the lost-render books alike, and a refused shot no
longer teaches a measured price; a film whose every shot was refused settles its hold against its
stills and narration only. The seed adds two DOCUMENTED families, `eleven_flash_*` and
`eleven_turbo_*` at 0.11 USD per 1k characters — the already-cited Creator figure at the half credit
per character the same price list states — and `price_row` ranks any price the Owner typed above
every documented one, then the most specific match. **Fixed: every paid path is faked, and a scan
checks the list.** The suite's autouse guard in `tests/conftest.py` now refuses DNS for anything but
loopback and asyncio's `sock_connect` as well — a new test caught a real ConnectEx attempt to
192.0.2.1 on Windows before the change — and records every refusal. The whole-day test and the
rehearsal share one list of eight fakes (`VENDOR_FAKES`, `install_vendor_fakes`), among them the
motion chooser, which keeps the studio's own `choose_model` decision and replaces only the vendor,
and the analytics adapter. `tests/test_no_paid_path_escapes.py` walks the call graph from
`execute_daily_run` and `build_stage_runners` and fails on any paid adapter reachable without a fake;
against the list as it stood before, it named exactly five sites — the four the rehearsal met and
`verified_search_provider` → `SearchProvider`, which it never did. **Fixed: the preflight says what
will stop tomorrow.** «Canal YouTube conectat» and «2 sloturi legate» now say they read the stored
state; `youtube_upload_access` (BLOCKING) fails on a missing `youtube.upload` or a standing token
refusal, and `youtube_statistics_access` (DEGRADING) on a missing `yt-analytics.readonly` or a
standing refusal, both giving each grant's age with the Testing-mode caveat and neither counting an
unrecorded scope or a failure Google never answered as a refusal; `daily_budget_films` asks the media
stage's own `estimate_film_cost_micros` whether the DAILY budget holds the day's films; and the
summary names the first check that would stop the day or lose a film (`first_stop`) instead of
«Studioul poate rula». On a fresh copy of his copy the preflight now reads DEGRADED: statistics fail
for Nexus Curiosity and Inside The Nexus («fără yt-analytics.readonly»), upload passes with both
grants seven days old and «tokenul poate fi deja expirat», and the budget line is INFORMATIONAL —
15 USD holds two TEST films at 1.2 USD each, while in PRODUCTION 2 × 12 = 24 USD and the serial is
refused once the short costs more than 3 USD.

**One real day, estimated.** The audit's `paid_run_estimate`, priced from the copy's own data, for a
day in TEST (two motion shots per film, a 0.60 USD motion ceiling per film, at most 0.12 USD a
second, private upload): Runway motion with `seedance2_mini` at 0.02 USD/s (HERO) and
`seedance2_fast` at 0.03 USD/s — at the rehearsal's shot lengths film 1 is 0.204 + 0.306 = 0.51 USD
and film 2 is 0.372 USD, its second shot (0.558) refused because only 0.228 of its ceiling is left:
about **0.88 USD**, with a hard ceiling of 1.20 USD a day; stills with `gen4_image` at 0.02 USD each,
7 scenes, **0.14 USD** plus any retry; narration of the rehearsal's 476 + 732 = 1,208 characters,
**0.27 USD** at the DOCUMENTED 0.22 per 1k and about 0.13 USD at the Flash half, and 0.19-0.37 USD
for the 800-900 characters a real film more likely has; YouTube, Analytics and research fetches
0 USD (quota only). **Total known vendor spend: about 1.1-1.3 USD, at most about 1.7 USD**, against
film holds of 1.30 and 1.36 USD and a 15 USD budget. In PRODUCTION (motion on every scene,
image-to-video, a film ceiling of min(12 USD, what the day has left), the cheapest model that reaches
quality at 0.05-0.08 USD/s): 2-4.4 USD of motion per 40-55 s film, plus about 0.07 USD of stills and
0.1-0.2 USD of voice, about 2.3-4.7 USD a film and 4.5-9 USD a day under the 15 USD cap — except that
each film holds 12 USD, so the second is refused whenever the first spent more than about 2.9 USD,
and a typical PRODUCTION day is one film at about 2.5-4.5 USD. **Unknown, and said so:** the language
models — Ollama Cloud is a subscription and he has typed no price; the rehearsal's 36 model runs were
the stand-in's and their token counts mean nothing; his real runs of 2026-09-12 average about 4,400
prompt and 820 completion tokens, roughly 160k and 30k a day, plus the separate `director_loop` and
`model_review` jobs. Also unknown: whether Runway accepts these requests and charges what its credits
estimate, how long real scripts are, how many stills are retried, and whether his tokens still work.
The audit's two conditions on the figure — up to about 0.5 USD more in the books with defect 2, and
most likely 0 USD spent and no film, or safe mode, with defect 1 — are removed in code by the parts
above, under faked providers.

**What was measured, and whose measurement each figure is.** The rehearsal: pass 1 on the copy, pass
1b on a fresh copy of the migrated state, and `tests/test_rehearsal_on_a_copy.py` on a fresh copy,
**1 passed** in 1.67 s with the day stopping at performance intake inside it. The audit: the same
test on its own fresh copy, **1 passed** in 1.11 s with an identical record, and the whole suite,
`uv run pytest -q tests -p no:cacheprovider`, **1265 passed, 2 skipped** in 829 s (the second skip is
the opt-in rehearsal itself) — on the tree as it stood at the rehearsal, before any of the fixes. The
failure-and-analytics part: `tests/test_phase7_analytics.py` **18**, `tests/test_day_survives_a_stage.py`
**14** (new), **124** across the runbook, mail, B/C-adversary and daily-run-stage files, and **202
passed, 1 skipped** across the ten related files. The books part: **13** in
`tests/test_books_and_history.py` for the new cases (red first at 9 passed, 4 failed),
`tests/test_pricing_truth.py` **22** (red first), **158** across seven economy and media files, with
`ruff`, `ruff format --check` and `mypy` clean. The fakes part: **14 passed, 1 skipped** across
`tests/test_no_paid_path_escapes.py` (new, red first), the whole-day test and the rehearsal; **340
passed, 1 skipped** across every file that fakes `getaddrinfo` and the research, provider and
adversary files; and the opt-in rehearsal on the scratchpad copy **1 passed** — the day COMPLETED
through all twelve stages, the chooser picked `seedance2_mini` for two shots at 20.4 credits each,
both through the fake, one film reached the simulator, and the guard made 74 refusals, all free
research reads. The preflight part: **30** across `tests/test_readiness.py` and
`tests/test_sources_and_readiness.py` (red first at 17 passed, 12 failed), **130** across the
preflight's direct consumers, and `node --test frontend/tests/readiness.test.js` **8**. This
documentation part: `scripts/check_docs.py` and `tests/test_documentation.py`. **No whole-suite run
was made by any of the four parts or by this one**; the audit's 1265 / 2 is the newest and is older
than the fixes. No migration was taken: the head stays `0045_reconciliation` and 0046 is free. No
provider was called, nothing was rendered by a vendor, no run was queued on the live studio, no
credit was spent and `data/studio.db` was never opened by any of them.

Not finished, honestly: **the reconnect the Owner is told to make can grant statistics access only
since a change made while these documents were being written.** `SCOPES`
(`backend/app/youtube/services.py`) asked Google for `youtube.readonly` and `youtube.upload` only,
so no reconnect could have granted the statistics scope; another part added `yt-analytics.readonly`
on the night of 2026-09-18, with
`tests/test_youtube_connections.py::test_the_consent_asks_for_the_statistics_the_day_reads` (**1
passed**, run by this documentation part; nothing else of that change was measured here). His
consent screen now asks for one more permission, the change reaches him only when his studio runs
this code, and a connection made before it must be reconnected once to hold the scope — until then
statistics stay «fără date». The
uploader (`providers/youtube.py`) logs a refused refresh and writes no ledger event, so a refusal at
upload reaches the preflight only after the statistics read meets the same dead token — and on the
first day with a dead token the films are made and paid for before the upload fails. The film's hold
still takes the dearest voice price (`estimate_film_cost_micros`), so it holds Flash narration at
about twice its cost while the books now charge the half. The harness now fakes the analytics
adapter, so the real Google refresh on his copy is no longer rehearsed: defect 1's fix is proven by
the failure-and-analytics part's tests with faked transports, and only a free real read — Verify or
Reconnect in Settings — proves his tokens; and the free rehearsal after the fixes, on a fresh copy,
has not been run. The panel does not read `summary`, `stages_productive`, `produced` or `first_stop`
yet, and `frontend/dist` is not rebuilt. (Corrected 2026-09-19: `frontend/src` reads all four,
through `frontend/src/day_outcome.js`; see the subsection below. `frontend/dist` is still not
rebuilt.) `backend/app/runbook/stages.py`'s module docstring still
says a raised fault «stops the day», and `_performance_intake` keeps the reconnect sentence in its
artefacts and the ledger rather than in its own reason line. The manual ingest endpoint
(`analytics/router.py`) now answers 409 with the Romanian reason, not 502, for a transport or
authentication failure. The scan's roots are the daily day only: the watchdog, the Director's loop,
the model review, the catalogue refresh, the reference-set route and the API routes are held by the
network guard alone, and the scan cannot see `getattr` by string, `importlib` or code built at run
time. The free research reads are refused in a rehearsal, not faked, so which of his 36 hosts are
readable today is a real run's measurement. And nothing here proves a vendor: whether Runway returns
usable clips at the estimated credits, whether his models answer the idea, Director and Accountant
schemas (kimi-k3 had already rambled on 2026-09-12), whether a vision model answers the picture gate,
whether the reviewers catch narration its cited claim does not support, and whether the Publisher
titles the serial as the episode — the first real day, watched, is where each of those is measured.
(Corrected 2026-09-19: narration that does not say its cited claims is now refused by a computed
check, before any money is spent; see the subsection below. What a real day still measures is
whether a real writer, given the check's note, repairs the script within the exchange budget.)

### After the rehearsal — 2026-09-19: the narration says what its claims say, and the panel says what the day made

Two parts closed two of the rehearsal's findings in code, under faked providers. The grounding part
made the narration answer to its claims. The panel part made the page show what a day produced.
This subsection records what each changed, what each measured and what is still open. The
rehearsal's findings above stand as they were found.

**Why the narration needed a measure.** In pass 1b the day selected the Owner's real topic «Why
Nepal Is Being Handed a Climate Bill It Cannot Pay», with verified claims about it. The stand-in
writer returned script 5ee7e22e, «The light your eyes were not built for», about the James Webb
telescope. Every scene cited the Nepal claim 0be61855, a SUPPORTED claim about the 83.3 billion
dollars of climate finance given to developing countries in 2020. The script passed the factual
gate, the story review and the Director, and was approved and published to the simulator (the
report's and the audit's FAKE_LIMIT finding). The factual gate (`evaluate_factual_gate`) asks
whether the cited claims exist and are SUPPORTED. Nothing the studio computed asked whether the
narration says them, so only a model's judgement stood between that script and a film. With a real
model the risk is smaller, but real: a film whose words drift from its sources is exactly the
factual failure the gates exist to prevent.

**Fixed: the narration is measured against its claims and its topic.**
`backend/app/factual/grounding.py` (new) reads the voiceover, the topic's title and angle, and the
text of each cited claim, with no model and at no cost. It measures three things, and each failure
gets a Romanian reason naming what is missing:
- every cited claim is present: at least two of the claim's terms (content words, numbers or
  names) appear in the voiceover;
- the voiceover is about the topic: at least two terms of the topic's title and angle appear in it;
- the voiceover is not taken over by facts from elsewhere: it is refused when more than half of its
  numbers and names, and at least two of them, appear in no cited claim and not in the topic.

Words match on their stem, with diacritics folded. Numbers are normalised: «7,000», «7.000» and
«7 000» are one number, and «about 83 billion» says 83.3. Number words are read in English and
Romanian. A script it cannot measure (no claims, a cited claim that no longer exists, or no
narration) is NOT_MEASURED and does not pass. An episode of the office serial is not measured.

It refuses in four places, all but the last before any money is spent:
- The story review has a new blocking check, `narration_is_grounded`. A failure sends the script
  back for a rewrite (REVISE) with a note naming the unsaid claim, and becomes REJECT at the last
  exchange, as the budget already did.
- `_director_approves` measures again and will not approve a script that fails.
- `story_gate`, before the shot descriptions and the render, measures again, so a PASS recorded
  earlier, or given by hand, cannot buy a shot.
- The Director's last look at the finished film (`gather_facts`) carries the measurement and
  refuses a factual film that fails it, before any model is asked.

The story review's facts for the Director carry the measurement too, placed last so that a
truncated payload keeps the scenes. Every one of the four only adds refusals: the factual gate, the
Director's verdict, the five publishing points and the other hard gates are unchanged. Its limit is
stated in the module: it measures words, not meaning, so a narration that repeats two of a claim's
terms while contradicting it passes. That judgement stays with the Director, who now receives the
measurement. `50_CONTENT_GATE_MATRIX` gains the gate's row and a section on what it certifies, and
is re-hashed (the decision log has the reason).

**Calibrated on his real scripts: the grounding part's measurement.** The part opened copies of the
rehearsal databases only, read-only. The real model wrote 31 factual scripts on 2026-09-12:
- Both approved scripts pass: f243bf48, the LHC film, and 37fc8ef6, the ATLAS film.
- 25 of the 29 waiting for the Owner's approval pass.
- The 4 refused each cite a claim their narration never says. 92028a88 cites the sunshield cooling
  the mirror to 40 kelvins, while its scene says «you just block it, one layer at a time».
  8d4f7306, aa3da89f and 670d6279 cite the decommissioning on Aug. 8, 2024, while their scenes say
  the equivalent of «NASA switched it off».
- Across these scripts, the highest share of numbers and names from nowhere was 0.40, against a
  limit of 0.5. The rehearsal's script measured 1.0 and is refused on all three counts.

A stricter rule, asking for each claim's own distinctive words, was rejected. It refused the
approved LHC film, which says «doesn't glow, doesn't absorb light» for «does not interact with the
electromagnetic force». The prefix slack was lowered from three letters to two after «bill» matched
«billion». One existing fixture was changed rather than the check weakened. In
`tests/test_editorial.py`, the film's one claim did not carry the narration's 2023, James Webb
Space Telescope and twenty-six light years, which is exactly what the writer's brief forbids. The
claim now carries them.

**Fixed: the panel says what the day made.** `frontend/src/day_outcome.js` (new) decides, and
`frontend/src/main.js`, `frontend/src/ledger.js` and `frontend/src/style.css` show:
- **Run cards.** The backend's Romanian `summary` appears under the header of each run card.
- **Stage counts.** Each stage row shows its count: «a produs N», «nu a produs nimic», nothing when
  the backend says the stage is not counted (`produced: null`, as for the preflight and the day's
  log), or «nenumărat» for a record older than the counts.
- **Empty and idle.** A COMPLETED run with `stages_productive === 0` gets `rb-empty`, a warning
  colour instead of the green of success. A stage that finished and made nothing gets `rb-idle`.
- **Preflight.** On the preflight card, the check named by `first_stop` sits above the list with
  its own message, labelled «Primul punct blocant» (BLOCKING) or «Ziua nu ajunge întreagă», and is
  outlined inside the list.
- **Ledger.** The ledger's «daily run finished» line carries the summary, and the head line adds
  «· N etape au produs ceva» when the event has the count.

A missing count is never read as zero. A run without `stages_productive` is not called empty, and
a stage record without `produced` is not called idle, because `list_runs` returns older stage
records as stored. Events recorded before the count read exactly as they did. The dependant's
reason, «Nu a fost încercată: etapa de care depinde, «X», a eșuat.», was already shown as the
stage's reason line. It is display only: no gate, verdict or button permission changed, and the
Start button still follows the preflight status.

**What was measured, and whose measurement each figure is.**
- The grounding part:
  - `tests/test_script_grounding.py` **15 passed** (new);
  - `tests/test_editorial.py` **16 passed**, 3 of them new;
  - the factual, editorial, pipeline, runbook, media, publishing and whole-day files together
    (`test_script_grounding`, `test_editorial`, `test_editorial_quality`, `test_phase4_factual`,
    `test_factual_agent_pipeline`, `test_script_writing`, `test_phase9_story`,
    `test_pipeline_coverage`, `test_serial_pipeline`, `test_autonomous_day_end_to_end`,
    `test_daily_run_stages`, `test_day_survives_a_stage`, `test_phase10_runbook`,
    `test_phase5_media`, `test_phase6_publishing`, `test_publish_policy`,
    `test_rehearsal_on_a_copy`) **352 passed, 1 skipped**, the skip being the opt-in rehearsal
    harness;
  - `ruff check` and `ruff format --check` clean on its six files.
- The panel part:
  - `node --test tests/day_outcome.test.js` red first, **0 passed, 1 failed**, because the module
    did not exist, then **9 passed**;
  - `npm test --prefix frontend` **124 passed** (125 on the tree as committed, which also carries
    the stream test of 9ce725a);
  - `npm run check --prefix frontend` (tsc) clean;
  - a `vite build` into a scratch directory compiled, with `frontend/dist` untouched.
- This documentation part: `scripts/check_docs.py` passed, with the matrix re-hashed, and
  `tests/test_documentation.py` **3 passed**.
- The verify part (adversarial, after the documents):
  - the whole suite on the tree it found: **1523 passed, 4 skipped, 2 failed**. Both failures
    were the new check refusing a fixture that breaks the writer's brief:
    `tests/test_phase_bc_adversary.py` narrated the serial's dialogue under a Webb claim, and
    `tests/test_search_step.py` cited a claim `c1` that does not exist, which is NOT_MEASURED
    and held at `story_gate`. The fixtures were corrected, not the check;
  - a faithful narration with its numbers spelled out («six hundred million dollars», «șase
    sute», «twenty eighteen», «locul patru») was refused. The number reader now reads a whole
    spelled-out number in English and Romanian, and ranks from third to tenth on both sides.
    `tests/test_script_grounding.py` went red at **3 failed, 19 passed**, then **22 passed**.
    The recalibration on the copied scripts is identical: both approved films pass, the same 4
    are refused, and the rehearsal's 5ee7e22e is refused;
  - the module docstring now says two letters of prefix slack, as the code does;
  - `ruff check` clean, `mypy backend` clean on 191 files, `npm test --prefix frontend`
    **125 passed**, `scripts/check_docs.py` passed. The build part's seventeen files:
    **359 passed, 1 skipped**;
  - its second whole run had 3 render tests failing that passed alone and with their files
    (52 passed). The cause was not proven there; the next run below shows it.
- The session that committed (2026-09-19, 14:09–14:24): the whole suite on the tree as committed,
  `uv run pytest -q tests -p no:cacheprovider -rfE`: **1518 passed, 4 skipped, 12 failed, 2
  errors** in 917 s. Every one of the 14 is the machine out of commit memory, not the code:
  the two errors and two failures are `MemoryError` inside SQLAlchemy, the render failures are
  FFmpeg dying mid-encode, and Windows logged a low-virtual-memory condition at 14:09, 14:14 and
  14:20 (the Owner's Market Signals held 22.6 GB of commit, the live Unreal stream 13.6 GB). The
  seven files that held them (`test_media_selection`, `test_motion`, `test_phase5_media`,
  `test_phase_bc_adversary`, `test_reattempt_buys_nothing_twice`, `test_phase10_runbook`,
  `test_youtube_connections`) were run again at 16:45: **169 passed**. So 1532 of 1532 pass,
  in two runs. The same shortage stopped the Owner's live stream at 14:23: Unreal crashed in a
  background worker, and a restart at 16:39 died at its second frame on `E_OUTOFMEMORY` with 41 MB
  of commit left. It was restarted at 16:45, when 27 GB were free, and loaded the level.

*Corrected 2026-09-19, after the verify part:* the verify part and the committing session each
made a whole-suite run, recorded above. What stood here: «No part made a whole-suite run, so the
audit's 1265 passed, 2 skipped is still the newest, and it is older than every fix.» No provider was called, nothing was rendered, no run was queued, no credit
was spent, and `data/studio.db`, `art-source/` and `backend/app/office/` were not touched.

Not finished, honestly:
- **The Owner's queue.** 4 of the 29 scripts waiting for his approval (92028a88, 8d4f7306,
  aa3da89f, 670d6279) would now be sent back for a rewrite, or held at `story_gate` if he approved
  one by hand. This is a dated line in step 12 of «Ce are Owner-ul de făcut».
- **A real rewrite.** Only a real model run shows whether a writer given the Romanian note fixes
  the script within the exchange budget. The replayed stand-in does not rewrite, so in its test it
  runs until REJECT.
- **Other languages.** Claims whose sources are in another language were tested only as a Romanian
  narration of English claims. Across languages, ordinary words match only where stems are shared;
  otherwise the match rests on numbers and names.
- *Corrected 2026-09-19 by the verify part:* the module docstring says two letters, as
  `SUFFIX_SLACK` does. What stood here: the docstring said «at most three letters to spare».
- **What a word count cannot hear, measured by the verify part.** The check is lexical, and these
  pass it; each stays the Director's judgement, and she now receives the measurement:
  - negation: «Nepal is NOT ranked fourth ... no US$600 million in damages» measured PASSED;
  - one claim said and the others carried by generic and topic words («countries», «developed»,
    «billion», «Nepal», «climate»). Two stricter rules were tried on the real scripts and both
    refuse the Owner's approved LHC and ATLAS films, so neither was adopted;
  - the claims' keywords in unrelated sentences, with no number from elsewhere;
  - «opt» and «nouă» are read as 8 and 9, so «opt in» or the Romanian «new» can add a number
    from nowhere. Nothing in the calibration set was affected;
  - when the Director refuses on grounding after a review said PASS (only if the text changed
    between the two reads), the rewrite's notes do not mention grounding. No money is at risk:
    `story_gate` measures again before the shot descriptions, the media stage and the render.
- **The panel.** `frontend/dist` is not rebuilt, so the Owner sees none of it until
  `npm run build --prefix frontend` or until `start.py` rebuilds a stale bundle. The panel was not
  seen in a browser against a live backend. A PARTIAL run's `stopped_at_stage` still reads
  «stopped at «X»» rather than «etapa eșuată». The ledger and the run cards still mix English and
  Romanian.
- **Unchanged.** `backend/app/runbook/stages.py`'s module docstring still says a raised fault
  «stops the day». The serial's upload taking the factual film's metadata, found by the rehearsal,
  is not addressed.
- **Scratch files.** The calibration copies (`grounding_calib/` in the session's scratchpad) can be
  deleted.

## Readiness for the first day (2026-09-18)

Six phases are built and the suite is green, which is not the same thing as a studio that can be
left alone on Monday morning. This day measured the distance between the two, in three places, and
closed what could be closed from the record alone. Measured before the work, each of them true of
every studio that has ever run: no budget was active anywhere, so `reserve_spend` took the write
lock and held a film's money against no limit at all; 391 `agent_run` rows on the live copy carried
`cost_vr` NULL because the models the employees actually think with had a price on neither token
side; `seed_initial_workforce` hired every employee onto a text model and no seeded model declares
`vision` at all, so `app.agents.vision.vision_agent` returned None and the picture and character
gates stood down as NOT_APPLICABLE on every film, forever, which means a film of eight blank fields
passed every automatic check;
`generate_storyboard_from_script` wrote `character_ids_json=[]` on every scene of every factual film
— the studio's main product — so the character gate had nothing to compare and only the serial's
storyboard ever filled it; a SUPERVISED day wrote one approval request per film and nothing left the
studio, so an unanswered question expired after twenty-four hours and the film was never made; and
every cost row the studio wrote for itself was ESTIMATED while `spend_since` summed every row in the
period whatever its status, so a render estimated at 4.20 and later billed at 4.55 charged the period
8.75.

**The preflight says what is missing before the Owner spends anything.** Five checks were added to
`app.runbook.preflight`, all of them reading the database and nothing else — no vendor is asked, no
key is used, no job is queued — so the preflight is as cheap and as safe on the hundredth run as on
the first. `spending_budget` (DEGRADING) reports that no budget is active at all: the hold is still
taken, it simply has no limit to refuse it against, and the line names `PUT /economy/budget` because
nobody but the Owner can set one. `model_prices` (DEGRADING) asks whether the models the day's
employees think with have a price on *both* token sides — `llm_cost_vr` returns None unless input and
output are both priced, which is how those 391 rows came to be NULL — and names the provider kinds
that are unpriced without inventing a figure for any of them. `vision_capability` (DEGRADING) asks
`vision_agent` whether anybody in the studio can look at a picture, and says the consequence rather
than the fact: with no model that declares vision, `picture_qc` and `character_drift_qc` stand down
on every film, so a film of blank fields passes every automatic check. `character_references` names
the characters whose slots hold no readable picture — DEGRADING for one whose look is locked, because
that character's film is refused before the first scene rather than having a face invented for it,
and INFORMATIONAL for an unlocked one, whose still is drawn from its prompt as it always was;
"readable" means the slot holds an asset id, the row exists, and the file is still on disk, since a
row pointing at a moved file looks filled in the database and has nothing to compare against in QC.
`serial_channel` (INFORMATIONAL) says whether the OFFICE_SERIAL slot is bound to a connected account
and whether the Director has the Owner's leave to approve episodes, naming
`POST /publishing/channels/{id}/publish-policy`; without the leave every episode stays DRAFT and
waits for him, which is his right and is not autonomy. None of the five is BLOCKING and two of them
never even degrade: a preflight check must not stop the day for something the Owner deliberately
chose, so a studio with nothing configured reports exactly the blocking failures it reported before —
`stop_autonomy` and `llm_provider` — and a test holds that list against the verdict, which is
computed over BLOCKING and DEGRADING only. Beside them, `APPROVAL_EXPIRES_AFTER_HOURS = 24`, a module
constant in `services.py` the Owner could not reach, is now `approval_expires_after_hours` in
`config.py` (default 24, one hour to a week, `STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`), read through the
same local-import-and-`getattr` shortcut `providers.retry` takes, with a documented fallback of 24 so
that a studio whose settings cannot be built can still ask him a question rather than raise while
asking it; the bounds are stated as what they protect — below an hour a question could expire before
he reads it, above a week a yes could be spent long after the film it was asked about — and the
behaviour is unchanged.

**Somebody can be hired who can see, and a factual film records who is in it.** The role now says
what it would want: `ROLE_PREFERENCES` writes `vision` on the Video Editor's role at the PREFERRED
level — which is not a gate and never becomes one — and `prefer_capable_models` moves that employee
onto a model that sees at the next start-up, if the Owner has admitted one. **Corrected at the same
day's closure (2026-09-18): she moves in the same sync that admits the model**, not at the next
start-up; see «Closed the same day» below. PREFERRED was read
nowhere in the code before (the only reading was `requirement_level == "REQUIRED"`, in
`_check_required_capabilities` and in the role projection); it is now read in the hiring path inside
`seed_initial_workforce`, and nowhere that could refuse a run: a studio whose Owner has admitted no
seeing model hires the same way, edits the same way, and is told honestly that nobody looked. His
choice stays his — an employee whose models were ever saved by the assignment command
(`agent.model_assigned`) is not touched, the same guard the start-up allocation uses (**corrected at
the same day's closure, 2026-09-18: that guard read the studio's own allocation file as his hand**,
because `apply_llm_allocation` writes the same event, so the first sync of any studio killed the
preference for a choice he had never made; `_owner_chose_models` now judges the last event that
moved her models) — and the move
writes `agent.model_preferred`, never `agent.model_assigned`, because that second event is the proof
of his choice and `apply_llm_allocation` reads it as "already configured". The capability itself is a
row and not a claim about any model: the seed creates `Capability(name="vision")`, because a role can
only prefer a capability the studio has by name, and attaches it to no proposed model —
`SEEDED_MODEL_CAPABILITIES` now enumerates the four text capabilities explicitly in place of the loop
that wrote "every capability" onto every proposed model, since nothing in the seed contacts a vendor
and a guess that a model can see would make the picture gate certify a look nobody took.
`sync_provider_models` attaches `vision` where the vendor itself declares it. On the film's side,
every factual scene now records its cast, read from what the scene itself says: the scriptwriter's
character list first, then the names the requested picture calls for — not the narration, because the
narrator has no face, and a name spoken over a photograph of a mirror does not put that person in
frame. A first name followed by another capitalised word is not counted (the observer "Vera Rubin" is
a telescope, not the cast), because an invented cast would make the gate certify a comparison nobody
asked for. **Corrected at the same day's closure (2026-09-18): that one exclusion was not enough** —
a bare given name whose next word is lower case ("Hurricane Elena made landfall") was cast as well,
so the reading is now split, the prose's guesses are recorded and never written to the scene, and
only what the film states buys a portrait or refuses a locked character; see «Closed the same day»
below. A film that shows nobody records an empty cast and says once, in the storyboard's own
creation event (`media.storyboard_created`, keys `scenes_with_cast` and `cast_note`), that the
absence is deliberate — readable through `app.media.services.storyboard_cast_note` and returned by
`get_storyboard` as `cast_note`. The consequence is that the reference sets reach the factual film at
last: a scene that names a character with a stored portrait is drawn from it, and a character whose
look is locked and has no reference refuses the scene instead of being given an invented face — a
rule that was until now unreachable from a factual film, because no factual scene listed anybody.

**The Accountant tells him what is waiting, and the books learn what things really cost.**
`waiting_approvals_letter` writes one letter a day, with the same idempotence as the other two — the
studio's business date decided behind the write lock — and writes nothing when nothing is waiting,
so a silent mailbox still means "nothing to decide". Each question is named by what it is in his
language (`APPROVAL_ACTION_LABELS`), with its cost — «necunoscut» where the studio cannot compute
one, never zero, taken from the request's own `cost_label` so that the governance page and the
mailbox can never say two different things about the same question — and with the hour the oldest
one expires; the questions are ordered as the day raised them, and the model-written evidence (a
film's title, a storyboard's estimate) is cut at 120 characters, because a long title may not become
the whole letter. The day's close carries it as its first act, before any question is put to a
model, so a close that fails because the report never came back does not swallow the one letter that
says he has decisions standing. **Corrected at the same day's closure (2026-09-18): the media stage
writes it too, in the minute the question is born**, and the figure in it now carries what the
estimate could not price; see «Closed the same day» below. Beside it, migration
**0045_reconciliation** gives the books the one word they had a vocabulary for and no function:
`provider_reconciliation`, plus `reconciled_at` and `reconciled_by_id` on `provider_cost_record`,
both NULL, so every existing row keeps the reading it had. Reconciliation is the Owner's act and
nobody else's, because only he sees the invoice: `PUT /economy/reconciliations` has the shape of
`PUT /economy/prices` — a `command_id` (a retry returns the original answer, the same id with a
different figure is 409) and `expected_version`, which here is required rather than optional,
because replacing an invoice moves money. An invoice covers a period (the same half-open window
`spend_since` reads) or one named thing — today a render, through the attribution key every row
carries. It writes the BILLED row that posts against VR Cash, stamps `reconciled_at` on the
estimates it covers, and keeps on the row, as data, every row it touched and could not replace, with
the reason. The estimate is marked, never subtracted: it is the document of what the studio believed
a film would cost, and `spend_since` skips it. The billed row carries the hour of the last spend it
pays for, not the hour the Owner typed it, so the period that counted the estimates is the period
that counts the invoice: afterwards a period counts the billed figure once, plus whatever the
invoice did not cover, and `treasury_snapshot.unbilled_provider_costs` falls the same way, because
an estimate that has been paid is no longer an obligation coming. A correction is a new version,
which reverses the previous invoice's posting in the ledger (`reverses_transaction_id`) and
re-adopts its estimates; nothing is edited and nothing is deleted.

**What was measured, and whose measurement each figure is.** The preflight part: `tests/test_readiness.py`
**11 passed** (new) and `tests/test_phase10_runbook.py` **46**, with `tests/test_approvals.py` **18**,
**144** across the eight daily-run, director, pipeline, research, reset, scheduler, sources and
media-toolchain files, **70** across approvals, autonomy modes, books and the closure adversary, and
the three whole-day tests **5**. The workforce and storyboard part: **18** in
`tests/test_phase1_agents.py`, **28** in `tests/test_phase5_media.py`, **16** in
`tests/test_picture_qc.py`, **22** in `tests/test_character_references.py` and **10** in
`tests/test_editorial.py`, with **83**, **51**, **87** and **138** across nineteen neighbouring files
that seed the workforce or build storyboards — 359 in all, all passed. The economy part:
`tests/test_reconciliation.py` **11 passed** (new), `tests/test_books_and_history.py` **17**,
`tests/test_phase11_economy.py` **34**, `tests/test_pricing_truth.py` **18**,
`tests/test_schema_and_audit_trail.py` **3**, **188** across the ten files the migration-head move in
`main.py` can reach, and the whole-day tests **5**, with `ruff`, `ruff format --check`, `mypy backend`
and `scripts/check_docs.py` clean. This documentation part: `scripts/check_docs.py` and
`tests/test_documentation.py`. **No whole-suite run has been made by any of the four**, and the
figure that stands in `PROJECT_STATE.json` — 1194 passed, 1 skipped, taken by the Phase D/G closure's
adversarial verifier on 2026-09-18 — is therefore older than the tree; the verifier's figure for this
phase lands after this document. The migration chain is 0039 → 0040 → 0043 → 0044 → **0045** and
`main.py` pins `0045_reconciliation`: the economy took 0045 as the brief reserved it, the media part
needed no column and took neither 0045 nor 0046, so **0046 is free**. No provider was called, nothing
was rendered, no run was queued and no credit was spent by any of the four.

Not finished, honestly: **nothing here has met a real vendor, a real model or a real invoice.**
Every test fakes every provider at its transport and `tests/conftest.py` refuses every non-loopback
socket, by the Owner's rule of 2026-09-17, so what is proven is behaviour and not a vendor's answer:
that a model declaring `vision` really does return the picture gate's schema on real frames is
unmeasured until he admits one, and the first true reconciliation — his, with his invoice in his
hand — is the measurement of the books. The preflight's five messages have been read in Romanian by
their author and not yet by him. `model_prices` covers the LLM token sides only, on the primary
model of each ACTIVE agent, because that is exactly what makes an agent run's `cost_vr` None; it
does not check the voice price (`per_1k_characters`) or the motion and image prices (`per_second`,
`per_generation`), because naming the voice kind honestly would mean reading the media selection
through the vault rather than the price table and pricing a motion model would mean knowing which
model a plan will pick, and a check that half-covered them would report a pass certifying less than
it looks like. The secondary and tertiary model slots are not priced either, because `vision_agent`
counts only the primary model and the two checks must agree about which model an employee runs on.
**Corrected at the same day's closure (2026-09-18): the Video Editor's preference no longer waits
for the next seed and is no longer invisible** — the second call is wired at the end of
`sync_provider_models`, after `apply_llm_allocation`, and `RoleView` carries
`preferred_capabilities` beside `required_capabilities`; what stands open of it is named below.
**Corrected at the same day's closure (2026-09-18): `picture_qc` reads the storyboard's record**, so
a film that genuinely shows nobody reports the board's own note and the old sentence now means only
what it says. An employee's run is still not reconcilable: the token cost the studio computes for
itself lives in `agent_run.cost_vr` and never passes through `provider_cost_record`, so an Ollama
Cloud invoice cannot yet replace it. An invoice matches on a correlation exactly and knows one
default key, `render_job_id`, which is what `_priced_scene_costs` and `record_failed_render_cost`
write; a hosting charge or a monthly subscription must be reconciled by period, or with a key he
names, because a book does not guess. **Corrected at the same day's closure (2026-09-18): the
waiting-approvals letter no longer leaves only at the day's close** — the media stage writes it in
the minute it raises the question and stops, and `_letter_once_a_day` keeps the close from writing a
second one. **Corrected at the same day's closure (2026-09-18): the panel renders the third severity
and names the checks** — a failing INFORMATIONAL check reads INFORMATIV in neutral grey instead of a
red "DEGRADES", and the five new checks and `autonomy_mode` have Romanian labels. What is still true
of the interface: `youtube_channel_binding` has no label either and still shows by its code name, as
it did before this phase (corrected 2026-09-18, measured in the tree while the rehearsal's documents
were written: `frontend/src/readiness.js` carries «Sloturi de canal legate de YouTube» for it, and
did since the commit that created the module); neither reconciliation screen exists; and `frontend/dist` is still not
rebuilt, so the Owner sees none of any of it until he builds.

### Closed the same day — 2026-09-18: the employee who can see arrives when the model does, a guessed name steers nothing, and the day speaks at the hour it stops

Three things the section above left open, in its own words: a preference that "reaches a studio that
is already running only at the next seed", a picture gate that "does not yet read the storyboard's
cast note", and a letter that "leaves only at the day's close" beside an interface that "has not
moved". An adversarial reading of the checklist — if the Owner did every line of it tonight, what
would the studio make tomorrow at 05:00 and what would most likely go wrong — named the same three
with a file and a line each, measured against this tree. All three are closed, and the second turned
out to be a larger fault than the note it had been filed as.

**The employee who can see arrives on the day the Owner admits the model, not on the day he first
seeded the studio.** Measured before the work: `prefer_capable_models` had exactly one caller,
`seed_initial_workforce`, and that caller one of its own, `scripts/bootstrap.py` — step 1 of his
morning, hours before step 9, where he admits a model that declares vision. Nothing looked again
between the two, so `app.agents.vision.vision_agent` returned None at 05:00, `picture_qc` and
`character_drift_qc` stood down on every film, and a short of eight blank fields would have reached
the Director as finished work. The preference now has its second call site, in `sync_provider_models`
and after `apply_llm_allocation`: `record_declared` a few lines above is the only place in the studio
that ever writes `vision` on a model, so the sync is the first moment at which a seeing model exists
as a row, and it is the Owner's own act — «sincronizează» in *Angajați → Model*, «verifică» in
*Setări → Conexiuni*. After the allocation and never before it, because the allocation is the
studio's baseline and skips only employees who already carry `agent.model_assigned`, which a
preferred move deliberately does not write: run first, the preference would be undone by the file
three lines later. The guard that protected the Owner's own choice was the bare existence of
`agent.model_assigned` — an event written by his command *and* by `apply_llm_allocation`, which
applies `config/workforce_seed.json` through that same command — so the first sync of any studio
assigned the Video Editor the file's own primary and the preference then stood down for ever for a
choice he had never made. `_owner_chose_models` reads instead the last event that moved her models:
none at all means the seed hired her and she may be moved; `agent.model_preferred` means this same
function moved her last and may move her again; `agent.model_assigned` is the file's when her three
slots hold exactly the models the file names for her role (compared through `resolve_model`, so a
":cloud" spelling is not mistaken for a different model) and his hand otherwise. A role the
allocation does not name, and an allocation that cannot be read, are both read as his: standing down
costs a picture check that says honestly it could not run, while moving wrongly overwrites a
decision, and only one of the two is undoable by the studio. Beside it, `RoleView` now carries
`preferred_capabilities` alongside `required_capabilities` — two fields, never one list, because a
preference listed as a requirement would tell him his Video Editor cannot work without a seeing
model, and she works without one — so his page can say why she sits on the model she sits on without
reading the database to explain it.

**A cast the studio guessed steers nothing it cannot take back.** Measured before the work:
`_characters_named_in` counted a bare given name whenever the next word was lower case, so
"Hurricane Elena made landfall" cast Elena Fact-Checker, "Lyra, the constellation, rises" cast Lyra
Voice Artist and "the Kael river delta" cast Kael Video Editor — and that column is not a label:
`assembler.py` hands it to the render, `factory.py` turns it into the vendor's `referenceImages`, and
`image_reference_for_scene` refuses the film outright when the named character's look is locked and
no reference is stored. Once step 10 of his list fills the reference slots, an astronomy short about
a constellation would have been drawn from the Voice Artist's portrait with real credits, and with
`identity_locks_json['visual']` set the same false positive would have refused the day's only factual
film. The reading is now split at the place where the evidence differs. A scene states its cast in
the writer's own `characters` list — read by given name, because a list of characters is a record of
who is in the scene — or by writing a character's whole canonical name in the picture it asks for;
that stated cast alone is written to `character_ids_json`, and it alone buys a portrait, is certified
by the character gate and may refuse a locked film. A bare given name in the prose is a guess: it is
recorded, per scene, on the storyboard's own creation event (`media.storyboard_created`, key
`guessed_cast`, read back through `app.media.services.storyboard_cast_record`), it never reaches the
scene, and the picture gate may look at it — the frame is asked about, the verdict kept as OBSERVED
with `basis: "guessed"`, no stored portrait attached — but it is never counted and can never fail a
film, because a check that measured only guesses has measured nothing. A film whose prose named
somebody and stated nobody therefore no longer claims an empty cast "by design": `cast_note` says
`NO_CAST_ONLY_GUESSED` instead of `NO_CAST_BY_DESIGN`, and the two are different facts. The line the
readiness phase left open is closed with it: `character_drift_qc` reads the board's note, so a film
that honestly shows nobody reports that its cast is empty by design rather than the old single
sentence "no scene in this film lists a character", which now means only what it says — nobody listed
anybody and the board never said why. The cost of the choice is stated rather than hidden: a factual
scene whose picture writes "Sarah at the studio window" and states nothing is no longer cast from
prose, so a reference the Owner paid for goes unused unless the writer lists her. That is the right
cost — the studio may miss a portrait it could have used, and may not buy one for somebody nobody
said was there.

**Under SUPERVISED the day says it stopped, in the same minute, and with a figure that admits what it
left out.** Measured before the work: `waiting_approvals_letter` had one caller, `reconcile_day`,
which runs inside `_post_run` — the day's last working stage — so a question the media stage raised
at 05:30 reached the Owner at the run's end at best, and not at all when the run stopped before
`_post_run`; the question then expired after `approval_expires_after_hours` and that film was never
made. And the figure in it was understated whenever ElevenLabs has no active `per_1k_characters`
price: `estimate_film_cost_micros` counted the narration as 0 and the caveat reached only the
reservation's note, a row he never reads. What he sees now, in order, on a first SUPERVISED morning:
**05:00** the day starts and the preflight is on the panel, every check by a Romanian name — «Buget
de cheltuieli», «Prețurile modelelor», «Angajat care poate privi», «Imaginile de referință ale
personajelor», «Canalul serialului», «Modul de autonomie» — and each failure marked by what it
actually is: BLOCHEAZĂ in red, DEGRADEAZĂ in amber, and, new, INFORMATIV in neutral grey for the
serial channel he has not created and the character whose look he has not locked, which used to print
as a red "DEGRADES" about a day they do not degrade. **≈05:30** the media stage prices the film,
finds the question is his (T3, over his threshold), writes it and stops — and writes the letter in
the same minute rather than waiting for the close: «O întrebare așteaptă răspunsul tău / 1. Un
randat plătit peste pragul stabilit — storyboard …, estimat 1.2 USD; cost 1.2 USD (estimare
incompletă: narația nu are preț stocat și este numărată ca zero); expiră 19.09.2026 05:30.»
**≈05:35 onward** the day runs its remaining stages and `_post_run`'s close calls the same letter and
writes nothing, because `_letter_once_a_day` already has today's date on it: one letter, whatever end
of the day raises it. **Whenever he opens the panel** the approvals card carries the same words
beside the number — «Cost: 1.2 USD (estimare incompletă: narația nu are preț stocat și este numărată
ca zero)» — so the caveat is read where the figure is read, not four lines below it, and the hold in
the books carries it too. **By 05:30 the next morning** the question is dead; he now has the
twenty-four hours he was supposed to have rather than the remainder after the run's close, and if his
answer comes in time the next run films the film it was about.

**What was measured, and whose measurement each figure is.** The seeing-employee part:
`tests/test_seeing_employee.py` **5 passed** (new, red first at 1 passed / 4 failed), with
`tests/test_phase1_agents.py`, `tests/test_multi_llm.py` and `tests/test_provider_discovery.py`
**60** together, **54** across the picture-QC, workflow, factual and truthfulness suites and **79**
across picture QC, readiness and the runbook; `ruff`, `ruff format --check` and `mypy` clean on its
two backend files. The cast part: `tests/test_phase5_media.py` **30**, `tests/test_picture_qc.py`
**17**, `tests/test_character_references.py` **23** — **70** together — with **72** across picture
QC, the seeing employee and editorial quality and **91** across the daily run, the serial pipeline,
the readiness adversary and the production policy; `ruff` and `ruff format --check` clean on its five
files. The letter-and-panel part: `tests/test_phase11_economy.py` **36**,
`tests/test_daily_run_stages.py` **34**, `tests/test_approvals.py` **20**,
`tests/test_books_and_history.py` **17**, and **234** across those four with the E/F adversary,
pricing truth, the runbook, readiness, the readiness adversary and the autonomy modes; on the panel
side `node --test tests/readiness.test.js` **8** (new) inside `node --test tests/*.test.js` **110**,
with `npm run check --prefix frontend` clean. This documentation part: `scripts/check_docs.py` and
`tests/test_documentation.py`. **No whole-suite run was made by any of the four**, and the figure in
`PROJECT_STATE.json` is still the Phase D/G closure verifier's 1194 passed / 1 skipped of 2026-09-18,
older than the tree twice over now; the verifier's figure for the readiness phase and for this
closure lands after this document. No migration was taken: the head stays `0045_reconciliation` and
**0046 is still free**. No provider was called, nothing was rendered, no run was queued, no credit
was spent and `data/studio.db` was not opened.

Not finished, honestly: **the three closures are behaviour under faked providers, and the Owner has
still seen none of them.** The panel was proved by `node --test` and `npm run check` only — no server
was started, no browser was opened and `frontend/dist` was deliberately not rebuilt, because that
build is his own launch act (step 2), so nobody has yet looked at an INFORMATIV card or an amber
caveat. `RUNBOOK_CHECK_LABELS` covers every check name this phase added and every one the panel
already named, but not `youtube_channel_binding`, which `run_preflight` also emits and which showed
by its code name before this work and still does (corrected 2026-09-18: it has a label, «Sloturi de
canal legate de YouTube», in the same module). The guessed cast is on the ledger event and not in
the REST answer: `get_storyboard` returns `cast_note` and not the map, so the Owner cannot yet see on
the storyboard page which names the studio read and refused to cast on. The serial's own board
(`backend/app/media/serial_storyboard.py`) writes no `guessed_cast`, correctly — its cast comes from
the episode roster and is always stated — which means `storyboard_cast_record` answers the empty
record for serial boards, and a later reader must not take that emptiness for "nobody is in it". The
caveat covers narration only, because narration is the only part of the estimate that can silently
become zero; `estimate_film_cost_micros` still does not price the stills at all, so a film's real
image spend is outside the figure rather than counted as zero inside it, and saying so in the caveat
would be a claim the function cannot measure. The caveat itself lives in the request's `evidence`
text and is read back by its first words (`UNPRICED_CAVEAT_PREFIX`) in three places — the
Accountant's letter, the approvals card and the media stage that writes it — because a column would
have needed migration 0046; a column is the right shape when a later phase takes one. The corner case
`_owner_chose_models` names is real and undecidable from the record: an Owner who assigns an employee
by hand to exactly the three models his own allocation file already gives her is read as the file,
and she may be moved — bounded, because the move only ever goes to a model declaring everything the
role requires as well as what it prefers and writes `agent.model_preferred`, so his next assignment
wins and stays won. `waiting_approvals_letter` is called from `_media` without a try/except, matching
the unguarded `budget_refusal_letter` call four lines below it, so if the Accountant's desk raised
from inside it the media stage would fail rather than return SKIPPED; the two were left consistent
rather than one of them guarded. One defect in the tree is named here rather than fixed, because it
belongs to a file this part does not own: `uv run mypy backend/app/media/picture_qc.py` reports one
`union-attr` error at line 285 — `board.id`, where the narrowing that makes it safe is `scenes` being
non-empty, so it is a type-narrowing gap and not a runtime fault. A second, recorded as open while
these documents were being written, was closed in the tree before they were finished:
`tests/test_phase_dg_closure_adversary.py::test_only_the_owners_command_module_reaches_an_approval_row`
had begun to fail because its whole-tree scan for the string "ApprovalRequest" found a docstring line
the Accountant gained in this phase; the scan now walks the parsed module and counts a class
definition, a name, an attribute or an import rather than characters, so prose that explains where
the Owner's question keeps its cost no longer reads as a writer of the row. Measured after that
change on this tree: `uv run pytest -q tests/test_phase_dg_closure_adversary.py` **12 passed**.

### Ce are Owner-ul de făcut

Lista de mai jos este ordinea dimineții primei zile adevărate. Numai Owner-ul poate face lucrurile
din ea; studioul nu le face singur și nu le cere de două ori. Fiecare rând spune ce are de făcut, cu
ce comandă sau pe ce ecran, și ce se întâmplă dacă sare peste el. Rescrisă ca listă ordonată pe
2026-09-18; niciun rând de dinainte nu a fost scos, iar rândurile noi ale acestei faze sunt așezate
la locul lor în ordine. Completată 2026-09-18 după repetiția pe o copie a datelor lui (secțiunea
«The rehearsal on the Owner's data (2026-09-18)» de mai sus): ce a găsit repetiția și numai el poate
face este adăugat în rândul căruia îi aparține, marcat «Adăugat 2026-09-18 după repetiție», fără să
schimbe numerotarea, pentru că pașii sunt citați după număr în alte documente. Completată din nou
2026-09-19, la pașii 2 și 12, cu rânduri marcate «Adăugat 2026-09-19»: ce s-a schimbat pe panou și
ce înseamnă pentru scenariile care îl așteaptă verificarea care arată dacă narațiunea spune ce spun
afirmațiile ei.

1. **Migrează baza de date live** — `uv run python scripts/bootstrap.py`. Lanțul este 0039 (economia
   și rezervările), 0040 (sursele de cercetare), 0043 (modul de autonomie), 0044 (subiectul unei
   cereri de aprobare și răspunsul lui pe rând), iar de azi **0045_reconciliation** (reconcilierea
   facturilor: un tabel nou și două coloane NULL pe rândurile de cost, deci niciun rând vechi nu își
   schimbă citirea). 0041 și 0042 au fost rezervate în faza D/G și nu au fost folosite; 0046 este
   liberă. Corectat 2026-09-18: rândul acesta a cerut pe rând `0040_research_sources`,
   `0043_autonomy_mode` și `0044_approval_answered`. **Dacă sare peste:** `backend/app/main.py` cere
   exact revizia `0045_reconciliation` la pornire, deci serverul nu pornește deloc. Niciun test nu
   atinge baza live. Măsurat 2026-09-18 de repetiție, pe o copie: **pasul acesta este făcut**, de
   mâna lui — repornirea studioului de la 22:42 a rulat `scripts/bootstrap.py` (`start.py` îl
   rulează primul), iar copia luată după ea era deja la `0045_reconciliation`; bootstrap rulat încă
   o dată pe copie nu a schimbat niciun rând. De la următoarea pornire, bootstrap mai seamănă două
   prețuri DOCUMENTED pentru narație (pasul 5).
2. **Construiește interfața** — `npm run build --prefix frontend`. Ecranele schimbate pe 2026-09-18 —
   starea site-urilor în *Cercetare → Surse*, banii ținuți în biroul Contabilitate, panoul de
   guvernanță (modul de autonomie, lista de aprobări, pastilele seturilor de referință) — sunt în
   sursă, nu în pachetul servit. **Dacă sare peste:** pagina servită rămâne pachetul vechi și el nu
   vede nici modul în care rulează studioul, nici întrebările care îl așteaptă. Construirea este
   actul lui de lansare; niciun agent nu a construit și nu a pornit serverul.
   Adăugat 2026-09-19: tot numai în sursă este și ce spune panoul zilei despre ce a produs ziua.
   Sub antetul fiecărei rulări apare propoziția ei. Lângă fiecare etapă scrie «a produs N», «nu a
   produs nimic» sau, la o rulare mai veche decât numărătoarea, «nenumărat». O zi COMPLETED care
   nu a produs nimic nu mai are verdele succesului. Deasupra listei preflight-ului stă prima
   verificare care ar opri ziua («Primul punct blocant») sau ar pierde un film («Ziua nu ajunge
   întreagă»). Le vede numai după construire.
3. **Pornește studioul și citește preflight-ul** — panoul zilei, sau `GET /api/v1/runbook/preflight`.
   De azi raportul numește și cele cinci lucruri pe care numai el le poate aduce: bugetul
   (`spending_budget`), prețurile modelelor (`model_prices`), un angajat care poate privi
   (`vision_capability`), imaginile de referință ale personajelor (`character_references`) și canalul
   serialului (`serial_channel`). Niciuna dintre ele nu oprește ziua — o verificare nu are voie să
   refuze ziua pentru o alegere a lui — deci lista aceasta este exact ce îi rămâne de făcut mai jos.
   Preflight-ul citește numai baza de date: nu întreabă niciun furnizor, nu folosește nicio cheie și
   nu pune nimic la coadă. Corectat la închiderea zilei (2026-09-18): pe panou, o verificare care
   cade fără să strice ziua se citește acum **INFORMATIV**, într-un gri neutru — canalul serialului,
   un personaj a cărui înfățișare nu este blocată — în loc de «DEGRADES» roșu, iar cele cinci
   verificări noi și `autonomy_mode` își au numele în limba lui. Singura care rămâne cu numele ei de
   cod este `youtube_channel_binding`, care nu avea etichetă nici înainte. Toate acestea se văd
   numai după pasul 2. Corectat 2026-09-18, măsurat în cod: și `youtube_channel_binding` are
   etichetă, «Sloturi de canal legate de YouTube». Adăugat 2026-09-18 după repetiție: «Canal
   YouTube conectat» și «2 sloturi legate» erau verzi citind numai starea stocată, nu tokenul; acum
   spun asta, iar trei verificări noi le urmează — «Dreptul de a încărca pe YouTube»
   (`youtube_upload_access`, **BLOCHEAZĂ** când Google nu a acordat încărcarea sau a refuzat tokenul
   după acordare), «Accesul la statisticile YouTube» (`youtube_statistics_access`, DEGRADEAZĂ) și
   «Filmele zilei în bugetul zilnic» (`daily_budget_films`). Rezumatul de sus nu mai spune
   «Studioul poate rula» deasupra unei verificări care vede ziua oprindu-se: numește prima linie care
   ar opri ziua sau ar pierde un film. **Dacă sare peste:** merge mai departe fără să știe ce
   lipsește.
4. **Pune bugetele** — `PUT /economy/budget`, biroul Contabilitate: zilnic, săptămânal, lunar. Nimeni
   altcineva nu le poate pune; Contabilul doar escaladează, nu aprobă. **Dacă sare peste:** rezervarea
   ține banii filmului, dar nu are de ce să îl refuze — o zi de reîncercări cheltuie cât îi vinde
   furnizorul, iar preflight-ul îi scrie `spending_budget` la fiecare pornire.
5. **Tastează prețurile planului** — `PUT /economy/prices`: ce plătește în realitate pentru ElevenLabs,
   Ollama Cloud și Runway, pe model sau `*` pentru tot felul, pe **ambele** unități de jetoane.
   **Dacă sare peste:** cărțile văd o fracțiune din zi — un cost calculabil doar pe o latură este
   None, nu zero, deci fiecare rulare a unui angajat se înregistrează fără cost și Contabilul
   raportează `unpriced_agent_runs`. Narația este singura excepție: bootstrap seamănă cifra publică
   ElevenLabs, marcată DOCUMENTED, care nu este planul lui. Ollama Cloud nu este semănată niciodată,
   pentru că un preț ghicit în cărți este mai rău decât golul pe care Contabilul îl raportează.
   Adăugat 2026-09-18 după repetiție: pe datele lui, șase modele Ollama Cloud (glm-5.3-flash,
   kimi-k3, minimax-m3, mistral-large-3:675b, nemotron-3-ultra, qwen3.5:397b) nu au preț — singura
   linie DEGRADEAZĂ a preflight-ului lui —, iar vocea lui, `eleven_flash_v2`, era prețuită la cifra
   DOCUMENTED pentru orice model («*», 0,22 USD la 1000 de caractere), deși aceeași listă de prețuri
   spune că Flash costă jumătate. De la următoarea pornire bootstrap seamănă și `eleven_flash_*` și
   `eleven_turbo_*` la 0,11 USD, tot DOCUMENTED; prețul pe care îl tastează el trece peste amândouă.
   Rezervarea filmului ia încă prețul cel mai scump al vocii, deci ține pentru narația Flash cam
   dublu față de ce costă.
6. **Pune plafonul de jetoane pe zi**, dacă vrea unul — `STUDIO_AGENT_DAILY_TOKEN_BUDGET`. 0 înseamnă
   fără plafon, așa cum a mers studioul până acum. **Dacă sare peste:** nimic nu se strică, dar bucla
   Directoarei și rundele de corespondență rulează fără tavan. Peste plafon, rularea este oprită
   BLOCKED_BUDGET și Contabilul îi scrie o dată în ziua aceea.
7. **Autorizează site-urile și, dacă vrea, conectează un motor de căutare** —
   `PUT /sources/allowed-hosts/{host}` și Setări → *Conexiuni* → „Căutare web (API JSON)"; butonul
   «Testează site-urile» din *Cercetare → Surse* le încearcă pe loc. Lista nu poate fi lărgită de
   niciun agent, de nicio cerere și de niciun rezultat al motorului: motorul numește adrese, studioul
   păstrează doar ce este pe lista lui și citește el însuși pagina. **Dacă sare peste:** studioul
   găsește pagini numai pe site-urile care poartă ele însele o adresă de căutare, iar
   `research_health` raportează DEGRADED când nu are cum să găsească nimic sau când au mai rămas sub
   zece afirmații verificate — o zi care nu găsește nimic se încheie cinstit cu nimic.
8. **Leagă canalele și pune-le politica** — sloturile în *Publicare → Canale*, apoi
   `POST /publishing/channels/{id}/publish-policy`: vizibilitatea, întârzierea,
   `public_publish_enabled` și dreptul Directoarei de a aproba episoade
   (`director_may_approve_episodes`). **Dacă sare peste:** canalul serialului apare în preflight ca
   `serial_channel` — fără legătură, episoadele se produc și nu au unde urca; fără dreptul
   Directoarei, un episod trecut de ea rămâne DRAFT și așteaptă mâna lui, ceea ce este dreptul lui și
   nu este autonomie. Măsurat 2026-09-18 de repetiție: ambele sloturi sunt legate, dar dreptul
   Directoarei de a aproba episoade este încă `false` pe datele lui (repetiția l-a dat numai pe o
   copie, cu comanda lui).
   Adăugat 2026-09-18 după repetiție: **verifică sau reconectează cele două conexiuni YouTube** —
   *Nexus Curiosity* (slotul MAIN_FACTUAL) și *Inside The Nexus* (slotul OFFICE_SERIAL) — din
   *Setări → Conturi și e-mail* (Verifică sau Reconectează, un apel gratuit), înainte de orice zi
   plătită. Amândouă au fost conectate pe 2026-09-11, Google le-a acordat numai `youtube.readonly` și
   `youtube.upload`, fără accesul la statistici (`yt-analytics.readonly`), iar dacă tokenurile lor
   mai merg nu se știe: repetiția nu le putea încerca fără să iasă din calculator, iar preflight-ul le
   arăta verzi citind numai starea stocată.
   **Reconectează-le pe amândouă acordând accesul la statistici**, și **scoate aplicația lui Google
   OAuth din modul Testing** (în Google Cloud Console, pe ecranul de consimțământ OAuth): cât timp
   aplicația este în Testing, tokenul de reîmprospătare moare la șapte zile după acordare — pentru
   conexiunile din 11 septembrie, cam acum — și va muri din nou la o săptămână după fiecare
   reconectare. Studioul nu vede în ce mod este aplicația; preflight-ul îi arată vârsta fiecărui
   acord. Ecranul lui Google oferă accesul la statistici numai dacă studioul îl cere, iar `SCOPES`
   (`backend/app/youtube/services.py`) a cerut doar `youtube.readonly` și `youtube.upload` — de aceea
   nicio reconectare de până acum nu putea acorda statisticile. În noaptea de 2026-09-18 i s-a
   adăugat `yt-analytics.readonly`: după ce studioul lui pornește cu codul acesta, ecranul îi cere o
   permisiune în plus, pe care trebuie s-o accepte. Până la reconectarea de după acea pornire,
   statisticile rămân «fără date». **Dacă sare peste:** un token mort se vede abia după ce Google l-a refuzat o
   dată. În prima zi cu el statisticile ies «fără date», iar filmele se fac și se plătesc, apoi
   încărcarea lor eșuează; de a doua zi `youtube_upload_access` blochează ziua înainte să cheltuie
   ceva. Până la reparația din 2026-09-18, același refuz oprea ziua la al doilea pas, înainte de
   orice filmare, și punea studioul în mod sigur cu AUTONOMIE OPRITĂ.
9. **Admite un model care poate privi** — Angajați → Model, după ce sincronizarea catalogului îl
   aduce de la furnizor. Niciun model semănat nu declară vedere, iar studioul nu presupune niciodată
   că unul vede: capabilitatea `vision` se atașează doar când vendorul însuși o declară. Rolul
   Monteurului o *preferă* de azi, deci angajata se mută pe un astfel de model la următoarea rulare a
   seed-ului — preferința nu cere nimic și nu refuză nicio rulare. Corectat la închiderea zilei
   (2026-09-18): **nu mai are nimic de atribuit cu mâna după ce admite modelul, și nu mai este nevoie
   nici de o a doua rulare a seed-ului, nici de o repornire.** Mutarea se face în chiar sincronizarea
   care aduce modelul de la furnizor — «sincronizează» în *Angajați → Model*, «verifică» în *Setări →
   Conexiuni* — pentru că acolo se scrie pentru prima oară `vision` pe un rând de model. Dacă îi
   atribuie el însuși un model, alegerea lui rămâne a lui și preferința nu o atinge; ce se mută este
   numai angajata lăsată pe modelul pe care i l-a dat fișierul studioului. **Dacă sare peste:**
   verificarea imaginilor și cea a personajelor stau deoparte la fiecare film, cinstit și vizibil în
   raport (`vision_capability`), deci un film de opt câmpuri goale trece toate verificările automate
   și ajunge la Directoare ca un scurtmetraj terminat.
10. **Produ seturile de referință ale personajelor** —
    `POST /media/characters/{id}/reference-set`, sau butonul de pe fișa personajului (fiecare slot
    este o pastilă, plină sau goală; butonul spune că se consumă credite de imagine și nu produce
    nimic până la a doua apăsare). Cele cinci sloturi — portret, corp întreg, față, profil, spate —
    sunt goale în orice studio care a rulat vreodată. Ruta consumă credite de imagine, deci este actul
    lui și al nimănui altcuiva: niciun pas al zilei nu o cheamă, iar un test ține asta. Răspunde cu
    sloturile umplute, cele refuzate și costul (`usd: None` dacă modelul nu are preț). **Dacă sare
    peste:** fiecare imagine a unui personaj este o invenție nouă și verificarea personajelor nu are
    cu ce compara; iar un personaj cu înfățișarea blocată și fără referință citibilă **refuză
    filmul** — de azi și filmul factual, nu doar episodul de serial — în loc să i se inventeze o
    față. Preflight-ul îi numește pe cei blocați înaintea zilei, ca să nu afle din refuz. Corectat la
    închiderea zilei (2026-09-18): refuzul acela urmează numai un personaj pe care **filmul îl
    spune** — lista de personaje a scenaristului, sau numele întreg în imaginea cerută — niciodată un
    prenume pe care proza doar l-a scris. Un nume ghicit nu cumpără niciun portret, nu refuză niciun
    film și nu apare nicăieri în studio: rămâne pe evenimentul de creare al storyboard-ului, ca să se
    vadă ce a citit studioul și ce a refuzat să creadă. Măsurat 2026-09-18 de auditul repetiției: pe
    datele lui niciunul dintre cele 8 personaje nu are imagine de referință, iar un set întreg
    înseamnă 8 × 5 = 40 de imagini, circa 0,80 USD la 0,02 USD pe imagine (`gen4_image`) — un cost
    pe care mesajul din preflight nu îl numește.
11. **Aprobă furnizorii de rezervă**, dacă vrea unul — `approved_fallbacks`, pe nivelul de politică al
    canalului, al seriei sau al storyboard-ului; pentru un personaj blocat, lista din
    `approved_fallbacks_json` scrisă de o schimbare de identitate APROBATĂ. Aprobarea este dovada că
    tehnologia păstrează personajul recognoscibil, deci nu o poate da studioul; lanțul rămâne oricum
    de cel mult o alternativă pe scop și pe scenă. **Dacă sare peste:** lanțul are un singur vendor și
    o scenă refuzată cade pe cartonul de rezervă pe care QC îl oprește de la publicare.
12. **Alege modul de autonomie** — `POST /api/v1/owner/autonomy-mode` sau panoul de guvernanță:
    MANUAL, SUPERVISED sau AUTONOMOUS_CEO. Coloana a fost scrisă pe AUTONOMOUS_CEO pentru că asta face
    codul de luni de zile, nu ca o promovare; comanda este singura care ridică modul și refuză
    ridicarea cât timp autonomia este oprită sau un incident este deschis, iar coborârea este
    întotdeauna permisă. MANUAL înseamnă o zi care scrie, dar nu cumpără cadre și nu urcă nimic;
    SUPERVISED filmează ziua și îi lasă câte o cerere de aprobare pentru **fiecare film** în loc de
    urcare. `GET /api/v1/owner/approvals` arată ce așteaptă (acțiunea în limba lui, despre ce este,
    treapta de risc, cine întreabă, costul — «necunoscut» când studioul nu îl poate calcula, niciodată
    zero — și cât mai stă în picioare), iar `POST /api/v1/owner/approvals/decision` este răspunsul, o
    singură dată pentru un singur act. De azi Contabilul îi scrie o dată pe zi, la închiderea zilei,
    ce întrebări stau în picioare și până când. Corectat la închiderea zilei (2026-09-18):
    **scrisoarea pleacă din pasul media, îndată ce acela a terminat de întrebat**, nu abia la
    închidere — tot una pe zi, oricare capăt al zilei o ridică primul, și numește fiecare întrebare
    pe care pasul a ridicat-o — deci cele douăzeci și patru de ore îi rămân aproape întregi.
    Corectat 2026-09-18 de verificatorul ultimei runde: o defecțiune de randare la un film de mai
    târziu în aceeași rulare iese din pas înaintea scrisorii, așa că întrebarea aceea îl așteaptă
    până la închiderea zilei. Tot de la închiderea zilei, acolo unde studioul nu a
    putut prețui o parte a filmului, cifra spune asta lângă ea, la fel în scrisoare, pe cartonașul de
    aprobare și în nota rezervării: «estimare incompletă: narația nu are preț stocat și este numărată
    ca zero». Ce nu spune: imaginile nu sunt prețuite deloc în estimare, deci nu lipsesc din ea ca
    zero, ci sunt în afara ei. Un «da» nu trece niciodată peste o poartă care refuză;
    oprirea și SAFE_MODE refuză înaintea lui și îi lasă «da»-ul necheltuit; o politică de canal
    schimbată după ce a răspuns îl retrage, pentru că a spus «da» filmului aceluia la vizibilitatea
    aceea. Pragul peste care o randare plătită devine decizia lui este
    `paid_generation_approval_threshold_usd` (5 USD implicit); cât timp stă o întrebare fără răspuns
    este `STUDIO_APPROVAL_EXPIRES_AFTER_HOURS` (24 de ore implicit, între o oră și o săptămână — sub
    o oră o întrebare i-ar putea expira înainte să o citească, peste o săptămână un «da» s-ar putea
    cheltui mult după filmul despre care a fost întrebat). **Dacă sare peste:** studioul rulează în
    modul scris în coloană, adică AUTONOMOUS_CEO, fără ca el să fi ales asta.
    Adăugat 2026-09-18 după repetiție: pe datele lui coloana arată AUTONOMOUS_CEO pentru că a scris-o
    migrarea 0043 (valoarea ei implicită), la pornirea lui, nu pentru că a ales-o el — iar
    preflight-ul o spune ca pe un fapt («Modul de autonomie este AUTONOMOUS_CEO: …»), fără să spună
    că este valoarea implicită. Tot răspunsul lui așteaptă și **cele 29 de scenarii din 2026-09-12**
    care au trecut poarta factuală (VERIFIED_PASS) și nu au fost aprobate de nimeni:
    `GET /api/v1/factual/scripts` le arată, iar butonul «Approve script» din pagina scenariilor (sau
    `POST /api/v1/factual/scripts/{id}/approve`) aprobă câte unul. Un scenariu aprobat intră în
    storyboard la ziua următoare și poate fi filmat, deci fiecare aprobare este o hotărâre de
    cheltuială; nu există o comandă care să le respingă. **Dacă sare peste:** nimic nu se pierde, dar
    fiecare zi repetă despre ele «Un scenariu așteaptă aprobarea ta înainte de storyboard.»
    Adăugat 2026-09-19: de azi studioul măsoară dacă narațiunea unui scenariu spune ce spun
    afirmațiile pe care le citează. **4 dintre cele 29 nu trec măsurătoarea**, pentru că fiecare
    citează o afirmație pe care narațiunea ei nu o spune:
    - 92028a88 citează parasolarul care răcește oglinda la 40 de kelvini, iar scena ei spune doar
      «you just block it, one layer at a time»;
    - 8d4f7306, aa3da89f și 670d6279 citează oprirea telescopului pe 8 august 2024, iar scenele lor
      spun doar, în cuvinte diferite, că NASA l-a oprit.

    Dacă aprobă cu mâna unul dintre ele, poarta dinaintea descrierii cadrelor și a randării
    (`story_gate`) îl oprește, cu motivul, înainte de orice cadru plătit. Un asemenea scenariu scris
    de acum ar fi trimis înapoi la rescriere de recenzia poveștii. Celelalte 25 trec, la fel ca cele
    două filme aprobate deja (LHC și ATLAS). Măsurătoarea s-a făcut pe copii ale bazelor repetiției,
    deschise numai pentru citire. Baza lui nu a fost deschisă.
13. **Alege mediul studioului: TEST sau PRODUCTION** — `POST /api/v1/owner/environment`, comanda
    lui versionată, sau pagina Owner. Adăugat 2026-09-18, după ce un verificator adversarial a
    răspuns la întrebarea „ce produce studioul mâine la 05:00 dacă face diseară toată lista" și a
    măsurat că lista nu îl întreba niciodată: coloana `owner_policy.environment` pornește pe TEST
    (`backend/app/models.py`), nimic din `scripts/bootstrap.py` nu o mută, iar în TEST fiecare film
    primește cel mult două cadre în mișcare (`STUDIO_TEST_MOTION_SCENES`) și restul stop-cadre, iar
    `resolve_publish_visibility` ține și „public" și „nelistat" la PRODUCTION — deci ambele filme ar
    pleca private, oricât de deschisă ar fi politica pe canal. **Dacă sare peste:** primește două
    filme scurte, făcute aproape numai din stop-cadre, pe care nu le poate vedea nimeni în afară de
    el; nu este o eroare, este exact ce înseamnă TEST, dar nu este ziua pe care o aștepta.
    **Dacă îl mută pe PRODUCTION:** filmele se fac la bugetul de mișcare întreg
    (`STUDIO_MOTION_BUDGET_USD`, 12 USD implicit pe film), iar vizibilitatea devine cea din politica
    fiecărui canal. Atunci cele două numere de la pasul 12 trebuie alese împreună cu acesta: pragul
    peste care o randare devine decizia lui (`paid_generation_approval_threshold_usd`, 5 USD) stă
    sub bugetul de mișcare, deci în PRODUCTION **fiecare** film trece pragul — sub SUPERVISED ziua
    nu ar mai face nimic singură și i-ar lăsa în fiecare dimineață câte o întrebare pentru fiecare
    film. Trei ieșiri, toate ale lui: ridică pragul peste bugetul de mișcare, coboară bugetul de
    mișcare, sau alege AUTONOMOUS_CEO și lasă porțile dure să fie cele care stau între zi și
    furnizor. Așa cum sunt acum, SUPERVISED și PRODUCTION nu pot coexista cu o dimineață autonomă.
    Adăugat 2026-09-18 după repetiție: pe datele lui coloana arată TEST, valoarea implicită scrisă
    de migrarea 0031; repetiția nu a găsit în spatele ei o alegere a lui. Și, pentru PRODUCTION: **bugetul
    lui zilnic de 15 USD ține un singur film la plafonul de mișcare de 12 USD, nu două.** Fiecare film
    ține 12 USD pentru mișcare, plus narația, înainte de prima scenă; scurtul factual este ținut
    primul, iar episodul serialului al doilea, deci episodul este refuzat de buget ori de câte ori
    scurtul a costat mai mult de circa 3 USD (auditul repetiției a socotit 2,9 USD, cu narația
    inclusă). O zi obișnuită în PRODUCTION este, așa cum stau numerele, un singur film de circa
    2,5-4,5 USD. Cele două numere pe care le poate schimba înainte de trecere: bugetul zilnic (pasul
    4), la cel puțin 24 USD pentru două filme, sau plafonul de mișcare pe film
    (`STUDIO_MOTION_BUDGET_USD`), la cel mult 7,5 USD. De azi preflight-ul îi arată asta, cât timp
    studioul este în TEST, ca linie INFORMATIV («Filmele zilei în bugetul zilnic»).
14. **Abia acum pornește ceasul** — activarea lucrării `daily_main` din panoul zilei, care este actul
    lui înregistrat (`workflow.job_activated`), și instalarea sarcinii Windows („AMN-AI Studio",
    `scripts/install_studio_service.ps1`), cu confirmarea o singură dată în `data/studio-service.log`
    că o autentificare S4U deschide cheia. **Dacă sare peste:** lucrarea zilei stă adormită și nu se
    întâmplă nimic — ceea ce este exact regula lui: generarea video costă bani și se face numai după
    ce totul s-a dovedit. Rândurile 1-13 sunt „totul": de aceea acesta este ultimul.
    Adăugat 2026-09-18 după repetiție: verdictul auditului a fost «REPARĂ ÎNTÂI». Cele două defecte
    găsite — o citire refuzată a statisticilor oprea ziua, iar cărțile treceau ca plătite clipurile
    Runway refuzate — sunt reparate în cod și dovedite numai cu furnizori imitați; repetiția gratuită
    de după reparații, pe o copie proaspătă, nu a fost încă rulată. O zi reală plătită în TEST (circa
    1,1-1,3 USD, cel mult circa 1,7 USD, fără modelele de limbaj, al căror cost este necunoscut)
    rămâne decizia lui, cu ceasul pornit de el.
15. **După prima zi cu cheltuială reală: reconciliază facturile furnizorilor** —
    `PUT /economy/reconciliations` (adăugat 2026-09-18), cu numărul facturii, ce acoperă (o perioadă
    sau un lucru numit, azi o randare) și `expected_version`, care aici este cerut pentru că
    înlocuirea unei facturi mișcă bani. Numai el vede factura, deci numai el poate face asta.
    Estimarea nu este ștearsă, ci marcată: ea rămâne documentul a ceea ce studioul a crezut că va
    costa filmul, iar perioada numără de atunci cifra facturată o singură dată, plus ce nu acoperă
    factura. O corecție este o versiune nouă, care întoarce postarea dinainte în registru.
    **Dacă sare peste:** fiecare cifră din cărți rămâne o estimare, iar diferența dintre ce a estimat
    studioul și ce a facturat furnizorul — prețul unei presupuneri — nu se vede nicăieri.

## Quality and governance (Phase D/G, 2026-09-18)

Phases D and G of running unattended: what the studio certifies about a film before the Director
sees it, and who decides that the studio may act at all. Measured on the tree before the work:
`character_drift_qc` reported `NOT_IMPLEMENTED` on every film ever made, and no gate anywhere ever
looked at a frame, so a film of eight blank fields, stripes or garbled writing passed technical QC,
the factual gate and the five publishing points and reached a channel as a finished short;
`CharacterBible.reference_assets_json` declared five slots — portrait, full body, front, side, back
— and every one of them was null in every studio that has ever run, so each generated picture of a
character was a fresh invention and a picture check would have had nothing to compare against; a
scene whose vendor refused it fell straight to the placeholder still that QC blocks from
publication, because a policy level could name one vendor and no other; and
`PolicyView.autonomy_mode` was `Literal["MANUAL"] = "MANUAL"`, a constant no command could move,
while the daily run walked twelve stages with no Owner approval between them, the Director approved
her own scripts, the media stage paid a vendor for shots and the publish stage wrote to YouTube.
`51_AUTONOMY_MODE_SEMANTICS` described three modes and the code had none of them.

**Quality control looks at the pictures before the Director does.** Every scene's middle frame is
cut from the finished film and sent, in one call for the whole film, to an employee whose provider
declares its model can see: is this a picture at all — a blank field, stripes, noise, garbled
writing is not — and does it show what the scene's visual prompt and narration asked for. The same
call carries the characters the storyboard put in each scene, with the Character Bible's canonical
face, hair, outfit, props, role symbols and palette, and, where a bible slot holds a stored asset
id, the portrait itself; a person in the wrong outfit is named with their scene, and
`character_drift_qc` no longer says NOT_IMPLEMENTED for a studio that has characters. A refusal
fails the film in every environment, as the degenerate-still check already does, because nothing in
TEST policy deliberately produces a picture of nothing. The check certifies only what it measured:
with no provider registry handed in, no employee's model declaring vision, no frame cut (no
encoder, no file), the day's token ceiling reached, or a model that narrated and never reached the
JSON, it is NOT_APPLICABLE with the reason, `passed` is None, no failure is added, and the film's
verdict is exactly what the other gates left it — and where the bible holds no characters at all the
character check stays NOT_IMPLEMENTED as it was. One film costs one vision call, two when the model
must be asked again with its own thinking on, and none at all when the check stands down; the call
is an ordinary agent run, so the day's token ceiling covers it.

**Reference pictures for the characters, and a second vendor when the first refuses.**
`POST /media/characters/{id}/reference-set` fills the five slots with real files: one prompt per
slot composed from the bible alone, each still stored as a `MediaAsset` with its own SHA-256 and
its bytes on disk under `backend/storage/character_references/{character}/`, and the asset ids
written back into the slots. A slot the vendor refused keeps what it held and is named in the
answer, so nobody is told a picture exists that was not produced. It spends image credits, so it is
the Owner's act and nothing else: it refuses under STOP AUTONOMY before the first request, asks the
budget once for the whole set through `reserve_spend` and settles or releases that hold, records an
ESTIMATED cost per produced slot, and reports `usd: None` rather than zero when the model has no
recorded price. Nothing in the runbook names it, and a test asserts that against
`runbook/stages.py`, `runbook/services.py` and `workflows/services.py`. From the slots to the film:
`image_reference_for_scene` hands the render the reference the scene's cast has, a character whose
look is locked and has no readable reference is refused rather than invented, and the reference is
passed only to an adapter that declares it can take one — the OpenAI adapter now posts it to the
documented `/v1/images/edits` endpoint as a multipart file part (`ACCEPTS_REFERENCE_IMAGE` is True,
`REFERENCE_IMAGE_VERIFIED` stays False until an Owner-approved run has actually drawn a scene that
way, because no test may buy one). And the production hierarchy resolves a second vendor: a level
may hold the Owner's `approved_fallbacks` for a purpose, a locked character narrows that list to the
technology approved for that character, the chain is bounded to one alternative per purpose per
scene (`MAX_FALLBACKS_PER_PURPOSE`), each attempt carries the connection, the model and what it is
worth at the recorded price, and a policy with no approved fallback behaves exactly as before — one
vendor, then the placeholder still that QC blocks from publication. In TEST the chain is ordered
cheapest-first, so a test still buys the cheapest compatible model; in PRODUCTION the Owner's order
stands.

**The autonomy mode became a fact the studio stores.** Migration `0043_autonomy_mode` adds
`owner_policy.autonomy_mode` (MANUAL | SUPERVISED | AUTONOMOUS_CEO) and takes the honest reading,
**AUTONOMOUS_CEO** — the Director executes T0–T3 within policy, T4 is executed autonomously nowhere,
and the hard gates are unchanged — because that is what the code has been doing, not a promotion the
migration grants. It moves only through `change_autonomy_mode`, a versioned idempotent Owner command
shaped exactly like `change_environment`, which refuses a *promotion* while autonomy is stopped or an
incident is open, and names in its Romanian refusal the two things of 51 it cannot measure
(acceptance criteria, burn-in) rather than pretending to have checked them; lowering the mode is
always allowed, as 51 requires. Beside it, a risk-tier table mapped entry by entry from 31's action
risk tiers and 32's tool risk classes, and one function `may_act(session, action, tier)` the Policy
Kernel asks before an agent acts: STOP AUTONOMY refuses every tier in every mode, SAFE_MODE leaves
monitoring and internal repair and takes the rest, T4 is refused in all three modes, MANUAL allows
T0–T1, SUPERVISED allows T0–T2 and writes an `owner_approval_request` for a T3 external write (31's
Approval object, with a nullable cost because a cost the studio cannot compute is None), and
AUTONOMOUS_CEO allows T0–T3. An action the table does not know and the caller does not classify is
refused `BLOCKED_UNCLASSIFIED`, never guessed. A test asks the five-point publishing gate for a
public film in each of the three modes and it refuses in all three: a mode decides what the studio
may attempt, never what a gate concludes.

**The day reads the new gates and the Owner's mode.** All three parts existed beside the daily run
without being in it; all three are wired. The quality-control stage hands `evaluate_media_qc` the
registry it already held and `settings.ffmpeg_path`, so a studio with a vision-capable model has its
frames looked at — and a studio without one measures the same film to the same verdict for the same
reasons, which is held by a test that runs the stage and the plain call over two identical files and
compares them. The media stage passes the plan's `image_chain` and `reference_for_scene` into the
render; the assembler draws each still through `still_from_chain`, records what each attempt cost on
the scene and on the job, and the Accountant prices a still by the vendor that drew *that scene*
instead of by the film-level record — a scene the approved alternative drew used to be charged to the
first vendor's model. A character whose look the Owner locked and whose reference cannot be read
refuses the film: the job is failed cleanly, what was already bought is costed and the hold goes back
the same second, exactly as a vendor's refusal does. And the day now says what each of its stages is:
`STAGE_ACTIONS` maps every stage to one action and one risk tier of `31_GOVERNANCE_APPROVAL_POLICY`
— performance intake T0, the drafting stages T1, research and the paid render T2, the upload T3
whatever visibility it carries — and `mode_refusal` asks `may_act` before the stage runs, again per
film before the money is held (T3 above `paid_generation_approval_threshold_usd`, five dollars by
default) and again per film before the upload. A stage above the mode is SKIPPED with the Owner's
reason, never BLOCKED, because a mode is his decision and not an incident, and the stages it does
allow still do their work. The preflight shows him which mode the day will run under and refuses
nothing for it: the line is INFORMATIONAL and the verdict is computed over the other two severities,
so it cannot fail a run structurally and not merely by happening to pass. A whole scheduled day is
now run under each mode with every vendor faked — MANUAL fetches no page, buys no shot, uploads
nothing and asks nothing, because MANUAL is already his answer; SUPERVISED films the day and writes
one `owner_approval_request` for `publishing.public_publish` instead of uploading — corrected
2026-09-18 at the closure below: **one request per film**, two on this day, because a request keyed by
its action alone let the day's second film reuse the first film's row; AUTONOMOUS_CEO publishes under
the channel's policy as PUBLISHED_SIMULATED, private, with no request raised.

Tests, by file set: 11 in `tests/test_picture_qc.py` (new), 20 in `tests/test_phase5_media.py` and 7
in `tests/test_cycle_fixes.py` (one appended each), with 77 across the five other callers of
`evaluate_media_qc`; 19 in `tests/test_character_references.py` (new), 21 in
`tests/test_media_selection.py`, 36 in `tests/test_media_providers.py` and 18 in
`tests/test_production_policy.py`, with 166 across the neighbouring media, runbook, economy, routing
and documentation suites; 21 in `tests/test_autonomy_modes.py` (new) and 26 in
`tests/test_foundation.py`, with 45, 6 and 6 across the agent, publish-policy, reset, schema and
route-authorisation files; and the wiring's own 29 (`tests/test_daily_run_stages.py`, eight
appended), 45 (`tests/test_phase10_runbook.py`, one appended) and 5
(`tests/test_autonomous_day_end_to_end.py`, three whole-day tests appended, one per mode). **The
whole suite on the integrated tree: 1148 passed, 1 skipped** (the opt-in real-Ollama test), with
`ruff check`, `ruff format --check` over 384 files, `mypy` over 143 source files and
`scripts/check_docs.py` clean; the adversarial pass that followed added four tests and re-ran
the suite at **1152 passed, 1 skipped** (2026-09-18, 9m48s), finding no defect to fix. The migration
chain is 0040 → 0043 and `main.py` pins it: 0041 and 0042 were reserved by two of the implementers and
neither needed a schema change. Corrected 2026-09-18 at the closure: the chain is 0040 → 0043 →
**0044_approval_answered** and `main.py` pins 0044; 0041 and 0042 stay reserved and unused. No
provider was called, nothing was rendered outside FFmpeg on this machine, no run was queued and no credit was
spent.

Not finished, honestly: **no vision model has ever answered the picture check, here or anywhere.**
Every test fakes the provider at its transport, by the Owner's rule of 2026-09-17 and because
`tests/conftest.py` refuses every non-loopback socket, so what is proven is the gate's behaviour —
one call per film, the frames and the bible in the prompt, a named scene on a refusal, and
NOT_APPLICABLE wherever the look could not happen. Whether a model that declares vision returns this
schema reliably on real frames needs a real render and a real model call, and the work stopped rather
than spend. `seed_initial_workforce` seeds no vision-capable model — the Director's glm-5.3 declares
completion, thinking and tools and no vision — so until the provider catalogue sync records one on an
employee the check will report NOT_APPLICABLE in the live studio, correctly and visibly in every
report. **No real render has been drawn through the second vendor either**, and a studio whose Owner
has approved no alternative has a chain of one, which is every studio today, so the path that matters
— first vendor refuses, approved alternative draws, the books charge the second model — is proven
only against fakes; the OpenAI `/v1/images/edits` multipart path is written to the documented contract
and `REFERENCE_IMAGE_VERIFIED` stays False until an Owner-approved run has actually drawn a scene that
way, because a 400 there would mean the body is wrong. `RunwayImageAdapter` still cannot be handed a
reference (`backend/app/providers/runway.py` was nobody's in this phase), so a Runway-drawn still is
honestly reported as drawn from the words — **corrected 2026-09-18 at the closure: it can**, through
the `referenceImages` field the `text_to_image` task publishes, and `ACCEPTS_REFERENCE_IMAGE` is now
True for it while `REFERENCE_IMAGE_VERIFIED` stays False. **The Owner cannot answer an approval**,
which was true when this was written and is **corrected 2026-09-18 at the closure**: a SUPERVISED day
wrote exactly one `owner_approval_request` for the upload and stopped there honestly, there was no
route to approve or refuse it, nothing consumed an APPROVED row, no stage re-attempted after one
appeared, and `owner_approval_request` was not in `maintenance.HISTORY_TABLES`, so a reset did not
clear it. All five are closed below, and the day now asks one question per film rather than one for
the day. 51's acceptance criteria and burn-in are not checked and cannot be from this database,
so the promotion refusal names them to the Owner instead; 51's department-scoped autonomy is not
implemented — the column is one global mode — and the `Literal["False"]` switches on `PolicyView`
(`external_payments_enabled`, `autonomous_firing_enabled`, `provider_auto_switch_enabled`,
`world_generation_enabled`) are still constants beside tiers that now reason about the same acts.
`backend/app/media/router.py` is still measuring films without the picture check and rendering
without the chain or the reference, so the Owner's manual render and his manual QC behave as they did
yesterday while the daily run does not — **corrected 2026-09-18 at the closure: both of its
`evaluate_media_qc` call sites now take the registry and `settings.ffmpeg_path` and `start_render`
passes the plan's chain and the scene's reference**, so the Owner's own reading of a film is the
reading the day would have given it. The character check reads the storyboard's
`character_ids_json`, which only `serial_storyboard.py` fills — a factual film records
`character_ids_json=[]`, so the record says `no scene in this film lists a character` rather than
passing — and the Director's `gather_facts` still filters the QC report to keys starting with
"measured", so the per-scene verdicts do not reach her prompt. The Director's `frames_for` cuts at
most eight frames, so a ninth scene onwards is recorded `no frame was cut for this scene`, never
looked at and never passed. The reference set uses the first filled slot for every scene rather than
choosing by shot type, and there is no frontend: no button produces a reference set, no page shows
which slots are filled, and nothing in `frontend/src` reads `autonomy_mode` yet — **corrected
2026-09-18 at the closure: the governance panel, the approvals list and the reference-set chips are
written in `frontend/src`**, and are invisible to the Owner until he runs
`npm run build --prefix frontend`, because `frontend/dist` was deliberately not rebuilt. The
research stage's mode refusal is coarse — under MANUAL the whole fetch is skipped including `retest_stale_hosts`, so a
MANUAL studio's host record goes stale — and a stage the mode skips is recorded in the run and the
day's summary but nobody writes the Owner a letter about it — **corrected in part 2026-09-18:**
the Accountant now writes once a day about the *approval requests* that are standing
(`waiting_approvals_letter`, carried by the day's close); a stage skipped because the mode itself
forbade it still gets no letter, because that is his own answer and not a question. `approval_expires_after_hours` stays the
module constant `APPROVAL_EXPIRES_AFTER_HOURS = 24` in `services.py` rather than a key in
`config.py`, because a key nothing reads is a lie about what is configurable — and since the closure
below it decides three things rather than one: how long an unanswered question stands, how long a
refusal stops the studio asking again, and how long a yes can still be spent. **Corrected 2026-09-18
in the readiness section above:** it is now `Settings.approval_expires_after_hours`
(`STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`, default 24, bounded one hour to one week), read by
`services.py` through a local import with a documented fallback of 24, and all three meanings are
named to the Owner where the setting is declared. The behaviour is unchanged.

### Closed the same day — 2026-09-18: the Owner answers, his own buttons see what the day sees, and there is a page

Three things the section above left open, in its own words: a SUPERVISED studio that "records the
question and never hears the answer", an Owner whose manual render and manual QC "behave as they did
yesterday while the daily run does not", and "no frontend for any of it". All three are closed, and
the first of them had to begin with the defect the adversarial pass named rather than with the route.

**The Owner answers, and the day acts on the answer.** A request was deduped by its `action` alone,
so the second, dearer film of a SUPERVISED day reused the first film's row, and an answering route on
top of that would have let a yes to a four-dollar film authorise a forty-dollar one. Migration
`0044_approval_answered` puts the thing the question is about on the row — `subject`: the media asset
for an upload, the storyboard for a paid render — and the key is now the action **and** the subject,
with `note`, `decided_at` and `consumed_at` beside it and an index on (action, subject, result). The
same defect existed one level up, where nothing had looked: the daily run's stage wrapper raised the
approval itself, before it knew which film, so the stage never ran, one answer would have covered
every film of the day, and a day with nothing to publish still put a question in his inbox. The
wrapper now asks the mode without asking the Owner (`ask_owner=False`): a mode that refuses outright
still refuses there, and a mode that would merely ask hands the asking to the stage, which asks per
film with that film's name, its price and its channel policy on the request.
`GET /api/v1/owner/approvals` is what is waiting — the action in Romanian, the tier, who asked, the
evidence, the expiry and the cost, with «necunoscut» where nothing in the studio could compute one and
never a zero. `POST /api/v1/owner/approvals/decision` is the answer: versioned, idempotent by command
id, behind the same write lock as his other commands, one `governance.approval_decided` event carrying
the old result and the new, 409 on a request already answered or expired and 404 on one the studio
never made. The answer is spent in exactly one place — inside `may_act`, in the SUPERVISED T3 branch,
after the stop, T4 and safe mode have had their say — so an approval only ever does what the gate
would otherwise have made him wait for, and never turns a refusal into a pass. It is spent once:
`consumed_at` is the lock and `governance.approval_consumed` the record, and an upload that then fails
asks again tomorrow rather than riding on yesterday's yes. A stop or an incident after he answers
leaves the yes unspent and still his, because neither of them is him changing his mind; a channel
policy version that moved after he answered does retract it, because he said yes to that film going
out at that visibility under that version, so the stale yes is left on the record and a fresh request
naming the new policy is raised instead. Lowering the mode to MANUAL refuses and never looks for his
answer at all, because MANUAL is him asking to be asked about everything. A refusal is COMPLETED, not
SKIPPED — the day's work done and the answer being no, the same shape as the Director's refusal — and
the film keeps its QC-PASSED report, stays unpublished and is not asked about again until his decision
expires; a question still standing is SKIPPED with the approval id in the artefacts, as it was.
`owner_approval_request` joins `HISTORY_TABLES` before `command_record`, so a reset clears it: the
questions are the agents', not his configuration, and a yes about a film that no longer exists is an
authority nothing should still be able to spend.

**The Owner's own render sees what the day sees, and Runway can draw from a reference.**
`backend/app/media/router.py` called `evaluate_media_qc` with the settings alone at both of its call
sites and `assemble_video_job` with neither `image_chain` nor `reference_for_scene`, so the same film
reported `picture_qc` and `character_drift_qc` NOT_APPLICABLE when he pressed Quality Control and
MEASURED when the stage ran it, and his render drew every scene with the one resolved vendor and no
character's reference sheet. The route now passes what the media stage passes: the plan's
`image_chain`, suppressed only when a test has injected an adapter on `app.state`, which is and stays
that render's only vendor; the plan's `reference_for_scene` whatever adapter draws, because which face
a scene must keep is a fact about the film's characters and not about the vendor; and, at both
quality-control call sites, `registry=app.state.registry` and `settings.ffmpeg_path` — the provider
that may hold a model declaring vision, and the encoder that cuts the frame it looks at. His Quality
Control button may therefore now make one vision call and cut frames inside the request, which is the
same single call per film the stage makes; with no seeing model, no registry or no encoder it is still
NOT_APPLICABLE with the reason and the verdict is exactly what the other gates left it. Nothing there
passes by absence. `ReferenceRequired` is a `ValueError`, so the render route answered it 404
"storyboard not found" about a storyboard sitting in front of him; it is now 422 naming the character,
caught before the vendor handler, so a refusal of the studio's own is never presented as a provider
fault. And `RunwayImageAdapter` now carries the contract the OpenAI adapter has: `referenceImages` on
the documented `text_to_image` task, an array of one object whose single required member is a `uri`,
built as an inline data URI by the same helper that has always validated an image-to-video first
frame — so a reference given as a path, an id, or bytes that are not a PNG, JPEG or WebP is refused
before the task is submitted, and `reference_images` is counted 0 or 1 in the attempt's raw response,
so a render's record says whether a character's face came from their sheet or from the words. No `tag`
is sent with it, because a tag means something to Runway only when the prompt names it as `@tag` and
inventing one would change the words the Director approved. `ACCEPTS_REFERENCE_IMAGE` is True because
the code builds the documented field; `REFERENCE_IMAGE_VERIFIED` stays False because no account has
ever answered one, and a test asserts that second flag so nobody can flip it on mock evidence. The
contract refusal for a model that *requires* reference images now fires only when none was given: the
reason was always the missing picture, not the model.

**The panel shows the mode, the approvals and the reference sets.** `policy.autonomy_mode` has been a
real column since 0043 and nothing in `frontend/src` touched it, so a studio running whole days as
AUTONOMOUS_CEO looked, to its Owner, exactly like one that asks before every step. The governance
panel now sits in the column that already shows the studio's state, under the module list: the mode
with the sentence `MODE_MEMORY` gives every agent when it moves, and the other two modes offered as
buttons that send `POST /api/v1/owner/autonomy-mode` with the `expected_version` the snapshot carried.
A promotion while the stop is on is refused by the page itself, in the stop's own words, because the
snapshot already says so; a promotion refused for SAFE_MODE is refused by the server and the panel
prints the server's Romanian sentence rather than a guess, since no safe-mode state is in the snapshot
to read — so a blocked button stays pressable, because pressing it answers *why* and a disabled one
cannot. Lowering the mode is never blocked there, as 51 requires, and an unconfirmed mode command is
resent only when it was for the mode now being asked for, so a slow network is one decision and a
change of mind is a different one. Beneath it, what a SUPERVISED studio wrote instead of acting:
`GET /api/v1/owner/approvals` read at most twice a minute, immediately after any decision and whenever
he presses refresh, each row showing the action in his language, what it is about, its risk tier with
31's definition in the tooltip, who asked, «necunoscut» for a cost nothing could compute and how long
the request still stands; «Aprobă» and «Refuză» send the decision command with a fresh command id, a
409 means it was answered or expired while the page was open and a 404 that it never existed, and a
backend without the route is recorded as not having it and stops being polled after one sentence,
because a panel that repeats a 404 every five seconds teaches its Owner to ignore the panel. Every
card repeats, in Romanian, that an approval lets a permitted action happen and never turns a hard
gate's refusal into a pass. On the Character Bible card the reference set is no longer the ratio
"3/5": every declared slot is a chip, filled or empty, and the button that produces them says in
Romanian that it spends image credits and produces nothing until it is pressed a second time — his
deliberate act, which is why nothing in the day calls that route. The judgements behind all three live
in `frontend/src/governance.js` so that they could be tested; the screens themselves are not tested,
because `main.js` touches the document at import and cannot be loaded by `node --test`, and no DOM
harness was invented to pretend otherwise.

**What the closure measured, and whose measurement each figure is.** No whole-suite run has been made
since these three parts landed, so the **1152 passed, 1 skipped** above remains the last whole-tree
measurement and is now older than the tree; the figures below are each named for the part that took
them. The governance part: `tests/test_approvals.py` **18 passed** (new); the four files it owns
together **75**; the three whole-day tests **5**; the runbook, publishing, publish-policy and
audit-trail suites **91**; foundation, cycle fixes, route authorisation and documentation **42** — 231
in all, with `ruff check`, `ruff format --check`, `mypy` over 187 source files and `check_docs.py`
clean. The media part: **98** across `tests/test_phase5_media.py` (23), `tests/test_media_providers.py`
(41), `tests/test_picture_qc.py` (14) and `tests/test_character_references.py` (20), ten of them new,
plus **88** across the Runway-connection, readiness, editorial-quality and media-selection suites as a
regression check. The frontend part: `npm test --prefix frontend` **102 passed**, fourteen of them the
new `frontend/tests/governance.test.js`, with `npm run check --prefix frontend` (tsc over `src/*.js`,
`checkJs` on) clean. This documentation part: `scripts/check_docs.py` and
`tests/test_documentation.py`. The migration chain is now 0039 → 0040 → 0043 → 0044 and `main.py` pins
`0044_approval_answered`, which is additive — four columns and one index on `owner_approval_request` —
and rewrites no data. No provider was called, nothing was rendered, no run was queued and no credit
was spent by any of the four.

**Still not finished after the closure.** No approval has ever been answered by a real Owner through
the real route against a real database: everything here is measured against the test engine with every
provider faked, and the migration has been walked from an empty database by every test in the run and
never against `data/studio.db`, which nobody opened. The Owner is not told that something is waiting —
a SUPERVISED day records one question per film and the run record carries the approval id, but no
letter and no notification is written, so the list is seen only by someone who opens the panel, and
whether an approval deserves the letter the Accountant writes for a refused budget is his call and not
an agent's. **Corrected 2026-09-18 in the readiness section above:** it does deserve one, and the
Accountant writes it — one letter per business date naming every standing question, carried by the
day's close; no notification is written, and the letter still leaves only in the evening rather than
at the hour the film was stopped. An approval cannot be withdrawn: once he says yes the yes stands until it is spent or
expires, because the honest way to stop a film going out is the stop, which refuses before his answer
is read at all. A film the Owner refused in the *media* stage still lands in `awaiting_owner` and
reports SKIPPED rather than getting the publish stage's COMPLETED distinction between a question and a
decision; the subject is on that stage's request, so his answer is per film there too, but the stage's
vocabulary was left alone. Neither adapter's reference path has ever been accepted by a vendor:
OpenAI's multipart body and Runway's `referenceImages` are both built from the published contracts and
asserted against faked transports, and an HTTP 400 on the first real render is the thing to watch,
because that is how the last unread contract detail announced itself. The size of an inline reference
is not checked: Runway publishes a limit on how large a data URI may be, the number could not be read
without fetching the vendor's documentation, and no guard invents a threshold, so a sheet too large
will come back as a vendor refusal rather than as a silent truncation. Whether a Runway model accepts
an *optional* reference is not a per-model fact the adapter can read — `parse_model_contract` records
only whether the contract *requires* them and `integrations/discovery.py` filters stored `api_metadata`
to a fixed field list — so `referenceImages` is treated as a property of the `text_to_image` task,
which is what Runway publishes today for both of its still models. His manual quality control can now
spend tokens, metered only by the day's ceiling and cached nowhere, because caching a measurement is
how a gate starts certifying what it did not measure this time. And the panel is invisible until he
runs `npm run build --prefix frontend`: no request in it was ever answered against a running backend,
the screens themselves have no test, the refusal card sends no `note` although the command accepts one
and the stage reports it back to him, and the character card still mixes the English labels it already
had with the Romanian the panel added.

## Money and sources (2026-09-17/18)

Phases E and F of running unattended: what a film costs before it is made, and where the day's
pages come from. Measured on a copy of the live database before the work: the check before a
render was `may_spend(engine, 0)` under a comment claiming the plan was costed, so a day at 14.99
of 15 USD started a full film; 391 `agent_run` rows on Ollama Cloud carried `cost_vr` NULL; all
nine live ElevenLabs models carried `pricing {}`, so narration was never costed at all; a render
that a `MediaProviderError` interrupted recorded no cost for the shots the vendor had already
generated; the DAILY window opened at UTC midnight while the studio's day is Europe/Bucharest; a
budget refusal was a SKIPPED stage nobody wrote to the Owner about; the Director's loop and the
mail rounds spent tokens under no ceiling; page discovery ran only through the OpenSearch address
the Owner had typed per host, and only the two Wikipedias carried one; 14 of the 36 authorised
hosts failed retrieval behind bot walls or script-only shells; the Researcher guessed addresses
that answered 404; the day read at most two topics of three pages; and the last live run fetched
0 pages and verified 0 claims, the studio living off the 98 claims verified on 2026-09-12.

**The books hold the money before it is spent, and the day begins when the studio's day begins.**
Migration `0039_pricing_truth_and_reservations` adds `provider_price`, `spend_reservation` and
`provider_cost_record.failed`. A budget period now opens at the studio's own midnight and first of
the month: `_period_start` takes the zone from the `studio` row, which bootstrap writes from
`STUDIO_TIMEZONE`, so the period the books count is the same business date the daily log closes,
and a cost at 22:30 UTC on the 17th belongs to the 18th. `reserve_spend` decides behind the write
lock and writes a RESERVED row that every budget counts until `settle_reservation` (the real cost
rows are in) or `release_reservation` (the film was not made); two films racing for the last ten
dollars get one hold, not two. `release_stale_reservations` is the watchdog's fourth sweep, for
holds older than `STUDIO_RESERVATION_TTL_SECONDS` (six hours) left by a process that died under a
render. `estimate_film_cost_micros` prices a plan conservatively before a frame exists — the
motion at the ceiling that render will be given (`motion_budget_usd` in PRODUCTION,
`test_max_cost_per_generation_usd` × `test_motion_scenes` in TEST) and the narration at the dearest
active per-thousand price over the storyboard's own voiceover — and reports `narration_priced=False`
when no voice price exists, so the stage can say the plan was only partly costed. A film that costs
less settles for less; a film let through on a hopeful estimate would spend the week.

**A price is the Owner's, or it is documented and says so.** A `ProviderPrice` row is written only
by `PUT /economy/prices` — Owner-only, idempotent by command id, versioned with `expected_version`,
provenance OWNER | DOCUMENTED | QUOTED | BILLED — or by `seed_documented_prices`, which carries one
row and one only: ElevenLabs' public list price (Creator plan, 22 USD for 100 000 credits, one
credit a character, so 0.22 USD per 1 000; Flash and Turbo bill half, so the figure is the dearer
one), marked DOCUMENTED with a note saying it is not the Owner's plan. It never overrides a row of
any provenance and adds nothing on a second run. Ollama Cloud is deliberately absent: its price is
whatever the Owner's plan says, and a guess in the books is worse than a gap the Accountant reports
as `unpriced_agent_runs`. Resource `"*"` prices every model of a kind that has no row of its own;
a model's own row outranks it. The ElevenLabs, Ollama and configured-LLM adapters take a
`price_lookup` and cost every call from what they measured — the characters actually sent, the
tokens the vendor reported — and answer None, never zero, without a price or with half of one: a
run priced on one side would be read by the budget as cheaper than it was.

**A render the vendor refused is still a cost, and a refusal is a letter.** `record_failed_render_cost`
writes ESTIMATED rows flagged `failed=True` for the scenes that were attempted, under their own
reference (`render:{job}:failed:scene:{n}:{unit}`), so a finished and a failed reading of the same
job cannot charge the same scene twice and a re-run charges nothing; the books count them like any
estimate and `GET /economy/provider-costs` labels them "ESTIMAT (randare eșuată)". `budget_refusal_letter`
and `may_run_agent` each write the Accountant's letter to the Owner once per business date, decided
behind the write lock, so two stages refused in the same minute write one letter; the Accountant
signs, the Director signs when the studio has no Accountant, and with neither the function reports
that nothing was written rather than inventing an author. `may_run_agent` is the Policy Kernel's
first gate, before the run's write transaction: it counts every token of every run since local
midnight, whatever its outcome, against `STUDIO_AGENT_DAILY_TOKEN_BUDGET` (0 = no ceiling, as the
studio has run until now), and past it the run is recorded BLOCKED_BUDGET like every other block.

**The studio finds its own pages, and the allowlist is not widened by finding them.** When a host
is tested (`test_allowed_host`) or retested by the weekly pass (`retest_stale_hosts`, seven days),
its front page is read through the same DNS-pinned, size-bounded retriever and its own search
address is looked for in `<link rel="search" type="application/opensearchdescription+xml">` and at
`/opensearch.xml`; what is found is stored as DISCOVERED (migration `0040_research_sources`:
`discovered_search_template`, `discovered_at`, `last_test_reason`), and the Owner's own address,
where he typed one, keeps winning. A host that answers 403, limits requests or serves a script-only
shell is FAILED with a reason from a closed vocabulary — HTTP_403, HTTP_ERROR, RATE_LIMITED,
SCRIPT_ONLY, NETWORK, OTHER — that the preflight can show without parsing prose. A web search API
the Owner connects through Settings → *Conexiuni* (catalog kind `search`, one HTTPS JSON contract:
endpoint, key header, result-list path, field names, the key in the vault; "Verify access" sends
one neutral word and checks the shape of the answer) may name addresses and nothing else:
`find_pages` asks the Owner's addresses, then the discovered ones, then the verified engine,
filters the engine's answers against the allowlist before anything downstream sees them, counts
what it dropped, and every page is then read by the studio's own retriever — never the engine's
copy, snippet or "answer". When any of these found pages, the Researcher's plan is a choice among
them and a guessed address is set aside unread and recorded (GUESS_SET_ASIDE); when nothing was
found, his addresses are tried as before and the escalation letter says what each answered. The
day's reading is the Owner's: `STUDIO_RESEARCH_CANDIDATES_PER_DAY` and
`STUDIO_RESEARCH_PAGES_PER_TOPIC`, four and four, clamped 1..12 so a typo cannot turn a research
pass into a crawl.

**The preflight asks whether the studio can find pages, not whether a row exists.**
`research_health` is computed from the record and probes nothing, so it is safe on every run: how
many hosts are authorised, how many were tested successfully, how many carry a search address,
which are failing and why, whether a search engine is VERIFIED, and how many SUPPORTED claims are
in hand. It reports DEGRADED with named Romanian reasons when no host passed, when there is no way
to find pages at all (no search address anywhere and no engine, which returns the Researcher to
guessing), or when fewer than ten verified claims remain — a thirty-second short spends three to
five. A DEGRADED report stops nothing by itself: a day that finds nothing completes honestly with
nothing, and the report is a fact for the Owner to read.

**The day is wired to both, and the studio has run one end to end.** The media stage reads the
day's remaining budget one line *before* it places the film's own hold (a film that counted its own
reservation against itself would render stills with money in the account), prices the plan, holds
the sum, settles only after `record_render_costs` has written the real rows, and releases on every
path where the film was not made — the Owner's stop between two scenes, an encoder that cannot run,
a vendor's refusal, which is costed first. The research stage gathers the Owner's number of
candidates, re-tests every authorised site nobody has tested for a week (one front page each,
nothing on the other six days, so no new scheduled job was needed) and the preflight reports the
health. And the project has the test it never had: `tests/test_autonomous_day_end_to_end.py` fires
the scheduled job, lets the worker execute the real runbook with the real stage runners against a
temporary database, and holds the whole day — twelve stages under a `scheduled:` idempotency key, a
claim extracted from a source and verified by a second employee, a script the Director passed, two
films encoded by FFmpeg and measured by quality control, both published private through the five
gates each to its own channel, and yesterday's serial episode grounded in yesterday's events and
approved under the Owner's Channel B policy — then a second tick that starts nothing. Only the
vendors are faked: one language model answering each prompt in that prompt's own schema, the local
picture and voice adapters, the publishing simulator. No socket leaves the machine, nothing was
rendered by a paid vendor and nothing cost money.

**Every adapter now costs what it spends, and the price table reaches the day.** The prices
existed and nothing carried them: `price_lookup` appeared in the three adapters and in
`economy/prices.py` and at no place where the studio actually builds one, so every
`agent_run.cost_vr` was NULL and every narration unpriced whatever the Owner had typed, and the
budgets counted a fraction of the day. The four construction sites are wired — the seeded Ollama
endpoint (`main.register_seeded_ollama`), the language connections loaded at start-up
(`integrations.services.load_registry`), the one re-registered when the Owner saves a connection
while the studio runs (`integrations/router.py`), and both doors into a voice
(`media.factory.tts_provider` and `tts_provider_for`) — each handed `price_lookup(engine, kind)`,
one short read per call, so a price typed this afternoon costs this evening's runs without a
restart; a model with no row still reports None, never zero. `integrations/credits.py` and
`integrations/discovery.py` are deliberately left without one, because reading a subscription or
listing voices generates nothing, and the list of priced sites is written down in
`tests/test_pricing_truth.py::PRICED_CONSTRUCTION_SITES` with the reason beside it — the scan that
walks it fails on a fifth site added later without a table, and fails too if a listed module stops
building an adapter at all. `seed_documented_prices(engine)` has a caller at last, in
`scripts/bootstrap.py` beside `seed_chart_of_accounts`: the one figure ElevenLabs publishes, marked
DOCUMENTED, never Ollama Cloud, and never over a price of any provenance, so a second bootstrap over
a live studio leaves the Owner's own price standing. And the failed render that recorded nothing is
now proved as well as fixed: a three-scene film whose vendor refuses the third leaves a FAILED job
carrying exactly scenes one and two — the attempt, never the plan — and `record_failed_render_cost`
writes two ESTIMATED rows flagged `failed=True`, referenced `render:{job}:failed:scene:{n}:voice`,
with a second reading charging nothing.

**The Owner can see the state of his sources, and the money that is held as well as the money that
is gone.** `research_health` and the forced retest were computed by the research half and called by
nothing; both now have a route under the factual router, behind the same Owner-only dependency the
allowlist endpoints already carry. `GET /api/v1/factual/research/health` returns the report as the
service builds it and probes nothing, so the screen may ask on every refresh;
`POST /api/v1/factual/research/allowed-hosts/retest` runs `retest_stale_hosts` with
`max_age_days=0`, which is what makes it "now" — the runbook's weekly pass leaves a site tested this
week alone, and this is the Owner asking anyway after fixing something. A test pins the 401 on both
from the other side of the door. *Cercetare → Surse* now prints, for every authorised site, whose
search address is in force (his, or the site's own), the address the studio found on the site itself
and when it found it, and, where the last test failed, the closed-vocabulary reason before the
site's own words for it, so a bot wall and a script-only shell are two different jobs rather than
one paragraph of Romanian; the header line above the list is the health report rather than a count
of rows, «Try it» is offered wherever any address is in force, and a «Test the sites» button asks
for the retest — the first control in the interface that reaches the network on the Owner's click.
In the Books office a run blocked by the day's token ceiling reads as a sentence instead of the raw
word BLOCKED_BUDGET, each budget card prints the sum held for films in production beside the
percentage it is already counted in, and the day prints what is held, what was paid for renders that
failed midway, and how many runs have no recorded price — named, because an unpriced run is real
usage the books cannot value and a total that hid it would read as complete.

Tests, by file set: economy 70 passed (`tests/test_pricing_truth.py` new, with
`test_phase11_economy`, `test_books_and_history`, `test_economy_under_concurrency` and
`test_schema_and_audit_trail`); research 87 passed (`tests/test_research_sources.py` new, 25 tests,
with `test_factual_agent_pipeline`, `test_claim_verification`, `test_sources_and_readiness`,
`test_research_retrieval` and the migration's schema match); the wiring 2 passed
(`tests/test_autonomous_day_end_to_end.py`, new), with 21 (the daily run's stages), 30 (scheduler
and worker), 44 (the runbook and its preflight) and 38 (the adversary, watchdog and sources files,
two of whose assertions the wiring changed). The whole suite on the
integrated tree: **1028 passed, 1 skipped** (the opt-in real-Ollama test), 1029 collected; ruff,
`ruff format --check` and mypy clean on every changed file; `scripts/check_docs.py` passes.
After the closure and its adversarial verification the whole suite is **1067 passed, 1 skipped**,
with `ruff check`, `ruff format --check`, `mypy backend` (183 source files) and
`scripts/check_docs.py` all clean.
The closure measured its own: 17 in
`tests/test_pricing_truth.py` (six new, each written failing first) and 19 in
`tests/test_phase5_media.py` (one new); 108 across the media, discovery, settings and
multi-LLM files and 69 across the adversary, production-policy and economy files; 15 across
`tests/test_phase4_factual.py` and `tests/test_sources_and_readiness.py` for the two new
routes; and 87 frontend tests, with `tsc`, ruff, `ruff format --check` and mypy clean.
Nothing ran against a real model, provider or platform, no daily run was queued and no
credits were spent.

Not finished, honestly: **the Owner's own prices are not in the database.** Wiring the lookups made
a cost computable; it did not invent one. Until `PUT /economy/prices` carries a per-million input
and output price for each model the studio actually runs — Ollama Cloud above all, which is
deliberately never seeded — every `agent_run.cost_vr` stays None and the Accountant keeps reporting
`unpriced_agent_runs`. Narration is the one exception from today: bootstrap seeds the DOCUMENTED
ElevenLabs figure, so a studio with no Owner price costs narration at the public Creator-plan rate
and says DOCUMENTED, not OWNER — that figure is the published list and not his invoice. The live
database has still not been migrated to `0040_research_sources` or bootstrapped, which is an Owner
act because no test may open `data/studio.db`; running bootstrap again is safe, the seed never
overriding a price of any provenance. `frontend/dist` is not rebuilt, so the served page still
carries the old bundle: a build is the Owner's release step, and nothing in this closure was seen
rendering in a browser. Reconciling ESTIMATED rows against a vendor's invoice — a BILLED row
replacing the estimates of one render — still has a vocabulary and no function, so every figure in
the books is ESTIMATED or DOCUMENTED. **Corrected 2026-09-18 in the readiness section above:**
migration `0045_reconciliation` and `PUT /economy/reconciliations` give it a function, which is the
Owner's to use because only he sees the invoice; until he uses it, every figure is still ESTIMATED or
DOCUMENTED. The one question the closure left open was answered in its
verification rather than left standing: the `except RenderStopped` branch released the film's hold
and recorded nothing, although the assembler leaves the same `production_json` for the Owner's stop
as for a vendor refusal, so a film stopped after one scene read in the books as a film that cost
nothing. The branch now costs the attempt before letting the hold go, in the order the refusal
branch already used — the switch decides whether the studio keeps working, not whether a vendor has
already been paid. Neither new route was exercised against a real site, and the
script-only heuristic and the OpenSearch discovery are still proven only on fixture HTML modelled on
the hosts that failed, because `tests/conftest.py` refuses every non-loopback socket — the first
retest against live hosts, which the Owner can now ask for with one button, is the measurement. And
the end-to-end test still skips where FFmpeg is absent, by the convention
`tests/test_phase5_media.py` already uses, its two tests taking about fifty seconds together because
they encode two real films.

### Ce are Owner-ul de făcut → mutată sus, la «Readiness for the first day (2026-09-18)»

Mutată acolo pe 2026-09-18, rescrisă ca listă ordonată a dimineții primei zile adevărate.
Niciun rând de aici nu a fost scos: fiecare este acum un pas numerotat, cu comanda sau ecranul
lui și cu ce se întâmplă dacă sare peste el, alături de pașii pe care i-a adăugat faza aceasta
— preflight-ul citit înaintea oricărei cheltuieli, admiterea unui model care poate privi și
reconcilierea facturilor furnizorilor.

## Delivery and the serial (2026-09-17/18)

Phase B/C of running unattended: what the studio delivers, and the serial as a film. Measured
before the work: `_publish` in `backend/app/runbook/stages.py` took `ready[0]` — the first bound
slot, whatever film came first — and uploaded at a constant `privacy_status="private"`;
`ChannelRecord.upload_privacy_default` was read by nobody on a publish path;
`scheduled_publish_time` was stored on the intent and never sent, and the YouTube adapter had no
`publishAt` and no `videos.update`; performance intake measured every publication through the
first bound slot's account; every `domain_event` carried visibility OWNER and the showrunner was
handed raw `key=value` payload pairs (model ids, message text, prices); continuity between
episodes was one previous title and a roster size; nothing consumed an APPROVED episode, and
`serial_queue` ran last, after the day's log, so no run ever filmed one; the day's log was frozen
at the run's own hour (the live log of 2026-09-16: 92 events, one of them narratable);
`captions.srt` was written beside the render and never muxed or burnt in; nothing normalised
loudness; quality control had no audio and no caption category although
`../architecture/08_VIDEO_PIPELINE.md` lists both; a scene whose motion model refused became a
slow push recorded in a note nobody read; and a render read the Owner's stop never — eight
scenes ran to their end after STOP.

**The Owner sets how a channel publishes, and the studio can say which policy published what.**
`channel_record` carries a versioned publish policy — `autonomous_privacy` (private | unlisted |
public, default private), `public_publish_enabled` (false), `publish_delay_minutes` (0),
`policy_version` (1), `policy_changed_event_id` — migration `0037_publish_policy`, changed only
through `POST /publishing/channels/{id}/publish-policy` (`PublishPolicyCommand`, `command_id`,
`expected_version` = the channel's `policy_version`), which follows `change_environment`
exactly: the write lock first, idempotent by command id, a stale version 409, NO_CHANGE without
a version bump or an event, and on a change `publishing.channel_policy_changed` with the old
and new values and the environment. "public" is accepted only with `public_publish_enabled=true`
in the same command and never while the studio is in TEST (since 2026-09-18 the command is
judged on the state it would leave, so the flag alone cannot re-arm a policy already "public"
while the studio is in TEST). `resolve_publish_visibility(channel, environment)` decides in one
place: private unless the policy says otherwise, public only with the flag and PRODUCTION
(corrected 2026-09-18: unlisted also needs PRODUCTION — an unlisted film is watched by anyone
with the link, so in TEST an unlisted policy resolves private and takes effect when the Owner
moves the studio to PRODUCTION), and a public policy with a delay yields a private upload with
`publish_at` and `release_privacy="public"`, because YouTube schedules a release as a private
upload carrying `status.publishAt` — which the adapter now sends (and refuses on a non-private
upload before any request leaves), beside `containsSyntheticMedia` and the disclosure;
`update_visibility` (videos.update, the synthetic flag re-declared) exists with no production
caller. **A film goes to its own channel or nowhere.** `select_channel_for` reads the storyboard
(`channel_id`, else series key `office_serial` → OFFICE_SERIAL, else MAIN_FACTUAL; corrected
2026-09-18: a `channel_id` whose channel type contradicts the series key is SKIPPED, not
followed, in either direction); a slot unbound or bound to a connection no longer CONNECTED is
SKIPPED by name, with no fallback to another channel. The five gates are untouched; a sixth
(`POLICY_AUTHORISATION_GATE`) runs only for a publication that would be seen and requires the
channel's current `policy_version` stamped on the publication
(`publication_record.policy_version`, in the `publishing.video_published` payload with
`publish_at`) and a requested visibility no more open than the policy resolves to; the Owner's
own intent endpoint is held to the same rule. Analytics ask per channel:
`analytics_provider_for_channel` builds the adapter from that slot's bound CONNECTED account
only, and `measure_channel_publications` measures that channel's PUBLISHED rows and nothing
else.

**The serial is a Channel B film, from a sanitised full-day log.** `app/story/projection.py`
classifies every event type by a table that is OWNER_PRIVATE by default; a PUBLIC_SAFE type
names the payload keys that may be mentioned and a plain phrase for the fact, and every
description passes `redact` (anything shaped like a key or token, a provider or model
identifier, a price, a URL, an address or an account number); a letter to or from the Owner is
projected as the fact that it was written, never its subject. `close_daily_log` stores the
projection on `daily_studio_log.narrative_projection_json` (migration `0036_serial_continuity`),
a log closed before the column existed is projected once from its own committed events, and
`write_episode` grounds beats against the projection only, so a beat citing a private event is
refused as ungrounded (tested: a fake key, a model id, a price and a URL in the day's raw
payloads reach neither the projection nor the prompt). `continuity_state` (one versioned row)
holds the canon episode number, open threads, recurring elements and the last three summaries;
the showrunner's prompt carries them with a "who they are" line per roster member quoted from
the Character Bibles; canon advances only on approval, once per episode. **The Director reads
the episode** (`app/story/review.py`): five computed checks first — grounding, privacy, length
(at most 8 beats, 45–70 s of dialogue), cast, accessibility — and only then her verdict through
`run_agent_task` with the episode as inert data; a FAIL rejects it with her notes and a HANDOFF
letter to the showrunner (one rewrite, then REJECTED); a PASS approves it with
`reviewed_by="director"` only when the OFFICE_SERIAL channel's `director_may_approve_episodes`
is set, otherwise the episode stays DRAFT for the Owner with the review on it. **An approved
episode becomes a storyboard** (`app/media/serial_storyboard.py`, `storyboard_from_episode`):
one scene per beat, the beat's dialogue as the voiceover, the scene and the characters' bible
lines as the visual prompt, bible ids in `character_ids_json` so a locked character's voice is
bound where the Owner has bound one, 9:16, `channel_id` = OFFICE_SERIAL,
`series_key="office_serial"`, behind a claim-less `ScriptDraft`
(`story_json.kind="office_serial_episode"`) with a `StoryReview` PASS written from the episode
review — in exactly the shape `generate_storyboard_from_script` produces (tested field for
field), so render, narration review, QC and publish run unchanged. `run_serial_stage`
(`app/story/serial_stage.py`) does the whole of it for the newest CLOSED log without an episode
and reports every content outcome — a quiet day, a refused draft, a double FAIL, an episode left
for the Owner — as COMPLETED with the reason; only a provider or network fault is raised, as
`TransientStageError`. Routes: `POST /story/episodes/{id}/review`,
`POST /story/episodes/{id}/storyboard`, `GET /story/continuity`,
`POST /story/logs/close-previous`.

**Every film carries captions and normalised loudness, and a mostly-still film is a gate, not a
note.** `backend/app/media/toolchain.py` owns one reading of one filter: `loudnorm` at −14 LUFS
/ −1 dBTP, measured on the joined narration first and applied as one linear gain
(`linear=true`; the one-pass mode audibly breathes on speech), with `LOUDNESS_RANGE_LU` 11 so
narration at 5–9 LU stays in linear mode; the manifest records target, filter, input and output
readings, and a placeholder render on the Owner's FFmpeg 9.0.1 lands at about −14 LUFS in band
with the true peak well under the ceiling. Captions are timed from the narration actually
recorded (`audio_seconds`, written per scene after synthesis), one cue per sentence, lines
wrapped to two of at most 42 characters and balanced, the SRT written after the voice pass and
always beside the film; with `captions_burn_in` (default true) it is burnt in above the bottom
fifth of the frame (measured on a rendered 1080×1920 frame: 50-pixel white type with a dark
edge and no box, baseline 390 px above the bottom). The motion summary counts `motion_scenes`,
`fallback_scenes` (asked and not delivered) and `skipped_scenes` (policy). Quality control
gained `audio_qc` (measured from the finished film, in band and under the ceiling),
`captions_qc` (valid SRT, two lines / 42 characters / no overlap, inside the film, covering the
narration at a word-sequence ratio of at least 0.95) and `motion_qc` (a PRODUCTION film whose
fallback scenes exceed `max_fallback_scenes`, default half, fails; in TEST the same count is a
warning); all three enter the verdict, and a check that cannot be made fails rather than passes.

**The daily run delivers to two channels, films the serial the same day, and stops between
scenes.** `STAGES` now puts `serial_queue` between `script_and_storyboard` and `media`
(the runbook document is renumbered to match, §7 the serial queue and §12 the daily log, with
its indexed hash updated), `_serial_queue` is `run_serial_stage`, and `_media` renders one
factual storyboard then one serial storyboard (told apart by the storyboard's series key
through `channel_type_for_storyboard`) through the same story gate and the same camera, asking
`may_spend` before each film — a refusal before the first film is SKIPPED as before, a refusal
after it names the film skipped (`artefacts.skipped_for_budget`). `execute_daily_run` closes
yesterday's log after a non-blocked preflight and before the stage loop (`close_previous_day`,
retried like a stage, recorded on the preflight line as `artefacts.previous_day_log`); today's
close at the end of the run is unchanged. `_publish` collapses the QC-PASSED queue to one entry
per film, routes each through `select_channel_for`, refuses a film whose slot is unbound or
revoked with the slot's name and never sends it elsewhere, resolves the visibility once and
passes it to the gate pre-check, `publish_media_asset` (with `policy_version` and
`scheduled_publish_time`) and the outcome (`artefacts.published[]` with channel, privacy,
release privacy, publish_at, policy version and the reason); one film per channel per run; a
studio with no slot bound at all is still SKIPPED with the old wording before films are looked
for. `_performance_intake` measures per channel and names an unbound slot in
`artefacts.skipped`. `assemble_video_job` polls `stop_requested` between scenes and before each
motion shot; a set stop fails the job with `STOP_REASON` ("Randarea s-a oprit între scene:
AUTONOMIE OPRITĂ …"), records no asset and raises `RenderStopped`, which `_media` reports
BLOCKED with the Owner's reason (PARTIAL, no safe mode) (corrected 2026-09-18: the render alone
read the stop, so a stop set during the factual film still started the serial's render; `_media`
now reads `stop_requested` before each film and reports BLOCKED naming the film it did not
start). `settings=` reaches the camera
(captions burn-in) and quality control (the fallback ceiling): `captions_burn_in` (true) and
`max_fallback_scenes` (none = half the scenes) are settings. `ScheduledJobView` exposes
`run_at_local` and `timezone`.

**The closure (2026-09-18): the serial film reaches Channel B without an Owner's click.** Two
measured defects stood between an approved episode and the serial's channel. The Director's
film review refused every serial film before any model: `gather_facts`
(`backend/app/agents/editorial.py`) hard-rejected a script with no claims ("scenariul nu se
sprijină pe nicio afirmație") and her brief said a film about the studio itself is REJECTED —
both right for a factual film, both wrong for a dramatisation — so `_publish_one` returned her
refusal before the routing ever saw the film. A serial film is now recognised by the marks the
serial storyboard already carries (`is_serial_film`: series key `office_serial`, or the
script's `story_json["kind"] == "office_serial_episode"`); for it the claims-based verdicts are
not asked, the facts say so plainly (`serial: true`, `series_key`, `episode`), and the brief is
the episode review's (`instructions_for`): a dramatisation makes no claims about the world and
needs no sources, and is judged for the situation, the turn, the payoff, whether each character
sounds like a person, whether the humour is in the situation rather than in explaining the
studio. Everything not about claims is unchanged for both kinds — no script, under forty words,
the wrong audience language and a blank frame still mean REJECT without a model — and a factual
script that rests on nothing is refused in the same words as before (tested, so the exception
cannot widen). And `director_may_approve_episodes` was read from Channel B's `series_rules_json`
and written by no command — the production-policy validator keeps that JSON to
`{series_key: {purpose: selection}}` and would have refused or overwritten the key — so a
Director's PASS left every episode DRAFT and the serial never became a storyboard on its own.
The flag is a column of the publish policy now (`channel_record.director_may_approve_episodes`,
NOT NULL, default false; migration `0038_director_may_approve_episodes`, which `main.py` pins),
in `policy_snapshot` and `ChannelView`, set only through `PublishPolicyCommand` under the
command's existing rules (stale `expected_version` refused, idempotent by command id, NO_CHANGE
without an event, a change bumping `policy_version` and recorded with old and new). A fresh
channel leaves episodes to the Owner; nothing sets the flag on its own. The mechanical leftovers
went with it: the media route's render button and standalone QC pass
`settings=request.app.state.settings` like the daily run, so the Owner's button makes the film
under the same rules; `continuity_state` is in `HISTORY_TABLES`, so a history reset no longer
leaves canon summaries pointing at deleted episodes; the five mypy `union-attr` errors in
`qc.py` are gone; `YouTubeAnalyticsProvider` takes `channel_id` and reads `STUDIO_YOUTUBE_*`
only from a bare constructor, so an adapter built from a channel's bound account no longer
inherits an access token from the Owner's machine; and `PolicyView.public_publish_enabled` is a
real bool — any channel may publish publicly — computed in `policy_view(policy, session)`, so
the snapshot and the result of the very command that enabled it agree.

Tests, by file set: `tests/test_publish_policy.py` 30 (29 new, plus the Director's leave);
`tests/test_serial_pipeline.py` 34 (new); `tests/test_media_toolchain.py` 9 (new) and
`tests/test_phase5_media.py` 18; `tests/test_daily_run_stages.py`, `test_phase10_runbook.py`
and `test_scheduler_worker.py` 89 with 9 new; the closure added 3 to `tests/test_editorial.py`
and 1 each to `test_publish_policy.py`, `test_phase5_media.py`, `test_phase7_analytics.py`
(13), `test_reset.py` (3) and `test_foundation.py` (26), each red first on the measured defect.
The integrator ran the whole suite at the commit: **945 passed, 1 skipped**; with the closure's
nine new tests the collection is 954, and the whole suite with both closures present is the
verifier's to run. ruff and mypy are clean on every changed file and `scripts/check_docs.py`
passes. Nothing was run against a real model, provider or YouTube: the camera, the publisher,
the analytics adapter, the showrunner and the Director are faked at the stage or provider
boundary, as the rules require; no daily run was queued and no render was paid for.

Not finished, honestly: no test drives a serial film through `_publish_one` to Channel B end to
end — the Director's serial brief is tested at `editorial_review` with a scripted model and the
routing with the review faked at the stage boundary; the two halves agree by construction on
the same series-key mark, and the first real day with Channel B bound should be watched, as
should the first real scheduled upload (`publishAt` and `videos.update` were exercised only
against a faked transport); whether `glm-5.3` judges an episode well under the new brief is
unmeasured until a real day; today's log is still closed at the end of the run, so a date whose
run completes is frozen at the run's hour and `close_previous_day` returns it unchanged the next
morning — a full-day log for every date needs that end-of-run close moved, which is the
runbook's decision and is recorded as open; one voice per scene: the assembler synthesises a
single voiceover per scene, so a beat with two speakers is voiced by the first locked character
or the narrator, and the seeded bibles carry no voice binding, so until the Owner binds voices
every scene is the narrator; redaction is pattern-based and over-redacts (years, four-digit
counts, tokens such as `mp4`), and `DomainEvent.visibility` itself is unchanged, still OWNER
everywhere; the old `notable_events_json` descriptions still carry raw payload pairs in the
Owner-only log API; continuity does not track the office layout version, employment intervals
or a canonical character version; caption coverage is matched against the storyboard text, not
transcribed from the audio, and the caption font is Arial by name rather than a licensed studio
face; `upload_privacy_default` and `update_visibility` remain, unread and uncalled;
`YouTubeAnalyticsProvider.from_verified_settings` still falls back to environment credentials
when the bound connection is not exactly one CONNECTED row (`analytics_provider_for_channel`
never calls it); no frontend screen sets the publish policy or the Director's leave — the
Owner has the API (`POST /api/v1/publishing/channels/{id}/publish-policy` with the channel's
`policy_version` as `expected_version`) until one does — and the scheduler panel does not yet
read `run_at_local`; three test files appended in the closure carry LF endings in the working
copy, which a checkout rewrites to CRLF without changing content; the daily job is still
dormant, by the Owner's rule, and no daily run has been queued by anyone.

**Phase B/C tried as an adversary, seven defects closed (2026-09-18).** The whole suite ran green
as delivered — the verifier's run 1, before any of its fixes: 953 passed, 1 skipped; ruff, mypy
(179 files) and `scripts/check_docs.py` clean — and twenty-one adversarial tests in
`tests/test_phase_bc_adversary.py` then measured what the rules had not yet been asked: an
unlisted policy resolved unlisted in TEST (an unlisted film is watched by anyone with the link;
`resolve_publish_visibility` now holds it to PRODUCTION like public, and the two tests that had
encoded the old reading moved to PRODUCTION); with the privacy already "public" from a PRODUCTION
day, `public_publish_enabled=true` in TEST was COMMITTED (the command now refuses on the state it
would leave); a serial-keyed storyboard pinned to Channel A by id was SELECTED for Channel A while
the media stage filmed it as the serial (`select_channel_for` refuses a pin that contradicts the
key, both directions); a currency-first price, a scheme-less link and an AWS-shaped key in a
*safe* title reached the showrunner prompt (three patterns added to `projection.py`, ordinary
titles unchanged); a key in the episode's summary passed the Director's privacy check and would
have entered canon and every later prompt (`episode_checks` now reads the summary, the opened
threads and the recurring elements); and `_media` read the Owner's stop never — a stop set during
the factual film started the serial's render (the stage reads it before each film and reports
BLOCKED). `tests/conftest.py` gained an autouse guard that refuses any socket that is not
loopback, so the Owner's rule that no test spends at a vendor is proven per run rather than
promised; every adapter goes through urllib or http.client, which the guard covers. Held without a
defect: the Owner's leave per channel, one rewrite, a closed log unchanged by late events, the
blank-frame rule for both kinds of film, loudness and captions QC naming their cause, the fallback
gate, the per-film budget. After its fixes the verifier ran the changed files (238, 103 and 21
passed; the new file was 13 red first); the whole suite on the final tree is the committer's run,
and no figure is claimed for it here. Not run against any model, provider or YouTube; no daily run
queued.

## The clock, and a day that asks again (2026-09-17)

Phase A of running unattended: the studio's own clock, and the durability under it. Measured
on a copy of the live database before the work: the daily job had never fired by itself; the
one thing that had stopped the studio for days was a single transient error — SQLite's
"database is locked" at the wrong second — recorded with the weight of a bug, which opened
safe mode and set the autonomy stop; no provider adapter retried anything, so one 503 from
the voice vendor or one 429 while Runway was polled was a failed scene or a SKIPPED stage;
two `video_render_job` rows had been RENDERING since 2026-09-12 with `finished_at` NULL;
`reconcile_publication` had no caller outside the tests; and the worker lived only inside
the foreground process `start.cmd` opens.

**A fault has a class.** A stage's exception is read for its shape and its chain
(`classify_fault`, `backend/app/runbook/services.py`): TRANSIENT is the world being slow — a
timeout, a connection refused or reset, DNS, a provider's 408/425/429/5xx wherever the
raising code put the status (`MediaProviderError.http_status`, `HTTPError.code`, the
"HTTP 502" in `ConfiguredLLM`'s message), SQLite's and SQLAlchemy's `OperationalError`,
`RemoteStateUnavailable`, and a `TransientStageError` a runner may raise when only it can
tell. The walk follows the exception chain as a traceback would, so `media_http`'s "could
not be reached from OSError" is seen for what it is. HARD is everything else — a wrong value,
a policy refusal, a missing file, a full disk, a bug. A transient fault is retried in place,
`STUDIO_STAGE_RETRY_ATTEMPTS` (3) times after the first failure with backoff 20, 40, 80 s,
each retry a `runbook.stage_retrying` event; a stage still failing makes the run FAILED with
`fault_class` TRANSIENT on the stage, the run and the new `daily_run.fault_class` column
(migration 0035), and does not open safe mode. A hard fault keeps the old behaviour: FAILED,
safe mode, the autonomy stop set, a person looks. **Corrected 2026-09-18, after the rehearsal on
the Owner's data: a failed stage did not cost only itself — any failure blocked every stage after
it, so one statistics token refused at performance intake left the day with nothing filmed, and a
hard fault in any stage, an HTTP 4xx from Google included, opened safe mode and set the autonomy
stop.** Since that day a failed stage blocks only the stages that take their input from it
(`STAGE_PREREQUISITES`), and a hard fault opens safe mode only where it is a P0 — in media, publish
or the day's log, or a database integrity error in any stage (`SAFE_MODE_STAGES`); anywhere else it
costs its stage, its dependants and one letter. See «The rehearsal on the Owner's data
(2026-09-18)» above.

**The clock re-attempts a day that could not run.** A clock-fired run is skipped only when
the date already has a run that did work (COMPLETED or PARTIAL) or `STUDIO_DAILY_MAX_ATTEMPTS`
(3) is spent; a BLOCKED preflight or a TRANSIENT failure queues attempt n+1 (corrected
2026-09-18: a TRANSIENT failure queues it only when it cost the day's films — a stage from
selection to publish lost — because a re-attempt re-runs the whole day and would buy a second film
to recover a report; a day whose films went through is PARTIAL and done) under the
idempotency key `daily-retry-<date>-<n>`, held `STUDIO_DAILY_RETRY_SECONDS` (1800) by the
queue's `next_attempt_at` gate (`enqueue_task` gained `not_before`, and the gate is now
tested). A retry that outlives its date skips itself; a waiting retry no longer refuses the
Owner's button; the Director's letter about a stopped day is written once, after the day's
last attempt.

**The day is on the wall clock.** `scheduled_job.run_at_local` ("HH:MM") and
`scheduled_job.timezone` put a job at the next occurrence of a local hour, DST-safe (tested
across Bucharest's 23- and 25-hour days). `daily_main` is seeded at
`STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) in `STUDIO_TIMEZONE`, follows the setting on every
start-up and stays dormant: waking it schedules the next 05:00, never a fire on the spot.

**STOP cancels a day in flight.** The switch is read again before every stage; a day already
running stops where it is, the remaining stages BLOCKED "Oprit de AUTONOMIE OPRITĂ.", the run
PARTIAL if any stage completed (the log is then closed, a partial day being a day) else
BLOCKED, no safe mode, no letter. `stop_requested(engine)` is exposed for the loops inside a
stage to poll between scenes; a runner that raises or returns BLOCKED while the stop is set
is recorded as the Owner's stop, not a fault.

**The adapters ask again before they fail the day.** `backend/app/providers/retry.py` holds
one policy, `call_with_retries`, for every outbound call in ElevenLabs, OpenAI images, Runway
(submit, poll, download, contract, organization), the seeded Ollama adapter, `ConfiguredLLM`
and YouTube (token refresh, session, chunks, status, search): bounded exponential backoff
with jitter — 1 s doubling, `STUDIO_PROVIDER_RETRY_ATTEMPTS` (3) attempts, one wait capped at
`STUDIO_PROVIDER_RETRY_MAX_SECONDS` (30) — on 429, 5xx and a connection that never opened,
never on another 4xx; a vendor's Retry-After is waited out exactly when it fits under the
cap. The HTTPS boundary (`media_http.request`) now tells the two failure phases apart
(`unsent`, `unanswered`) and carries the vendor's status and Retry-After on the exception. A
billed request — a narration, a still, a Runway task, an LLM generation — that left and got
no answer is not sent again, because the vendor may have served it; reads are. Runway's
estimated credits are recorded once, from the answer that succeeded. The error after the last
attempt is the vendor's own class and fields with "(after N attempts)" on it; the log gets
attempt numbers, status and class, never the error text. Nothing about what "verified" means
for a provider changed.

**The watchdog.** `backend/app/workflows/watchdog.py` (`WATCHDOG`, job `watchdog`, seeded
ACTIVE every `STUDIO_WATCHDOG_INTERVAL_SECONDS` (600), behind the autonomy stop like
everything scheduled; the module is imported only when a task fires, and a build without it
dead-letters the fire with the reason) does three things per pass and records each. A render
RENDERING longer than `STUDIO_RENDER_STUCK_AFTER_SECONDS` (three hours) is failed the way the
assembler fails one — status, `finished_at`, "Blocat: fără progres de N ore" on the row, a
`media.render_failed` event — and the VideoEditor left typing by the dead process is marked
idle. Every publication in REMOTE_UNKNOWN or FAILED_RETRYABLE goes through the reconciliation
that already existed (`reconcile_publication` for an unknown one with a remote id,
`execute_publication`'s retry path for a retryable one, which asks the platform by
idempotency key before it uploads); a platform that does not answer is asked
`STUDIO_RECONCILE_MAX_ATTEMPTS` (3) times, counted from the watchdog's own
`publishing.watchdog_reconcile` events, then the row is moved to NEEDS_RECONCILIATION with a
`publishing.reconcile_exhausted` event and a note for the Owner, and not asked again; an
unknown publication with no remote id — YouTube's UNKNOWN never carries one — is handed over
at once. Lapsed task leases are reported and left alone: `claim_task` re-claims an expired
lease itself, and the test proves it. The pass changes nothing while STOP AUTONOMY is set.

**The studio as a service.** `scripts/install_studio_service.ps1` registers a Windows
Scheduled Task "AMN-AI Studio" (`start.py --skip-frontend` at logon and at startup, three
restarts one minute apart, no execution time limit, output in `data/studio-service.log`,
`-RunWhenLoggedOff` for an S4U logon), idempotently and printing what it registered;
`scripts/uninstall_studio_service.ps1` removes it. Both are the Owner's to run and were
parsed here, not run. The README section "Running as a service" says how, that the daily
job stays dormant until the Owner's recorded activation, that the machine must not sleep at
the run hour (the power plan is the Owner's), and how to check with `schtasks /Query`.

Tests, by file set: runbook, scheduler/worker and the migration schema match 66 passed;
`tests/test_provider_retry.py` 28 passed (new), with 503-then-200, 400-not-retried,
exhaustion and no-double-billing cases added to the media, Ollama and integration-settings
files (46, 14 and 24 passed) and 34 passed on the existing files that drive the changed
adapters; `tests/test_watchdog.py` 11 passed (new); ruff, format and mypy clean on every
changed file; `scripts/check_docs.py` passes. The whole suite was not run by the
implementers; it is the verifier's. Verified as an adversary: the whole suite ran twice,
863 passed, 0 failed, 1 skipped; the close of the day is retried like any stage and a slot
is compared as an instant (two defects the verifier found and fixed, with a red-then-green
test each).

Not finished, honestly (what Phase B/C closed is marked inline): `ScheduledJobView` does not
expose `run_at_local` and `timezone`, so the scheduler API and the page cannot yet show the
fixed hour (closed 2026-09-17: the view carries both; the page does not read them yet); the
runbook reads the stop between stages, but the media scene loop and the other long runners
in `backend/app/runbook/stages.py` do not yet poll `stop_requested` between units of work,
nor raise `TransientStageError` where only they can tell a fault is transient, so the new
behaviour does not reach inside a stage (closed in part 2026-09-17: the render polls the
stop between scenes and before each motion shot, and the serial stage raises
`TransientStageError` for a provider fault; corrected 2026-09-18: the media stage itself reads
the stop before each film, so a stop set during the factual film leaves the serial unfilmed;
the other long runners still do neither); the watchdog dispatch was tested with an injected
stub module — the real module's exports match the handler, but an end-to-end fire with it
was not run; `tests/test_remote_state_honesty.py::test_the_real_provider_turns_a_failed_request_into_unavailable`
now takes about four seconds, because its fake's bare `OSError` is correctly retried with
real 1 s + 2 s sleeps (an autouse fixture in `tests/conftest.py` patching
`app.providers.retry.sleep` would make it instant again); a REMOTE_UNKNOWN publication
without a remote id is handed to the Owner rather than resolved, because
`execute_publication` does not yet admit that state to its reconcile-by-key branch; only the
VideoEditor's runtime state is reconciled when a stuck render is failed, and other employees
left WORKING by a crash are not reset; whether an S4U logon can open the DPAPI-wrapped
credential key on this machine was not verified, and the Owner should read
`data/studio-service.log` once after installing with that switch; `MULTI_LLM.md` named 0034
as the latest migration in passing (corrected 2026-09-18); `main.py` pins the head revision
(`0035_clock_and_fault_class` at this commit, `0038_director_may_approve_episodes` since
2026-09-18), so `scripts/bootstrap.py` (migrate) must run before the server starts on this
version. The "Running on its own" section below said every 24 hours and CATCH_UP; it was
rewritten on 2026-09-18 from the code as it is now. `backend/app/office/unreal.py` fails
`ruff format --check` and has one mypy error (line 72), pre-existing and untouched.

## An employee may think with more than one model (2026-09-12)

Every agent now has an optional second and third model beside its primary, from the same
registry, with a strategy that says what to do with them: single, fallback, review, debate or
parallel (migration 0034). No model is named in the studio's logic — a test scans the backend
and fails if one is — so any slot can be replaced from Settings without a code change. Extra
models are spent only where the agent's own policy says the task earns them, and the reason is
recorded. In review, debate and parallel the answer acted on is always a run on the employee's
own model: a critic advises and cannot publish, command or decide. A review that could not be
done is recorded as incomplete rather than filled in, and the Director's decision then carries
low confidence. The Owner's current allocation lives in `config/workforce_seed.json`: the
Director with a strategic critic, everyone else single. The report is `MULTI_LLM.md`.

## The company is managed, not only measured (2026-09-12)

The Director now answers where the company stands, what is preventing growth and who acts next
(migration 0033). Performance is normalised per film — views per hour, subscriber conversion,
cost and production time on the same row — and judged against the channel's own rolling median,
never an absolute number: a verdict needs three measured films, a day of age and a rate, or the
answer is INSUFFICIENT_DATA. A diagnosis separates reach from retention from conversion and
names the department that can fix it. Her pass runs every six hours on the existing scheduler,
assigns at most three things through the existing mailbox with a review condition on each,
never raises a matter already in hand, and sends STOP and SCALE to the Owner. Each decision is
a row the database refuses to accept without a review condition, and it comes back when the
films it was waiting for have been published. Verified on a copy of the live database: it found
the real bottleneck, six films through quality control and none published. The report is
`DIRECTOR_COMMAND.md`.

## The content decides, before the generation (2026-09-12)

A film now has to be worth making before it can be made. A topic carries an argument — the
fact, why it matters, the payoff, the hook, the ending, a call to action — scored on twelve
weighted editorial dimensions, and an idea that fails the rules is kept with its reasons. A
script carries its story and declares the part every scene plays. Before anything is
generated, the story is reviewed: computed checks for hook, progression, payoff, ending, CTA
and pacing, plus the Director's estimate of where a viewer would stop watching; a script that
is sent back is rewritten once. The render and the prompt agent both refuse a film whose story
has not passed. Then one master visual bible and a full prompt package per shot replace the
single line that used to be sent to a model at 2.60 USD a shot — the same package in both
environments, because TEST saves money on the model, not on the thinking. The report is
`EDITORIAL_PIPELINE.md`.

## Two environments, decided by the studio (2026-09-12)

The studio knows whether it is testing or publishing (`owner_policy.environment`, migration
0031), and that decides which policy chooses each scene's model: in TEST the cheapest
compatible model under a cost ceiling per generation and per second, in PRODUCTION the least
expensive model that reaches the quality the scene's part in the film requires. The
environment is server-side state changed only by the Owner's versioned command; the page
displays it and asks for a change. A model now carries a standing it has to earn
(DISCOVERED → … → PREFERRED) and cannot film anything that will be published until its own
recorded results admit it. Prices carry their provenance — documented, quoted, billed — with
what they were before, and a change past the Owner's threshold reaches him as a letter.

## The clean studio's first film, approved and unpublished (2026-09-12)

From an empty history: six topics proposed in English on authorised sites, pages found
through Wikipedia's and CERN's own addresses, 23 claims verified, a script whose every scene
cites a claim, a storyboard that speaks the writer's words, a 45.6-second 9:16 render with
Runway stills (`seedream5_lite`, after the studio dropped an editing-only model) and an
ElevenLabs voice, quality control passed on every check, and an APPROVE from the Director —
on `kimi-k3`, the first model she has had that can see, citing what the frames show. The
film is not published: that decision is the Owner's.

## Pages are found, not guessed (2026-09-12)

An authorised site can carry its own search address (OpenSearch JSON, `{query}` inside);
the studio asks it before the Researcher plans and reads the pages found when his guesses
fail. On the clean studio's first day every guessed address returned 404; with Wikipedia's
search address recorded, the day is expected to read real pages. Sites that serve articles
only to browsers (UNESCO) stay unreadable under the studio's honest identity.

## Starting over, and a Director who decides once (2026-09-12)

`scripts/reset_history.py` deletes the agents' history and the live ledger and keeps the
configuration (a backup is taken first; the studio must be stopped). The ledger begins at
the reset line. The Director's escalations now close the escalated message, one open letter
per matter reaches the Owner, an investigation's answer is not investigated again, and the
correspondence round runs at most three reviews an hour — the evening of 2026-09-11 ran
nine in twenty-four minutes.

## The Director watches before publishing (2026-09-12)

Nothing reaches a channel without the Director's editorial verdict (migration 0029): she
reads the film as data and frames from the file, decides APPROVE or REJECT with reasons,
and writes to the departments that must change something. The one video that went out —
demo script, sourceless claim, Romanian narration, twenty words — would be rejected on
three counts before any model is asked.

## English on the way out (2026-09-12)

`STUDIO_CONTENT_LANGUAGE` (default `en`) is told to every employee whose words reach the
audience, and a publication whose title or description is not in that language holds. The
Owner's first real upload (private, Main Channel A, title in Romanian) is the case that
motivated it. Structured tasks ask the provider for JSON on the first attempt and think
natively on the second; the Director on `glm-5.3` needs the second, at ~11 minutes and ~46k
tokens per twelve messages.

## The cycle, watched (2026-09-12)

A real day run on a copy of the Owner's data: trends read, five topics proposed, claims
verified, a stalled storyboard re-rendered with real visuals, the Accountant's close parsed,
letters filed. Still short of a published video because the Researcher's guessed URLs 404
(no search step; see the changelog) and the Director's long analysis needed the new
formatting pass. The publish stage was disabled in the copy on purpose.

## Polish pass (2026-09-12)

Every view read from a screenshot and set on one text scale, one radius and shadow, actions
sized to their words, the scene chrome as one bar in two groups, the ledger breathing, and
Settings on the same dialog pattern as the rest. Details in `CHANGELOG.md`.

## Signals: vendor pages and search trends (2026-09-12)

Kael and Lyra choose their models by reading the vendors' own pages (fetched by the studio,
restricted to the vendor's hosts) and scoring the account's models where the production
hierarchy reads scores; a fallback default follows the recommendation, a locked one is
reported on. Google Trends for the studio's country is read daily (migration 0028) and, with
the studio's own measured cohorts, reaches the Researcher's proposals and the Director's
weekly review — so the adaptation loop runs the day real numbers appear. `STUDIO_TRENDS_GEO`.

## Correspondence, and the day that stopped (2026-09-12)

Messages are letters in threads (migration 0027): the ledger names both ends and opens the
thread; the Owner reads the exchange and writes back. Employees answer the letters that ask
for something at each worker pass, and the Director reads the answers at once; a letter to
the Owner (a decision that is hers, a day that stopped, a review that could not run) is red,
under the Owner chip, and waits for the Owner's reply. The empty answers of 2026-09-11 came
from the adapter the studio actually uses (`ConfiguredLLM`, thinking now off, ten-minute
timeout), a stale THINKING flag (runs are records while they run), and media defaults never
chosen (the day finishes its own setup). Token budgets are three times larger.

Still open from the Owner's office-logic request: employees choosing a video model by
researching online (cost, capability, examples), analytics-driven adaptation from Google
Trends and channel numbers, and the visual polish pass — tracked in `13_ROADMAP_TODO.md`.

## The Director's mandate: grow views and retention — 2026-09-11, ZCode (verified, scope released)

Owner's second decree of the day, implemented and live-verified:

- **Sarah's mission is now the growth of the audience** — raising views and retention is her
  primary charge (`_ROLE_DEFINITIONS` + migration `0026_director_mandate`, which also offers
  contract seed v3 to roles never Owner-edited).
- **Contract v3 powers**: she directs ANY employee in writing (every instruction, choice and
  request documented as a message), steers each channel's direction and changes or
  deprioritises topics when the measured performance says so, and requests a larger budget
  from the Accountant with the numbers and the reason written down — the Owner alone
  decides budgets, so a justified request also reaches the Owner. The Accountant's matching
  duty: answer every budget request from the books, in writing.
- **The weekly review routes the mandate.** Its answer is now structured
  (`weekly-review-v2`): verdict, sound indications (→ Lyra), video indications (→ Kael),
  channel direction and topic changes (→ LeadResearcher and ScriptWriter, and remembered as
  STRATEGY memory), a budget request (→ the Accountant, amount + justification) and an
  Owner escalation — all filed as messages that enter each employee's runs, plus her spoken
  summary in the office and the full review in her inbox. A schema-breaking answer files
  nothing and says so; a week with nothing published still reports that at zero tokens.
- **The Accountant answers budget requests at the daily close**: each open request is
  answered with the books' figures, resolved as "transmitted to the Owner", and the close
  escalates — documentation without ever granting a budget (Owner-only, unchanged).

Live verification: server restarted on `0026_director_mandate` (mission + contracts at v3
confirmed in the database), weekly review triggered and completed with the honest
"nimic publicat, nimic de măsurat" STATUS. Tests: backend 528 passed / 1 skipped (new:
schema-break files nothing; the Accountant's budget-request close); ruff, format, mypy
clean; frontend 79/79; docs integrity passes. The pre-existing secret-scan false positive
(`discovery.py:80`) stands, untouched, in Codex's file.

## The roles the Owner ordered: sound, video, and a Director who checks weekly — 2026-09-11, ZCode (verified, scope released)

Owner directive implemented end to end, live-verified against the running studio:

- **Contracts v2** (`config/role_contracts.json`, migration `0025_role_contracts_v2` data-only):
  the sound artist stewards the audio — chooses voice and TTS model where the channel's
  policy allows, weighs naturalness, recorded cost and measured retention, follows the
  Director's written indications, escalates when an indication would break a lock; the video
  editor the same for film models (quality/cost/what kept viewers watching); the Director
  decides from measured performance, sends production indications as messages to the two
  departments, and never skips the weekly review while anything published exists. A role the
  Owner has edited keeps the Owner's text (the migration only offers the newer seed).
- **The Director's indications now reach the employees.** Open messages addressed to an
  agent enter that agent's composed identity ("WHAT IS ASKED OF YOU RIGHT NOW", capped at
  ten, recorded in the context manifest) — identity v2. Resolved messages stop following
  the employee.
- **The weekly performance review** (`backend/app/runbook/weekly.py`): a scheduled job every
  seven days (active standing policy, first fire an hour after birth) plus an Owner button
  in the runbook panel and `POST /runbook/weekly-review`. It reads only what is recorded
  (publications with measured views/retention/CTR, per-channel totals, open strategy
  recommendations), puts the digest in front of the Director through her identity, and files
  her answer as HANDOFF indications to the sound and video departments and a STATUS report
  in her inbox. A week with nothing published reports exactly that and costs no tokens —
  verified live: task `COMPLETED`, "Revizia săptămânală 2026-S37: nimic publicat, nimic de
  măsurat". The autonomy stop gates both the schedule and the button; a week is reviewed at
  most once by the clock.
- Failed agent runs now log the exception with its traceback (`exc_info`), for diagnosis.

Tests: backend 526 passed / 1 skipped (new: open-messages identity test, three weekly-review
tests, scheduler asserts the two standing jobs); ruff, format, mypy clean; frontend 79/79,
tsc clean, build OK; docs integrity passes. Live: server restarted on 0025, contracts at v2,
both jobs registered (daily dormant, weekly active), UI checks 5/5
(`scratch/verify_weekly_review_ui.mjs`). The pre-existing secret-scan flag
(`discovery.py:80`, keyword false positive in Codex's file) stands, untouched.

Honest limits: the review reads the numbers `performance_intake` has collected — with no
publications yet there is nothing to judge, and the departments have no bound voices/models
to be bound by indications until those are configured (the Owner's next configuration step,
not code).

## ZCode investigation + inspector extend — 2026-09-11 (verified, scope released)

Owner questions answered by investigation (no behaviour change): the double "Sarah said"
line is two real `owner_chat` runs sent by the first verification pass, not duplication —
each has its own run row and its own freshly generated answer (today's re-verification
added a third turn). The `performance_intake` SKIPPED message was written at 20:17, before
the channel slots were bound (20:18–20:19, events `channel.credentials_bound`); verified
live against the current database that both bindings are `publisher_ready` and the
analytics provider resolves — the next daily run will not repeat that skip (it will report
"Nicio publicare reală de măsurat", which is the honest state while nothing is published).
Per-channel production criteria are implemented end to end (`media/production_policy.py`
hierarchy and locks, `media/factory.py render_plan` building real ElevenLabs/Runway
adapters per scene, the plan recorded on the render job); the gaps are data, not code:
no character has a bound/locked voice yet and no storyboard carries a `channel_id`, so on
Channel B the "fixed voice" has nothing defined to enforce and nothing routes production
to a channel. Agents have no tool-calling: a run is one prompt; the STATUS lines an
employee "says" are written by deterministic stage code in its name.

Code change: an «⛶ Extinde» button on the Agent Inspector header — the dialog fills the
screen and the whole history reads as one traversable page (no inner scroll box); the
choice persists while reopening the inspector during the session. Frontend only
(`index.html`, `main.js`, `style.css`). Verified: frontend 79/79, tsc clean, build OK,
browser checks 16/16 (`scratch/verify_conversation_live.mjs`, including expand/restore),
zero page errors; screenshot `output/playwright/conversation-inspector-expanded.png`.

## The conversation reads like one — 2026-09-11, ZCode (verified, scope released)

Owner-reported defects, fixed frontend-only against the data already recorded:

- **Raw JSON is no longer shown to the Owner.** A run whose output is JSON (URL picks,
  claims, topics, scenes, verdicts) renders as sentences and lists
  (`frontend/src/friendly_text.js`); the exact model output stays collapsed under
  «Răspunsul exact al modelului», and everything remains saved on the run. A truncated
  answer (token limit mid-list) has its complete items salvaged and shown with a note —
  the Owner-visible case came from Dr. Aris's stored runs and is unit-tested. Old runs
  whose only line was the engineered prompt no longer print instructions as the headline;
  the prompt stays under «Cererea completă».
- **The inspector chat is a live, saved exchange.** Owner question right, employee answer
  left; a "scrie…" indicator driven by the real THINKING/IDLE events; the history refreshes
  itself on message/run events for the open employee, including runs fired from outside
  the page. Proven with a real chat turn (Sarah/glm-5.3-flash) that survived a reload.
- **A live window into an employee's work.** The inspector's «Fereastră live ↗» opens a
  standalone popup (`frontend/src/live_window.js`): state pill, "Acum: …" line, and the
  employee's own event chain, seeded with the day from the ledger and updated from every
  newly recorded event via `Ledger`'s new `onEvents` callback (one funnel for socket,
  snapshot and events endpoint). The inspector detail view is unchanged.
- **The wide dialogs actually reach the page** — they were already styled at
  `min(1180px, 94vw)`; the served build was stale. Rebuilt; measured 1180px in Chromium.

Tests at release: frontend `npm test` 79/79 (14 new for the two modules), `tsc` clean,
build OK; backend `pytest` 522 passed / 1 skipped (unchanged code); ruff, ruff format,
mypy, documentation integrity pass. Browser verification: 14/14 checks in
`scratch/verify_conversation_live.mjs` against the running studio on port 8000, zero page
errors; screenshots `output/playwright/conversation-*.png`. One live chat turn was sent to
an existing configured provider as part of verification.

**Pre-existing baseline failure discovered, not mine and left for its owner:** since the
ElevenLabs work landed (`backend/app/integrations/discovery.py:80`, commit 1c8de87/096dd26),
`scripts/check_secrets.py` flags the dictionary key `"invalid_api_key"` — a keyword-detector
false positive on a key *name*, not a credential. Confirmed present on a clean tree
(stash/pop). `discovery.py` is inside Codex's active claim, so I did not touch it.

## The day starts without blocking the page (2026-09-11)

The Owner's "Pornește rularea de azi" queues the day on the background worker and says so;
the run panel shows the day on its way, and the ledger names each stage as it starts and
ends. Agent runs carry a one-sentence summary of their task, so a history reads as work done
rather than as the prompt behind it, and a run that returned no visible text is recorded
EMPTY_OUTPUT with its reason — thinking models were spending the whole token budget on
reasoning, which is now switched off for Ollama generation.

## Live ledger and the office first (2026-09-11)

The workspace opens on the office, wide, with a live ledger in the left column: every message
an employee sends or files, every task, stage, cost and Owner action, in words and by name,
newest first, filtered by kind, with the production stage and the last daily run in the
head line. The ledger streams over the WebSocket and backfills the day from `GET /events`.
Owner Control and Workforce panels are gone; autonomy is one ON/OFF switch in the office
toolbar. The evening books report is filed by the Accountant, with her headline and holds.

## Books, budget, history (2026-09-11)

Eight employees: Nadia (Accountant) joined, with contract, Bible and a desk in the Accounting
& Treasury office that replaced the Commons. The Owner sets a daily or monthly budget in
Trezorerie; spend is measured from the books, the media stage refuses what an exceeded
budget cannot afford, every render's narration is costed per scene at the stored price, and
the Accountant closes each day before the Director's review. Every employee has a history
(runs, messages, decisions with reasons) and a chat in the Agent Inspector; speech bubbles
page through the whole answer at reading speed. Details and limits:
`ACCOUNTING_AND_HISTORY.md`. Migration 0024.

## The pipeline has no empty stages left (2026-09-11)

Every stage of `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` now has work behind it. New:
§3 idea generation (the Lead Researcher proposes candidates scored on the runbook's six
criteria, deduplicated, limited to authorised hosts), the retrieval half of §4 (the studio
fetches its own pages and keeps only what actually came back) and §5 selection (the Director
chooses among topics that have a verified claim, and the decision is recorded on the topic).
A channel slot now names the YouTube account it publishes through; publishing and analytics
use that binding instead of "the first row", and `GET /publishing/channels` no longer answers
500 when several accounts are connected. `POST /settings/auto-configure` finishes what a
verified connection leaves unfinished, only where the choice is forced. Details and limits:
`PIPELINE_COVERAGE.md`. Migration 0023.

## Employees: identity, memory, reports (2026-09-11)

Every agent run now carries the employee's identity as the system prompt, composed from stored
data (role mission, allowed/prohibited tasks, the role's work contract from
`config/role_contracts.json`, the character's speech style and phrases, the memory its role may
read, standing rules) and records the context manifest on the run. Character Bible entries are
linked to the employees holding their roles. Memory (`memory_record`, classes per
`../architecture/04_AGENT_SYSTEM.md` §9) is written by services on real outcomes with
provenance and read by role scope. Typed messages (`agent_message`) carry STATUS reports and
escalations to the Director; the runbook's `post_run` stage files the day's reports and runs
Sarah's review. Lyra reviews narration, Kael diagnoses failed renders, Vera prepares
publication metadata and may hold a candidate. Details and limits: `AGENT_IDENTITY_MEMORY.md`.
Migration 0022. No new agents were added: hiring stays evidence-driven through workforce
proposals.

## Identity

The agency is **AMN-AI — Autonomous Machine Nexus — Artificial Intelligence**. The name and logo
assets, and the rule that the stored studio name is domain state rather than configuration, are
documented in `BRAND_AMN_AI.md`. Renaming an existing studio is done with
`scripts/rename_studio.py`, which appends a `studio.renamed` event; bootstrap never rewrites it.

## Audit history

- **2026-09-09**, external: found fabricated channel configuration, simulated uploads recorded as
  real publications, a non-playable file named `.mp4`, a self-certifying QC gate. Remediated; see
  `AUDIT_2026-09-09_EXTERNAL.md`.
- **2026-09-10**, third party: `AUDIT_2026-09-10_THIRD_PARTY.md`.
- **2026-09-11**, internal, at the Owner's request: nine defects found and fixed, five areas
  verified and put under test. The most serious were an unanswered question to YouTube recorded as
  a "no" (risking a duplicate upload), a factual gate passing assets it had never traced while
  claiming verification, and Owner funding that a retried request could double. See
  `AUDIT_2026-09-11_INTERNAL.md`.

## Running on its own

Since 2026-09-11 the application process carries a background worker that fires due scheduled
jobs and executes the tasks they enqueue (`backend/app/workflows/worker.py`); since 2026-09-17
the daily job is on the wall clock. `daily_main` (`DAILY_RUN`) is seeded at start-up at
`STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) in `STUDIO_TIMEZONE` (Europe/Bucharest) —
`scheduled_job.run_at_local` and `.timezone` on the row, a changed hour followed on every
start-up — and seeded dormant: the Owner starts it from the daily-run panel, that decision is
the event `workflow.job_activated`, and waking it schedules the next 05:00, never a fire on the
spot. When a slot passes, the tick enqueues one task keyed on the job and the slot and moves
the job to the next local occurrence of its hour (`next_local_occurrence`, computed on the
local calendar and compared as UTC instants, so the clocks changing neither doubles nor skips
a day); a slot missed while the studio was off fires once when it is back, never a backlog.
Nothing fires while the autonomy stop is set. The clock does at most one successful day per
business date: a date with a COMPLETED or PARTIAL run is not repeated (a second run that day
is the Owner's button, which counts toward the attempts); a day that could not run — a
BLOCKED preflight, a stage that failed on a TRANSIENT fault — is re-attempted the same day
after `STUDIO_DAILY_RETRY_SECONDS` (1800), up to `STUDIO_DAILY_MAX_ATTEMPTS` (3), each attempt
queued under `daily-retry-<date>-<n>` and held by the queue's `not_before`; a re-attempt that
outlives its date skips itself, and a HARD fault opens safe mode and is not re-attempted
(corrected 2026-09-18: a HARD fault opens safe mode only in media, publish or the day's log, or
for a database integrity error; a failed stage blocks only the stages that depend on it, and the
re-attempt follows only a transient fault that cost the day's films — see «The rehearsal on the
Owner's data (2026-09-18)»). Of
the twelve runbook stages, `build_stage_runners` supplies ten (`performance_intake` through
`post_run`, and `serial_queue`); `preflight` and `daily_log` are built into the run itself,
and every stage reports COMPLETED or SKIPPED with a count and a reason.

## Connected accounts

Avatar repair verified 2026-09-11: the CSP now permits YouTube's two avatar origins and the
snapshot selects high → medium → default. Both existing connections (Nexus Curiosity and Inside
The Nexus) were refreshed through the real Verify buttons and displayed their own 800×800 API
images in Chromium, with persisted URLs and zero image-policy violations. Missing-thumbnail
fallback passed a separate browser fixture; completed-Reconnect refresh passed stubbed API tests.
Changed: YouTube snapshot selection, HTTP image CSP, connection-card avatar/CSS, regression tests
and `scripts/verify_youtube_avatars.mjs`. No migration. The local server was rebuilt/restarted.
Validation: 435 backend tests passed, 1 skipped (unconfigured real Ollama); 52 frontend tests
passed; Python/JS type checks, lint, frontend build, documentation integrity and secret scan passed.
Evidence and scope limits are in `YOUTUBE_CONNECTIONS.md`. No remaining avatar blocker.

YouTube channels are connected by OAuth, not by pasting credentials. Settings → *Conturi și
e-mail* takes a connection name, a Google OAuth client id and secret, and a redirect URI; the
Authorization Code flow with `access_type=offline` does the rest, and the channel identity is read
back from `channels.list` rather than typed. Refresh tokens and client secrets live in the Fernet
vault and are never returned by any route. Multiple independent channels are supported, and no
channel is named in the code. Connecting a channel is not the same as publishing to one — see the
Phase 6 correction below. Evidence: `YOUTUBE_CONNECTIONS.md`.

## Baseline and document authority

Started from 83 Markdown documents with no application code, tests, dependencies or Git history.
All original documents were read. The Master Prompt remains authoritative under Owner instructions.
There was no pre-existing test suite to run.

Per Owner request, 78 specifications/review documents live in ../architecture/; five original
tracking documents live here. The document index records original and post-move hashes. Only path
references were changed inside the architecture package. CI/local checks protect the indexed files.

## Working and verified locally

**Phase 0 (complete):**
- FastAPI application at http://127.0.0.1:8000, with private Owner Bearer authentication.
- HTML/Tailwind/JavaScript UI built with Vite; desktop and 390px mobile layouts inspected.
- SQLite database and Alembic revisions 0001_foundation, 0002_phase1_agents, 0003_phase2_automation, 0004_phase4_factual; explicit bootstrap.
- Persisted studio, empty initial room, Owner STOP flag, immutable command/event history.
- Atomic policy/event transactions, optimistic version checks and command idempotency.
- Duplicate/concurrent commands tested; failed event insertion rolls back policy changes.
- STOP state survives application restart; clearing it keeps MANUAL mode.
- Owner-only consistent snapshots/event pagination; disconnects label stale UI.
- No credentials in frontend builds, API projections or request logs.
- Structured request logs, request correlation, health endpoints, CSP/Host checks.
- Locked Python/Node dependencies, lint/types/build/test baseline and GitHub Actions.
- Documentation inventory/hash checks with integrity tests.

**Phase 1 (complete — verified 2026-09-09):**
- Abstract LLMProvider interface (base.py): health_check, list_models, generate, is_cloud model metadata.
- Ollama HTTP adapter (ollama.py v1.0.0): real /api/tags discovery + /api/generate; returns OFFLINE if not running; supports cloud models (glm-5.2:cloud, kimi-k2.6:cloud, qwen3-coder:480b-cloud), api_key bearer auth, and /api/show model inspection.
- ProviderRegistry (registry.py): maps provider IDs to adapter instances; in-process health cache.
- Dynamic model discovery (sync_provider_models): automatically discovers both local and cloud models from provider endpoint, updates model_record, links text_generation capabilities, and emits provider.model_discovered events.
- Role entity with mission, allowed_task_types, prohibited_actions; RoleCapability requirement levels (REQUIRED/PREFERRED).
- Capability entity (text_generation, tool_calling, etc.); ModelCapability mapping with confidence.
- ProviderRecord, ModelRecord: registered providers and models with discovery_method tracking.
- Agent entity: lifecycle (PROPOSED/CANDIDATE/HIRED/ACTIVE/PAUSED/SUSPENDED/TERMINATING/TERMINATED/ARCHIVED) and runtime_state (IDLE/THINKING/WORKING/...).
- AgentRun envelope: full audit record of every LLM invocation with status, tokens, cost_vr, event_id.
- ToolReceipt: immutable append-only receipts (DB trigger, no UPDATE/DELETE) for all tool calls.
- Owner Policy Kernel: enforces autonomy_stop check, lifecycle check, capability match, provider health before any LLM run.
- FastAPI routes: GET/POST /api/v1/agents/, GET/POST /api/v1/providers/, /sync-models, /run.

**Phase 2 (complete — verified 2026-09-09):**
- Persisted workflow state machine (Workflow, WorkflowStep): tracks 17 pipeline stages (DISCOVERY -> ... -> PUBLISHED -> ANALYTICS -> LEARNING) according to 47_STATE_MACHINE_SPECIFICATIONS.md; rejects illegal state transitions.
- Task queue with leases and backoff (TaskQueueItem): atomic task claims with time-bounded worker leases, automatic expired-lease reclamation when workers fail, heartbeat renewal, and task completion.
- Error classification and dead-letter queue: retryable failures trigger exponential backoff with computed next_attempt_at; max attempts exhausted routes tasks to DEAD_LETTER; operator recovery endpoint allows manual retry.
- Singleton-safe scheduler (ScheduledJob): recurring jobs with leader leases to prevent duplicate work across scheduler instances, with support for SKIP and CATCH_UP missed-run policies.
- Transactional outbox (OutboxRecord): atomic commit guarantees that business events and outbox records commit together; outbox dispatcher broadcasts to WebSocket clients and marks status PUBLISHED.
- WebSocket gateway (/api/v1/ws): authenticated real-time event streaming with replay protocol supporting after_sequence cursor to replay missed events after reconnection.
- Autonomy stop hard-gate: task worker and scheduler refuse to claim or run tasks when autonomy_stopped is active.
- Alembic migration 0003_phase2_automation: 5 new tables (workflow, workflow_step, task_queue, scheduled_job, outbox_record) with zero schema drift.

**Phase 3 (complete — visual system v2 2026-09-10, see `PIXEL_OFFICE_V2.md`; Blender sprite pipeline tried on the RESEARCH floor 2026-09-11 and switched off after the Owner's comparison; Character Bible now drives character looks, see `PIXEL_ART_PIPELINE.md`; per-channel production policies with locked character identities 2026-09-11, see `PRODUCTION_POLICY.md`):**
- Premium pixel-art rebuild of the cutaway (palette module with hue-shifted ramps, compiled outlined character sprites with role costumes, per-department room shells and interiors, baked lighting, limestone facade, glass lift). Designed first in Figma (`AMN-AI Office · Pixel Art Design System`, file `bqTc0PoCbjL5dH5xw0FRDI`), then implemented frontend-only; backend, API and events untouched. Measured 60 FPS at ~6 ms/frame; 43 frontend tests pass.
- Lateral cutaway multi-floor skyscraper canvas rendered at 60fps with zero simulated state, inspired by Space Haven, Anomaly President, and retro pixel-art simulation games.
- Seniority-based corporate hierarchy from top to bottom:
  * Floor 4 (Penthouse / Executive Suite): Director / CEO (Sarah) with panoramic city view, executive mahogany desk, gold trendlines, and award trophies.
  * Floor 3 (Research & Fact-Check Lab): Lead Researcher (Dr. Aris) & Fact Checker (Elena) with glowing holographic network graph whiteboard.
  * Floor 2 (Creative Writing & Narrative Studio): Script Writer (Marcus) with cork storyboard pinned with colored cards and red string.
  * Floor 1 (Media Lab & Production Bay): Voice Artist (Lyra) in acoustic foam vocal booth with boom mic & active LED EQ meter; Video Editor (Kael) with triple editing monitors.
  * Ground Floor / Level 0 (Infrastructure, Distribution & Lounge): Ollama Local Cluster & Cloud AI Gateway racks with blinking LED matrices and cooling fans; Coffee lounge with espresso machine emitting steam, water cooler, couch, and wall clock; Distribution hub with Vera at release console with radar map.
- Functional Glass Elevator Shaft on building exterior with moving elevator cabin traveling between floors.
- Procedural Animated Characters (Personaje):
  * Idle breathing bounce and periodic eye blinking.
  * Rapid typing hands on keyboard with dynamic monitor light reflections when WORKING.
  * Chin scratching gesture with floating glowing idea lightbulb and sparks when THINKING.
  * Resting / Zzz animation when PAUSED.
- Smooth camera controls: mouse pan, pinch/wheel zoom (0.4x to 2.5x), `fitToOffice()`, 1:1 reset, and dedicated Fullscreen (`#fullscreen-btn`) & Exit Fullscreen (`#exit-fullscreen-btn`) buttons with automatic canvas resize and Escape key support.
- Interactive Agent Inspector drawer modal (`#agent-inspector`) opened by clicking any character workstation, supporting live agent state inspection, direct task execution, and pause/resume actions (`POST /api/v1/agents/{id}/pause`, `POST /api/v1/agents/{id}/resume`).
- Real-time WebSocket connection to `/api/v1/ws` syncing backend events directly into `OfficeState`.
- Zero CSP violations (`style-src 'self'`). Frontend bundle remains compact.

**Phase 4 (PARTIAL — verification machinery works, real research does not exist):**
- Alembic migration `0004_phase4_factual`: 5 new tables (`topic_idea`, `source_snapshot`, `factual_claim`, `script_draft`, `hook_option`).
- Zone D Prompt Injection Defense (`sanitizer.py`): token stripping, instruction override filtering, and inert `<untrusted_source_evidence>` XML boundary tagging.
- Immutable source snapshots with SHA-256 digests (`content_hash`) and metadata (url, publisher, author, credibility_score). **Source text is supplied to the API by the Owner; nothing is retrieved from the web — there is no search or research adapter.**
- Atomic claim model (`factual_claim`) with status (`UNVERIFIED`, `SUPPORTED`, `REFUTED`), importance (`CRITICAL`, `SUPPORTING`, `FLAVOR`), and confidence.
- Strict Content Gate: attempts to generate or approve scripts with unverified or refuted claims raise `FactualGateError` and record an immutable `BLOCKED_UNVERIFIED_CLAIMS` draft for auditability (`factual.script_blocked_by_gate`).
- Script generation with 100% `SUPPORTED` claims compiles scene cues, voiceovers, and claim references. **A claim becomes SUPPORTED only through `POST /factual/claims/{id}/verify`, whose status is decided by the caller; there is no independent fact-checking agent.**
- Hook Specialist: opening hook variations with psychological techniques (`CURIOSITY_GAP`, `CONTRARIAN`, `STATISTIC_SHOCK`, `STORY_IN_MEDIA_RES`) and retention scores.
- Deduplication novelty calculation preventing repetitive content drift.
- Ollama Cloud model integration (`glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud`).
- Frontend Topic Submission & Verification Modal (`#research-modal`) in 2D Office.
- **Not met for Phase 4 acceptance** (`IMPLEMENTATION_PLAN.md`: "real research, evidence, independent fact checks"): research and independent verification are manual.

**Phase 5 (PARTIAL — real encoding works, real visuals/voice do not exist):**
- Character Bible (`character_bible`): Pre-seeded with 7 canonical studio employees (Sarah, Dr. Aris, Elena, Marcus, Lyra, Kael, Vera) with immutable visual descriptions, hex palettes, role symbols, and voice profiles.
- Storyboard generator (`storyboard`, `storyboard_scene`): Transforms approved scripts into multi-scene visual shot lists enforcing aspect ratio 9:16 (1080x1920); strictly blocks unapproved scripts or scripts with unverified claims via `FactualGateError`.
- Placeholder media adapters (`DeterministicVisualAdapter`, `DeterministicTTSAdapter`): produce SVG layout cards and RIFF/WAVE tones locally. These are placeholders, not generated content: no image model and no voice model is connected. Assets built from them are recorded with provider `PLACEHOLDER_DETERMINISTIC_VISUALS` and are **blocked by QC from publication**.
- Subtitle generator: Compiles synchronized SRT subtitle tracks matching scene voiceover segments and durations.
- Video Assembly Engine (`VideoRenderJob`, `MediaAsset`): encodes a real H.264 1080x1920 MP4 with FFmpeg from raster placeholder frames plus the narration track, and records a SHA-256 digest of the encoded bytes (`media.video_rendered`). **Without FFmpeg the render fails** (`RenderEngineUnavailable`, HTTP 503) and no MediaAsset is recorded; the studio no longer writes a stand-in file with an `.mp4` name.
- Quality Control Engine (`quality_control_report`): Technical QC now **measures the file with ffprobe** (video stream present, measured resolution, measured duration) and **recomputes** the SHA-256 provenance digest, instead of trusting the metadata the renderer wrote. Rights QC checks the license field. Content-source QC fails any asset built from placeholder visuals. Factual QC re-checks every referenced claim. Character-drift QC is reported as `NOT_IMPLEMENTED` — it performs no comparison and certifies nothing.
- Alembic migration `0005_phase5_media`: 6 new tables (`character_bible`, `storyboard`, `storyboard_scene`, `media_asset`, `video_render_job`, `quality_control_report`).
- Media API routes (`/api/v1/media`): Character Bible endpoints, Storyboards, `POST /storyboards/demo-fixture` (creates a topic/script with an **UNVERIFIED** claim; it never marks anything SUPPORTED), video rendering, streaming, and QC gate verification.
- Frontend Media Production Modal (`#media-modal`): Storyboard pipeline viewer, 9:16 preview, QC scorecard, provenance hash badge, Character Bible inspector.
- **Not met for Phase 5 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §F): there is no image or TTS provider, so no real footage or narration exists; character continuity is unimplemented.

**Phase 6 (PARTIAL as written on 2026-09-09; corrected 2026-09-18 — the pipeline and gates work, and two private uploads have reached Main Channel A since):**
- Channel slots (`channel_record`, `channel_brand_asset`): two slots (`MAIN_FACTUAL`, `OFFICE_SERIAL`) are seeded with **no remote channel ID, no credentials and status `NOT_CONFIGURED`**. Status is derived from what is actually present (`NOT_CONFIGURED` -> `AUTH_REQUIRED` -> `AUTHENTICATED`); nothing is ever reported as configured on the strength of a seed.
- Five-check publishing gate (`evaluate_publishing_gate`). This is a **subset** of the publish column of `../architecture/50_CONTENT_GATE_MATRIX.md`, not an implementation of it — rights on the final package, platform policy, novelty on final metadata, brand strategy, budget, and Channel B continuity/narrative privacy are not implemented:
  1. Global Autonomy Stop check (fails if `autonomy_stopped` is active).
  2. Media file on disk existence check (fails if file missing or 0 bytes).
  3. Quality Control check (fails if QC status is not `PASSED` or score < 0.90).
  4. Factual claim integrity check (fails if any claim referenced in the script is not `SUPPORTED`).
  5. Idempotency & duplicate protection check (fails if asset was already published on that channel).
- YouTube Data API v3 Adapter (`YouTubeProvider`): OAuth2 refresh-token exchange, chunked resumable upload with `Content-Range` and 308 resume, synthetic-content disclosure (`containsSyntheticMedia` plus a disclosure line in the description), remote status polling, and reconciliation that is actually invoked before any retry. **This adapter has never run against Google** — as of 2026-09-09; superseded: channels connect by OAuth since 2026-09-11 and `publication_record` holds two PUBLISHED private uploads of 2026-09-12 with real remote ids (`98JltCPoOKs`, `sDEtt-WQGh8`; see `CHANGELOG.md`, 2026-09-13). `publishAt` and `videos.update`, added 2026-09-17, have run only against a faked transport.
- Simulated Publishing Adapter (`DeterministicPublishingAdapter`): **tests and CI only**. It is never selected at runtime; without real credentials the API returns 503 `PublisherNotConfigured`. Its results carry `simulated=True`, a `sim:` identifier and no platform URL, and are stored as `PUBLISHED_SIMULATED` with event `publishing.video_published_simulated`.
- Publication State Machine & Tracking (`publication_record`): Enforces `DRAFT_INTENT` -> `VALIDATED` -> `STARTED` -> `REMOTE_CONFIRMED` -> `PUBLISHED` transitions with recovery from `REMOTE_UNKNOWN` and `FAILED_RETRYABLE`.
- Unique constraint `uq_channel_idempotency`: Prevents duplicate uploads of the same intent.
- Alembic migration `0006_phase6_publishing`: 3 new tables (`channel_record`, `channel_brand_asset`, `publication_record`).
- Publishing API routes (`/api/v1/publishing`): Channel management, gate evaluation, intent creation, publication execution, quick-publish, and publication history retrieval.
- Frontend Distribution Hub Modal (`#publishing-modal`): shows real channel status with plain-language hints, a banner when no credentials are configured, the gate breakdown including what is not implemented, and publication history where a simulated run is labelled "SIMULAT (nepublicat)" and gets no link. Only a genuine `youtube.com` URL becomes a clickable link.
- **Not met for Phase 6 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §G): OAuth has never been exercised, no private upload has been verified, and no real remote ID has ever been persisted — as of 2026-09-09; met since: OAuth exercised 2026-09-11, two private uploads with real remote ids persisted 2026-09-12. The per-channel policy of 2026-09-17 is unproven against Google for a scheduled release.

**Phase 11 (complete for the ledger — verified 2026-09-10, see `PHASE11_ECONOMY.md`):**
- Immutable double-entry VR$ books: `ledger_account`, `ledger_transaction`, `ledger_entry`, with
  a seeded chart of accounts covering cash, restricted cash, receivables, fixed assets,
  depreciation, debt, equity, revenue by source and expense lines.
- External evidence layer: `revenue_evidence` (YouTube, donations, sponsorship, other),
  `provider_cost_record`, `owner_funding_event` and `fx_snapshot`. Recording evidence mints
  nothing; only SETTLED revenue mints, and only a BILLED invoice posts a cost.
- The 1:1 rule holds under retry and re-import: `(source, external_reference)` is unique and a
  minted row is stamped with its transaction, so one verified dollar becomes one VR$ exactly once.
- Forecast and pending payouts are reported beside the treasury, labelled, and can never be
  minted or spent. FX is never invented: a non-USD amount without a recorded rate is refused.
- Reversals post a mirrored transaction and never delete; a transaction is reversible at most
  once. A chargeback after real spending shows a deficit rather than hiding it.
- Money is integer micros throughout, so the books cannot drift; `trial_balance` re-adds every
  stored line and is surfaced in the UI.
- Owner-only routes under `/api/v1/economy`; **no route anywhere in the API pays, buys, transfers
  or checks out**, and a test asserts that across the whole OpenAPI surface.
- Frontend **Trezorerie** panel renders the backend's own labels (VR VIRTUAL / PENDING / FORECAST
  / ESTIMAT), the trial-balance verdict and the "not filed accounts" disclaimer.
- Alembic migration `0016_phase11_economy`: 7 new tables. 31 new tests.
- **Not met yet**: nothing spends VR$, no interest accrues, no budgets/runway/P&L, no depreciation,
  and no automatic revenue import — those are Phases 12–14.

## Partial / exact limits (written 2026-09-09; dated corrections inline)

- The application runs end to end locally: foundation, automation, 2D office, factual gating,
  media assembly and the publishing state machine are all exercisable.
- **Two films have been published, both private** (corrected 2026-09-18; the sentence "nothing
  has ever been published" stood here from 2026-09-09): Main Channel A, 2026-09-12, remote ids
  `98JltCPoOKs` and `sDEtt-WQGh8`, recorded PUBLISHED in `publication_record`. Without a bound
  CONNECTED account the publishing API still refuses (503), and the simulator is reachable
  only by injecting a provider in tests.
- **Placeholder renders never pass QC for publication** — content-source QC fails them by
  design; since the Runway and ElevenLabs connections were verified (2026-09-12) real renders
  have passed QC and been published.
- Rendering requires FFmpeg on the host. Without it, `POST /media/render/{id}` returns 503.
- Local single-owner SQLite deployment only. PostgreSQL and multi-user auth remain pending.
- Real Ollama end-to-end test is skip-marked; it runs when `STUDIO_OLLAMA_URL` is set.

## Not implemented (written 2026-09-09; dated corrections inline)

- Search/research adapter (Phase 4 acceptance) and independent fact-checking agent.
- Character-continuity drift detection: quality control reports the check `NOT_IMPLEMENTED` and
  certifies nothing. (The image and TTS providers this line once named are connected since
  2026-09-12: Runway and ElevenLabs.)
- The remaining publish-time gates of `../architecture/50_CONTENT_GATE_MATRIX.md` (rights on final package,
  platform policy, novelty on final metadata, brand, budget, Channel B continuity/privacy).
  Since 2026-09-17 a sixth, policy-authorisation gate runs for a publication that would be
  seen, and Channel B's privacy is enforced when the log is projected, not at publish time.
- Dynamic departments. (The Office Serial's showrunner, the Director's episode review, the
  serial storyboard and its routing to Channel B exist since 2026-09-17/18 — see "Delivery
  and the serial" above — and no real day has filmed an episode yet.)
- Spending VR$: procurement/VendorShop (Phase 13) and treasury financing with interest accrual
  (Phase 14). The ledger they will post to exists; nothing spends from it yet.
- Finance dashboard: budgets, cost centres, runway/burn, P&L, balance sheet, cash flow and
  30/90/180-day scenarios (Phase 12).

## Test evidence

Independent audit environment (Linux, Python 3.13, SQLAlchemy 2.0), 2026-09-09, after remediation:

- `pytest` **with FFmpeg available**: 87 passed, 1 skipped (real Ollama), 0 failed.
- `pytest` **without FFmpeg**: 85 passed, 3 skipped (Ollama + two render tests that are skipped
  rather than silently exercising a fake path), 0 failed.
- `tests/test_truthfulness_gates.py` (new, 10 tests) locks the governance invariants: channel
  slots are never reported as configured, publishing refuses without credentials, a simulated
  upload is never stored as a real publication, a gate refusal is persisted with its event,
  QC rejects a non-video file named `.mp4`, QC rejects a tampered provenance digest, and the
  character-drift check never claims to pass.
- `ffprobe` on a produced render: 1080x1920, h264, duration equal to the storyboard timeline.
- `npm test --prefix frontend`: 6 passed. `npm run check`: 0 errors. `npm run build`: succeeded
  (51.33 kB JS, 24.44 kB CSS).
- **Live application verification** (`scratch/verify_post_audit_e2e.mjs`, real Chromium against a
  running server): **27/27 checks passed**, 0 console errors, 0 CSP violations. It exercises the
  full chain — login, clearing the Owner STOP, channel status, the credential banner, the 1-click
  publish refusal, the demo fixture, the factual gate blocking an unverified script, claim
  verification, approval, storyboarding, rendering, QC, and the publishing gate refusal — and
  confirms with `ffprobe` that the produced file is a real 1080x1920 H.264 video of 18.00s.
  Screenshots: `output/playwright/post-audit-publishing-hub.png`, `post-audit-history.png`,
  `post-audit-media-modal.png`, `post-audit-mobile.png`.
- **Cold-start verification**: from a clean checkout with no `.venv`, no `node_modules`, no `.env`
  and no database, `uv run python scripts/start.py` brought the studio up unattended (uv venv +
  `uv sync --locked` + `npm ci` + Vite build + bootstrap + server), `/health/live` answered 200,
  and the 27-check Playwright suite passed against that fresh instance.

Note on the previous revision of this section: the "80 passed" figure it reported was
reproducible, but the suite passed **because** FFmpeg was absent on the development machine —
the real encoder path raised `DetachedInstanceError` and had never been executed. The suite now
fails loudly in that situation instead of certifying the fallback.

## Files changed / architecture impact

Post-audit remediation (2026-09-09):
- `backend/app/config.py`: `STUDIO_YOUTUBE_*` and `STUDIO_FFMPEG_PATH` settings; credentials no
  longer read ad hoc via `os.getenv`.
- `backend/app/publishing/services.py`: honest channel seeding and `derive_channel_status`;
  gate refusals persisted before raising; `PUBLISHED_SIMULATED` state; QC score minimum
  enforced; reconciliation before any retry; no provider fallback.
- `backend/app/publishing/router.py`: 503 `PublisherNotConfigured`; `POST /channels/seed`
  replaces seeding inside a GET; 404 instead of 500 for a missing asset; quick-publish requires
  an AUTHENTICATED channel.
- `backend/app/providers/publishing_base.py`, `deterministic_pub.py`: `simulated` flag,
  `sim:` identifiers, no fabricated platform URL.
- `backend/app/providers/youtube.py`: chunked resumable upload, synthetic-content disclosure,
  `youtube_provider_from_settings`.
- `backend/app/media/assembler.py`: placeholder raster frames + real FFmpeg encode or
  `RenderEngineUnavailable`; no stand-in `.mp4`; storage root no longer a hardcoded Windows
  path; detached-ORM bug fixed.
- `backend/app/media/qc.py`: ffprobe measurement, provenance re-verification, content-source
  check, character drift reported as `NOT_IMPLEMENTED`.
- `backend/app/media/router.py`: `POST /storyboards/demo-fixture` creates UNVERIFIED claims
  only; render surfaces 503 when no encoder exists.
- `scripts/bootstrap.py`: fixed a `TypeError` that broke first-time `.env` creation.
- `frontend/index.html`, `src/main.js`, `src/style.css`: truthful channel and publication
  status vocabulary, credential banner, no links to non-existent videos.
- `tests/test_truthfulness_gates.py` (new); `tests/test_phase5_media.py` and
  `tests/test_phase6_publishing.py` updated to assert the honest behaviour.
- `pyproject.toml` / `uv.lock`: added `websockets` — without it uvicorn answered the
  `/api/v1/ws` handshake with 404 and the office never received live events. Run `uv sync`.
- `backend/app/factual/services.py`, `router.py`, `schemas.py`: new
  `POST /api/v1/factual/scripts/{id}/approve`, which re-runs the factual gate at approval time.
  Without it, scripts created through the real API (`VERIFIED_PASS`) could never reach the
  `APPROVED` status storyboarding requires — only the removed fixture endpoint could.
- `start.cmd` and `scripts/start.py` (new): single-command launcher with a preflight report that
  states which integrations are configured; `scripts/bootstrap.py` and `../../README.md` point at it.
- `scratch/verify_post_audit_e2e.mjs` (new): the Playwright verification described below.
- `docs/project/AUDIT_2026-09-09_EXTERNAL.md` (new): the audit these changes answer.

- `backend/migrations/versions/0007_correct_fabricated_records.py` (new, data-only): corrects
  rows already written by the pre-audit code — invented channel IDs are cleared and the channels
  set to `NOT_CONFIGURED`, `yt_sim_*` publications become `PUBLISHED_SIMULATED` with their dead
  YouTube URLs removed, and every earlier `PASSED` QC report is marked `INVALIDATED` because the
  gate that granted it measured nothing. Nothing is deleted; history stays auditable.
- `backend/app/main.py`: startup revision check moved to `0007_correct_fabricated_records`.

Modular monolith; no table was added or altered (migration 0007 is data-only). Phase 7 analytics
must therefore start at `0008`.

## Blockers and risks

- **Publishing is blocked by design** until `STUDIO_YOUTUBE_CLIENT_ID`,
  `STUDIO_YOUTUBE_CLIENT_SECRET` and `STUDIO_YOUTUBE_REFRESH_TOKEN` are configured and a
  channel is moved to `AUTHENTICATED`. The whole YouTube path is still unexercised against
  Google. (As of 2026-09-09. Superseded: channels connect by OAuth since 2026-09-11, two
  private uploads reached Main Channel A on 2026-09-12, and since 2026-09-17 a film goes only
  to the channel its storyboard names, at that channel's Owner-set visibility, private by
  default.)
- **Publishable content is blocked** until a real image/TTS provider replaces the placeholder
  adapters; content-source QC fails placeholder visuals on purpose.
- Rendering requires FFmpeg on the host.
- Phase 7 analytics code on disk is inert and unmigrated; wiring it as-is would cause schema
  drift and refuse startup.

## Exact next task

Close the acceptance gaps before advancing to Phase 7, in this order:

1. **Phase 4 acceptance** — a real search/research adapter (`../architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md`
   search adapter contract) feeding `ingest_source_snapshot`, plus an independent fact-checking
   role that cannot verify its own claims.
2. **Phase 5 acceptance** — a real image provider and a real TTS provider, so renders stop being
   placeholder frames and content-source QC can pass; then character-continuity drift detection.
3. **Phase 6 acceptance** — configure Google OAuth, verify one private upload end to end against
   the real API, and record the real remote ID. (Done: OAuth 2026-09-11, two private uploads
   with real remote ids 2026-09-12.)
4. Only then Phase 7 (analytics), starting by adding migration `0008` for the analytics tables
   and wiring the router and `Base.metadata`.


## Codex research scope claim — 2026-09-09T23:19

Active: isolated public HTTPS source retrieval in new backend/app/research files, a local Owner CLI and dedicated tests. UI, media, app wiring, dependencies and migrations remain outside this claim while Claude works there. Baseline: 88 passed, 3 skipped; one documentation test fails on nine stale relative references.

## Codex research increment — completed, scope released

- Implemented Owner-directed known-URL HTTPS retrieval in new `backend/app/research/` files and `scripts/research_source.py`; existing UI/media/application code remains outside this change.
- The CLI can feed the existing authenticated source-ingestion API. No claim is automatically verified; no search provider or worker is activated. Phase 4 remains partial.
- Corrected nine stale architecture/root-document references in project tracking. Original architecture hashes are unchanged.
- Windows validation: 121 passed, 3 skipped (real Ollama unavailable; two FFmpeg checks unavailable). New-module Ruff and mypy pass; document inventory/hash verification passes.
- Real IANA HTTPS retrieval and authenticated ingestion into an isolated temporary database succeeded with matching hashes. Live studio state was not changed.
- Usage, limitations, touched paths and exact remaining research work: `RESEARCH_HANDOFF.md`.
- Next: keyword-search provider integration and independently authorized fact checking; coordinate separately before modifying shared factual routes. Claude retains UI/media scope.

Verification follow-up: the secret scanner flagged a pre-existing hardcoded provenance fixture in `tests/test_phase6_publishing.py`. Replaced only that fixture value with the actual SHA-256 of its test video bytes; no scanner suppression or publishing implementation change.

Final follow-up checks: all six publishing tests pass after the fixture correction; secret scan and documentation inventory/hash checks pass. No frontend or pre-existing backend source file was modified.

## Codex Settings scope — 2026-09-09T23:38

Owner explicitly requested Settings UI: LLM providers, agent assignments, video/audio tools, YouTube/TikTok/Instagram/Facebook and optional email credentials. Scope: new integrations backend + migration 0008, separate settings UI module/styles and minimal app wiring. No office animation edits. Credentials encrypted; saved configuration must never imply verified connectivity or publishing capability.

## Owner-directed renderer fixes — 2026-09-10, ZCode

Owner-reported visual defects only, scope `frontend/src/office_engine.js` scenery/nameplates + one new frontend unit test: remove the invented bus route number "12", stop same-lane vehicles passing through each other (lane spacing at spawn + car-following), and shrink the agent nameplates onto a light "paper" plate for readability. No backend, settings, integrations or office-state changes.

Completed and released the same day. Details:

- `drawCar`: the hard-coded bus route label "12" is gone; the destination blind stays blank.
- `makeTraffic`/`updateTraffic` (new, exported): vehicles now spawn spread across each lane's loop stretch and move as a platoon — a follower near its leader adopts the leader's speed and a hard clamp holds a 24 px bumper gap, including across the road's wrap seam, so same-lane vehicles can no longer drive through each other.
- `drawNamePlate`: the name renders at single scale (was double) on a light paper card with dark ink and a muted state line — half the height, far less floor area, readable over the night interiors; the selected variant keeps the gold border.
- Follow-up (Owner direction, same day): the runtime state moved out of the floor card
  entirely. The card at the character's feet now carries the name only; a new
  `drawStateTag` floats the state (IDLE, WORKING…) above the head as a dark chip with
  department-accent text, and the thinking bulb / sleeping Z marks were raised above it
  so the three never overlap.
- Verification: `npm test` 11/11 (3 new traffic invariant tests: spawn spacing, fast-car-catches-slow-bus, 15-minute mixed-timestep seam run), `npm run check` clean, `npm run build` OK (86 kB). Live browser check on the running local studio confirmed the bus has no number, traffic flows with no overlap across frames, and the nameplates render as small light cards.

## Documentation identifiers, initial Git commit — 2026-09-10, ZCode (second session)

Owner-directed documentation and repository repairs; recorded as D-DOC-001 in the decision log:

- `16_DECISION_LOG.md`: removed the byte-identical duplicate of the ADR-001…ADR-V5-003 block
  (verified identical before deletion; 706 → 551 lines, every ADR now single).
- `../architecture/02_SRS.md`: the v3 additional FRs are renamed `FR-V3-037…FR-V3-066`
  (same numeric suffix, consistent with the existing `FR-V4-`/`FR-ECON-` namespaces), clearing the
  collision with base FR-037…066. NFR-013…021 never collided and are unchanged. Requirement text
  unchanged. `../architecture/V3_FILE_BY_FILE_REVIEW.md` notes the rename; `IMPLEMENTATION_PLAN.md`
  marks the
  recorded conflict resolved. Indexed `sha256` values for both architecture documents updated
  explicitly (original hashes preserved).
- `tests/test_integration_settings.py` (two fixture values only, inside the active Codex Settings
  claim — flagged here so that agent is aware): `"do-not-echo"` → `"abc"` and
  un URL de test cu utilizator și parolă în el → unul doar cu nume de utilizator, so `scripts/check_secrets.py`
  passes without suppression. Both payloads still assert the same 422 refusals; all 15 settings
  tests pass.
- Initial Git commit created at the Owner's request (`ae4dee3`, branch `codex/foundation`, with a
  `main` branch pointer at the same commit): 212 files — source, tests, docs, scratch verification
  scripts. `.gitignore` extended with `backend/storage/` and `Claude outputs/` (generated media and
  screenshots); `.env`, `data/`, `output/`, `dist/`, `node_modules` were already excluded and are
  confirmed absent from the commit.

Verification at commit time: `pytest` 136 passed / 3 skipped; frontend `npm test` 11/11, `tsc`
clean, build OK; `scripts/check_docs.py` and `scripts/check_secrets.py` pass.

## Owner-directed LLM connectivity test — 2026-09-10, ZCode (third session)

Verified the Ollama Cloud integration end to end and added the missing Settings test affordance:

- Live state checked first: the "Ollama Cloud" integration (`https://ollama.com`) is saved and
  VERIFIED, 22 models discovered, all 7 agents carry an assigned model on that provider,
  autonomy stop inactive.
- Real runs through the policy kernel succeeded against the live provider: Sarah/glm-5.3-flash
  (reasoning output; token counts recorded) and Lyra/gpt-oss:120b answered
  "Da, sunt funcțional și gata să te ajut." in ~1s. Runs, tokens and events are in the audit trail.
- New: `POST /api/v1/settings/agents/{id}/test` runs one real connectivity task through the
  agent's assigned model (fixed short objective, max 800 tokens) and returns the same AgentRun
  envelope plus duration; 404 for unknown agents, policy blocks recorded as BLOCKED_* statuses.
- New: each agent card in Settings → Agenți has a "Testează răspunsul" button that surfaces the
  model's answer (or the block reason). Verified live in the browser: the button returned
  "glm-5.3-flash a răspuns: «Da, sunt complet funcțional…»".
- Test: `test_agent_llm_test_endpoint_runs_assigned_model` (provider monkeypatched; no network in
  tests). Settings suite 16/16.

## Whole-tree lint and type cleanup — 2026-09-10, ZCode

With the parallel agents' sessions finished, the committed baseline still failed the README's own
`ruff check .`, `ruff format --check .` and `mypy` (177 ruff findings, 9 mypy errors, inherited
from pre-audit and remediation code). Cleaned without behaviour change:

- `ruff format` across the tree (23 files) plus manual wrapping of the remaining 65 long lines
  (string literals split with identical content; the deterministic SVG template's XML attributes
  re-wrapped — rendering unchanged, hashes are computed at runtime).
- Auto-fixes: 22 unused imports, 11 unsorted import blocks, small UP modernisations.
- Manual: SQLAlchemy `== True` filters → `.is_(True)` (analytics), an unused local dropped
  (publishing), explicit `strict=False` on an intentionally asymmetric `zip` (office layout test),
  `requires_ffmpeg` moved below the imports it uses (E402).
- mypy: explicit `dict[str, Any]` annotations for the ffprobe result and the storyboard scene
  payloads (media/qc.py, media/assembler.py).

Verification after cleanup: `ruff check .` clean, `ruff format --check .` clean (185 files),
`mypy` clean (68 files), `pytest` 137 passed / 3 skipped, frontend `npm test` 11/11, `tsc` clean,
build OK, `check_docs.py` and `check_secrets.py` pass.

## Live speech bubbles wired end to end — 2026-09-10, ZCode (fourth session)

The speech-bubble projection existed in the frontend (handler, expiry, paper bubble renderer)
but nothing ever fed it: the backend never emitted `agent.message_sent`, and the transactional
outbox had no dispatcher, so no event was broadcast live after the initial replay. Three fixes:

1. **Producer** — `run_agent_task` now emits `agent.message_sent` (through
   `append_event_with_outbox`) in the same transaction that records the successful run, with the
   model's real output text (whitespace-normalised, capped at 200 chars) plus `run_id` and
   `task_type`. Per `../architecture/06_BACKEND_EVENT_MODEL.md` §7 only real messages may become
   live bubbles: failed runs and successful runs with no visible text (reasoning models with a
   small budget) emit nothing.
2. **Dispatcher** — the app lifespan now runs the outbox dispatcher every second
   (`publish_pending_outbox`), broadcasting committed outbox events to WebSocket clients. It runs
   on the server's own event loop on purpose: the broadcast tasks and the sockets belong to that
   loop. This also un-silences the workflow events that were already written to the outbox.
3. **UI label** — `agent.message_sent` shows as "Agentul a răspuns" in the activity log.

Verification: three new phase-1 tests (successful run emits the event with the real text and a
PENDING outbox record; failed run emits nothing; empty visible output emits nothing). Live E2E
against Ollama Cloud with the office open: an API-triggered run for Lyra/gpt-oss:120b produced
the speech bubble above her head reading "SUNT GATA SĂ LUCREZ ÎN CABINA VOCALĂ." — the run was
fired from outside the page, so the bubble proves the live event chain, not page-local state.
Full suite: ruff/format/mypy clean, pytest 140 passed / 3 skipped, frontend 11/11, docs and
secret checks pass.

Known related gap (not addressed here): agent runtime-state changes (THINKING/IDLE) are column
updates without events, so the state tag above the head updates on layout refresh rather than
instantly.

## Research agent works the pipeline; office fully live — 2026-09-10, ZCode (fifth session)

Two increments, both verified against the configured Ollama Cloud provider:

**1. The office is fully live.** `run_agent_task` now emits `agent.state_changed`
(THINKING at start, IDLE at completion) through the outbox, and `agent.paused`/`agent.resumed`
were moved onto the outbox too — the state tag above each character's head and the pause
animation now follow backend events in real time instead of waiting for a layout refresh.

**2. The research agent actually reads sources.** New
`POST /api/v1/factual/sources/{id}/extract-with-agent` (`backend/app/factual/agent_pipeline.py`):
the LeadResearcher agent (or any given ACTIVE agent with a model) receives the source's
sanitized text inside the inert `<untrusted_source_evidence>` boundary, extracts up to 12
atomic claims through its real LLM, and the JSON is strictly schema-validated before anything
is stored. Every claim lands **UNVERIFIED** regardless of the model's confidence — the model
that read the source is never the one that verifies it. Unparseable output raises (422) and
stores nothing. A truncated JSON list (token cap hit mid-item) keeps only the complete
objects — the dangling partial claim is dropped, never guessed. The agent announces a human
summary ("Am extras N afirmații...") as its speech bubble instead of raw JSON
(`run_agent_task` gained an `emit_message` flag for structured pipelines).

Live evidence: the IANA Example Domains page was fetched with the research retrieval adapter
(real SHA-256 provenance) and ingested; Dr. Aris (nemotron-3-super) returned 9 accurate claims
(RFC 2606/6761 reservations, registration restrictions, subdomain guidance) recorded UNVERIFIED,
and his speech bubble appeared in the 2D office. Phase 4 remains partial: keyword
search/discovery and an independently authorized fact-checker are still open.

Tests: 4 pipeline tests (stubbed adapter: valid JSON with fences; unparseable output rejected
with nothing stored; policy STOP blocks before any claim; truncated list keeps only complete
claims), phase-1 run tests extended to assert THINKING/IDLE state events. Suite: 144 passed /
3 skipped; ruff, ruff format, mypy, docs and secret checks pass.

## Codex Settings completion and bug audit — 2026-09-10T09:23

Scope resumed on current tree after ZCode additions: finish Settings channel binding UI, reproduce five factual-pipeline test failures, fix confirmed hardcoded operational claims and model availability guards. Preserve concurrent office/research additions. Baseline: 199 passed, 5 failed, 3 skipped; Ruff passed. No production credentials or messages will be generated during tests.

## Codex premium pixel office — 2026-09-10T14:55

Active claim: frontend/src/office_engine.js and a dedicated visual-art module; visual verification artifacts and tracking docs. Owner requested richer pixel characters, architecture, furniture, street people, dogs and cars. Preserve backend projections and concurrent Settings/research changes. Earlier audit verification/handoff remains to finish after this visual increment.

## Codex pixel office — verified, scope released

Visual increment completed; see `PIXEL_OFFICE_REFINEMENT.md`. Added material library, refined building/furniture/characters/dogs/cars/foliage, moved camera controls below the scene and fixed portrait framing. Frontend typecheck/build passed, 18 tests passed; Playwright desktop/fullscreen/mobile and real agent selection passed with zero page errors. Port 8000 serves the rebuilt assets. No backend or provider execution was part of this increment. Concurrent media changes preserved; earlier audit scope remains separately tracked.

## Codex street simulation — active claim

Owner requested round wheels/correct vehicle depth, randomized vehicle/pedestrian activities, animals and a local-clock day/night cycle. Scope: office_engine.js, new street simulation module, frontend tests and tracking docs. Decorative street events remain separate from operational agent events.

## Codex ambient street — complete, scope released

Round pixel wheels and far-to-near vehicle rendering fixed. Added session RNG, ten vehicle models, randomized pedestrian/animal activities, 48 shuffled decorative phrases and local-clock day/night density/lighting. 25 frontend tests, typecheck/build and browser 12:00/03:00 checks passed. Existing agent selection/mobile browser QA passed. See `STREET_LIFE.md` for limits, time semantics and screenshots. No operational backend changes.

## Codex weekly street rhythm — active claim

Refine ambient-life probabilities by local hour and weekday, including weekend nightlife crossing midnight, ordinary passersby throughout the day, coordinated groups and commute props. Scope limited to street simulation, renderer activity props, tests and docs.

## Codex weekly street rhythm — verified, scope released

Replaced exclusive time bins with blended weekday/hour activity and vehicle probabilities. Added morning runners, visible commuters/shoppers, coordinated social groups, weekend nightlife continuing after midnight and quieter Sunday evenings. Ordinary passersby remain possible throughout; groups cannot monopolize the scene. 33 frontend tests pass, typecheck/build pass, five fixed-clock weekly browser scenarios and desktop/mobile/agent selection pass. See `STREET_LIFE.md`. No backend/provider work in this scope.

## Codex outdoor Bucharest clock — active claim

Add a pixel electronic exterior clock, 24-hour HH:mm, Europe/Bucharest with DST. Align decorative street schedule with the same timezone. Scope: clock module, renderer, street time conversion and tests.

## Codex Bucharest clock — verified

Exterior seven-segment HH:mm display added at the building base. Intl Europe/Bucharest supplies DST-aware time and weekday independently of device timezone; street rhythms share this time basis. Typecheck/build, 35 frontend tests (including both DST transitions) and browser canvas/mobile/selection checks passed. Owner has asked about bar placement; clarification pending before changing its location.

## Codex street clock placement / toolbar consistency — active

Owner clarified: controls must match the bottom dock preview; electronic clock should be a freestanding street object to one side. Fix stylesheet packaging under existing CSP and place a sculptural pixel clock to the right. Preserve concurrent dashboard additions.

## Codex clock placement / toolbar — verified, scope released

Moved HH:mm Bucharest clock off the building base onto a sculptural freestanding support at the right pavement edge, based on Owner reference images. Fixed actual toolbar inconsistency: Vite inlined the small dynamic stylesheet as a data URL, blocked by the app CSP; ?no-inline now emits a same-origin CSS asset. No CSP relaxation. Browser asserts stylesheet loaded and dock bottom placement in normal/fullscreen, mobile overflow and real agent selection; zero page errors. Main port 8000 serves the new CSS with HTTP 200. Typecheck/build passed.

## Codex inspector model mismatch — active claim

Read-only live reproduction: /office/layout omits all model fields while /settings reports Sarah has a persisted model_id. Running server exposes an older layout shape. Fix inspector to resolve authoritative agent/provider model records on open, distinguish loading/error from no assignment, and discard stale responses. No model/provider execution or reassignment.

## Codex inspector model mismatch — verified, scope released

Resolved assigned models directly from persisted agent/provider catalogs when opening the inspector; old /office/layout omissions no longer imply no assignment. Loading/error/unverified states are distinct. Added stale-request guards including queued close events. 38 frontend tests and typecheck/build pass. Read-only browser verification on actual port 8000 matched all 7 agents to Settings, including Sarah/glm-5.3-flash; no LLM calls or writes. See `INSPECTOR_MODEL_FIX.md`.

## Codex articulated street actors — active claim

Owner rejects translated walking sprites and disconnected props. Replace ambient human rendering with contact-driven articulated poses for walk/run/cycle/skate/phone/briefcase; add varied appearances and fix clock occlusion. Research: BioMotionLab and Blender IK documentation. Scope street_actor module, ambient update/renderer, tests and visual QA; operational employees/backend preserved.

## Migration-branch unification and full-tree verification — 2026-09-10, ZCode (sixth session)

The parallel sessions had advanced the project massively but left the tree unable to run:
two concurrent revisions after `0011_claim_attribution` (`0012_channel_verification` and
`0012_workforce -> 0013_story -> 0014_runbook`) gave Alembic two heads, so every
`upgrade head` — every test fixture and every bootstrap — failed with 243 errors, and
`main.py` pinned yet another revision. Verified where each session had got to, then:

- `0015_merge_heads` merges both branches into a single head (no schema of its own);
  `main.py` now pins `0015_merge_heads`. Live database bootstrapped through it.
- The 13 Phase-10 runbook failures were environmental, not logical: FFmpeg is a BLOCKING
  preflight check and this machine (like CI) has no FFmpeg. The `studio` fixture now names
  a stub path when no real encoder exists — the stage state machine stays observable
  everywhere; the real encoder path remains covered by the Phase-5 skips.
- ZCode's earlier writer tests were superseded by the parallel session's stronger
  `script_agent.py` implementation (scene-level claim citations) and its
  `test_script_writing.py` suite; the superseded tests were removed. The extraction
  pipeline tests (7) remain.

Combined tree verification: pytest **306 passed / 6 skipped**, ruff + ruff format clean,
mypy clean (89 files), frontend `tsc` clean, **38/38 frontend tests**, Vite build OK
(142.8 kB), docs integrity and secret scan pass. Live studio restarted on `0015_merge_heads`.

## FFmpeg installed on the dev machine — 2026-09-10, ZCode

Owner-approved system change: FFmpeg 9.0.1 (full build, via winget/Gyan) is installed and on
the user PATH; `.env` pins `STUDIO_FFMPEG_PATH` to the absolute executable. The studio's
live preflight moved from BLOCKED to **DEGRADED** — render_engine and media_inspection are
now OK; the remaining degradations are exactly the unlinked credentials (image provider,
voice provider, YouTube) and the empty research allowlist. Full suite with the real encoder
on PATH: **311 passed / 1 skipped** (the render tests no longer skip and pass on the real
FFmpeg path). Future `start.cmd` launches pick FFmpeg up from the registry PATH.


## Codex visual continuation — claim released 2026-09-18

Scope: art-source/unreal/flat_material.py, an isolated material repair/verification script, and visual evidence under output/visual-audit. Investigate skeletal material fallback, validate repair in a copied asset before applying, capture the existing HQ_Dusk baseline and preserve the existing Pixel Streaming/backend integration. No architecture changes. Preserve the pre-existing modification in art-source/blender/hq/build_vehicles.py. Agent: Codex /root.


## Studio Office material repair and native visual audit — 2026-09-18, Codex

Closed the narrow visual-audit scope: M_HQ_Flat skeletal usage and four garment
instances repaired, persisted in a separate UE 5.8.2 process, backed up and applied.
Captured a fresh native PlateCam still at 1920x1008 and compared L2 to the exact
Owner reference. Runtime restored after capture. No L2 geometry/look changes yet.
36 office/layout/stream/bridge tests passed; check_docs passed. New-material creation
and reuse also passed in the isolated UE project, including independent reload.
Direct Python WebRTC capture remains experimental (connected, zero video frames).
See [VISUAL_AUDIT_2026-09-18.md](VISUAL_AUDIT_2026-09-18.md) for evidence, backups, limits and the next AI's exact steps.
Concurrent backend changes and the earlier build_vehicles.py edit were preserved.


## Codex L2 review — claim released 2026-09-18; art pass deferred for stream fix

Scope: isolated Blender mesh variant and copied Unreal review level, L2 composition only. Preserve live HQ_Dusk, materials outside the review assets, backend IDs and all concurrent changes. Render before/after and record actual results. Agent: Codex /root.


### Scope steering — stream stability, 2026-09-18

Owner reports UI freezes/flicker and briefly appearing cars. L2 edits deferred while fixing proven stale reconnect timers in frontend/src/hq_stream.js and regression tests frontend/tests/hq_stream_lifecycle.test.js. No artistic assets changed in this continuation; Blender/UE inventories completed read-only.


## HQ stream stability fix — 2026-09-18, Codex

A stale fallback reconnect timer could tear down a recovered connection. Fixed cancellation/state guarding and immediate/final frame preservation in hq_stream.js. Three red regressions now pass; all 115 frontend tests, TypeScript and Vite build pass. The server serves the new bundle. Actual browser viewer recovered from a controlled outage and remained live through second 86 without another disconnect. Authenticated Owner page requires reload; full UI/traffic stability is not yet proven there. Evidence and next checks: [STREAM_STABILITY_2026-09-18.md](STREAM_STABILITY_2026-09-18.md). L2 inventory completed read-only; no art asset changed during this continuation. Scope released.


### The result, measured independently — 2026-09-23

A third pass re-shot all thirteen views at 1280×800, 1440×900, 1920×1080 and 2560×1440 into
`shots_final3`, looked at every one against `shots_final2`, and re-measured from the real pixels
rather than from the cascade. Nothing in `frontend/src` was changed by this pass; two test files
were added.

**What the numbers say.** 2 998 text/ground pairs read from the pixels of 22 views at three
widths: **0 below threshold, worst 5.09:1** (`04-media` at 2560, the model-choice reason). Over the
render: 28 pairs, 0 below, worst 5.99:1. In the per-agent Live window: 14 pairs, 0 below, worst
5.73:1. Geometry at all four widths: `scrollWidth` equals the viewport, **0** elements past the
right edge, **0** controls under 32px. A real Tab walk over the sign-in screen, the workspace and
all eight dialogs at all four widths: 0 invisible focus rings, 0 rings under 3:1, 0 focus escapes,
0 traps, Escape closes all eight and returns focus to the control that opened them. `report.json`:
**0 missing fixtures and 0 console errors at every width**. **162 frontend tests pass** (146 + 16
new), `tsc` clean, the build succeeds.

**The claims, checked one by one.** The register prints **0** rows whose detail repeats its
headline, at all three widths (was 10 of 13). The eight dialogs now open at **one** top edge per
width (40 / 54 / 72px) and **one** width (1180px at 1280, 1440px at 1920 and 2560) — before, the
tops ran 55 … 300px. The inspector's contract is three columns with a **57px** rag at 1920 and at
2560 (was 225px at 1920 and a wholly empty column at 2560). The rails are cards 92–208px tall
instead of 858px of painted ground. The module meters draw one track at one x. The live badge is
gone from the failure and loading plates.

**Two tests were added, for rules that nothing could see break.**
`frontend/tests/no_echo.test.js` holds the "print the sentence once" rule at all three places it is
applied — `withoutEcho`, the register's own row through `describeEvent`, and the letter in the mail
window — including the cases that must *not* be dropped. `frontend/tests/one_shell.test.js` reads
`style.css` and holds the one-top-edge, one-width and one-meter-track rules, and names the phone
block as the exception it still is.

**What this pass found that is still open.**

- **The mail window says its sentence twice, not three times.** The body echo is gone, but the
  dialog title and the letter's own subject line still carry the same sentence 150px apart. Closing
  that is a string or a markup decision, not a stylesheet one.
- **The Live window's void moved rather than closed.** The caption now sits at y335 directly under
  the last entry, but the 430px below it is empty and nothing anchors the window's foot. The
  duplicate-sentence half of that finding is a clear win; the layout half reads no better than
  before, and arguably worse.
- **The Daily Run tiles are a measured staircase**: rows rag 45px and 114px at 1920, 64px and 153px
  at 1280. This is the trade the stylesheet records, taken knowingly — but `audit_final.mjs`'s
  "tiles that share a row but not a bottom edge" check reports 0 because it looks for
  `.company-card` / `.wf-stat` / `.stat-card` and these tiles are `.runbook-check`. The check has a
  blind spot exactly where the trade was made.
- **The meters still read backwards under 600px.** `@media (max-width: 600px)` lays `.modules li`
  out with an `auto` status column and `min-width: 0` on the meter — the very geometry that was
  fixed above it. No width the Owner uses reaches it; `one_shell.test.js` names it out loud.
- **The wider dialog leaves some boxes short of their own section rule.** At 1440px the error,
  loading and empty wells in Research and Daily Run stop at ~1200px while the head rule beside them
  runs to the margin, and at 2560 the publishing checks card ends 125px above the channel card
  beside it.
- Everything the section above refuses is unchanged and still the Owner's: one display language,
  the `.env` sentence and the `.md` filename, the numeric fps, the seven room icons, the band above
  the render, the research form's four labels, the sign-in brand plate, and the ghost-control
  borders.

**Closed after that report, in this session, by hand (evidence `shots_last/`):**

- A state plate now meets its own section rule instead of stopping two thirds of the way across:
  the plate spans the section and the sentence keeps its 104-character measure through the box's
  own padding (`.topics-loading`, `.ledger-empty`, `.text-error`, `.settings-error`).
- A single-line form field keeps a form's measure (72ch) now that a dialog is 1440px wide, and the
  two fields of one row stay a pair instead of being pushed to opposite sides of the dialog.
- The mail window prints its sentence once: a letter whose subject *is* the window's title shows
  its intent tag without repeating the sentence 150px below it. Two tests hold the rule
  (`frontend/tests/no_echo.test.js`), and a letter with its own subject still prints it.
- The per-agent Live window's caption closes the window again (`margin-top: auto`), instead of
  floating directly under three entries with 430px of bare ground beneath it.
- The module meter reads the same under 600px as it does at every wider rule: one track, one width,
  filled 100/50/0. The phone block had kept the old `auto` geometry.

Frontend tests: **164 pass** (162 after the verifier's two files, plus the two for the mail rule),
`tsc` clean, the build succeeds, 0 missing fixtures and 0 console errors at 1920 and 1280.

Evidence: `shots_final3/`, `shots_live_p8/`, `shots_scene_p8/`, `shots_p8_states/`,
`shots_p8_dstates/` in the session scratchpad. No server, no Unreal, no Python suite, no provider,
no git command that changes state.
