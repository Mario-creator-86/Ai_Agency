# Production policy — two channels, one technology stack — 2026-09-11

Owner brief: AMN-AI runs two YouTube channels with different creative constraints on the same
provider/model infrastructure. **Nexus Curiosity** (channel type `MAIN_FACTUAL`) is
*flexible*: every video may pick its own TTS model, voice, video model, and so on. **Inside
The Nexus** (`OFFICE_SERIAL`) is a recurring fictional series: its characters must sound and
look the same episode after episode, whatever the technology underneath.

Design record: `../superpowers/specs/2026-09-11-production-policy-design.md`.

## What already existed and was reused

| Reused as-is | Where |
|---|---|
| Provider connections, encrypted credentials, verification | `Integration`, `CredentialVault` |
| ElevenLabs discovery of models/voices, research annotations, refresh leases | `integrations/discovery.py`, `ProviderResource` |
| Purpose selection (`voice`, `image`, …) and per-connection model/voice | `ServiceSelection`, `MediaProductionConfig` |
| Two channel records and two OAuth YouTube connections | `ChannelRecord`, `YouTubeConnection` |
| Character Bible | `CharacterBible` |
| Approval-workflow shape | `WorkforceProposal`, `DirectorRecommendation`, `decide_episode` |
| Roles (Director, Researcher, FactChecker, ScriptWriter, VoiceArtist, VideoEditor, Publisher) | `config/workforce_seed.json` |
| Render, provenance, QC, publishing, analytics, ledger | `media/assembler.py`, `publishing/`, `analytics/`, `economy/` |

No new agents, no second registry, no second discovery, no second production path.

## What changed

**Organization default, not global rule.** `MediaProductionConfig` (the "Production model /
voice" fields) is now the Organization default with `allow_production_override` (True by
default). The Settings card says so: "Model implicit", "Voce implicită", a switch "Permite
suprascrierea de către producție".

**Configuration hierarchy** (`backend/app/media/production_policy.py`):

```
Organization   ServiceSelection(purpose) + MediaProductionConfig
Channel        ChannelRecord.production_defaults_json[purpose]      (+ production_policy)
Series         ChannelRecord.series_rules_json[series_key][purpose]
Episode/Video  Storyboard.production_overrides_json[purpose]        (+ channel_id, series_key)
Scene          StoryboardScene.production_overrides_json[purpose]
Character      CharacterBible.voice_binding_json under identity_locks_json
```

Later levels override earlier ones. `allow_production_override = False` on the Organization
default or on the channel stops the merge there. A selection is `valid` only if it names a
verified connection and discovered, available resources (the same validator discovery uses).

**Policies.** `FLEXIBLE`: every level may override, and `{"strategy": "auto", "criteria":
{...}}` asks `rank_candidates()` to choose from the discovered resources by the research
annotations already stored (`capabilities.quality_score / reliability_score / latency_score`,
`pricing.per_1k_characters_usd`, language match from API metadata). Unannotated resources
score neutrally; with no annotations the order is deterministic, never invented.
`CONSISTENCY_LOCKED`: episode and scene levels may tune settings but may not swap providers or
models (those are decided at channel/series level, where an approval lands), automatic voice
choice is refused, and locked character identities win over everything.

**Character identity locks.** `voice_binding_json` ties a character to a discovered voice
(and optionally a preferred model, settings, language, pronunciation rules).
`identity_locks_json` locks `voice`, `visual`, `personality`, `speech_style`. A locked voice
is what every scene that casts the character uses, regardless of defaults, channel defaults
or per-episode wishes; the plan records `lock_applied` and `source_level: character`.
Technology may still improve: a model reaches a locked character only through
`approved_fallbacks_json` (`POST /media/character-bible/{id}/approved-models`, or the
previous model when a voice change is approved). `consistency_status` is
UNVERIFIED | CONSISTENT | CHANGE_PENDING | DRIFT_SUSPECTED.

