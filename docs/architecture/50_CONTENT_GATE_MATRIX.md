# Content Gate Matrix

## Gate stages

| Gate | Before script | Before media | Before publish |
|---|---:|---:|---:|
| Source/evidence quality | Yes | Recheck if changed | Yes for stale-sensitive |
| Claim factual verification | Yes | Yes if storyboard adds implication | Yes |
| Novelty/duplication | Candidate | Script | Final metadata |
| Rights/license | Source media planning | Asset generation/sourcing | Final package |
| Platform policy | Topic | Storyboard as needed | Final |
| Brand strategy | Candidate | Script/storyboard | Metadata |
| Technical QC | No | Render | Yes |
| Visual factual QC | No | Storyboard/assets | Yes |
| Picture reality and intent | No | Render | Yes |
| Character drift | No | Render | Yes |
| Continuity (Channel B) | Story | Storyboard/assets | Yes |
| Narrative privacy (Channel B) | Event selection | Script | Yes |
| Budget | Research budget | media spend | publishing/extra spend |
| Autonomy | Workflow | side effect | publish |

## Gate behavior

PASS:
continue.

FAIL:
block stage.

NEEDS_REVIEW:
route according to approval policy.

NOT_APPLICABLE:
record reason.

NOT_IMPLEMENTED:
record reason (since 2026-09-18 this is a status a gate may carry, and the code has used it since
the quality-control report existed: it means the check is not built for this studio's data at all,
where NOT_APPLICABLE means it is built and could not run here).

A gate certifies only what it measured (stated 2026-09-18, the rule the code has followed since the
quality-control report existed). A check that could not run carries its status, a reason in plain
words and `passed: null` — never `passed: true` and never a silent absence. The distinction is
load-bearing: a report with `passed: null` and a reason is a studio that says it did not look; a
report with a missing key is a studio that could later be read as having looked and found nothing
wrong. Nothing downstream — the Director's verdict, the five-point publishing gate, the day's
summary — may treat a `passed: null` as a pass, and nothing may add a failure from it either: the
film's verdict is exactly what the gates that did run left it.

## Picture and character gates (built 2026-09-18)

The two rows added to the table above exist in code (`backend/app/media/picture_qc.py`,
`backend/app/media/qc.py`). Until 2026-09-18 the matrix listed visual and continuity gates that
nothing performed: `character_drift_qc` reported NOT_IMPLEMENTED on every film ever made, and no
gate anywhere looked at a frame, so a film of blank fields, stripes or garbled writing could pass
technical QC, the factual gate and the five publishing points.

**What they measure.** Every scene's middle frame is cut from the finished film — never from the
plan, never from the storyboard — and sent, in one call for the whole film, to an employee whose
provider declares its model can see. The picture gate asks two things of each frame: whether it is a
picture at all (a blank field, stripes, noise or garbled writing is not) and whether it shows what
that scene's visual prompt and narration asked for. The character gate asks, of the same frames,
whether each character the storyboard put in a scene is the one the Character Bible describes —
canonical face, hair, outfit, props, role symbols and palette, and, where a bible slot holds a
stored asset id, the portrait itself, attached as a reference image. A person in the wrong outfit is
named with their scene.

**What they certify.** A refusal fails the film in both environments, beside the degenerate-still
and placeholder-footage checks and unlike the fallback-scene ceiling, which is conditional on
PRODUCTION because in TEST the fallback count is the studio's own policy. Nothing in TEST policy
deliberately produces a picture of nothing or a stranger in a character's clothes.

**When they stand down, and what that means.** Both gates report NOT_APPLICABLE with the reason,
`passed: null`, no failure added and the film's verdict unchanged when: no provider registry is
handed in; no employee's model declares vision; no frame could be cut (no encoder, no file); the
day's token ceiling has been reached; or the model narrated and never returned the JSON. A scene the
model leaves out of its answer is recorded with the reason that no verdict was returned for it, and
a scene past the frame cap with the reason that no frame was cut for it — neither counts towards a
pass. Where the Character Bible holds no characters at all, the character gate stays
NOT_IMPLEMENTED. A studio whose workforce has no vision-capable model therefore sees these two gates
stand down in every report, visibly and with the reason, which is the honest reading and not a pass.

## Gate immutability

A pass applies to a specific:
- content version;
- asset/render version;
- policy version.

If content changes materially after a gate passes, invalidate/re-run affected gates.

## Critical rule

QC cannot "approve the idea generally." It approves exact versions.


## V4 Marketing gates

Before teaser/social publish:
- grounding gate;
- sanitizer;
- rights;
- brand safety;
- platform policy;
- episode-commitment/payoff check when CTA promises next episode.

Before paid/sponsor campaign:
- all above;
- budget;
- advertising disclosure;
- Legal/Compliance;
- Owner approval where configured.


# V5 Financial/Commercial Gates

Before publishing financial/company-economy story content:
- verify event actually exists;
- verify amount disclosure policy;
- distinguish estimated vs settled revenue;
- distinguish virtual VendorShop purchase vs real external purchase;
- distinguish virtual financing vs real loan;
- Legal/commercial disclosure if sponsorship/donation/paid pitch involved;
- no misleading "we bought X in real life" claim.
