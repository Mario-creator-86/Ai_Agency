# Architecture decisions for the published source

The source remains local-first, single-owner and loopback-bound. SQLite records, workflow state and committed domain events are authoritative. Durable leases, outbox events, idempotent commands, credentials encryption and Owner STOP/approval/budget rules remain required. The active presentation is the side-view pixel studio; legacy 3D sources remain archival. Treasury and virtual financing are retired from the active interface. Paid vendors are optional existing adapters, never automatic replacements for local integrations. Film QC, research provenance and rights gates remain mandatory. New architectural decisions must document reason, alternatives, compatibility, migration, tests and rollback. The private operational decision history remains only in the original application; this publication summary does not change the indexed normative architecture.

This summary replaces private operational records only in the GitHub copy.

## ADR-TOWN-SIDECAR — 2026-11-05

Reason: Owner explicitly requested a new village with ten agents, then authorized using an existing GitHub repository when new-repository creation was unavailable. Scope: isolated `mario-agent-town/` on feature branch `mario-agent-town`; this is an explicit exception to the normal source placement for a NEW independent prototype, not a replacement/competing implementation of the AMN-AI studio. Alternative: a new repository, unavailable through the current connection; adapting the studio immediately would broaden scope and couple unrelated identities/accounts. Compatibility: parent backend/frontend, normative architecture and production data remain untouched. Migration: none. Tests: nine subproject offline tests; no live-provider or existing-studio regression claim. Rollback: remove the added sidecar directory and these tracking additions, or leave this branch unmerged. Future integration requires a scoped bridge and the parent's relevant specifications.

## 2026-11-05 — Owner graphic handoff v2

Completed the Owner's explicit request to draw the colorful RPG town and characters for Claude to continue: original painted map, ten unique 16-frame character sheets, preserved quarter-zip CEO, 12-building atlas, prop atlas, manifest, art guide and original-PNG art pack. The new art is integrated in the independent sidecar. Twelve offline tests pass; desktop scene inspected. Graphic entry: `../../mario-agent-town/art/README_CLAUDE.md`. Existing studio runtime and normative architecture remain unchanged; no new live-account integration is claimed.
