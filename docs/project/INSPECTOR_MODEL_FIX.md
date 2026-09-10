# Agent inspector assignment mismatch — 2026-09-10

## Reproduction and cause

Live read-only requests to port 8000 showed that `/office/layout` still returned only desk/agent placement fields, with no model_id/model_name/model_is_available. `/settings` reported a real persisted model_id for the same Sarah agent. The newer frontend treated missing projection fields as proof of no assignment, so it falsely displayed “Niciun model alocat” and disabled running. Source code already contained an enriched office projection, but the running backend process predated it.

## Fix

`frontend/src/agent_details.js` resolves the persisted agent through GET `/agents/{id}`, then reads its provider model catalog and provider metadata through read-only endpoints. These are the same model records used by Settings. No connection check or provider execution is performed. Only an explicitly empty model_id is rendered as unassigned; missing fields, missing catalog entries and network errors are distinct failures. An assigned unavailable model is still shown as assigned, with the unverified label.

`frontend/src/main.js` refreshes this data when opening the inspector and after Settings changes. Loading disables running and shows a loading message. Request/session checks discard late responses after selecting another agent, closing or logging out. A queued close event from an older dialog must not invalidate a newly opened inspector. The server continues to enforce all execution policy.

This fixes compatibility with the running backend without restarting another developer's work, migrating the database, changing any assignments or executing an LLM task. An eventual coordinated backend restart can expose the richer layout shape too; the inspector remains authoritative through direct reads regardless.

## Verification

- Frontend typecheck, 38 tests and production build passed.
- Browser on the actual application at port 8000 compared all 7 visible agents against Settings records. Names and run availability matched; Sarah displayed glm-5.3-flash.
- Browser simulated a failed catalog read: error label, run disabled, no false unassigned label.
- Browser closed the dialog during a delayed details request: it stayed closed. Rapid sequential agent selection passed.
- Browser blocked all mutating API requests during the check: zero writes, zero LLM calls, zero page errors.
- Screenshot: `output/playwright/inspector-model-fixed.png`.

Files: `frontend/src/agent_details.js`, `frontend/src/main.js`, `frontend/tests/agent_details.test.js`. QA script: `output/playwright/inspector-model-review.mjs`. Concurrent UI/backend changes preserved.
