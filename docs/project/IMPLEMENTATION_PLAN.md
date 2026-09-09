# Sequential implementation plan

Master authority: [00_MASTER_PROMPT](../architecture/00_MASTER_PROMPT.md).
This plan resolves duplicated roadmap phase labels without deleting or weakening requirements.

| Canonical phase | Original scope | Outcome |
|---|---|---|
| 0 | Core 0 + v3 additions | Runnable backend/UI/DB, config, logging, migrations, tests, CI baseline |
| 1 | Core 1 | Agent/role contracts, policy gates, provider registry, real LLM run |
| 2 | Core 2 | Durable workflow, scheduler/worker, bounded recovery, outbox, replay |
| 3 | Core 3 | Production 2D renderer, dynamic staff/rooms, backend-driven activity |
| 4 | Core 4 | Real research, evidence, independent fact checks, verified script |
| 5 | Core 5 | Provenance-backed media and validated vertical MP4 |
| 6 | Core 6 | Official OAuth, private upload with verified remote ID |
| 7 | Core 7 | Real analytics and constrained experiments |
| 8 | Core 8 | Evidence-driven workforce changes and safe reassignment |
| 9 | Core 9 | Daily log, historical continuity, next-day Office Serial |
| 10 | Core 10 | Full automation hardening and burn-in |
| 11 | Core 11 | Public/fan hooks and sanitized world interfaces |
| 12 | V4 11 | Dynamic organization |
| 13 | V4 12 | Marketing and cross-platform communication |
| 14 | V4 13 | Market intelligence |
| 15 | V4 14 | People/HR/personas |
| 16 | V4 15 | Finance/Legal organizational services |
| 17 | V4 16 | Company calendar/events |
| 18 | V5 11 | External evidence and immutable VR ledger |
| 19 | V5 12 | Finance dashboard and forecasts |
| 20 | V5 13 | Market-backed procurement/VendorShop/Asset Architect |
| 21 | V5 14 | Constrained virtual financing |

Small required contracts can be introduced earlier; this does not mark their parent phase complete.
The Master Prompt's first **product milestone** is phases 0–4: manual topic → real research/sources →
verified claims → script → real agent events → identical office projection. Phase 0 completion alone
does not satisfy that product milestone.

## Phase 0 implementation sequence

1. Read all source documentation, inventory source files and baseline (no pre-existing code/tests).
2. Establish clean source/documentation boundaries and document precedence/conflicts.
3. Build versioned SQLite schema, explicit bootstrap/configuration and structured logging.
4. Build authenticated Owner snapshots and a persisted STOP control as an early governance primitive.
5. Build a truthful UI shell with empty initial room; no invented workers, integrations or balances.
6. Verify migrations, rollback-on-error, concurrency/idempotency, restart and browser interaction.
7. Record reproducible evidence and remaining scope; keep specification integrity checks green.

## Next coding task

Phase 1: define role/capability/permission contracts and provider registry. Add an Ollama adapter using
current official contracts and actual model discovery. Use only configured models; without an available
provider record a real blocker rather than constructing fake runtime results. No public publishing.

## Cross-document conflicts recorded

- Repeated phase 11–14 labels across v3/v4/v5: use canonical mapping above, preserve original labels.
- Repeated FR-037–068 identifiers in SRS: resolved 2026-09-10 — the v3 additional block is now
  numbered FR-V3-037…FR-V3-066 (decision D-DOC-001), so base FR-001–068 identifiers are unique;
  NFR-013–021 were already unique and kept their numbers.
- Provider usage versus no-real-spend rule: V5 permits authorized provider usage; outbound real
  checkout/loan/payment commands remain outside the application. No such integrations exist in Phase 0.
- User requires a clean separation of architecture: source document links updated to their new
  locations; product requirements unchanged. Original and post-move hashes are indexed.

