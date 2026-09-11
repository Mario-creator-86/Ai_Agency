# Two channels, two production policies — design, 2026-09-11

## Audit: what exists (reused, not rebuilt)

| Capability | Where | Verdict |
|---|---|---|
| Provider connections, encrypted credentials, verification | `integrations/{models,services,vault}.py`, `Integration` | reuse |
| Dynamic ElevenLabs model/voice discovery, research annotations (pricing, capabilities, availability) | `integrations/discovery.py`, `ProviderResource`, `ProviderDiscovery` | reuse |
| Organization-level purpose selection (`voice`, `image`, …) | `ServiceSelection` | reuse as **Organization default** |
| Per-connection production model/voice | `MediaProductionConfig` | reuse as **Organization default**, add override flag |
| Adapter factory from verified selections | `media/factory.py` | extend: build adapters from a *resolved* selection |
| Two channels (MAIN_FACTUAL, OFFICE_SERIAL) + two YouTube connections | `ChannelRecord`, `YouTubeConnection` | reuse; Nexus Curiosity = MAIN_FACTUAL, Inside The Nexus = OFFICE_SERIAL |
| Character Bible (appearance, voice profile, persona, speech, expressions, behaviour, reference slots) | `CharacterBible` | extend with voice binding, locks, status, approved fallbacks |
| Storyboard → scenes with `character_ids_json` | `Storyboard`, `StoryboardScene` | extend with channel/series/overrides |
| Render job + asset provenance (provider *name*) | `assembler.py`, `VideoRenderJob`, `MediaAsset` | extend: record model, voice, retries, timing, estimate |
| Approval workflows (PROPOSED/APPROVED/REJECTED) | `WorkforceProposal`, `DirectorRecommendation`, `decide_episode` | pattern reused for identity changes |
| Cost records, ledger | `ProviderCostRecord.attribution_json` | reuse; estimates from `ProviderResource.pricing` |
| Analytics per publication/channel | `AnalyticsSnapshot` | reuse; production record joins through asset → render job |
| Roles Director, LeadResearcher, FactChecker, ScriptWriter, VoiceArtist, VideoEditor, Publisher | `config/workforce_seed.json` | reuse; no new agents |

Missing: channel production policy, the configuration hierarchy, character identity locks, an
identity-change workflow, per-video/per-scene selection, production records, and the UI that
shows the distinction.

## Design

**Hierarchy** — Organization (ServiceSelection + MediaProductionConfig) → Channel
(`ChannelRecord.production_defaults_json`) → Series (`ChannelRecord.series_rules_json[series_key]`)
→ Episode/Video (`Storyboard.production_overrides_json`) → Scene
(`StoryboardScene.production_overrides_json`) → Character (`CharacterBible.voice_binding_json`
under `identity_locks_json`). Later levels override earlier ones, **except** a locked character
field, which wins over every level and is recorded as `lock_applied`.

**Policies** — `FLEXIBLE`: every level may override, and `{"strategy": "auto"}` at any level asks
`rank_candidates()` to pick from the discovered, available resources by the research
annotations already stored (capabilities, pricing, quality/latency/reliability when present).
`CONSISTENCY_LOCKED`: overrides that touch a locked character field are ignored; technology
(model) may still change only through the character's `approved_fallbacks_json`.

**Identity change** — `CharacterIdentityChange` PROPOSED → TESTING → APPROVED | REJECTED. Only an
APPROVED change rewrites a locked binding (bible version + event). Nothing else can.

**Records** — `VideoRenderJob.production_json`: per purpose and per scene the resolved
integration, model, voice, source level (organization/channel/series/episode/scene/character),
whether a lock applied, retries, timings, and a cost estimate when pricing is known.

**Seeds** — policy defaults come from stored `channel_type` at seed time (OFFICE_SERIAL →
CONSISTENCY_LOCKED, otherwise FLEXIBLE) and are editable through the API. No channel id, model,
voice or price appears in source.

## Non-goals

New agents, a new provider registry, a second discovery, budget tables (none exist), video
generation providers (none are integrated yet; the hierarchy carries the `video`/`image`
purposes so they slot in unchanged).
