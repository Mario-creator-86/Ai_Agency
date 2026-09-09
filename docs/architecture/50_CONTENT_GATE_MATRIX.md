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
