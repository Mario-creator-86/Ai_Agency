# Changelog

## 2026-10-13 — Office serial: «Scrie episodul» writes, reads, approves and readies in one press

- The serial room's «Scrie episodul» («Zile închise») calls `POST /story/logs/{log_id}/tell`
  (`serial_stage.tell_day_now`), the daily run's serial ladder for that one closed day: the
  day's unread DRAFT is taken up, else a draft is written (as the rewrite of the day's last
  refused draft, with the notes, while `MAX_DRAFTS_PER_DAY` lasts), then `judged_review`, the
  approval under the channel's policy, the storyboard and the filming queued (PRODUCTION).
  The same limits (`MAX_DRAFTS` per press, `MAX_DRAFTS_PER_DAY`), the Owner's stop (409, in
  the studio's words), one answer per `command_id`. Before: the button called
  `/story/episodes/write` alone, Marcus wrote «The Nine-Scene Rewrite» (DRAFT) and the
  Director read it only at the next run («De ce nu-l citește? Nu trebuie să o facă
  automat?»). That route is unchanged.
- While it runs the button says «Se scrie și se citește…»; afterwards the page prints the
  backend's words of where the episode ended: «a trecut citirea Directorului și e aprobat;
  pregătit de filmare», «așteaptă aprobarea ta», «respins de Director: …», «respins de
  verificările calculate: …», «ziua și-a folosit cele 3 ciorne» (`tellOutcomeMessage`).
- Tests: `tests/test_serial_tell_now.py`, `frontend/tests/serial_room.test.js`.
## 2026-10-13 — Nadia's threshold before money is spent again on the same picture

- New `backend/app/economy/repurchase_gate.py`, hooked in `runbook.stages._apply_repairs`
  after the Director's second look and her correction, after the redo is priced and before
  `redo_scene` buys it (the Owner: «încă un prag de verificare la Nadia, după ce trece de
  Director, doar când vine vorba de a cheltui iar bani pentru aceeași imagine sau video sau
  sunet»). Gated: a PAID redo of a still or a clip the film already paid credits for once
  (`paid_takes`). Not gated: a layer's first purchase, a re-roll inside an approved plan's
  cap, a redo the film's ceiling (OVER_FILM_BUDGET, the Owner's, unchanged) or the day's
  budget refuses.
- Nadia reads, as inert data: the film, the scene and the layer, what was wrong (quality
  control's and the Director's words, her brief's diagnosis and the old words), the corrected
  prompt, the redo's price at today's table (cap, USD), the film's books against its ceiling
  and what remains, the redos bought on the scene and the film with the caps (5/20), the
  day's budget when one is set, and the rule. Her answer is structured
  (`{verdict APPROVE|REFUSE, reason, cheaper_alternative}`) and validated; an answer nobody
  can read is not an approval: nothing is bought on that walk, the scene is held
  (`REPURCHASE_UNDECIDED`) for the next try, and the event says so.
- On REFUSE she writes to the Director (a HANDOFF with her reason, figures and alternative)
  and the Director decides once (`{decision ACCEPT_MINOR|CLOSE_SCENE|INSIST, reason}`):
  INSIST buys within the ceiling with both opinions recorded; ACCEPT_MINOR keeps the take
  through the path her second look's overturn has (`result['overturned']`, the findings
  settled; never for a defect measured serious); CLOSE_SCENE holds the scene
  (`REPURCHASE_REFUSED`) with their words. No Owner card: «de la contabilitate nu ar trebui
  să ajungă la mine». Both remember their verdict (AGENT_OPINION).
- Durable and idempotent: `economy.repurchase_gate` on the film's record, keyed by film,
  scene, layer and plan hash; a walk resumed on the same plan (his yes under the ask-me rule,
  the next reading) reads it instead of asking again. The contracts of the Accountant and the
  Director say the rule (`config/role_contracts.json`, version 7).
- Tests: `tests/test_accountant_gates_the_repurchase.py` (scripted agents, the vendor spy;
  nothing proves a live model). Narration is not gated: the path has no paid narration redo.
## 2026-10-13 — The Scriptwriter's brief: the platform, the judge, the idea, the money, her letters

- The factual writer's brief (`factual.agent_pipeline._write_instructions`) says where the
  film plays and for whom — a vertical YouTube Short on the studio's channel (named from the
  publishing record when one exists), on a phone, often muted at first, in a loop, never over
  60 s; a stranger with no context — and the hook window once, as the judge scores it (two
  seconds; the brief said three). It carries the Director's five criteria in her own words
  and her bar (`editorial_judgement.criteria_lines`, `PASS_TOTAL`, `CRITERION_FLOOR`, the
  rounds setting), the idea she chose as inert data with the research scores under 0,70
  named first, what the cover (`hook`, at most about 8 words) and the published title
  (`title`: subject first, at most 60 characters, no clickbait) are made from, what one LIVE
  scene costs from the price table on the model the studio films with and the film's ceiling
  (no price line when no model is selected or the table cannot price it; cards cost 0;
  «preferă N scene LIVE puternice față de 12 slabe»), and, with at least three measured films
  on the channel, the three best and the three worst by average view percentage with hook,
  CTA kind, length and editorial total (`MĂSURAT PE ACEST CANAL`; absent otherwise).
