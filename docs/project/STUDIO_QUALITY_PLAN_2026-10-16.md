# Studio quality plan, 2026-10-16

## Why

The Owner on «Zero Scripts, Blocked Log»: «Eu nu înțeleg nimic». He wants shorts and episodes
of a quality a stranger understands, with a small story, made by the studio with no
intervention. On the same day he asked for the studio's skills to be put to use
(10x-Team roles, skill-creator playbooks, a filtered AI-Firstify audit).

Four inputs, all from 2026-10-16:

- **The adversarial review of today's commits** (47d65a2..c4fad3d). It confirmed 30 defects,
  9 of them high. They are being fixed: this is step 0.
- **The filtered AI-Firstify audit** of the studio's agents. It kept 34 findings and dropped 6,
  and mapped every role's brief. It was read-only, on the nightly backup
  studio-20261016T015919Z.db.
- **The deep research** on short-video storytelling and LLM judges. 17 claims survived three
  adversarial votes each. See [STORYCRAFT_RESEARCH_2026-10-16.md](STORYCRAFT_RESEARCH_2026-10-16.md).
- **The skills evaluation** (wf_f6c8c3f0-5b8). The useful 10x-Team lenses are SRE, PM, QA and
  staff engineer. From AI-Firstify, only the anti-pattern "the author reviews his own work" applies.

## What the audit found, in one paragraph

Every agent call carries the agent's whole identity: the 120 newest memories, up to 20 open
asks with their threads, and the full role contract. That is about 94% of all input. A Director
judgement reads 320-350K characters of identity around a 5-48K task. The recency window evicts
the Owner's 16 live policies from the Director's and Marcus's prompts, and stale asks about
closed films ride every call. 51 of Marcus's 103 answer_mail runs failed on the model's context
window. Provisional prompt lessons reach the Director through her memory. That bypasses the
2026-10-15 rule that she reads proven lessons only.

The judges are not independent:

- in the prompt-audit loop, the Director checks her own diagnosis three times;
- Kael judges the pictures his own prompts produced, on his own model;
- the editorial judge re-scores rewrites while seeing her earlier totals and her brief.

Her refusals must quote the words, but code never checks the quote, and she cannot tell the
composer's fixed sentences from the Editor's words. That is the root of the loops of
10-15 and 10-16.

The writers are never shown the rubric they are judged on. They get no worked example, and they
fix a local defect by regenerating the whole artifact. 4 of 35 serial drafts were approved.
The factual story review gave 16 PASS, 60 REVISE and 3 REJECT.

## Success criterion (PM lens)

The criterion is checkable before any money is spent: on a frozen set of past days, the studio's
writers, judged blind, produce scripts a stranger would understand and finish. It is measured as:

1. **Pass rate on the frozen evaluation set.** A blind judge on a pinned model, calibrated on
   the Owner's own verdicts, scores each script. The deterministic checks must pass.
2. **Rounds to the bar and drafts per approval**, compared with today's baseline.
3. **Audience truth after publication.** YouTube's measured_view_percentage per film, laid
   beside the judges' scores every week.
4. **SLO (SRE lens).** The day reaches its goal (a short and an episode published) with no
   intervention. The error budget decides whether the next week is reliability or features.

## Steps

### 0. Today's defects (in progress, no decision needed)

- The 30 confirmed review defects are being fixed in seven worktrees, each patch adversarially
  verified.
- Audit #27 is being fixed alongside: a factual montage shot is judged against the whole scene,
  so a correct detail still is refused and bought again.
- Audit #22 is being fixed alongside: prompt lessons leak into identities.
- Then the full suite runs, one commit, and the docs are updated. The server stays stopped until
  the Owner says otherwise.

### 1. A frozen evaluation harness (0 USD)

`scripts/writer_eval.py` follows `scripts/qc_audit.py`. It works on a copy of a nightly backup
per past day, holds only the LLM registry, and asserts that no media adapter exists.

- **Inputs.** 10 past days from the nightly backups (2026-10-12..16):
  - write_episode on the serial log of each day;
  - agent_write_script on topics with SUPPORTED claims.
  The model is pinned (the Director answered on 3 models in 3 days, Marcus on 6).
- **Scorers.** First the free deterministic checks:
  - draft_checks and episode_checks;
  - citations, scene kinds and the narration budget;
  - the film-length estimate against the 180 s wall.

  Then one blind judge with a bare identity, on a different model family, using yes/no rubric
  tests with justifications. It runs the criteria in 3 permuted orders and both orders of a
  pairwise "which would a stranger finish" comparison.
- **Golden pairs that exist today:**
  - episode v1 26/50 against v2 38/50 (2026-10-14);
  - factual topic be6dfc6d with 10 drafts;
  - the «Zero Scripts, Blocked Log» chain.
- **Schedule.** It runs at night, never beside the live Director loop, never inside pytest.
  The output is a baseline, and every later step is measured against it.

### 2. Context profiles per task (audit P0 #0, #21, #25, #26)

