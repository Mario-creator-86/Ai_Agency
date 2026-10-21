# Director token budget x2 — verification report, 2026-10-11

Implementation, offline verification and runtime activation are complete. The
`DIRECTOR_TOKEN_BUDGET_X2` claim is released. Runtime activation was checked after the
controlled restart at 19:24 Bucharest. A successful new QC answer from Kimi is unproven:
no paid model request or media redo was initiated to verify this change.

## The recorded failure

The Owner reported `director_qc_review` on `kimi-k3` for
“Why Ernest Lawrence's First Cyclotron Barely Fit on a Desk” at 18:11 local on 2026-10-11.

| Record | Identifier |
| --- | --- |
| Storyboard | `aa170155-56c7-4e29-9616-e1e917fb243e` |
| Rendered media asset | `c00866fc-0a03-4bd5-95cc-1201a3c4573b` |
| QC report | `2a3b5130-7c48-42ec-940a-f5be9f100c15` |
| Correlation | `0b5a919c-96fc-4af7-bd1e-8c3a6793e545` |

| Attempt | Prompt tokens | Completion tokens | Recorded result |
| --- | ---: | ---: | --- |
| First | 11,134 | 1,128 | Visible object did not validate: four repair reasons were 705, 617, 618 and 499 characters, above the existing 400-character maximum. |
| Second | 11,201 | 6,000 | No visible answer; `EMPTY_OUTPUT` after consuming the completion allowance. |

The first failure was output validation, not an answer consisting only of reasoning. The
second exhausted its allowance without a usable answer. Stored usage and error text do not
establish how many completion tokens were private reasoning. Private reasoning was not
read, displayed or added to history for this audit. Historical runs and the film's decisions
remain as originally recorded.

## Implemented behavior

`Settings.director_token_multiplier` / `STUDIO_DIRECTOR_TOKEN_MULTIPLIER` defaults to **2**
and validates integer values **1..4**. `DEFAULT_DIRECTOR_TOKEN_MULTIPLIER` supplies the same
default when the runtime's existing settings fallback has no setting object. Settings are
read once per `run_agent_task` and reused for the existing budget gate.

After resolving the agent and its role, `run_agent_task` multiplies an explicit `max_tokens`
once only for `Role.name == "Director"`. All Director tasks reaching this shared path use
the same rule, including calls on configured secondary/seeing models. The model's name does
not determine eligibility. Other roles use multiplier 1. `max_tokens=None` remains `None`.

| Example | Requested limit | Default effective limit |
| --- | ---: | ---: |
| Director film QC, first attempt | 6,000 | 12,000 |
| Director film QC, second attempt | 6,000 | 12,000 |
| Director inbox | 24,000 | 48,000 |
| Other employee with a 6,000-token limit | 6,000 | 6,000 |
| Unspecified limit | `None` | `None` |

Both structured attempts call the shared runtime separately with the original requested
limit, so the second attempt is doubled once rather than receiving a cumulative multiplier.
The Ollama adapters map the effective limit to `options.num_predict`. The first structured
attempt continues to request `think=False` plus JSON formatting; an invalid visible object
can trigger one second attempt with `think=True`. An empty or failed run still stops the loop.

Executed runs preserve this additive audit metadata under `context_json.generation_limits`:

```json
{
  "requested_max_tokens": 6000,
  "token_multiplier": 2,
  "effective_max_tokens": 12000
}
```

QC prompt version `director-qc-v5` now tells the model the schema's existing maxima:
400 characters per verdict/repair reason, 800 per summary, 80 findings and 24 repairs.
It does not loosen the schema or the decision gates. Invalid structured output now logs
`structured_answer_invalid`; invalid output alone does not prove narrated reasoning.

## Verification

