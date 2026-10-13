# Private source publication — 2026-10-13

The Owner selected the main application, rather than the AMN_r4_wp7 development worktree.
This snapshot comes from source revision `5bf3f0d40860679984ce9a5ab367fb2c6c560fe4`.
It is imported into a new Git history in `Mario-creator-86/Ai_Agency`, branch `main`.
Other worktrees, their unmerged changes and the original Git metadata are not imported.

## Source retained

Backend and migrations, frontend source and approved runtime assets, all test modules,
sanitized regression inputs, agent definitions/character bible, workflow definitions,
operator scripts, locked dependency manifests, configuration templates, normative
architecture, art provenance/licences and useful code-map documentation are retained.

The backend executable Python syntax is unchanged: 314 files compare identically after
excluding docstrings. Frontend application source text is unchanged; some files have
normalized LF endings. The original application's 1,417 selected files were hash-checked
after preparation and none changed.

## Exclusions and sanitization

- No `.git` history from the application, `.env`, credentials key, database, account vault,
  licensed music, media storage, logs, runtime data or backup is included.
- No Python environment, node_modules, build output, caches, IDE/Claude worktree settings,
  scratch verification tools, other application version or rejected artwork draft is included.
- No model weights are included, including the small YuNet QC ONNX file. Its licence,
  source and checksum remain; see docs/CLAUDE_CLOUD_SETUP.md for local restoration.
- The tiny offline video test fixture is retained because browser tests depend on it.
- Private operational histories/audit rows are replaced by source-focused summaries.
  Production identifiers are anonymized consistently in the regression fixtures; the
  factual QC accounting fixture has synthetic balances/consumption. Private production
  tracing in module docstrings is omitted. Normative architecture hashes remain intact.
- Derived code-map inventories/graphs are omitted and can be regenerated from the script.
  The local audit/mapping data remains outside this repository.

Configuration secrets are empty or placeholder-only. Some security regression tests
deliberately contain fake credential-shaped strings and URLs; these are reviewed synthetic
inputs, not configured accounts. Existing secret baseline entries are retained; no new
credential finding has been automatically approved.

## Small changes made only in this copy

Added CLAUDE.md and docs/CLAUDE_CLOUD_SETUP.md. Strengthened .gitignore, documented the existing
STUDIO_EDITORIAL_ROUNDS default in .env.example, normalized one test import, and adapted
fixture expectations/appearance metadata to the anonymized data. Updated project-document
index hashes for sanitized summaries, without changing any architecture document.

The only dependency change is the compatible transitive frontend build dependency
`source-map-js` 1.2.1 → 1.2.2, fixing GHSA-68fv-2mgg-jv7q. The frontend package manifest
and Python lock are unchanged; npm audit reports zero vulnerabilities after this patch.

The inherited GitHub Actions workflow is manual-only (`workflow_dispatch`). Initial
publication does not start hosted CI, GPU work, paid vendors or deployments.

## Validation

- Locked Python and npm dependencies installed in this independent checkout.
- 952 frontend unit tests pass; TypeScript check and Vite build pass.
- 99 focused backend/startup/template/fixture tests pass.
- Ruff lint and formatting pass; documentation inventory and architecture hashes pass.
- Secret scan passes; independent credential-pattern/template review is recorded locally.
- A real disposable loopback server started and stopped successfully. Health/frontend
  return 200, unauthenticated snapshot returns 401, authenticated snapshot returns 200.
  It used a separate temporary database, with worker/provider refresh off and external
  networking denied. The production application was not connected to or restarted.
- Backend mypy reports 32 existing errors in nine modules. The executable source is
  unchanged; these are audit work, not evidence that this publication repaired the app.
- The broader non-slow backend run was stopped at the Owner's explicit request before
  completion. It exposed one existing approval-expiry expectation mismatch and thirteen
  tests tied to historical documentation replaced for privacy, plus two paid-path lock audit
  failures. The run was interrupted around 50%; results are partial and no full-suite pass
  is claimed. Final documentation-format edits were not retested after the stop request.
  Full film/GPU/vendor, production publishing, DPAPI/service and legacy graphics acceptance
  are not claimed.

The original production configuration, models, data and Git history remain local.
Cloud changes must use a feature branch/PR and be verified for Windows compatibility
before the Owner applies them to the original installation.