- `analytics.story_performance` rows carry `measured_at`, `hook`, `cta_kind`, `seconds` and
  `editorial_scores`; the weekly digest names each film's hook, CTA kind, length and total.
- The story review's REVISE/REJECT letter is a REQUEST_REVIEW addressed to the Scriptwriter
  (it was posted to the Director's own inbox, `to_agent_id=None`), with her retention row and
  the span where she loses the viewer in its words, and is resolved when a later draft of the
  story passes. When a story ships, one AGENT_OPINION on his memory keeps the title, the
  versions read, the shipped scores and her last note (`story_review.remember_shipped_story`).
- The weekly review's «topics» direction is studio-wide STRATEGY memory (it was on the
  Director's own id, which `memory.recall` showed to nobody else); a `writing` field — how to
  write, from the numbers — is routed as its own HANDOFF to the Scriptwriter («departamentul
  de scris»), apart from the topics letter; HANDOFF bodies name their `department`; prompt
  version `weekly-review-v3`.
- ScriptWriter contract (`config/role_contracts.json` v7): the platform and the money in
  `watch_for`, «merge two scenes that show the same thing» in `correct`.
- Tests: `tests/test_writer_brief.py`. Offline only, scripted models; nothing proves a live
  model, vendor or publication.

## 2026-10-13 — Office serial: words per beat is a recommendation; a computed rejection is signed by the checks

- `words_per_beat` is `advisory` (the Owner: «nu trebuie să fie ceva fix, este ceva recomandat,
  dar nici să respingi serialul de la asta»): a beat outside 8-22 spoken words is measured and
  shown, the showrunner is not asked again for it, and the Director reads the episode with the
  measure under «recommendations» and decides; the brief says the band is a recommendation.
  The clip's own limit (`filmable`) and the episode's length stay rules. Before: «The Ninth
  Rewrite» (13.10.2026) was REJECTED for a 23-word beat before she read it.
- A FAIL the computed rules gave without her reading is `reviewed_by: checks` (the episode row
  and `story.episode_rejected`): the journal's cover says «Verificările calculate · RESPINS ·
  Directorul nu a citit episodul», the list «Respins de verificările calculate», the feed «nu a
  trecut verificările calculate». The check list counts rules apart from recommendations
  («9 din 9 trecute · 1 recomandare de decis»).
- Tests: `tests/test_words_per_beat_is_a_recommendation.py`, `frontend/tests/serial_room.test.js`.

## 2026-10-13 — Prompt path repair: static stills, planned markings, the resumed redo

- The still (image) prompt carries no movement: a clause of the plan that moves the camera is
  left out of the still (its moment stays), a tempo or a span of the clip leaves its clause,
  the serial's first moment the same; the motion prompt keeps all of it. New lint
  `STILL_MOTION` (WARN). The shot writer's and the rewrite's instructions say the rule.
- New `backend/app/media/markings.py`: the objects a plan names that carry their own markings
  (thermometer, gauge, dial, clock, ruler, graduated glass, instrument panel, keyboard…).
  Writing on such an object is no hard limit of the bible: the Director overturns it in one
  look (`second_look`), the stills gate leaves the refusal to her look (`may_be_overturned`),
  clip QC's `look_may_overturn` too, the vision checks are told the instrument keeps its scale
  (`judge_still`, `judge_clip`, the film's picture QC), a re-roll keeps it
  (`positive_instruction`), her rewrite review does not anchor the finding serious
  (`scene_rewrite.hard_limit`), and the still prompt ends «The thermometer keeps its own scale
  and markings; no caption, no logo.» instead of «No text, no logo.».
- A paid redo corrected under the Owner's ask-me rule is bought on his yes: the resumed walk
  no longer corrects (or looks at) the scene again before spending it
  (`runbook.stages._corrected_for_film`).
- After the PR's automated review (Codex, three P1 findings, all real): the still's negative
  channel no longer says «text, lettering» for a scene whose plan names an object with its own
  markings (`stills_stage.still_negative`); a named camera move in a plan field counts as the
  camera's only beside the camera or in the cinema's own words («Earth orbits the Sun» and
  «she pulls back the curtain» stay in the still; `prompt_lint._camera_moves_in`); the
  resumed paid redo binds to her brief's rewrite (`reason: director_brief`), never to the
  serial's recomposition or re-roll, which write the same event.
- Tests: `test_still_prompt_is_static.py`, `test_planned_markings.py`,
  `test_rewritten_still_reaches_the_model.py`, `test_rewritten_motion_reaches_the_model.py`,
  `test_redo_resume_spends_his_yes.py`; `test_director_rewrites_failed_scene.py` now asserts
  the exact rewritten motion prompt reaches the vendor fake. Offline only; nothing proves a
  live vendor or model.

## 2026-10-13 — Private source publication

 prepared a clean source snapshot for a private GitHub repository. Excluded local environments, credentials, databases, storage, caches, outputs, scratch tools, rejected artwork drafts and model weights. Sanitized production-derived fixtures and replaced private operational history with source-focused summaries. Preserved the original application without modifying it. Added CLAUDE.md and a cloud setup guide. Publication validation is recorded in GITHUB_PUBLICATION.md; historical production outcomes are not included.

This summary replaces private operational records only in the GitHub copy.