| Check | Result |
| --- | --- |
| Related baseline before production changes | 63 passed, 1 live-provider skip |
| New regressions before production changes | RED: 7 failed, 1 passed |
| Initial new regressions after implementation | GREEN: 8 passed |
| Latest focused regressions, including Director `None` | 9 passed, 18 deselected; 2.82 seconds |
| Final related suite | 123 passed, 1 skipped; 98.91 seconds |
| Changed-file Ruff | Passed |
| mypy on four changed source modules | Passed |
| Independent read-only patch review | No actionable issue found |
| Licence fixtures after two scanner annotations | 5 passed; 1.67 seconds; Ruff passed |
| Documentation inventory, hashes and status header | Passed |
| Documentation truth and note tests | 26 passed; 0.51 seconds |
| Secret scan after fixture annotations | Passed: 1,157 files, 63 previously reviewed findings |
| Runtime activation | Verified new process, effective multiplier 2, healthy API and worker |
| Real paid model or media acceptance | Not attempted for this task |

The nine focused cases in `tests/test_phase1_agents.py` verify role-based doubling and stored
limits, the inbox-sized allowance, another role unchanged, configuration values 1 and 3,
rejection of values outside 1..4, an unspecified Director limit remaining `None`, and both
actual Ollama request bodies carrying 12,000. That provider-wire regression constructs
isolated Settings with `_env_file=None` and multiplier 2, replaces `_post` and makes no
external request; it does not prove the live process read the local configuration. It also checks
the two thinking flags and the concise schema-bound instructions. Existing related tests
cover unusable output waiting without redos, empty-output status, and policy/budget refusal.
The live-provider case is skipped; test doubles do not prove that `kimi-k3` will now answer.

The secret gate initially reported two pre-existing fictitious licence credentials in
`tests/test_plan_licence.py`. Independent review confirmed test fixtures, and only two inline
`pragma: allowlist secret` comments were added. Fixture values, the scanner and
`.secrets.baseline` are unchanged; the five licence tests and Ruff pass. This ancillary
quality-gate cleanup does not alter application behavior.

## Runtime activation evidence

The coordinator verified the controlled restart separately from the offline provider-wire
tests. Before stopping, there were zero agents, tasks, production days and cloud jobs in
flight; the independent state check also found zero GPU/spend reservations. The previous
launcher process group 32972 stopped cleanly using CTRL_BREAK.

The replacement API server PID 2096 started at `2026-10-11T16:24:28Z`, 19:24 Bucharest;
replacement launcher process IDs were 36452/30460 and the start script ID was 42936.
The live and ready health endpoints returned HTTP 200 with HEALTHY status, and the worker
check was OK. Fresh Settings loaded from the actual local configuration reported
`director_token_multiplier=2`. No new AgentRun existed at the post-restart 19:25 check.

This confirms the new runtime and configuration are active. The 12,000-token request bodies
were demonstrated offline, not by spending on the film. No post-change successful QC verdict
from Kimi is claimed. The studio's normal subsequent work remains governed by its Owner policy.

## Scope, practical limits and rollback

USD budgets, the studio-wide daily-token ceiling, STOP, permissions, the structured-attempt
count and media purchase rules keep their existing behavior. The larger allowance can spend
more tokens and take longer. It does not guarantee valid JSON or successful completion, and
this task does not change the existing admission/reservation policy or claim new provider
limits. Architecture specifications, indexed hashes and database schema are unchanged.

Application files: `backend/app/config.py`, `backend/app/agents/services.py`,
`backend/app/agents/reviews.py`, `backend/app/agents/structured.py`, `.env.example` and
`tests/test_phase1_agents.py`. The ancillary fixture annotations are in
`tests/test_plan_licence.py`. This report and the four project journals record the outcome.
Pre-change copies are in `output/director-token-budget-2026-10-11/before/`.

To restore the earlier allowance, configure `STUDIO_DIRECTOR_TOKEN_MULTIPLIER=1` and perform
the normal controlled restart; settings are cached by the running process. This preserves
the additive audit metadata and clearer QC prompt. Source rollback can use the saved
pre-change copies, followed by the normal checks and controlled restart; no migration or
historical-record rewrite is needed.
