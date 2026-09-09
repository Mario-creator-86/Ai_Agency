# Autonomous AI Studio — working instructions

Read `docs/architecture/README.md` and `docs/architecture/00_MASTER_PROMPT.md` first.
The complete architecture package is normative; preserve its invariants and follow its reading order.

Before editing, read `docs/project/CURRENT_STATUS.md`, `docs/project/13_ROADMAP_TODO.md`,
`docs/project/16_DECISION_LOG.md`, `docs/project/14_AI_HANDOFF_PROTOCOL.md` and the relevant specifications.

- Architecture belongs only in `docs/architecture/`; application source belongs in `backend/` and `frontend/`.
- Implementation tracking belongs in `docs/project/`. Do not create competing copies of specifications.
- Record the task claim and tested outcome in CURRENT_STATUS and keep roadmap/changelog/decisions current.
- `scripts/check_docs.py` verifies the original document inventory and architecture SHA-256 hashes.
- If a deliberate specification change is needed, record the reason in the decision log and update that
  document's index hash explicitly. Do not bypass a failing integrity check.
- Product agents cannot bypass Owner policy; developer AUTORUN does not enable product autonomy.
- Never mark a provider integration or production feature working based on mocks.
- Use `uv sync --locked`, `npm ci --prefix frontend`, and checks from the root README.

