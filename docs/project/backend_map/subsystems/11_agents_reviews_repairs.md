# 11 — Agent reviews, editorial verdicts and judgement loops, and the Director's repair desk

> Files (11, 6,841 lines):
> `backend/app/agents/reviews.py` (1750) ·
> `backend/app/agents/editorial.py` (629) ·
> `backend/app/agents/editorial_judgement.py` (823) ·
> `backend/app/agents/repairs/__init__.py` (263) ·
> `backend/app/agents/repairs/agent_health.py` (778) ·
> `backend/app/agents/repairs/desk.py` (794) ·
> `backend/app/agents/repairs/film_cost.py` (324) ·
> `backend/app/agents/repairs/reprice.py` (529) ·
> `backend/app/agents/repairs/stale_decisions.py` (213) ·
> `backend/app/agents/repairs/threads.py` (372) ·
> `backend/app/agents/repairs/unbilled.py` (366).
> 179 functions and methods in scope (inventory), 4,763 function lines.
>
> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

---

## In one paragraph

This group holds the **judgement tasks** that sit beside the studio's measured gates, and the
**Director's repair desk**. `app.agents.reviews` gives four roles schema-bound judgement tasks
(one each, the Director two):
Lyra (VoiceArtist) reads a storyboard's narration before it is voiced; Kael (VideoEditor)
diagnoses a failed quality-control report (the priced redo list is computed by code, not by
him); the Director decides what happens to a film that failed QC (a verdict per finding and
ACCEPT or REPAIR, validated against a schema bound to that report and to the Owner's limits)
and looks herself at bought pictures a gate refused; Vera (Publisher) writes the title,
description and tags and says READY or HOLD, after which code fits, checks and may replace her
words. The same module labels employees' letters that claim media work no event proves.
`app.agents.editorial` is the Director's last look at a finished film before publishing
(code-decided hard rejects first, then her APPROVE/REJECT with frames when her model can see);
the first sentence of her note to the Video Editor, when code finds it a general rule, becomes
an unverified prompt lesson for that kind of film (serial or factual).
`app.agents.editorial_judgement` scores a script or episode on five 0-10 criteria and drives a
rewrite loop of up to `Settings.editorial_rounds` (default 10) versions, then ships the
best-scored eligible one. `app.agents.repairs` is a registry of seven deterministic repairs
(diagnose an employee's failures, switch a failing model after probes, price unpriced runs,
report film cost, close stale decisions, close looping letter threads, ask the Owner for
invoices) that the Director's loop can choose; `repairs.desk` asks the Policy Kernel before
queueing and again before applying, records a `DirectorDecision`, an event and one STATUS
letter, and turns anything only the Owner can do into one deduplicated decision card. Of the
eleven files, only eight functions write a question to a model (899 of 4,763 function lines);
everything in `repairs/*` except one liveness probe is strict code.

---

## Why it exists

| Problem / incident | What it produced here | Source |
|---|---|---|
| The VoiceArtist, VideoEditor and Publisher "had no work of their own — their names sat on stages that ran without them". | One judgement task each, with a fixed output schema validated before anything is stored; an unparsable answer is a failed review, never interpreted. | `reviews.py:1-16` |
| Nepal film, 2026-09-26: Kael's free-text correction ("re-render") bought a second whole film with the same prompts. | His diagnosis now carries the studio's own priced per-scene redo proposals; a whole-film render is never recommended (`_WHOLE_FILM`, `retry_recommended` forced False). | `reviews.py:18-23`, `reviews.py:310-315`, `reviews.py:512-521` |
| Same evening: Kael wrote "Am re-randat pista audio" with nothing rendered, and the Director reported it to the Owner as done. | `mark_unproven_claims` labels such letters "NEEFĂCUT — afirmație fără dovadă" before the Director reads them. | `reviews.py:24-28`, `reviews.py:1260`, `mail.py:563-566` |
| 2026-10-10, film babcf272: Kael's diagnosis was ignored and a mechanical repair redid scenes 1-2 unasked, retiring takes the Owner approved. Owner: «BA DA! POATE DECIDE SINGURĂ!» | Nothing is redone before the Director reads the report: a verdict per finding, a decision, and code carries it out under the Owner's rules (ADR-2026-10-10). | `reviews.py:566-577`, `16_DECISION_LOG.md` (ADR-2026-10-10) |
| Template history v2…v8 of the Director's QC prompt (REPAIR that can be carried out, LOCAL_MOVE, music licences, approved takes, her looks, non-final approvals). | `DIRECTOR_QC_TEMPLATE_VERSION = "director-qc-v8"`. | `reviews.py:580-589` |
| Owner 2026-10-12: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE» (19.50 USD spent that day, 11.05 on redos). | Every REAL/ACCEPTED finding must state severity, cause and lesson; a minor defect is ACCEPTED, never REAL. | `reviews.py:585-588`, `reviews.py:610-620`, `reviews.py:683-704` |
| Owner 2026-10-11: «Nu trebuie să respingă un film, trebuie să îl refacă până trece QC». | CLOSE is refused by the bound schema; the film is REPAIRed or ACCEPTed. | `reviews.py:860`, `reviews.py:865-871` |
| aa170155, 2026-10-12: a scene that passed three times failed the fourth unchanged; scenes 4-5 that had passed were relisted and new motion bought. Owner: «Nu putem permite loopuri pe bani…». | `passed_scene_refusal`: a scene `passed_before_unchanged` is never REAL on a picture finding and never redone; a paid redo only for a scene a REAL finding names. | `reviews.py:781-845` |
| 2026-10-10 review: with the paid-redo limits spent, a REPAIR of only paid redos validated, did nothing, and was asked every hour until the watchdog gave up. | `decision_schema` refuses a REPAIR none of whose redos can be carried out now; the prompt says so up front. | `reviews.py:856-860`, `reviews.py:1009-1022` |
| 2026-10-10 20:06, Owner: «Directorul ce face? El ar trebui să hotărască dacă poza este bună sau nu.» A stills gate refused every candidate of her repair on a misreading. | `review_bought_pictures`: she looks at the refused candidates herself and CHOOSEs one or REJECTs all. | `reviews.py:1077-1083` |
| Audit PUB-06: a Publisher answer a few characters over YouTube's limits cost the film its day. | Generous schema bounds; code fits title/tags (`youtube_safe_metadata`), at most 15 tags. | `reviews.py:1438-1453`, `reviews.py:1577-1585` |
| Rehearsal 2026-09-18: both films went up as "Infrared light and what it shows". | `publication_metadata_refusals` guard; for a serial episode the studio's own fallback metadata replaces refused Publisher words. | `reviews.py:1586-1630` |
| The Owner asked how a film with no story, in the wrong language, on one sourceless claim could be published. | `editorial.py`: the Director's last look; code-decided hard rejects; frames from the file. | `editorial.py:1-24` |
| ATLAS film: three frames at 20/50/80 % showed three of five scenes; eleven seconds of stripes were approved. | One frame from the middle of every scene, scaled to the real length. | `editorial.py:340-345` |
| Review of a9f84ea, 2026-10-12: her note to the Video Editor was stored bare as a studio-wide lesson, so a note about one film's «scene 4» would have been a rule for every film, and a note over 400 characters was refused whole, its rule with it. | `picture_lesson` keeps only the note's first sentence when it is a general rule; it is stored for its kind of film (serial or factual) and as unverified (commit 68fa0b4). | `editorial.py:403-417`, `editorial.py:578-590` |
| «The Zero Script Club» (episode 043317d3): structurally clean, but a status meeting. Owner card 2026-10-11 23:30: «vreau să încerce de 10 ori…». | `editorial_judgement.py`: five criteria, bar 35/50 with floor 5, brief, rewrite, up to 10 versions, best ships. | `editorial_judgement.py:1-46`, `16_DECISION_LOG.md:71-73`, `CHANGELOG.md:122-128` |
| Owner 2026-10-11: «vreau ca directoarea să poată repara asta». 167 runs unpriced; a 30-day failure rate (92.9 %) that was one retry storm; three HANDOFFs about film cost looping; ten decisions OPEN for weeks; 47 cost rows ESTIMATED. | The repair desk and its seven repairs (commit 54bd847). | `repairs/__init__.py:1-53`, `agent_health.py:1-33`, `reprice.py:1-26`, `film_cost.py:1-22`, `threads.py:1-25`, `stale_decisions.py:1-19`, `unbilled.py:1-19`, `CHANGELOG.md:196-199` |

Specifications implemented: the risk tiers and Owner decision cards of
`docs/architecture/31_GOVERNANCE_APPROVAL_POLICY.md` ("Action risk tiers": T2 "change employee
model" is exactly `switch_agent_model`'s tier; "Owner decision cards (amended 2026-10-03)":
"Anyone may propose; only the Owner decides" is how every card here is raised); the modes of
`docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md` (read through `may_act`); runbook §9 Edit/QC
and §10 Publish of `docs/architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` (the QC reviews and the
pre-publication reviews are called from those stages).

---

## Who decides here

| # | Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|---|
| 1 | Whether a storyboard's narration is speakable (PASS/FLAG) and its pronunciation hints | LLM | `reviews.py:203-284` | Lyra's answer, schema `NarrationReview`; a FLAG is only an ESCALATE letter: the render proceeds regardless (`stages.py:3364-3371`) |
| 2 | Which scenes/tracks of a failed render are proposed for redo, and at what price | CODE_RULE | `reviews.py:400-452`, `reviews.py:327-388` | `qc_report.redo_proposals` over the report and the sheet; prices from the recorded sheet, else the raw price table (`load_price_table`, a CONFIG file); a model not in the table stays unpriced |
| 3 | Whether Kael's correction is used | CODE_RULE | `reviews.py:512-531` | His text is kept as `model_correction`; the published correction is `_correction_ro(proposals)`; refused in words when it asks for a whole render (`_WHOLE_FILM` regex or `retry_recommended`) |
| 4 | `owner_action_needed` on a render diagnosis | LLM_CHECKED_BY_CODE | `reviews.py:523-525` | OR of Kael's flag and "any proposal with credits ≠ 0" (an unpriced proposal counts); only stored in his letter's body |
| 5 | Verdict per QC finding (REAL / FALSE / OWNER_CHOICE / ACCEPTED) | LLM_CHECKED_BY_CODE | `reviews.py:605-708`, `reviews.py:862-891` | Every finding judged once, none invented; REAL/ACCEPTED need severity, cause, lesson ≤240 chars; minor ≠ REAL; picture finding on a `passed_before_unchanged` scene ≠ REAL |
| 6 | The film's fate after failed QC: ACCEPT or REPAIR | LLM_CHECKED_BY_CODE | `reviews.py:981-1074`, then `stages.py:4316-4365`, `stages.py:4466-4479` | Bound schema; ACCEPT with any REAL refused; REPAIR needs ≥1 REAL and ≥1 redo carriable now (`repair_refusal`); an ACCEPT over a `not_yours` finding is turned into ACCEPT_REFUSED by the caller |
| 7 | Closing a film for quality | CODE_RULE | `reviews.py:865-871` | CLOSE never validates (Owner rule 2026-10-11): refused, whatever the model answers |
| 8 | Which redos a REPAIR may list | CODE_RULE | `reviews.py:711-769`, `reviews.py:781-845` | The list is hers; the rule over it is code: no card redo on a filmed scene; free fix once per film; no redo of a scene `passed_before_unchanged`; no redo of a take the Owner approved as final; no paid motion on LOCAL_MOVE; paid redo only with `paid_redos_left > 0` or motion after a new still; still/motion only for a scene a REAL finding names |
| 9 | Paid redos actually bought for her REPAIR | OWNER | outside scope: `stages.py:4483-4502` → `_director_repairs` / `_apply_repairs` | The Owner's `paid_media_approval` read in `may_act` (`services.py:1520-1592`: EVERY_PAID_STEP asks him for every step in every mode, OVER_USD above his threshold, MODE hands it to the mode); code adds the per-scene/per-film caps (`Settings.film_max_paid_redos_per_scene` 5 / `film_max_paid_redos` 20, `config.py:314-315`, read in `stages.py:4212-4216`), the prompt corrected first, and the budget reservation |
| 10 | Which refused candidate becomes a scene's take | LLM | `reviews.py:1148-1255`, executed by `director_qc.record_look` | `look_schema`: CHOOSE names a shown candidate (1..n); nothing else about the picture is checked by code; the Owner's later look replaces hers |
| 11 | Model used for her look | CODE_RULE | `reviews.py:1181`, `vision.py:162-185` | Her model if it sees, else her 2nd/3rd slot, else a LOOKERS employee's model; the kernel checks the borrowed model against her role (`PolicyKernelError` → `ReviewError`) |
| 12 | A letter's claim of media work labelled NEEFĂCUT | CODE_RULE | `reviews.py:1350-1432` | Past-tense regexes; negation/future in the same clause ignored; proven only by a media.* event of a matching type since the thread began |
| 13 | Publication metadata (title, description, tags) | LLM_CHECKED_BY_CODE | `reviews.py:1485-1703` | Language hold, YouTube-safe fitting, ≤15 tags of ≤30 chars, `publication_metadata_refusals`, serial fallback and series format |
| 14 | READY vs HOLD for publication | LLM_CHECKED_BY_CODE | `reviews.py:1572-1634` | Vera's HOLD stands; her READY is turned to HOLD by the language rule or the metadata guard; a serial READY with refused words is replaced by the studio's fallback, HOLD if that also fails |
| 15 | Whether a candidate may proceed past a Publisher HOLD | LLM | `reviews.py:1717-1750`, `stages.py:5774-5796` | An OPEN ESCALATE with verdict HOLD blocks. It is lifted by whoever closes the letter; the decider labelled here is the Director's inbox review, a model decision (`agents/director.py:345-466`): ACKNOWLEDGE / APPROVE / REJECT resolve it RESOLVED, and `approved_metadata` then reuses the held metadata (re-checked only by `publication_metadata_refusals`, `stages.py:5784-5796`); REQUEST_INVESTIGATION / ESCALATE_TO_OWNER mark it ANSWERED (`director.py:409-415`, `director.py:442-448`; an ESCALATE_TO_OWNER that is not the Owner's matter is first turned into ACKNOWLEDGE, `director.py:370-378`), which also ends the block but is not "approved", so the Publisher is asked again. The Owner's resolve button (`router.py:180-188`) and a `close_thread` repair can close it too |
| 16 | Hard editorial rejects (missing claim row, no/sourceless or unverified claim, < 40 words, not English, no script, narration not grounded) | CODE_RULE | `editorial.py:199-250` | `MIN_WORDS = 40`; English check only when language is "en"; serial episodes are exempt from the source, verification, no-claims and grounding rules (`editorial.py:222-223`, `editorial.py:239`, `editorial.py:246`), but a claim id whose row is gone is a hard reject for both kinds (`editorial.py:204-207`) |
| 17 | APPROVE / REJECT of a finished film | LLM | `editorial.py:455-508`, `editorial.py:546-549` | Only when no hard reject; schema `EditorialVerdict`; REJECT sets `Storyboard.status = "REJECTED"`; APPROVE is necessary for publishing (`stages.py:5729-5736`) but the publishing gate and the Owner's mode still decide after it |
| 18 | Whether frames are attached for the editorial look | EXTERNAL | `editorial.py:313-331`, `editorial.py:459-466` | The provider's declared `vision` capability of the Director's own model (a stored `ModelCapability` row); ffmpeg present and the file readable |
| 19 | VideoEditor note → prompt lesson for its kind of film | LLM_CHECKED_BY_CODE | `editorial.py:578-590`, `editorial.py:403-417` | Her note's text is hers; code keeps only its first sentence (cut at the first `.`, `!` or `?` followed by whitespace, `editorial.py:400`), and only if it is ≤ `LESSON_MAX_CHARS` 400 (`prompt_agent.py:133`) and `lesson_is_general` against this film's title (the script's, else the storyboard's, `editorial.py:261`) finds no whole UUID, no scene, shot or beat named by its number (English or Romanian forms; a length such as «shot 5 seconds» passes, `prompt_agent.py:3126-3131`) and no run of three consecutive title words of which two carry meaning (`prompt_agent.py:3361-3373`, `prompt_agent.py:3376-3397`); else nothing is learned. Nothing checks whether the rule is true. `record_prompt_lesson` then refuses it again against every storyboard's title and the head of any storyboard id (`lesson_refusal`, `prompt_agent.py:3415-3426`) and compares it with the 40 newest live lessons of its scope and of "all": when the closest holds ≥ 0.9 of its words, that older lesson is refreshed: retired and stored again as newest, in the older words if they are longer or of another scope, under the older's scope, confirmed if the older was confirmed, with this run as its source (`prompt_agent.py:3474-3488`); ≥ 0.6 → it supersedes the closest when that one has the same scope (an "all" lesson stays); else stored (`prompt_agent.py:3429-3492`). Stored with scope `serial` when `facts["serial"]`, else `factual`, and `provisional=True` (`editorial.py:584-590`); recorded on APPROVE as well as REJECT |
| 20 | Editorial scores (five criteria 0-10) | LLM | `editorial_judgement.py:168-282` | Schema only: a score outside 0..10 is refused, not clamped (`Field(ge=0, le=10)`); "7", 7.0 and 7.5 become 7 (`_whole`); nothing checks the scores themselves. Totals and weakest two are computed by code from them, her own "weakest" list is ignored |
| 21 | Whether a version passes the bar | LLM | `editorial_judgement.py:278-281` | Her scores, taken as given, summed against a fixed bar the prompt tells her (`editorial_judgement.py:335-344`): total ≥ 35 and every criterion ≥ 5. The bar is code; the pass is decided by her numbers |
| 22 | Whether another rewrite round runs | LLM_CHECKED_BY_CODE | `editorial_judgement.py:688-713` | Her scores below the bar ask for a rewrite; code stops at the first *eligible* pass (structural review PASS), when `allowed` rounds are spent, when the writer returns None, or when the judge returns None |
| 23 | Number of rounds | CONFIG | `editorial_judgement.py:629-637`, `config.py:15`, `config.py:434` | `Settings.editorial_rounds` (`STUDIO_EDITORIAL_ROUNDS`), default 10, bounds 1..20 |
| 24 | Which version ships | LLM_CHECKED_BY_CODE | `editorial_judgement.py:715-717`, `editorial_judgement.py:540-545` | Highest (total, floor, earlier) among eligible judged versions; eligibility = the structural review's PASS; none judged → the first version ships unjudged |
| 25 | Letter to the Owner about the judgement | CODE_RULE | `editorial_judgement.py:773-823` | Only when a judged version ships below the bar |
| 26 | Which matters the repair desk offers the Director | CODE_RULE | `desk.py:122-204` | Detector output, less cases OPEN or SETTLED; a declined/held/dead case again after 24 h, at most 3 tries; a held matter waits 24 h |
| 27 | Whether a repair is made at all (choice) | LLM | `command.py:944-1004` (caller) | Her `_choose` answer (via `ensemble.run_with_strategy`, `command.py:1156`; without a Director or model the measurements' own suggestions, `command.py:1097-1099`); a HOLD/COOLDOWN/REDUCE/STOP (or NEEDS_MORE_DATA where the matter did not suggest it) is acted on as given → `hold_repair` (`command.py:982-986`). Code adds: T0-T2 repairs she left out follow with the matter's suggested decision (`command.py:949-956`); at most `MAX_REPAIRS` = 6 per loop; nothing above T2 runs unchosen |
| 28 | Whether a chosen repair is queued | CODE_RULE | `desk.py:313-332` | Policy Kernel: `may_act(action, tier, ask_owner=False)`; STOP, T4, SAFE_MODE (> T1), mode ceiling (MANUAL T1, SUPERVISED T2, AUTONOMOUS_CEO T3: `services.py:528`) |
| 29 | A second decision for the same case | CODE_RULE | `desk.py:336-352` | Same idempotency key today, or any OPEN decision on the matter → ALREADY_DECIDED |
| 30 | Whether a queued repair is applied | CODE_RULE | `desk.py:531-594` | Decision still OPEN; no applied/declined event for this task; kernel asked again; precondition read again; exception → DECLINED |
| 31 | A repair the kernel refuses, or one repeated ≥3 times in 24 h | CODE_RULE | `command.py:987-1021`, `desk.py:489-508` | Escalated by code as one card per matter and cause, quiet 7 days after an answer; what then happens is the Owner's answer on the card |
| 32 | Cause of an employee's failures | CODE_RULE | `agent_health.py:201-294`, `agent_health.py:154-168` | Failing now = the current model is gone (verified once, unavailable since), or its last 3 runs since it was assigned all failed at the model (FAILED/EMPTY_OUTPUT) with the latest < 24 h (`agent_health.py:243-259`). Cause: MODEL_GONE; else the last 3 classified (HTTP 401/402/403, 404/"unavailable", 429, all EMPTY_OUTPUT, schema/json/validation text, else PROVIDER_ERROR); else, with ≥3 runs and ≥50 % failures in 7 days, the week's failures classified the same way; else STALE_HISTORY (`agent_health.py:267-274`). Probe runs are left out |
| 33 | Whether the employee's current model is down now | EXTERNAL | `agent_health.py:634-647` | The probe's run status: answered (SUCCEEDED, non-empty text) → NOTHING_TO_DO; a status in `DOWN` (FAILED, EMPTY_OUTPUT, BLOCKED_PROVIDER, ValueError) → switch proceeds; any other status (a budget or kernel refusal recorded as a BLOCKED_* run, a `PolicyKernelError`) → DECLINED |
| 34 | Which model replaces it | CODE_RULE | `agent_health.py:455-527`, `agent_health.py:665-672` | Available, on a verified `settings:` connection with an adapter in the registry, provider cached status HEALTHY/UNKNOWN (EXTERNAL), not Anthropic/Claude (hard-coded Owner rule), not on the Owner's deny list (CONFIG: `integrations.lifecycle.deny_patterns(settings)`; no settings → no candidate), role capabilities, priced both token sides, not failing elsewhere; ranked home → seeded allocation → successes in 7 days → name; first of ≤3 that answers a probe (EXTERNAL) |
| 35 | A second model switch in a day | OWNER | `agent_health.py:652-664` | `SWITCHES_PER_DAY = 1` (rolling 24 h, origin DIRECTOR_REPAIR); the second is an `agent_model_failing` card |
| 36 | Pricing unpriced runs | CODE_RULE | `reprice.py:286-439` | Only a price active now, both sides; never writes a price (prices are the Owner's); refused if it would push a non-exceeded active budget period over its limit, and the budget then goes to the Owner as a card |
| 37 | Asking the Owner for a price | CODE_RULE | `reprice.py:201-219`, `reprice.py:384-391` | Kind with no price, oldest run ≥ 24 h, no open card for that kind |
| 38 | Closing a stale DirectorDecision | CODE_RULE | `stale_decisions.py:97-136` | Letter RESOLVED/ANSWERED (HANDOFF needs a done=true reply) and no review pending; or a later `review_<matter>` REVIEWED; or its repair task ended/never queued (60 min) |
| 39 | Whether a letter thread is looping | CODE_RULE | `threads.py:78-117` | ≥3 replies by one employee in 600 s, or two consecutive replies of one employee whose body texts share ≥ 0.8 of their content words (Jaccard, `ensemble.agreement`, `ensemble.py:169-176`), within 48 h and after the Director last closed it |
| 40 | Which letters the Director may close | CODE_RULE | `threads.py:120-158` | Not the Owner's (to or from), not the worker's own reports, not standing weekly guidance, not a budget request |
| 41 | Asking the Owner for an invoice | CODE_RULE | `unbilled.py:109-145`, `unbilled.py:275-351` | ESTIMATED, unreconciled cost rows older than 7 days, per provider and month; one card per exact set of rows, never asked again for that set |
| 42 | Film cost report and closing the review that asked for it | CODE_RULE | `film_cost.py:120-309` | One join over the books and the latest analytics snapshot; agent cost stated "neatribuit"; with a `decision_id` param the reviewed decision is closed with the report, and its thread's letters only when that decision asked for this report (`asks_film_cost`, `film_cost.py:266-290`) |

---

## LLM involvement

### How much is LLM here

| Measure (inventory, static) | Value |
|---|---|
| Functions/methods in scope | 179 (4,763 function lines) |
| LLM call sites (write the question, use the answer) | 8 (899 lines, 19 %) |
| Functions with any static path to `run_agent_task` | 11 (1,167 lines, 24.5 %): the 8 sites, the gateway `reviews._run`, `editorial_judgement.editorial_loop` (3 hops), `repairs.agent_health.switch_model` (2 hops) |
| Not seen statically | `repairs.desk.execute_repair` reaches `switch_model` → `_probe` → `run_agent_task` through the registered `Repair.function` object (`desk.py:581`) |
| Repairs that ask a model | 1 of 7 (`switch_agent_model`, a liveness probe whose text is not read) |

Every call site except the liveness probe (#8, free text, not parsed) validates the model's
answer against a pydantic schema before anything is stored; four of them (`review_film_qc`, `review_bought_pictures`, `editorial_review`, `judge`)
go through `app.agents.structured.structured_run` (two attempts at most: the shape is fitted
before it is refused; no object → same prompt with native thinking; refused object → the
refusal quoted, thinking off: `structured.py:93-96`; a run that is not SUCCEEDED or returns
empty text, e.g. a kernel or budget refusal recorded as a BLOCKED_* run, is not retried:
`structured.py:138-140`);
the other three reviews go through `reviews._run` (one attempt, temperature 0.1, no message
emitted: `reviews.py:121-151`) and `parse_structured`. The liveness probe (#8) calls
`run_agent_task` directly. The Director's explicit output limits
are multiplied in `run_agent_task` by `Settings.director_token_multiplier` (default 2, bounds
1..4; `16_DECISION_LOG.md` ADR-DIRECTOR-TOKEN-BUDGET-X2), so her 6,000-token requests run at
12,000 by default.

### 1. `review_narration` — Lyra, the VoiceArtist (`reviews.py:203`)

| Item | Value |
|---|---|
| Speaker | The active `VoiceArtist` (`agent_for_role`, `reviews.py:214`); `NoReviewer` when none |
| Task / template | `review_narration` / `review-v1` (`reviews.py:94`), temperature 0.1, `max_tokens=4500` (`reviews.py:228`) |
| Asks | Whether each scene can be spoken naturally within its duration; pronunciation hints for numbers, units, acronyms, foreign names; never rewrite the words (`reviews.py:191-200`). Data: title + per scene index, narration, duration, inside `wrap_in_inert_boundary` |
| Answer | `NarrationReview {verdict: "PASS"\|"FLAG", notes ≤12, pronunciation ≤40 × PronunciationHint{scene_index ≥0, term ≤120, hint ≤300}}` (`reviews.py:177-188`) |
| Use | AGENT_OPINION memory (`reviews.py:252-259`); a letter to the Director's inbox, ESCALATE for FLAG, STATUS for PASS, carrying the hints (`reviews.py:260-274`). The caller only records the verdict (`stages.py:3364-3371`): the render goes on whatever she says |
| Trust | **ADVISORY** |
| Failure | Run not SUCCEEDED or empty text → `ReviewError` (`reviews.py:145-150`); a structured blocker → ESCALATE letter and verdict BLOCKED (`reviews.py:235-244`); unparsable → `ReviewError`, nothing saved (`reviews.py:245-247`). The caller catches `ReviewError`, `NoReviewer`, `ValueError` and continues (`stages.py:3370-3371`) |
| Spend | No. It runs after the film's budget reservation (`stages.py:3348-3362`); its verdict does not change what is bought |

### 2. `review_failed_render` — Kael, the VideoEditor (`reviews.py:455`)

| Item | Value |
|---|---|
| Speaker | The active `VideoEditor` (`reviews.py:469`) |
| Task / template | `review_failed_render` / `review-v1`, temperature 0.1, `max_tokens=3600` (`reviews.py:497`) |
| Asks | Diagnose which check failed and why, say which of the studio's computed redo proposals to take and in what order, or what the Owner must decide; never propose rendering the whole film (`reviews.py:298-308`). Data (≤12,000 chars, `reviews.py:488`): the redo proposals first, asset id, provider, failure reasons, scene kinds, checks, production purposes |
| Answer | `RenderDiagnosis {diagnosis ≤1000, correction ≤1000, retry_recommended: bool, owner_action_needed: bool}` (`reviews.py:290-295`) |
| Use | His `diagnosis` text is kept. His `correction` is kept only as `model_correction`; the stored `correction` is the code's `_correction_ro(proposals)` (`reviews.py:391-397`, `reviews.py:520`); `retry_recommended` is always False (`reviews.py:521`); a whole-film correction is refused in words (`reviews.py:512-517`); `owner_action_needed` is OR-ed with "any proposal not 0 credits" (`reviews.py:523-525`). AGENT_OPINION memory + one ESCALATE letter with the Owner's deterministic summary (`qc_summary_ro`) as body text (`reviews.py:532-555`). The result is passed into the Director's QC context (`stages.py:3789-3791`) |
| Trust | **ADVISORY** (the redo list and its prices do not depend on his answer; his diagnosis is one input the Director weighs in her own decision, #3) |
| Failure | Same as #1; caller records `error`/`error_class` and still asks the Director (`stages.py:3779-3791`) |
| Spend | No. Prices are information only |

### 3. `review_film_qc` — the Director, deciding a failed film (`reviews.py:981`)

| Item | Value |
|---|---|
| Speaker | The active `Director` (`reviews.py:999`) |
| Task / template | `director_qc_review` (`reviews.py:579`) / `director-qc-v8` (`reviews.py:589`), via `structured_run`, `max_tokens=6000` (×2 by the Director multiplier) (`reviews.py:1028-1043`) |
| Asks | A verdict for every finding (REAL / FALSE / OWNER_CHOICE / ACCEPTED, with severity, cause and a lesson for REAL/ACCEPTED), then ACCEPT or REPAIR with a per-scene redo list (still / motion / card / audio / encode) and a two-sentence Romanian summary for the Owner (`reviews.py:896-959`). The prompt states the Owner's constraints (final approvals, LOCAL_MOVE, paid redos left, free fix once, `not_yours` findings, "money is not yours to decide"). When no redo at all is possible, a prefix tells her REPAIR is impossible now (`reviews.py:1009-1022`). Data: the context built by `media.director_qc.film_qc_context`, serialised to ≤ 24,000 chars by dropping optional keys (`checks`, `earlier_reviews`, `redo_proposals`, `your_looks`) before core evidence (`reviews.py:963-978`) |
| Answer | `decision_schema(findings, scenes, context)` → `BoundDecision(DirectorQcDecision)`: `verdicts[1..80] × FindingVerdict{finding ≥1, verdict, reason ≤400, severity minor\|serious, cause ≤400, lesson ≤240}`, `decision ACCEPT\|REPAIR\|CLOSE`, `repairs ≤24 × DirectorRedo{scene_index ≥1, redo, reason ≤400}`, `summary ≤800` (`reviews.py:605-708`, `reviews.py:848-893`) |
| Checks in code | One verdict per finding; ACCEPT with a REAL refused; REPAIR needs repairs and ≥1 REAL; non-REPAIR lists no repairs; REAL/ACCEPTED need severity, cause, lesson; REAL ≠ minor (`reviews.py:671-708`). Bound to the report: CLOSE refused; the judged set equals the report's findings; repaired scenes exist; `passed_scene_refusal`; `repair_refusal` (`reviews.py:862-891`). After it returns: lessons stored (`stages.py:4345`), an ACCEPT over a `not_yours` finding becomes ACCEPT_REFUSED (`stages.py:4466-4476`), a REPAIR is carried out only through the paid redo path under the Owner's rules (`stages.py:4483-4502`, docstring `stages.py:4604-4612`) |
| Use | AGENT_OPINION memory (`reviews.py:1054-1065`); the decision dict returned to `runbook.stages._director_reads` |
| Trust | **CHECKED_BY_CODE** |
| Failure | No valid object after at most two attempts (a failed or empty run is not retried) → if a blocker: `ReviewError("Directoarea s-a oprit…")`; else `ReviewError`, "nimic nu s-a refăcut" (`reviews.py:1045-1053`); no Director → `NoReviewer`; no findings → `ReviewError` (`reviews.py:1004-1005`). The caller then puts the report back to wait (`director_qc.wait_for_director`, `stages.py:4327-4328`; also with no language model, `stages.py:4321-4324`); the `director_qc_review` watchdog pass queues the film's continuation again after `RETRY_MINUTES` = 60, at most `MAX_TRIES` = 24 rounds that reached her (`workflows/passes/director_qc_review.py:42-49`) |
| Spend | **Yes, indirectly**: a REPAIR leads to paid still/motion redos on the media providers, gated by `repair_refusal` here and, downstream, by the Owner's paid-media rule in `may_act`, his per-scene/per-film redo limits, the corrected-prompt rule and the budget |

### 4. `review_bought_pictures` — the Director looks at refused candidates (`reviews.py:1148`)

| Item | Value |
|---|---|
| Speaker | The Director's identity, on a model that sees: `vision.seeing_model(session, director_id, *LOOKERS)` with `LOOKERS = ("VideoEditor", "Director", "QualityAssurance")` (`reviews.py:1181`, `picture_qc.py:119`); the run is hers whichever model answers |
| Task / template | `director_take_look` / `director-look-v1` (`reviews.py:1085-1086`), `structured_run`, `max_tokens=4000` (×2: the run is the Director's, so `run_agent_task` applies her multiplier, `services.py:793-798`), images in `extra`, `model_id` pinned (`reviews.py:1201-1218`) |
| Asks | Look at every candidate (one picture per still candidate, or first/middle/last frames per clip); CHOOSE the one right for the scene (continuous picture, the scene's subject, the film's look, the bible's rules) or REJECT all; say what she sees and whether the gate's reasons are really there (`reviews.py:1126-1145`). Data ≤12,000 chars |
| Answer | `look_schema(n)` → `BoundLook(DirectorLook){decision CHOOSE\|REJECT, candidate 1..n or null, reason ≤600}` (`reviews.py:1091-1123`) |
| Use | AGENT_OPINION memory; returned to `stages._director_looks`, which calls `director_qc.record_look`: the chosen take is written APPROVED by her (`approved_by` the Director, not the Owner), so the walk continues "exactly as with a still the gate approved" (`director_qc.py:2076-2088`) |
| Trust | **FINAL** (her choice overrides the gate's refusal; code only checks that the candidate was shown and, at record time, that the take did not change since) |
| Failure | No images → `ReviewError`; no Director → `NoReviewer`; nobody's model sees → `ReviewError` (`reviews.py:1184-1187`); borrowed model unavailable or refused by the role check → `PolicyKernelError` → `ReviewError` (`reviews.py:1219-1222`, raised at `services.py:819-824`); no valid object after at most two attempts → `ReviewError`. The caller waits (`stages.py:4426-4432`) |
| Spend | Choosing buys nothing (`reviews.py:1138`), but a chosen still lets her REPAIR's walk proceed to the scene's motion step "under every money gate" (`director_qc.py:2083-2085`) |

### 5. `prepare_publication` — Vera, the Publisher (`reviews.py:1485`)

| Item | Value |
|---|---|
| Speaker | The active `Publisher` (`reviews.py:1495`) |
| Task / template | `prepare_publication` / `review-v1`, temperature 0.1, `max_tokens=4500` (`reviews.py:1546-1555`) |
| Asks | Title (≈60, never >100 chars), description (hook + takeaway first, 2-3 sentences, 2-3 hashtags), up to 15 specific tags, nothing not in the script, then READY or HOLD (`reviews.py:1456-1472`); for a serial episode, the series' title format and logline (`reviews.py:1476-1482`). The audience language line is prepended. Data (≤12,000 chars): script title (`hook_of`), channel, scenes, the story's hook/message/takeaway, and the episode identity |
| Answer | `PublicationMetadata {verdict READY\|HOLD, title ≤300, description ≤20000, tags ≤60, hold_reasons ≤10}` (`reviews.py:1438-1448`) |
| Checks in code | Language hold → HOLD (`reviews.py:1572-1576`); tags whitespace-normalised and cut to 30 chars, title made YouTube-safe (≤100 chars, no `<`/`>`), ≤15 tags (`reviews.py:1577-1585`); `publication_metadata_refusals` (episode title/tags must not copy another channel's film of the last 24 h and must share a meaning word with the episode; it returns nothing for a factual film, so a factual READY is checked only by the language rule and the YouTube fitting: `publishing/services.py:1509-1519`) (`reviews.py:1591-1594`); for a serial READY with refusals her words are replaced by `fallback_metadata`, judged again by the same guard and language rule, HOLD if refused (`reviews.py:1597-1630`); otherwise refusals turn READY into HOLD (`reviews.py:1631-1634`); every episode gets the series title/description/tags format (`reviews.py:1635-1645`) |
| Use | AGENT_OPINION memory; a letter (ESCALATE for HOLD, STATUS for READY) with the final metadata, `metadata_source` and any refused Publisher answer (`reviews.py:1646-1690`). `_publish_one` refuses to publish on HOLD and uses the metadata on READY (`stages.py:5806-5827`) |
| Trust | **CHECKED_BY_CODE** |
| Failure | As #1; caller returns SKIPPED for the day (`stages.py:5809-5814`) |
| Spend | No money; READY leads toward a public upload (T3 external write). In `_publish_one` the editorial look and the publishing gate run before her (`stages.py:5699-5771`); after her READY only `mode_refusal("publishing.public_publish")` stands between her metadata and the upload (`stages.py:5845-5856`) |

### 6. `editorial_review` — the Director's last look (`editorial.py:428`)

| Item | Value |
|---|---|
| Speaker | The active `Director` (`editorial.py:439`) |
| Task / template | `editorial_review` / `editorial-v1` (`editorial.py:72-73`), `structured_run`, `max_tokens=6000` (×2), temperature 0.1, frames in `extra` (`editorial.py:484-501`) |
| Asks | Judge the film as the audience will: factual brief (one clear story with a hook and point, every sentence learnable and sourced, in the audience's language; a film about the studio itself is REJECTED) or serial brief (situation, turn, payoff, characters sounding like people; no sources needed) (`editorial.py:112-156`); a blank field, stripes, noise or garbled writing in any frame means REJECT. Data (≤14,000 chars): `gather_facts` minus path and hard rejects |
| Answer | `EditorialVerdict {verdict APPROVE\|REJECT, story ≤400 (clipped), reasons ≤8, notes_for {role: text}}` (`editorial.py:90-96`) |
| Checks in code | Before the model: hard rejects decide REJECT with no model (`editorial.py:448-454`); after: none on the verdict. Only the VideoEditor note is filtered before it becomes a lesson: `picture_lesson` keeps its first sentence if that is a general rule of ≤400 chars (`editorial.py:403-417`), then `record_prompt_lesson` refuses, refreshes or supersedes (Who decides #19) |
| Use | `media.editorial_reviewed` event and an `EditorialReview` row (`editorial.py:514-545`); REJECT → `Storyboard.status = "REJECTED"` (`editorial.py:546-549`); a STATUS/ESCALATE letter to the Director's inbox (`editorial.py:564-574`); the first sentence of her VideoEditor note, when `picture_lesson` and `record_prompt_lesson` keep it, becomes an unverified prompt lesson for the film's kind (`record_prompt_lesson(scope=serial\|factual, provisional=True)`, `editorial.py:578-590`), given to that kind's prompt writers after the confirmed lessons, with " (unverified)", within the 12 lessons given (`LESSONS_GIVEN`, `prompt_agent.py:126`, `prompt_agent.py:3348-3351`); on REJECT one HANDOFF "Refăcut: …" per department named in `notes_for` (`editorial.py:592-611`); AGENT_OPINION memory. `_publish_one` publishes only after APPROVE (`stages.py:5729-5736`) |
| Trust | **FINAL** for REJECT (the storyboard is closed); APPROVE is necessary but the publishing gate, the Publisher's HOLD and the Owner's mode still follow. The lesson drawn from her note is **CHECKED_BY_CODE** (first sentence, length, `lesson_is_general`, `lesson_refusal`) |
| Failure | No valid object after at most two attempts (a failed or empty run is not retried) → `EditorialError` (`editorial.py:503-507`); no registry → `EditorialError` (`editorial.py:509-510`); no Director → `EditorialError` (`editorial.py:440-441`). Caller: SKIPPED for the day (`stages.py:5719-5724`) |
| Spend | No |

### 7. `judge` — the Director's editorial judgement (`editorial_judgement.py:410`)

| Item | Value |
|---|---|
| Speaker | The Director (`JUDGE_ROLE`, `editorial_judgement.py:76`), or the `director_id` passed in |
| Task / template | `editorial_judgement` / `editorial-judgement-v1` (`editorial_judgement.py:74-75`), `structured_run`, `max_tokens=2000` (×2), temperature 0.2 (`editorial_judgement.py:442-455`) |
| Asks | "Would a stranger … watch it to the end and want the next one?" Five criteria with what a 0 and a 10 look like (`editorial_judgement.py:102-138`), the bar and round count, the kind's note (factual: facts fixed, judge the telling; serial: a status meeting is not a story), the two weakest, and a KEEP/CHANGE/AVOID brief ≤600 chars (`editorial_judgement.py:326-372`). Text cut at a word to 12,000 chars; the boundary's closing tag inside the text is escaped (`editorial_judgement.py:382-407`) |
| Answer | `EditorialAnswer {hook, clarity, moment, punchline, follow: CriterionScore{score 0..10, reason ≤240}, weakest ≤2, brief: WriterBrief{keep ≤200, change ≤280, avoid ≤120}}` (`editorial_judgement.py:168-275`); a bare number is fitted to `{score, reason:""}`, "7"/7.5 → 7, a paragraph brief → `change` |
| Checks in code | Schema only on the scores (0..10, refused outside, never clamped). Totals, floor and weakest two computed from her scores; her own "weakest" list is kept but not used (`editorial_judgement.py:226-275`); pass = total ≥ 35 and min ≥ 5 (`editorial_judgement.py:278-281`) |
| Use | Returned as `Judgement` to `editorial_loop`: her scores decide whether a rewrite is asked (below the bar) and rank the versions (`Round.key`: total, floor, earlier); her KEEP/CHANGE/AVOID goes into the Scriptwriter's brief (`brief_for_writer`) |
| Trust | **FINAL** (her scores are acted on as given after schema validation: nothing verifies them. Code only derives the total and the weakest two from them, and the rules around them are independent of her answer: only a structurally eligible version can stop the loop or ship, at most `allowed` rounds, and a version always ships, so the worst a wrong score costs is model calls) |
| Failure | No model, no Director, or no valid object after at most two attempts → `None` ("not a verdict"); the loop stops with `judge_silent` and ships the best judged eligible version or the first, unjudged (`editorial_judgement.py:427-463`, `editorial_judgement.py:692-694`) |
| Spend | No media spend; each round costs model calls (the judge's and the rewrite's) |

### 8. `_probe` — the failing employee's liveness run (`agent_health.py:568`)

| Item | Value |
|---|---|
| Speaker | The employee whose model is probed (her `agent_id`), on a pinned `model_id`, on behalf of the Director's `switch_agent_model` repair |
| Task / template | `TEST_CONNECTIVITY` / `director-probe-v1` (`agent_health.py:79`), prompt "Reply with the single word OK." (`agent_health.py:86`), `max_tokens=64`, temperature 0.0, no message (`agent_health.py:575-588`) |
| Answer | Free text, not parsed |
| Use | `answered = status == "SUCCEEDED" and text non-empty` (`agent_health.py:591`); the word OK is not checked. Probe runs are excluded from later diagnoses (`agent_health.py:226`) |
| Trust | **CHECKED_BY_CODE** (only the run status and non-emptiness count) |
| Failure | `PolicyKernelError`/`ValueError` → `{status: <exception name>, answered: False}` (`agent_health.py:589-590`). A kernel or budget refusal is not an exception: `run_agent_task` records it as a run with a BLOCKED_* status and returns it (`services.py:828-856`), so it comes back unanswered with that status. For her own model, a status in `DOWN` (FAILED, EMPTY_OUTPUT, BLOCKED_PROVIDER, ValueError) lets the switch proceed; any other status declines the repair (`agent_health.py:641-647`); no candidate answers → an Owner card (`agent_health.py:673-683`) |
| Spend | Model tokens only (≤ 4 probes of 64 tokens per repair: own model + `PROBES = 3`); the chosen replacement must be priced on both sides |

### Functions here that reach the LLM indirectly

| Function | Through | Notes |
|---|---|---|
| `reviews._run` (`reviews.py:121`) | `run_agent_task` | Gateway for #1, #2, #5 |
| `editorial_judgement.editorial_loop` (`editorial_judgement.py:640`) | `read` → `judge` → `structured_run` → `run_agent_task`; plus the caller's `rewrite` callback, invisible to the static call graph: factual `agent_write_script(notes=[brief])` + `review_story` (`factual/story_review.py:784-817`); serial `write_episode(notes=brief, judged=True)` + `review_episode` (`story/review.py:1296-1340`) — both model calls | Up to `allowed` judge calls and `allowed - 1` rewrites (each rewrite = a writer run plus a structural review run) |
| `repairs.agent_health.switch_model` (`agent_health.py:601`) | `_probe` → `run_agent_task` | Up to 4 probes |
| `repairs.desk.execute_repair` (`desk.py:514`) | `Repair.function` (dynamic) → `switch_model` → `_probe` | Invisible to the static call graph |
| Feeds a prompt elsewhere | `repairs.registered_repairs()` summaries → `command.repair_desk()` → the Director's `_choose` prompt (`command.py:192-195`, `command.py:1143`); `brief_for_writer` output → the Scriptwriter's rewrite notes; the lesson `editorial_review` stores → `prompt_agent.prompt_lessons(scope=…)` → the picture-prompt writers of that kind of film (`build_visual_bible`, `write_shot_prompts`: `prompt_agent.py:1042`, `prompt_agent.py:1153`; `director_brief`, `review_rewrite`, `rewrite_scene`: `scene_rewrite.py:1358`, `scene_rewrite.py:1685`, `scene_rewrite.py:2159`; for a serial lesson also the beat writer through `story.services._picture_lessons`, `story/services.py:1545`) | No model call in this group |

---

## Hard rules and limits

| Constant / rule | Value | Where |
|---|---|---|
| `REVIEW_TEMPLATE_VERSION` | `review-v1` | `reviews.py:94` |
| `_run` temperature / message | 0.1 / `emit_message=False` | `reviews.py:142-143` |
| Narration review limits | notes ≤12, hints ≤40, `max_tokens` 4500 | `reviews.py:187-188`, `reviews.py:228` |
| Render diagnosis payload / tokens | 12,000 chars / 3600 | `reviews.py:488`, `reviews.py:497` |
| `_WHOLE_FILM` regex | re-render, randat din nou, whole/entire film, tot filmul, retry the render… | `reviews.py:311-315` |
| Redo sheet pricing | 2 stills at the stills tier + motion at 1080p for the scene's planned seconds; CARD_KINDS = 0 credits | `reviews.py:359-383` |
| `DIRECTOR_QC_TASK` / template | `director_qc_review` / `director-qc-v8` | `reviews.py:579`, `reviews.py:589` |
| `QC_VERDICTS` | REAL, FALSE, OWNER_CHOICE, ACCEPTED | `reviews.py:591` |
| `LESSON_MAX_CHARS` | 240 | `reviews.py:593` |
| `PICTURE_FINDING_CHECKS` | picture_qc, picture_spans_qc, character_drift_qc | `reviews.py:596` |
| `FILM_DECISIONS` | ACCEPT, REPAIR, CLOSE (CLOSE refused by the bound schema) | `reviews.py:598`, `reviews.py:865` |
| `DIRECTOR_REDO_KINDS` / `FILM_LEVEL_REDOS` | still, motion, card, audio, encode / audio, encode | `reviews.py:600-602` |
| Director QC answer bounds | ≤80 verdicts, ≤24 repairs, reasons ≤400, summary ≤800 | `reviews.py:661-664` |
| `DIRECTOR_QC_PAYLOAD_CHARS` | 24,000 (soft; optional keys dropped first) | `reviews.py:963-978` |
| Director QC tokens | 6000 requested (12,000 effective at multiplier 2) | `reviews.py:1042`, `16_DECISION_LOG.md:100-104` |
| Look task / template / tokens | `director_take_look` / `director-look-v1` / 4000 (8,000 effective at multiplier 2) | `reviews.py:1085-1086`, `reviews.py:1215` |
| Look payload | 12,000 chars | `reviews.py:1198` |
| `UNPROVEN_LABEL` | "NEEFĂCUT — afirmație fără dovadă" | `reviews.py:1260` |
| Claim kinds | render, audio, prompt, sent (each with its proving event types) | `reviews.py:1267-1330` |
| Labelled letter cap | body_text cut to 8,000 chars | `reviews.py:1415` |
| `MAX_PUBLICATION_TAGS` | 15; each tag ≤30 chars | `reviews.py:1453`, `reviews.py:1577` |
| Publication payload / tokens | 12,000 chars / 4500 | `reviews.py:1539`, `reviews.py:1553` |
| HOLD / approved-metadata scan | 200 open inbox letters / 200 latest STATUS+ESCALATE | `reviews.py:1719`, `reviews.py:1738` |
| `EDITORIAL_TASK` / template | `editorial_review` / `editorial-v1` | `editorial.py:72-73` |
| `MIN_WORDS` | 40 spoken words | `editorial.py:75` |
| Frames | 1 per scene up to `MAX_FRAMES` 8; fallback `FRAMES` 3 at 20/50/80 %; width 480; ffmpeg timeout 60 s | `editorial.py:76-79`, `editorial.py:351-360`, `editorial.py:389` |
| Editorial payload / tokens | 14,000 chars / 6000 (×2) | `editorial.py:482`, `editorial.py:498` |
| Picture lesson from her note | First sentence only (`_SENTENCE_END` = `(?<=[.!?])\s+`); ≤ `prompt_agent.LESSON_MAX_CHARS` 400 (not `reviews.LESSON_MAX_CHARS` 240, which bounds a QC verdict's lesson); scope `serial` / `factual`; `provisional=True`; compared with `LESSONS_COMPARED` 40, overlap `LESSON_OVERLAP` 0.6, refresh at `LESSON_CONTAINED` 0.9; a writer is given at most `LESSONS_GIVEN` 12 lessons, confirmed first | `editorial.py:400`, `editorial.py:413-417`, `editorial.py:584-590`, `prompt_agent.py:126-140` |
| `JUDGEMENT_TASK` / template | `editorial_judgement` / `editorial-judgement-v1` | `editorial_judgement.py:74-75` |
| Bar | `PASS_TOTAL` 35/50, `CRITERION_FLOOR` 5, `MAX_SCORE` 10 | `editorial_judgement.py:86-89` |
| `BRIEF_CHARS` / `TEXT_BUDGET` | 600 / 12,000 | `editorial_judgement.py:92-94` |
| Rounds | `Settings.editorial_rounds`, default 10 (`DEFAULT_EDITORIAL_ROUNDS`), 1..20 | `editorial_judgement.py:81`, `config.py:15`, `config.py:434` |
| Loop stop reasons | passed, rounds_spent, writer_silent, judge_silent | `editorial_judgement.py:96-99` |
| Judge tokens / temperature | 2000 (×2) / 0.2 | `editorial_judgement.py:453-454` |
| `REPAIR_TIERS` | T0..T3 (T4 never) | `repairs/__init__.py:68` |
| Repair statuses | APPLIED, NOTHING_TO_DO, DECLINED (+ HELD on the decision) | `repairs/__init__.py:72-74`, `desk.py:70` |
| Repair name | `^[a-z][a-z0-9_]{0,59}$` | `repairs/__init__.py:76` |
| `REPAIR_TASK` | `DIRECTOR_REPAIR`, priority 5, `max_attempts=1`, key `director-repair:<name>:<case>:<date>` | `desk.py:57`, `desk.py:312`, `desk.py:368-383` |
| `REVIEW_AFTER_HOURS` | 24 | `desk.py:64` |
| `RETRY_HOURS` / `MAX_TRIES` | 24 h / 3 per case | `desk.py:75-76` |
| `BLOCKED_QUIET_DAYS` | 7 | `desk.py:80` |
| Fingerprint | sha256 of JSON parts, 24 hex chars | `desk.py:83-86` |
| Loop bounds (caller) | `MAX_REPAIRS` 6 per loop; `MAX_ATTEMPTS_PER_MATTER` 3 in `REPAIR_ATTEMPTS_HOURS` 24; `UNASKED_TIERS` T0-T2 | `command.py:160-170` |
| Paid-redo limits fed into the Director's QC context (caller) | `Settings.film_max_paid_redos_per_scene` 5 (0..5), `film_max_paid_redos` 20 (0..20); fallbacks 1 / 2 with no settings | `config.py:314-315`, `stages.py:4212-4216` |
| Re-asking a failed report (caller) | `RETRY_MINUTES` 60, `MAX_WAIT_MINUTES` 1440, `LOOKBACK_DAYS` 7, `MAX_TRIES` 24 | `workflows/passes/director_qc_review.py:42-49` |
| Agent health windows | 30 d observation, `MIN_RUNS` 5, `FAILURE_RATE` 0.5, `FAILING_RUNS` 3, `FAILING_NOW_HOURS` 24, `RECENT_DAYS` 7 | `agent_health.py:61-70` |
| Bursts | gap ≤600 s, ≥5 failures, top 3 | `agent_health.py:72-73`, `agent_health.py:126-151` |
| `MODEL_FAULTS` / `DOWN` | FAILED, EMPTY_OUTPUT / + BLOCKED_PROVIDER, ValueError | `agent_health.py:77`, `agent_health.py:81` |
| `SWITCHES_PER_DAY` / `PROBES` | 1 / 3 | `agent_health.py:83-85` |
| `VERIFIED_STATUSES` | VERIFIED, ACCESS_VERIFIED | `agent_health.py:88` |
| `UNCOVERED_GRACE_HOURS` | 24 | `reprice.py:70` |
| `UNQUEUED_AFTER_MINUTES` | 60 | `stale_decisions.py:42` |
| Loop detection | `LOOP_REPLIES` 3 in `LOOP_WINDOW_SECONDS` 600; `SAME_REPLY` 0.8; `LOOP_RECENT_HOURS` 48; `THREADS_PER_REPAIR` 50 | `threads.py:50-59` |
| `UNBILLED_AFTER_DAYS` | 7 | `unbilled.py:51` |
| Policy tiers of the repairs | diagnose_agent T0 `analytics.read`; switch_agent_model T2 `agent.change_model`; reprice_unpriced_runs T1; film_cost_report T1; close_stale_decisions T1; close_thread T1; unbilled_estimates T1 | `agent_health.py:750-775`, `reprice.py:518-529`, `film_cost.py:312-324`, `stale_decisions.py:202-213`, `threads.py:361-372`, `unbilled.py:354-366` |
| Mode ceilings read by `may_act` | MANUAL T1, SUPERVISED T2, AUTONOMOUS_CEO T3; SAFE_MODE allows ≤T1 | `services.py:528-532` |

**State machines.**

- *Repair decision* (`DirectorDecision` rows written by the desk): `OPEN` (queued) → `REVIEWED`
  with `evidence_json.repair.status` ∈ {APPLIED, NOTHING_TO_DO, DECLINED} (`desk.py:639-646`,
  `desk.py:662-674`); or born `REVIEWED` with status HELD (`desk.py:417-435`). `undecided`
  reads an OPEN case as decided while it stays open, APPLIED/NOTHING_TO_DO as settled for
  good, and DECLINED/HELD/dead (closed with no status) as retryable after 24 h, 3 tries in
  all (`desk.py:155-180`). `close_stale_decisions` closes OPEN rows whose task ended
  or was never queued (`stale_decisions.py:122-135`).
- *Editorial loop*: read → (pass ∧ eligible → stop PASSED) | (last round → ROUNDS_SPENT) |
  brief → rewrite → (None → WRITER_SILENT) | next read; a None judgement → JUDGE_SILENT
  (`editorial_judgement.py:688-713`). Shipped: the best `Round.key` among eligible judged
  versions, else round 1 (`editorial_judgement.py:715-716`).
- *Film after failed QC* (decision object only; executed in `runbook.stages`): ACCEPT →
  ACCEPTED or ACCEPT_REFUSED; REPAIR → REPAIRED / ASKED / BOUGHT_WAITING / NOTHING_DONE
  (`stages.py:4466-4545`).

---

## Modules

### `app.agents.reviews` — backend/app/agents/reviews.py (1750 lines)

The judgement tasks of the VoiceArtist, VideoEditor, Publisher and the Director's QC and look
decisions, plus the claim checker. Exists because the gates measured files and nobody owned
judgement; every task has a fixed schema and records an AGENT_OPINION memory with the run as
provenance (`reviews.py:1-16`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `ReviewError`, `NoReviewer` (classes) | 97, 101 | Errors: unusable answer / no active employee in the role | Nothing is stored as a verdict on failure | — |
| `_scene_lines` | 105 | Scenes of a storyboard as {index, narration, seconds} | Shared prompt data | CODE_RULE |
| `_run` | 121 | `run_agent_task` with `review-v1`, temperature 0.1, no message; raises `ReviewError` unless SUCCEEDED with text | Single gateway for the three label roles | CODE_RULE |
| `_escalate_blocker` | 154 | A structured `{"blocker": …}` answer becomes an ESCALATE letter | Blockers reach the Director, never interpreted | CODE_RULE |
| `PronunciationHint`, `NarrationReview` (classes) | 177, 184 | Lyra's answer schema: verdict PASS\|FLAG, ≤12 notes, ≤40 hints | Fixed shape, validated before anything is stored | CODE_RULE (schema) |
| `review_narration` | 203 | Lyra's PASS/FLAG and pronunciation hints → memory + letter | VoiceArtist had no task | LLM (advisory) |
| `RenderDiagnosis` (class) | 290 | Kael's answer schema: diagnosis, correction ≤1000 each, two booleans | Fixed shape | CODE_RULE (schema) |
| `_effective_kind` | 318 | Scene kind; a LIVE scene whose prompt asks for a chart/title/black screen reads as a card | Nepal scenes 5-6 predate scene kinds | CODE_RULE |
| `redo_sheet` | 327 | Per-scene redo prices: the recorded sheet, else the price table (stills tier + motion at 1080p), unpriced stays None | Nothing guessed; a broken table leaves redos unpriced rather than stopping | CODE_RULE (prices read from the recorded sheet or the price table file) |
| `_correction_ro` | 391 | Romanian correction from the proposals | Replaces the model's free text | CODE_RULE |
| `failed_render_reading` | 400 | The report, the render job's production, the sheet, `redo_proposals`, `qc_summary_ro`; no model, no write | Shared reading for Kael and the Director | CODE_RULE |
| `review_failed_render` | 455 | Kael's diagnosis plus the code's priced redo, one ESCALATE letter | Nepal whole-film repurchase | CODE_RULE (the redo list and the stored correction; his diagnosis text is ADVISORY) |
| `FindingVerdict` (+ `_upper`, `_lower`) | 605, 624, 629 | One finding's verdict, severity, cause, lesson; normalises case | Owner 2026-10-12 small-defects rule | CODE_RULE (schema) |
| `DirectorRedo` (+ `_lower`, `_where`) | 636, 644, 648 | One redo; audio/encode drop the scene; still/motion/card must name a scene | Film-level vs scene-level redos | CODE_RULE |
| `DirectorQcDecision` (+ `_upper`, `_consistent`) | 657, 668, 672 | Decision consistency rules (see LLM #3) | REAL means needs work; minor is ACCEPTED | CODE_RULE |
| `repair_refusal` | 711 | Why no redo of a REPAIR can be carried out now, or None if at least one can | 2026-10-10 hourly re-ask loop with limits spent | CODE_RULE (Owner limits in context) |
| `_names_scene` | 772 | Whether a finding names a scene (its index or the number in its words) | Generous: only decides what may not be bought | CODE_RULE |
| `passed_scene_refusal` | 781 | Refuses REAL picture findings and paid redos on `passed_before_unchanged` scenes, and paid redos for scenes no REAL finding names | aa170155, 2026-10-12 | CODE_RULE |
| `decision_schema` (+ `BoundDecision._this_report`) | 848, 864 | Schema bound to the report's findings, scenes and context; refuses CLOSE | Half-read reports are never carried out | CODE_RULE |
| `_director_payload` | 966 | JSON evidence ≤24,000 chars, dropping optional keys first | Slicing JSON lost corrective intent | CODE_RULE |
| `review_film_qc` | 981 | The Director's verdicts and decision on a failed QC report | Owner 2026-10-10: she decides alone | LLM_CHECKED_BY_CODE |
| `DirectorLook` (+ `_upper`, `_consistent`), `look_schema` | 1091, 1101, 1105, 1113 | CHOOSE/REJECT bound to the shown candidates | A choice names a shown candidate | CODE_RULE |
| `review_bought_pictures` | 1148 | Her look at refused candidates on a seeing model | Owner 2026-10-10 20:06 | LLM |
| `_clause` | 1341 | Words before a match in its clause, and the clause | Negation/future detection | CODE_RULE |
| `check_work_claims` | 1350 | Each claim kind found in a text, proven or not by a media.* event since `since` | Unproven "done" claims | CODE_RULE |
| `mark_unproven_claims` | 1389 | Prefixes the letter with the NEEFĂCUT label, stores `claim_check`, emits `agent.claim_unproven` | Same; called by `agents.mail.answer_mail` (`mail.py:566`) | CODE_RULE |
| `PublicationMetadata` | 1438 | Publisher answer schema, generous bounds | PUB-06 | CODE_RULE |
| `prepare_publication` | 1485 | Vera's metadata and READY/HOLD, then code fitting and guards | Publisher had no task; 2026-09-18 duplicate titles | LLM_CHECKED_BY_CODE |
| `_episode_characters` | 1706 | Characters of an episode in order of appearance | Serial fallback metadata | CODE_RULE |
| `publication_hold` | 1717 | An OPEN Publisher HOLD (ESCALATE, verdict HOLD) on a candidate | Blocks the day's publication | CODE_RULE |
| `approved_metadata` | 1730 | Newest letter for the candidate carrying a title that is READY or RESOLVED (whoever resolved it, whatever action resolved it), among the latest 200 STATUS/ESCALATE letters | The Director lifting a HOLD | CODE_RULE |

Data read: `Storyboard`, `StoryboardScene`, `MediaAsset`, `QualityControlReport`,
`VideoRenderJob.production_json`, `ScriptDraft` (title, story_json, scenes_json),
`ChannelRecord`, `AgentMessage`, `DomainEvent`, `ModelRecord`, the price table
(`media.cost_plan.load_price_table`). Written: `AgentMessage` (ESCALATE/STATUS letters;
`body_text`/`body_json` of a labelled letter), agent memory (`remember`, AGENT_OPINION),
`DomainEvent` `agent.claim_unproven`, `AgentRun` rows through `run_agent_task`. External calls:
the language model providers only; no media purchase, no publishing call.

### `app.agents.editorial` — backend/app/agents/editorial.py (629 lines)

The Director's pre-publication viewing ("the missing gate", `editorial.py:10-17`), with a serial
brief for the office serial (`editorial.py:19-24`). Also exports the frame cutter and the vision
check reused by `app.agents.vision` (`VISION`, `frames_for`, `model_can_see`: `vision.py:34`),
the frame constants read by `media.picture_qc` (`FRAME_WIDTH`, `MAX_FRAMES`: `picture_qc.py:89`),
and `is_serial_film`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `EditorialVerdict` | 90 | APPROVE/REJECT, story, reasons, notes per department | Fixed answer shape | CODE_RULE (schema) |
| `instructions_for` | 147 | Formats the brief: factual or serial judgement | The first serial film was refused for having no claims | CODE_RULE |
| `is_serial_film` | 159 | Serial if the storyboard's series key is `office_serial` or the script's story_json kind is `office_serial_episode` | Same marks the publish routing reads; used by `media.assembler`, `media.scene_rewrite`, `media.stills_stage` (`stills_stage.py:486`), `media.second_look` (`second_look.py:221`), `workflows.passes.training_set` | CODE_RULE |
| `EditorialError` | 173 | Nothing was decided | — | — |
| `gather_facts` | 177 | Everything the Director reads, and the hard rejects (missing claim, sourceless or unverified claim, no script, < 40 words, not English, no claims for a factual film, narration not grounded) | Not matters of taste | CODE_RULE |
| `model_can_see` | 313 | Whether the Director's own model declares the `vision` capability | A provider refuses the whole call if frames go to a blind model | EXTERNAL (provider declaration) |
| `frames_for` | 334 | One JPEG frame from the middle of each scene (≤8), scaled to the real duration, via ffmpeg | ATLAS stripes approved on 3 frames | CODE_RULE |
| `picture_lesson` | 403 | The rule in her note to the Video Editor: its whitespace-normalised first sentence, or None when the note is empty, that sentence is over `LESSON_MAX_CHARS` (400), or `prompt_agent.lesson_is_general` refuses it against this film's title (scene/shot number, whole id, the title named) | Review of a9f84ea, 2026-10-12: a bare note made one film's scene a rule for every film, and a long note was refused whole | CODE_RULE |
| `latest_editorial` | 420 | Newest `EditorialReview` for an asset | `_publish_one` reuses a verdict | CODE_RULE |
| `editorial_review` | 428 | Hard rejects or her verdict; event, review row, storyboard REJECTED on reject, letters, a scoped provisional prompt lesson from her VideoEditor note, HANDOFFs | Last look before a channel | LLM (her APPROVE/REJECT, after code's hard rejects) |

Data read: `MediaAsset`, `VideoRenderJob`, `Storyboard`, `StoryboardScene`, `ScriptDraft`,
`TopicIdea`, `FactualClaim`, `SourceSnapshot`, `QualityControlReport`, `Agent`/`Role`,
`ModelCapability`/`Capability`, `factual.grounding.script_grounding`, and through
`record_prompt_lesson` the live STRATEGY lesson rows and every storyboard's title and id
(`prompt_agent.py:3400-3426`). Written:
`EditorialReview`, `DomainEvent` `media.editorial_reviewed`, `Storyboard.status`
("REJECTED"), `AgentMessage` (STATUS/ESCALATE, HANDOFFs), memory (AGENT_OPINION, and through
`record_prompt_lesson` a STRATEGY prompt lesson stored as `prompt lesson: [serial|factual][?] …`,
or, when it only refreshes an older lesson, under that lesson's scope and proof state; it may
retire an older lesson it refreshes or supersedes: `prompt_agent.py:3232-3233`,
`prompt_agent.py:3472-3492`). External: ffmpeg subprocess (`editorial.py:365-391`), the model
provider.

### `app.agents.editorial_judgement` — backend/app/agents/editorial_judgement.py (823 lines)

Scores a version on five criteria and runs the rewrite loop; the callers
(`factual.story_review.judged_story`, `story.review.judged_review`) supply the rewrite path,
record the rounds and write the Owner's letter (`story_review.py:819-845`). Nothing here writes
rows except through `record_rounds` and `letter_to_owner` in the caller's session.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_scored` | 153 | A bare number becomes `{score, reason: ""}` | Fit before refuse | CODE_RULE |
| `CriterionScore` (+ `_whole`) | 168, 177 | Score 0..10, reason ≤240; floats and strings rounded down | A 7.5 must not cost a second call | CODE_RULE |
| `WriterBrief` (+ `words`) | 192, 203 | KEEP/CHANGE/AVOID ≤200/280/120 chars, rendered as lines | A brief readable in a minute | CODE_RULE |
| `_criteria_named` | 212 | Which criteria a word or sentence names | Normalises her "weakest" | CODE_RULE |
| `EditorialAnswer` (+ `_criteria_only`, `_brief_as_object`, `scores`, `reasons`, `total`, `weakest_two`, `passes`) | 226-275 | Her answer; totals and weakest two computed from scores, ties in film order | "never trusted from her list" | CODE_RULE |
| `passes` | 278 | total ≥ 35 and every criterion ≥ 5 | The bar ("a 7 on every criterion") | CODE_RULE |
| `Judgement` (+ `scores`, `total`, `weakest`, `passed`, `floor`, `record`) | 284-321 | One reading with its run | — | CODE_RULE |
| `criteria_lines` | 376 | The criteria with 0 and 10 descriptions | Stable scoring | CODE_RULE |
| `judgement_prompt` | 382 | The full prompt; text cut at a word, boundary tag escaped | Prompt-injection hygiene | CODE_RULE |
| `judge` | 410 | One reading by the Director, or None | — | LLM_CHECKED_BY_CODE |
| `brief_for_writer` | 469 | Scores, two weakest with reasons, structural refusals first, her KEEP/CHANGE/AVOID, the rewrite order | Concrete rewrite notes | CODE_RULE |
| `Version`, `Round` (+ `key`, `record`), `EditorialOutcome` (+ `judged`, `passed`, `rewrites`, `record`, `record_for`) | 513-626 | Loop data; ranking key (total, floor, earlier round); the review JSON | — | CODE_RULE |
| `editorial_rounds_setting` | 629 | `Settings().editorial_rounds`, else 10 | Per-studio setting | CONFIG |
| `editorial_loop` | 640 | Read → brief → rewrite → read, ≤ rounds; ships the best eligible judged version, else the first unjudged | Owner card 2026-10-11 23:30 | LLM_CHECKED_BY_CODE (her scores; code caps the rounds and requires structural eligibility) |
| `record_rounds` | 735 | One `editorial.judged` event per version, on its own row | Weekly review compares scores with views | CODE_RULE |
| `_stopped_ro` | 762 | Why the loop stopped, in Romanian | Letter wording | CODE_RULE |
| `letter_to_owner` | 773 | One STATUS letter to the Owner only when a judged version ships below the bar | "only what needs him reaches him" | CODE_RULE |

Data read: none directly (the Director's agent id). Written (through callers' sessions):
`DomainEvent` `editorial.judged` on `script_draft` / `story_episode` aggregates, an
`AgentMessage` to the Owner. External: model provider via `structured_run`.

### `app.agents.repairs` — backend/app/agents/repairs/__init__.py (263 lines)

The registry of the Director's repairs and their contract: repair data/config the studio owns,
never buy, approve or move money, never write a price, budget, ledger, reconciliation,
credential or the Owner's policy, never decide his cards; idempotent; precondition read again
at apply time; import only registers (`repairs/__init__.py:39-52`). Enforced in tests by the
Owner and money scans (`tests/test_watchdog_passes.py`, `tests/test_no_paid_path_escapes.py`,
named at `repairs/__init__.py:44-45`, `repairs/__init__.py:111-112`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `RepairContext`, `Repair` (dataclasses) | 80, 104 | What a repair receives (engine, settings, registry, correlation, director, decision); a registered repair (tier, kernel action, summary, function, precondition, detector, `place_ro`) | One shape for every repair | — |
| `register_repair` | 128 | Validates name, tier ∈ T0..T3, action non-empty, name not taken by another function; registers | T4 is the Owner's alone | CODE_RULE |
| `_same` | 167 | Same function registered twice (module imported twice) | Idempotent import | CODE_RULE |
| `registered_repairs`, `repair_named` | 180, 186 | Load the package's modules on first call; lookup | Lazy discovery (`PackageLoader`) | CODE_RULE |
| `unregister_repair` | 191 | Remove (tests) | — | — |
| `outcome` | 196 | Status, Owner-words outcome, changed, letter subject; status must be one of three | Uniform result | CODE_RULE |
| `finding` | 215 | A detector's matter in `command.findings` shape with `repair: {name, params, fingerprint}` | Same case = same fingerprint, one decision | CODE_RULE |

### `app.agents.repairs.desk` — backend/app/agents/repairs/desk.py (794 lines)

Offer → queue → apply → record, identical for every repair (`desk.py:1-26`). Called by
`agents.command.findings` / `direct_company` and by the worker's `DIRECTOR_REPAIR` handler
(`worker.py:400-404`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `fingerprint` | 83 | 24-hex sha256 of JSON parts | Stable case names | CODE_RULE |
| `usd_ro` | 93 | Micro-USD formatted with a comma | Owner-readable sums | CODE_RULE |
| `director_of` | 101 | Director id and name, or (None, "Director") | Repairs run without her row too | CODE_RULE |
| `undecided` | 122 | Filters matters by their cases' decision history (OPEN/settled; retry after 24 h, ≤3 tries; held matter waits 24 h) | Before 2026-10-11 a refusal under a lifted stop stayed refused forever | CODE_RULE |
| `repair_matters` | 183 | Runs every detector; a failing detector is logged and skipped | One broken repair must not take the loop down | CODE_RULE |
| `_record_decision` | 210 | Writes `director.decision_recorded` and the `DirectorDecision` (OPEN, or REVIEWED with outcome) with `review_after_at` +24 h | Her decision is the record | CODE_RULE |
| `submit_repair` | 284 | Kernel check (`may_act`, `ask_owner=False`); dedupe by task key and open decision; record; enqueue `DIRECTOR_REPAIR` (1 attempt) | Queue once per case per day | CODE_RULE (Policy Kernel) |
| `hold_repair` | 394 | Records her wait decision, closed at once with status HELD | Repairs that follow unasked must not override her wait | LLM (her choice, recorded) |
| `blocked_card` | 444 | Card `director_repair_blocked`: options "Mă ocup eu" (guided, if `place_ro`) and "Las cum este" | What she may not do is his | CODE_RULE |
| `ask_owner_about_repair` | 489 | One card per matter+cause via `owner_card_once`, quiet 7 days | Replaced an ESCALATE letter at every loop | CODE_RULE |
| `execute_repair` | 514 | Idempotence (decision closed, event exists), kernel again, precondition again, run; exception → DECLINED; `_record` | The studio moves between choice and execution | CODE_RULE |
| `_record` | 605 | Event `director.repair_applied`/`_declined`, closes the decision keeping status, STATUS letter to the Owner if APPLIED with a subject | One transaction | CODE_RULE |
| `close_decision` | 662 | OPEN → REVIEWED with outcome | Shared by repairs | CODE_RULE |
| `status_letter` | 677 | STATUS letter to the Owner, a statement (deduped by subject in `post_message`) | Owner informed, never asked | CODE_RULE |
| `owner_card` | 703 | `decisions.sources.ask` in a savepoint; failure logged, never undoes the repair | Cards are proposals only | CODE_RULE |
| `owner_card_once` | 722 | Open card with the key returns it; a closed one is not re-asked within `quiet_days` (None = never) | Questions answered once | CODE_RULE |
| `withdraw_card` | 746 | Withdraws an open card whose question went away | Not an answer in his name | CODE_RULE |
| `open_card_keys` | 759 | Open card keys by prefix | Detectors skip asked kinds | CODE_RULE |

Helpers: `_now` (`desk.py:89`), the current time in UTC, read for the 24-hour retry window, the
`review_after_at` stamp, the task key's date and the cards' quiet days (`desk.py:165`,
`desk.py:268`, `desk.py:312`, `desk.py:740`); `_when` (`desk.py:114`), a stored ISO stamp read
as an aware time (a naive one taken as UTC, an unreadable one None), for a decision's last
attempt and a card's closing time (`desk.py:160`, `desk.py:738`).

Data: `DirectorDecision`, `TaskQueueItem`, `DomainEvent`, `OwnerDecision` (read), `AgentMessage`
(written). Events: `director.decision_recorded`, `director.repair_applied`,
`director.repair_declined`. External: none.

### `app.agents.repairs.agent_health` — backend/app/agents/repairs/agent_health.py (778 lines)

Two repairs on one diagnosis: `diagnose_agent` (T0) and `switch_agent_model` (T2). Born from
"Nadia: 92,9 % eșecuri" being one retry storm of 2026-10-04 on a model she no longer used
(`agent_health.py:3-7`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_when`, `_error_class`, `_rate`, `_percent`, `_compact` | 103, 111, 117, 297, 329 | Helpers: timestamps, error text before " — ", failure rate, percentage, compact evidence | — | CODE_RULE |
| `_bursts` | 126 | Failures grouped by ≤600 s gaps; top 3 of ≥5 | Separate a storm from today | CODE_RULE |
| `_class_of` | 154 | Cause from HTTP codes and text | Names the cause | CODE_RULE |
| `provider_label` | 171 | A saved connection by the Owner's name | Owner wording | CODE_RULE |
| `assigned_at` | 183 | Last `agent.model_assigned`/`agent.model_preferred` | A failure before his (re)choice is not evidence | CODE_RULE |
| `diagnosis` | 201 | 30-day runs (probes excluded), windows 24h/7d/30d on the current model, failing-now rule, cause, bursts | — | CODE_RULE |
| `diagnosis_words` | 301 | Romanian sentences | Owner letter | CODE_RULE |
| `agents_failing` | 337 | Detector: ACTIVE agents failing now (→ switch) or with ≥5 runs at ≥50 % failures (→ diagnose) | Raises both repairs' matters | CODE_RULE |
| `_agent`, `agent_exists`, `still_failing` | 372, 379, 407 | Preconditions: agent active; still failing now | Read again at apply time | CODE_RULE |
| `diagnose` | 386 | APPLIED outcome with the diagnosis; changes nothing | A diagnosis is the outcome | CODE_RULE |
| `_switches_today` | 417 | Switches with origin DIRECTOR_REPAIR in the last 24 h | One per day | CODE_RULE |
| `_anthropic` | 434 | Excludes "claude"/"anthropic" | Owner rule | CODE_RULE (the Owner's rule, hard-coded) |
| `_failing_elsewhere` | 440 | Model's last 3 runs (anyone's) all failed | Do not move onto a broken model | CODE_RULE |
| `candidates` | 455 | Replacement filter and ranking (see Who decides #34) | — | CODE_RULE (reads provider health and the deny list) |
| `model_card` | 530 | Card `agent_model_failing`, guided "Aleg eu modelul" | Owner chooses when she cannot | CODE_RULE |
| `_ask_owner` | 559 | Proposes the model card | — | CODE_RULE |
| `_probe` | 568 | LLM liveness run (see LLM #8) | Hours-long outages vs. dead models | EXTERNAL |
| `switch_model` | 601 | Own probe; second switch → card; probe ≤3 candidates; refuse while the agent is not IDLE; `integrations.services.assign_agent` with origin DIRECTOR_REPAIR keeping slots and strategy; revert data in `changed` | Replace only a model that fails now | CODE_RULE (on EXTERNAL probe results) |

Data read: `Agent`, `AgentRun`, `ModelRecord`, `ProviderRecord`, `Role`, `Integration`,
`DomainEvent`, prices (`economy.prices.price_for`), deny list (`integrations.lifecycle`), role
allocation (`agents.services._allocation_entry`). Written: through `assign_agent` (the agent's
model, an `agent.model_assigned` event), probe `AgentRun` rows, cards. External: the model
provider (probes), the registry's cached provider health.

### `app.agents.repairs.film_cost` — backend/app/agents/repairs/film_cost.py (324 lines)

`film_cost_report` (T1, `director.close_review`): what each published film cost against what it
returned, computed instead of asking the Accountant (`film_cost.py:3-22`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `asks_film_cost` | 58 | A decision asked for the film cost: `review_*` or `idle_costs_unread` matter, or an action beginning with the canonical phrase | Equality missed three decisions on 2026-10-11 | CODE_RULE |
| `_cost_view` | 69 | Estimated/reconciled/billed/total in Owner format | — | CODE_RULE |
| `_returns` | 90 | Latest analytics snapshot, LIFETIME first | — | CODE_RULE |
| `film_report` | 120 | Per published film: cost on its board (`analytics.performance.film_cost`), sibling boards of the same topic, returns, agent cost "neatribuit" | One join, no letter | CODE_RULE |
| `report_words` | 169 | One sentence per film | Owner letter | CODE_RULE |
| `films_without_cost` | 215 | Detector: published films with no cost on the performance page | — | CODE_RULE |
| `films_published` | 246 | Precondition: any published film | — | CODE_RULE |
| `report_film_cost` | 256 | Builds the report; closes the reviewed decision and, if that decision asked for this report, its thread's letters | Ends the HANDOFF loop | CODE_RULE |

Data read: `PublicationRecord`, `VideoRenderJob`, `Storyboard`, `ScriptDraft`,
`AnalyticsSnapshot`, cost rows via `analytics.performance`. Written: `DirectorDecision` close,
`AgentMessage` resolutions. External: none.

### `app.agents.repairs.reprice` — backend/app/agents/repairs/reprice.py (529 lines)

`reprice_unpriced_runs` (T1, `economy.apply_active_price`): applies a price active now to
SUCCEEDED runs with no cost in the books' current month; never writes a price
(`reprice.py:9-26`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `provider_kinds` | 73 | Provider name → price-table kind (Integration kind for `settings:` providers) | Same reading as the preflight's price check | CODE_RULE |
| `month_start`, `window` | 95, 102 | Books' current month start; params override | September runs predate any price | CODE_RULE |
| `_unpriced`, `_older` | 109, 124 | Unpriced SUCCEEDED runs with both token counts, in / before the window | — | CODE_RULE |
| `_prices`, `_cost` | 141, 152 | Both active price rows or None; cost with `llm_cost_vr` | Half a price understates a run | CODE_RULE (the prices themselves are the Owner's) |
| `_survey` | 165 | Groups unpriced runs by kind and model with the covered cost | Detector evidence | CODE_RULE |
| `unpriced_usage` | 201 | Detector: covered groups, or uncovered groups ≥24 h old with no open price card | — | CODE_RULE |
| `still_unpriced` | 275 | Precondition | — | CODE_RULE |
| `apply_active_price` | 286 | Prices runs, stamps `context_json.priced_after`, emits `economy.agent_runs_repriced`; refuses with a budget card if a non-exceeded active period would go over its limit; cards for uncovered kinds; withdraws price cards no longer needed | Budget exceeded stops every employee: his decision | CODE_RULE (a budget it would exceed goes to the Owner as a card) |
| `price_card` | 442 | Card `agent_model_price` (guided to «Autonomie → Prețurile modelelor») | Price is the Owner's | CODE_RULE |
| `budget_card` | 478 | Card `agent_runs_over_budget` (look at budget / leave unpriced) | Budget is the Owner's | CODE_RULE |

Data read: `AgentRun`, `ProviderRecord`, `Integration`, active price rows, `budget_status`.
Written: `AgentRun.cost_vr`, `AgentRun.context_json.priced_after`, event
`economy.agent_runs_repriced`, cards. External: none.

### `app.agents.repairs.stale_decisions` — backend/app/agents/repairs/stale_decisions.py (213 lines)

`close_stale_decisions` (T1, `director.close_decisions`): an OPEN decision keeps its matter out
of the Director's loop, so one whose work is over is closed with what became of it
(`stale_decisions.py:3-19`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `published_films` | 47 | Count of PUBLISHED records | Review-after-N-films | CODE_RULE |
| `review_pending` | 60 | Review after N films or a date not yet due | A decision awaiting measurement stays OPEN | CODE_RULE |
| `work_done` | 75 | Letter RESOLVED, or ANSWERED (a HANDOFF only with a done=true reply from its addressee) | `agents.mail` semantics | CODE_RULE |
| `why_closed` | 97 | Reason a decision's work is over (letter, later review, dead/unqueued repair task), or None | — | CODE_RULE |
| `_stale`, `stale_decisions` | 139, 155 | All OPEN decisions with a reason; detector | — | CODE_RULE |
| `any_still_stale`, `close_stale` | 175, 183 | Precondition; closes the listed ones still stale | — | CODE_RULE |

### `app.agents.repairs.threads` — backend/app/agents/repairs/threads.py (372 lines)

`close_thread` (T1, `director.close_thread`): resolves the open letters of a looping thread
(Nadia's nine near-identical replies, `threads.py:3-8`), never the Owner's.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_when` | 70 | A letter's ISO stamp as an aware time (naive taken as UTC, unreadable None) | Read by `loop_reasons` (`threads.py:89`, `threads.py:95`, `threads.py:105`) | CODE_RULE |
| `loop_reasons` | 78 | "burst" and/or "duplicate" over replies after the last Director close, within 48 h | A September burst is history | CODE_RULE |
| `his`, `the_workers`, `standing`, `closable` | 120, 129, 140, 150 | Letter classes the Director may not close | Owner letters, worker state, weekly guidance, budget requests | CODE_RULE |
| `_open_threads` | 161 | Threads with a closable OPEN letter | — | CODE_RULE |
| `close_thread_letters` | 172 | Resolves closable letters, stamps `closed_by_director` | Also used by `film_cost` | CODE_RULE |
| `thread_loops` | 207 | Detector; skips any thread with a letter from the Owner; ≤50 threads | — | CODE_RULE |
| `threads_still_open` | 253 | Precondition | — | CODE_RULE |
| `_film_cost_decisions` | 263 | Whether a thread carries a film-cost decision | Answer it with the report | CODE_RULE |
| `close_threads` | 281 | Closes decisions on those threads (film-cost ones with the report; work-done ones awaiting review are left), then their letters | — | CODE_RULE |

### `app.agents.repairs.unbilled` — backend/app/agents/repairs/unbilled.py (366 lines)

`unbilled_estimates` (T1, `director.ask_for_invoices`): one card per provider, month and exact
set of ESTIMATED cost rows older than 7 days; she never posts, bills or reconciles
(`unbilled.py:3-19`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_vendor`, `_cutoff`, `rows_fingerprint`, `card_key`, `_card_case`, `_asked` | 57-104 | Helpers: vendor label, 7-day cutoff, key `unbilled:<provider>:<month>:<rows>`, parse, keys already asked | One question per set of rows | CODE_RULE |
| `_open_estimates` | 61 | ESTIMATED, unreconciled `ProviderCostRecord` rows by (provider, month) | — | CODE_RULE |
| `unbilled_estimates` | 109 | Detector: groups not yet asked | — | CODE_RULE |
| `_runway_check`, `_runway_words` | 151, 199 | Splits Runway estimates into measured balance drops vs planned credits, with the films' measured drops | A prepaid account has no per-render invoice | CODE_RULE |
| `invoice_card` | 214 | Card `provider_invoice_missing`: "Introduc factura" (guided to Treasury) / "Cont preplătit" | Only the Owner sees invoices | CODE_RULE |
| `still_unbilled` | 264 | Precondition | — | CODE_RULE |
| `ask_for_invoices` | 275 | Proposes cards once per row set; withdraws cards for reconciled or changed months | — | CODE_RULE |

---

## Connections

**Who calls in** (static call graph, `docs/project/backend_map/callgraph.json`, plus grep):

| Caller | Calls |
|---|---|
| `runbook.stages._media_films` (`stages.py:3366`) | `review_narration` |
| `runbook.stages._edit_and_qc` (`stages.py:3775`) | `review_failed_render`, then `director_decides_failed_film` |
| `runbook.stages._director_reads` (`stages.py:4290`, `stages.py:4316-4326`) | `failed_render_reading`, `review_film_qc` (via `director_decides_failed_film`: from `_edit_and_qc`, `stages.py:3789`, and from `_continue_rendered`, `stages.py:5609`, the FILM_CONTINUE walk that the `workflows.passes.director_qc_review` watchdog pass queues again every `RETRY_MINUTES` = 60) |
| `runbook.stages._director_looks` (`stages.py:4428`) | `review_bought_pictures` |
| `runbook.stages._publish_one` (`stages.py:5703-5827`) | `latest_editorial`, `editorial_review`, `publication_hold`, `approved_metadata`, `prepare_publication` |
| `agents.mail.answer_mail` (`mail.py:566`) | `mark_unproven_claims` |
| `factual.story_review.judged_story` (`story_review.py:819-845`), `story.review.judged_review` (`story/review.py:1343-1378`) | `editorial_loop`, `record_rounds`, `letter_to_owner` |
| `agents.command.findings` (`command.py:771-773`) | `undecided`, `repair_matters`, `fingerprint` |
| `agents.command.direct_company` (`command.py:944-1021`) | `registered_repairs`, `hold_repair`, `submit_repair`, `ask_owner_about_repair` |
| `workflows.worker.build_task_handlers.director_repair` (`worker.py:400-404`) | `execute_repair` |
| `agents.vision` (`vision.py:34`) | `VISION`, `frames_for`, `model_can_see` |
| `media.picture_qc` (`picture_qc.py:89`) | `FRAME_WIDTH`, `MAX_FRAMES` |
| `media.assembler` (`assembler.py:9844`, `assembler.py:13932`), `media.scene_rewrite` (`scene_rewrite.py:968`, `scene_rewrite.py:2628`, `scene_rewrite.py:2651`), `media.stills_stage._read_scenes` (`stills_stage.py:486`) and `media.second_look.scene_intent` (`second_look.py:221`), both added after b00083c, `workflows.passes.training_set` (`training_set.py:73`) | `is_serial_film` |
| `media.director_qc` (`director_qc.py:84`) | `FILM_LEVEL_REDOS` |

**What it calls out to:** `agents.services.run_agent_task`, `agents.structured.structured_run`,
`agents.identity` (`parse_structured`, `blocker_of`, `clipped`, `cut_at_word`), `agents.memory`
(`agent_for_role`, `remember`), `agents.messages` (`post_message`, `open_messages`,
`thread_messages`, `resolve_message`, `is_for_owner`), `agents.vision.seeing_model`,
`agents.language`, `factual.sanitizer.wrap_in_inert_boundary`, `factual.grounding`,
`media.cost_plan`, `media.qc_report`, `media.prompt_agent` (`record_prompt_lesson`,
`lesson_is_general`, `LESSON_MAX_CHARS`, `SCOPE_SERIAL`, `SCOPE_FACTUAL`: `editorial.py:58-64`),
`media.toolchain.find_ffmpeg`, `media.assembler.film_step_spend`, `providers.youtube`,
`publishing.serial_identity`, `publishing.services.publication_metadata_refusals`,
`services.may_act` / `append_event`, `decisions.sources.ask` /
`decisions.services.withdraw_owner_decision`, `workflows.services.enqueue_task`,
`integrations.services.assign_agent`, `integrations.lifecycle`, `economy.prices`,
`economy.budget.budget_status`, `analytics.performance`.

**Events emitted:** `agent.claim_unproven` (`reviews.py:1416`), `media.editorial_reviewed`
(`editorial.py:514`), `editorial.judged` (`editorial_judgement.py:742`),
`director.decision_recorded` (`desk.py:234`), `director.repair_applied` /
`director.repair_declined` (`desk.py:623-638`), `economy.agent_runs_repriced`
(`reprice.py:365`), and through `assign_agent` an `agent.model_assigned` with origin
DIRECTOR_REPAIR. **Events consumed:** media.* events as proof of work (`reviews.py:1278-1328`),
`agent.model_assigned`/`agent.model_preferred` (`agent_health.py:189-198`, `agent_health.py:417-431`),
`director.repair_applied`/`_declined` for idempotence (`desk.py:536-543`).

---

## Owner touchpoints

| Touchpoint | Kind | What the Owner decides | Where |
|---|---|---|---|
| Paid-redo limits, final approvals, LOCAL_MOVE choice | Settings (`film_max_paid_redos_per_scene` 5, `film_max_paid_redos` 20: `config.py:314-315`, read in `stages.py:4212-4216`) and sheet choices, read in the QC context | What the Director may redo and buy | `reviews.py:711-769`, prompt `reviews.py:929-947` |
| His paid-media rule (`paid_media_approval`) | Policy setting read by `may_act` | Whether each paid redo of her REPAIR asks him first (EVERY_PAID_STEP: always) | `services.py:1520-1592` (downstream of `review_film_qc`) |
| "Never close a film for quality" | Owner rule in code | CLOSE refused | `reviews.py:865-871` |
| Small defects accepted with cause and lesson | Owner rule in code | Schema rule | `reviews.py:683-704` |
| `not_yours` findings (rights, music licences, claims, placeholders) | Owner or sources | Her ACCEPT cannot settle them | prompt `reviews.py:943-946`; caller `stages.py:4466-4476` |
| His look on the sheet | Sheet action | Replaces the Director's chosen take | `director_qc.py:2086-2088` |
| Language rule (English only out) | Rule | Publication HOLD | `reviews.py:1572-1576` |
| A Publisher HOLD letter in the Director's inbox | His resolve button (`router.py:180-188`), besides the Director's inbox review | Resolving it lifts the HOLD and makes its metadata "approved" | `reviews.py:1717-1750`, `stages.py:5774-5796` |
| Editorial rounds | Setting `STUDIO_EDITORIAL_ROUNDS` (1..20, default 10) | How many rewrites | `config.py:434` |
| Judgement shipped below the bar | STATUS letter (no question) | Informational | `editorial_judgement.py:773-823` |
| A repair the kernel refuses or that repeats | Card `director_repair_blocked` ("Mă ocup eu" / "Las cum este"), quiet 7 days | Do it himself or leave it | `desk.py:444-508`, `command.py:987-1021` |
| Autonomy mode, STOP, SAFE_MODE | Policy | Whether a repair may run (T1 MANUAL, T2 SUPERVISED…) | `desk.py:316-332`, `desk.py:555-568` |
| Every applied repair | STATUS letter (statement) | Informational | `desk.py:647-656` |
| Second model switch in a day, or no working candidate | Card `agent_model_failing` ("Aleg eu modelul") | Choose a model | `agent_health.py:530-565`, `agent_health.py:652-683` |
| His chosen model stays her home | Setting kept | He can revert in «Setări → Angajați» | `agent_health.py:714-726` |
| Deny list, verified connections | Settings / «Verifică» | Which models are candidates | `agent_health.py:468-499` |
| Model price | Card `agent_model_price` | Set price in «Autonomie → Prețurile modelelor» | `reprice.py:442-475` |
| Budget limit when pricing would exceed it | Card `agent_runs_over_budget` | Raise the budget or leave runs unpriced | `reprice.py:319-343`, `reprice.py:478-515` |
| Provider invoices | Card `provider_invoice_missing` ("Introduc factura" / "Cont preplătit") | Enter invoice/reconciliation in the Treasury | `unbilled.py:214-261` |
| Letters to/from him | Never closed by the Director | His to answer | `threads.py:120-126`, `threads.py:214-215` |

---

## Oddities and gaps

1. **Raw price table in `redo_sheet`.** When no sheet was recorded with the render,
   `redo_sheet` prices redos with `load_price_table()` (`reviews.py:341`).
   `CHANGELOG.md:97-99` records that the raw tariff has no row for the Owner's RunPod profile
   and moved `assembler._motion_state` to `shooting_sheet.price_table_for`; this function still
   reads the raw table, so its proposals can be unpriced or priced differently from the sheet.
2. **CLOSE still in the base schema.** `FILM_DECISIONS` and `DirectorQcDecision.decision`
   include CLOSE (`reviews.py:598`, `reviews.py:662`), but the bound schema always refuses it
   (`reviews.py:865-871`) and the prompt's shape lists only ACCEPT | REPAIR (`reviews.py:951`);
   `stages._carry_out` keeps a CLOSE branch (`stages.py:4480-4482`) that the model cannot reach.
3. **Docstring vs. retry behaviour.** `review_film_qc` says a refused answer "is asked once
   more with the model's own thinking" (`reviews.py:990-992`); `structured_run` quotes the
   refusal with thinking off when an object was refused, and uses native thinking only when no
   object came back (`structured.py:93-96`).
4. **Stale comment on Kael's verdict.** "Credits are bought only with the Owner's yes on the
   shooting sheet" (`reviews.py:522`) predates the 2026-10-10 path where her REPAIR buys under
   his paid-media rule (which can be MODE); and `p.credits != 0` is True for an unpriced
   proposal (None), so `owner_action_needed` is set by unpriced proposals too
   (`reviews.py:524`).
5. **Claim proof is studio-wide and by prefix.** `check_work_claims` accepts any media.* event
   whose type starts with one of the kind's prefixes, recorded since the thread began, anywhere
   in the studio (`reviews.py:1365-1371`); it is not tied to the letter's film or scene.
6. **Frames text vs. frames sent.** The editorial prompt always says "one frame from every
   scene is attached" (`editorial.py:138-139`), while `frames_for` sends none for a blind model
   (the note then says she cannot see, `editorial.py:474-479`) and at most `MAX_FRAMES` = 8
   (`editorial.py:356`), so scenes after the eighth get no frame.
7. **Two "can she see" rules.** `editorial_review` checks only the Director's own model
   (`model_can_see`, `editorial.py:313-331`); `review_bought_pictures` uses
   `vision.seeing_model`, which also tries her other slots and borrows a LOOKERS employee's model
   (`reviews.py:1181`, `vision.py:162-185`), as does the second look added in 20abffd
   (`second_look.py:686`).
8. **Hard rejects need no model, but the caller requires one.** `editorial_review` decides hard
   rejects without a model (`editorial.py:448-454`), yet `_publish_one` returns SKIPPED before
   calling it when no language model is configured (`stages.py:5705-5709`), so those
   model-free verdicts are not recorded on that path.
9. **An editorial REJECT closes the storyboard.** `editorial.py:546-549` sets
   `Storyboard.status = "REJECTED"` on her REJECT; the QC path refuses CLOSE for quality under
   the Owner's rule of 2026-10-11 (`reviews.py:865-871`). Nothing in this group re-produces a
   rejected film; it sends HANDOFF letters «Refăcut: …» (`editorial.py:592-611`).
10. **English-only language checks.** The editorial hard reject (`editorial.py:234`) and
    `publication_language_hold` (`language.py`, returns None unless the code is "en") only
    test English.
11. **Any resolution lifts a Publisher HOLD.** `approved_metadata` returns the metadata of any
    RESOLVED STATUS/ESCALATE letter carrying a title (`reviews.py:1744`), whoever resolved it
    and with whatever action: the Director's inbox review resolves a letter RESOLVED on
    ACKNOWLEDGE, APPROVE *and* REJECT (`agents/director.py:451-462`), so her REJECT of a HOLD
    makes the held metadata "approved"; `_publish_one` then re-checks only
    `publication_metadata_refusals` (serial episodes only), not the language rule
    (`stages.py:5784-5796`). Her REQUEST_INVESTIGATION or ESCALATE_TO_OWNER (when it is kept as one,
    `director.py:370-378`) marks the HOLD ANSWERED (`director.py:409-415`,
    `director.py:442-448`): no longer OPEN, so
    `publication_hold` stops blocking while the question may be with the Owner, and the
    Publisher is simply asked again on the next run. `threads.closable` does not exclude
    Publisher HOLD letters (`threads.py:150-158`), so a `close_thread` repair on a looping
    thread containing one would resolve it. Both scans are bounded to 200 letters
    (`reviews.py:1719`, `reviews.py:1738`).
12. **Editorial loop durability.** The rounds' events are written by the callers after the loop
    returns (`story_review.py:830-845`), so a crash mid-loop loses that loop's rounds; and
    `POST /episodes/{id}/review` still approves without the judgement (both stated as open in
    `CHANGELOG.md:128`).
13. **A case is dropped after three tries.** `undecided` treats a case with `MAX_TRIES` (3)
    declined/held/dead attempts as waiting forever for that fingerprint (`desk.py:167-173`);
    only a changed fingerprint brings it back.
14. **Exceeded budgets are not checked by repricing.** `apply_active_price` checks only
    periods whose state is not EXCEEDED (`reprice.py:293`), so runs inside an already exceeded
    period are priced without a refusal or card.
15. **Repair actions outside the risk-tier table.** Of the seven kernel actions only
    `analytics.read` (T0) and `agent.change_model` (T2) are in `ACTION_RISK_TIERS`
    (`services.py:467-482`); `economy.apply_active_price`, `director.close_review`,
    `director.close_decisions`, `director.close_thread` and `director.ask_for_invoices` get
    their tier (T1) from the caller, which `may_act` accepts when the table does not know the
    action (`services.py:1459-1463`).
16. **Probe failure classes.** `DOWN` counts a `ValueError` from her own model's probe as
    "down" (switch proceeds) but a `PolicyKernelError` as "could not try" (DECLINED)
    (`agent_health.py:81`, `agent_health.py:589-590`, `agent_health.py:641-647`); a kernel or
    budget refusal arrives as a returned run with its BLOCKED_* status (`services.py:828-856`)
    and declines too, except BLOCKED_PROVIDER, which is in `DOWN`. The probe does not check
    that the answer is "OK" (`agent_health.py:591`).
17. **`switch_agent_model` has no detector of its own.** Its matters come from
    `agents_failing`, registered on `diagnose_agent` (`agent_health.py:337-366`,
    `agent_health.py:750-775`); the call to it from the worker goes through the registry object
    and is invisible to the static call graph (`desk.py:581`).
18. **Narration FLAG has no effect on production.** A FLAG is an ESCALATE letter only; the render
    is not held (`stages.py:3364-3371`). Pronunciation hints are stored in the letter body
    (`reviews.py:268`); a grep of `backend/app` finds no reader of that `pronunciation` field (the voice binding's own `pronunciation_rules` in `media/factory.py:384-389` are a separate configuration).
19. **The editorial bar is decided by her numbers.** `passes` is a fixed rule
    (`editorial_judgement.py:278-281`), but its only input is her five scores, which nothing
    verifies, and the prompt tells her the bar (`editorial_judgement.py:335-344`); a score
    outside 0..10 makes the whole answer invalid rather than being clamped (`CriterionScore`,
    `editorial_judgement.py:168-189`), costing a second model call.
20. **Her picture lesson is never verified.** `editorial_review` stores the lesson with
    `provisional=True` and its own run as source (`editorial.py:584-590`). The only code that
    confirms or withdraws provisional lessons, `fix_check.settle_lessons`, looks them up by the
    run ids of the rewrite review's findings (`review_sources`, `fix_check.py:525-533`, items
    built with the review's `run_id` at `fix_check.py:359-367`; `settle_lessons`,
    `fix_check.py:536-572`), so an editorial lesson is never
    among them: it stays «[?]» and is given with " (unverified)" after the confirmed lessons,
    and not at all once 12 lessons rank before it (`prompt_agent.py:126`,
    `prompt_agent.py:3348-3351`), until a later lesson refreshes or supersedes it
    (`prompt_agent.py:3472-3492`). One case differs: a note that only
    repeats an older lesson (≥ 0.9 of its words) stores that lesson again with this editorial
    run as its source, confirmed if the older was (`prompt_agent.py:3474-3488`). When the older
    was a rewrite review's provisional lesson, it now carries the editorial run's id, so
    `settle_lessons` can no longer find it to confirm or withdraw it.
21. **Only the first sentence is read.** `picture_lesson` looks at the note's first sentence and
    nothing else (`editorial.py:413-417`): a note that opens on one film («Scene 4 flickers.»)
    teaches nothing even when its next sentence is a general rule. The sentence ends at any `.`,
    `!` or `?` followed by whitespace (`editorial.py:400`), so an abbreviation such as «e.g. »
    ends it too.