- `compose_identity(task_type)` chooses one of three profiles:
  - **BARE:** name, role and standing rules. For audits, critics, rewrite reviews, second
    looks and the lesson curator.
  - **CRAFT:** role, the contract slice for that stage, OWNER_POLICY always pinned, and the
    role's playbook index. For writers and judges.
  - **INBOX:** paged, one thread per call. For answer_mail and director_review.
- Memory is chosen by task and subject, with a fixed budget, instead of the 120 newest.
- Asks of closed, published or superseded films resolve themselves, expire after N days and
  collapse by subject.
- Lessons are given per layer (still, motion, bible).
- The profile used is recorded in context_json.
- **Expected:** a Director call drops from about 110K prompt tokens to 15-30K, answer_mail
  stops failing, and the Owner's policies are actually in the prompt.
- **Measured on the harness:** tokens, latency, scores.

### 3. The audit loop stops judging itself (audit P0 #1, #7, #8, #14, #15, #28, #10, #20)

- **Attributed words.** The composer returns words_to_send as attributed segments
  (`composer:<CONST>` or `field:<name>`).
- **Checked quotes.** A refusal must quote words, and code checks the quote. A refusal whose
  quotes all fall in composer text becomes a developer note on round 1, with no Editor rewrite.
- **No self-review hop.** In the audit path, the intermediate rewrite review is dropped, and
  the next audit is the only judgement of the new words.
- **An arbiter at a streak of 2.** It runs on another model, sees only the words, the plan and
  her finding, and either quotes the span or answers ABSENT. It does this before TOOL_DEFECT.
- **Lessons.** Provisional lessons are withdrawn when their streak ends in TOOL_DEFECT, and are
  retired when the audit template changes. A lesson becomes a rule only after two kept takes in
  different scenes, graded by a looker other than its author.

### 4. Independent judges (audit #9, #11, #12, #18; research)

- **The picture gate.** It runs on a vision model Kael does not use (the QualityAssurance
  role). It sees the scene, not his compiled prompt, until it has answered.
- **Editorial scoring.**
  - It is blind: no version number, no earlier totals, no brief. It runs on a model other than
    the Director's.
  - The rubric becomes yes/no tests with a 1-3 sentence justification each, summed. The
    criteria order is permuted 3 times.
  - The shipped version is chosen by a blind pairwise comparison, run in both orders.
- **episode_review** keeps only truth and grounding, handled by the Fact Checker on a different
  model. Taste has a single rubric, shared with the writer.
- **Under the drafts cap** the best-scored draft ships, not the newest.

### 5. Playbooks (Owner's yes of 2026-10-16, "measured")

- **Files.** `config/playbooks/`: serial_writer, factual_writer, shot_grammar, rubric_examples
  (one file, read by the writer and by the judge) and diagnostic (defect class, then its usual
  wording cause, then a positive fix).
- **Contents.** Positive patterns, each with one good and one bad example drawn from the
  studio's own history. Examples: 'Twenty-Eight Rewrites Before Breakfast' 38/50 beside its 26/50
  sibling, and the best-retention shorts.
- **Forbidden-word lists** move from the writing prompts to the lint and the judge.
- **The edit pass (LAMP).** The judge marks the weak passages, and the writer rewrites only
  those beats or scenes, returned by index. Code merges them and runs the checks again.
- **Gate.** Each playbook goes live only if it beats the baseline on the harness.

### 6. Calibration and audience truth (research: an uncalibrated judge ≈ chance)

- **The Owner's verdicts.** He answers yes/no to five questions on about 15 past scripts and
  episodes:
  - Do I understand where we are in the first 10 s?
  - Is there a story?
  - Would I watch it to the end?
  - Is the ending earned?
  - Is it funny or surprising?

  The judge's agreement with him is measured (kappa), and the judge goes live only above an
  agreed floor.
- **Audience truth.** The serial writer and the judges get measured retention, as the factual
  writer already does. A weekly report lays the judges' scores beside measured_view_percentage.
- **A slop profile** of the studio's own texts against a human corpus of the same genre gives
  the lint a measured list.

### 7. Operations (SRE / QA lenses)

- **Restart checks.** scripts/restart.py runs post-restart checks, and /health shows the running
  commit.
- **A composer replay before every restart** (audit #19): compile the un-bought packages and a
  frozen corpus of past refusals. Refuse the restart on any new lint or composition block.
- **A fast QA tier on the paid paths**, plus idempotency tests of every resume.

## What needs the Owner

- The order of the steps.
- The model of the independent judge. LLM calls are free on the subscription, but share its
  usage limits.
- Whether he will label about 15 past scripts for calibration.
- The daily budget once the montage's cost per day is known. Fixer g prices a production day.
  Before the montage a film had 5-8 rows; now it has 30-50.

## Not in scope

- AI-Firstify Re-engineer or a full audit: its principle 5 would delete the studio's agents.
- The 10x-Team SDE protocol (.10x/ folder): state stays in docs/project.
- Manifold, by a later card only.