**Identity change workflow.** `CharacterIdentityChange`: PROPOSED → TESTING → APPROVED |
REJECTED, with the previous value, rationale, test evidence, who decided and when. Only
APPROVED rewrites the bible (new version + event). Rebinding a locked voice directly returns
409 and points to this workflow.

**Production record.** `VideoRenderJob.production_json` stores the resolved plan and, per
scene, the provider, model, voice, characters synthesised, audio seconds, synthesis time and
attempts. Analytics reaches it through publication → asset → render job.

**Seeds.** `DEFAULT_CHANNELS` carries the seed policy per channel type (FLEXIBLE for
MAIN_FACTUAL, CONSISTENCY_LOCKED for OFFICE_SERIAL); the seed fills only a NULL policy and
never overwrites an Owner's choice. Migration 0021 adds the columns and the workflow table
with neutral defaults; rehearsed on a copy of the live database with connections, secrets,
discovered resources, defaults, YouTube channels and characters unchanged.

## API added

- `PUT /publishing/channels/{id}/production-policy` — policy, channel defaults, series rules, override switch.
- `PUT /settings/integrations/{id}/production` — gains `allow_production_override`.
- `PUT /media/storyboards/{id}/production` — channel, series key, episode and scene overrides.
- `GET /media/storyboards/{id}/production-plan` — the resolved plan before a render.
- `PUT /media/character-bible/{id}/voice-binding`, `PUT …/identity-locks`, `POST …/approved-models`.
- `POST /media/character-bible/{id}/identity-changes`, `GET /media/identity-changes`,
  `POST /media/identity-changes/{id}/decision`.

Renders (`POST /media/render/{id}` and the daily runbook's media stage) use the plan per scene.
A storyboard that never named a channel resolves at the Organization level, exactly as before.

## Acceptance tests (`tests/test_production_policy.py`)

1. Nexus Curiosity: Video A (Voice A, Model A) and Video B (Voice B, Model B) from one
   connection; adapters carry the choices; the connection and the default are untouched.
   Automatic selection follows stored annotations on the flexible channel and is refused on
   the locked one.
2. Inside The Nexus: Sarah bound and locked to Voice ABC keeps it across three episodes despite
   per-episode wishes, and across an Organization default change (test 4); rebinding returns
   409; the render adapters honour the lock; scenes without her follow the hierarchy.
3. A newly discovered model appears in the catalogue and overwrites neither the default nor
   the binding nor an existing plan; it reaches the locked character only after
   `approved-models` and a series-level decision.
4. Default voice change: Nexus Curiosity follows it, the locked character does not; an
   Organization default with override disabled freezes production.
5. Video model evolution: adopted per video on the flexible channel, ignored as an episode
   wish on the locked channel, adopted once set at channel level.
6. ElevenLabs stays VERIFIED and discovery still works; a YouTube connection stays CONNECTED.
7. One inventory (`ProviderResource` count = models + voices), one default row, and the
   policy module uses discovery's own validator.

Identity workflow: PROPOSED → TESTING → APPROVED rewrites the binding, keeps the lock, records
the previous model as approved technology; REJECTED leaves the character as it was; a second
open proposal for the same field is refused.

## Remaining limitations

- No video/music/sfx provider adapter exists yet; the hierarchy resolves those purposes and
  records them, but only `voice` and `image` produce media today.
- Cost estimates use `pricing.per_1k_characters_usd` when research has recorded it; there is
  no budget table, so "daily/monthly budget" checks are not enforced (none existed before).
- Retries are recorded as `attempts: 1`; the assembler does not retry a vendor call.
- The Inside The Nexus serial is still text episodes (`StoryEpisode`); video production of
  the serial, with `character_ids_json` on scenes, is the path this work prepares.
- UI exposes the policy badge, the default/override switch and the character identity line;
  editing bindings, locks and identity changes is API-only for now.
