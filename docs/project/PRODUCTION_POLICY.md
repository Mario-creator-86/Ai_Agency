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

## Runway: connection form and video models — 2026-09-11

Owner brief: the Runway form must ask only for a connection name and an API key; the "Model
ID" field must go. After saving, the key is verified, the account's models and their
capabilities are read into the existing registry, and production chooses among them; any
model choice on the connection is an optional "Default Video Model" (a fallback), which
production may override. Audit first, reuse, extend, no duplicate systems.

**Audit.** Runway was a catalog entry `[KEY, MODEL]` with runtime `stored` ("adapter to be
connected"), no adapter, no probe, no discovery, and a UI branch that hid its "Verify" button.
ElevenLabs already had the whole path the brief asks for: key-only save → `refresh_catalog`
→ `ProviderResource` → `MediaProductionConfig` default with `allow_production_override` →
the hierarchy. The path was ElevenLabs-only by a handful of `kind == "elevenlabs"` branches.

**Reused, now generic.** `DISCOVERED_KINDS` in `integrations/discovery.py` lists the
connections whose inventory is read from the vendor (ElevenLabs, Runway) with their
Owner-facing labels. The save route, the verify route, the periodic refresh, the catalog in
`GET /settings`, `save_production`, `production_resource` and the policy validator all key on
it instead of on one vendor name. One discovery, one inventory, one default row, one
hierarchy. `production_resource` asks `model_usable(kind, resource)`: a TTS model on
ElevenLabs, a video model on Runway.

**Runway adapter** (`providers/runway.py`, a `VideoProvider`). Runway has no model-listing
endpoint; the models an account may call are the keys of `tier.models` in
`GET /v1/organization`, with per-model concurrency and daily limits and today's usage. Which
task each model serves (`text_to_video`, `image_to_video`, …) and the ratios and durations it
accepts come from the vendor's published OpenAPI contract for the same API version
(`docs.dev.runwayml.com/openapi.json`), parsed at refresh time into `api_metadata`
(`tasks`, `ratios`, `durations`). No model name, ratio or duration is written in code. If the
contract cannot be read, the models are still stored, marked as not usable for video until
the next refresh or a research annotation (`capabilities.tasks`) says otherwise; research may
add what the API did not say, never invent availability. `create_generation` posts to the
task endpoint the contract names for the model, with the contract ratio closest to the
requested aspect and a contract duration; `get_generation_status` polls `/v1/tasks/{id}` and
downloads the output. `factory.video_provider_for()` builds the adapter from a valid resolved
`video` selection, carrying the model's contract; `render_plan()` returns `video_for_scene`.

**Form and default.** `CATALOG["runway"]` is `[KEY]`, runtime `media`, purpose `video`.
The Settings card shows the same production section ElevenLabs has (`provider_production.js`,
formerly `elevenlabs_settings.js`): "Model video implicit", no voice picker, the override
switch, options limited to discovered models that make video. A Runway row saved earlier with
a `model` in its config keeps working: `organization_default()` still reads it as the default
until the Owner saves one from the catalog.

**Channels.** Nothing new was needed for Nexus Curiosity: the FLEXIBLE policy already lets an
episode or a scene name any discovered, available video model, and `strategy: auto` ranks
them. For Inside The Nexus the CONSISTENCY_LOCKED rule already keeps model changes at
channel/series level. Added: a character whose `visual` identity is locked is rendered only
by video models in its `approved_fallbacks_json` (the same list a locked voice uses for TTS
models; `POST …/approved-models` accepts any discovered model now). The per-scene plan gains a
`video` entry resolved with the scene's cast, and an unapproved model makes that scene's
video selection invalid with a note naming the characters. Approval after a consistency test
is the evidence that the look is preserved.

Tests: `tests/test_runway_connection.py` (form, discovery, contract, default, adapter) and
two video scenarios in `tests/test_production_policy.py`. The ElevenLabs suites are unchanged
and still pass.

## Remaining limitations

- Runway generates clips (task + poll), but the assembler still builds videos from stills and
  narration; feeding generated clips into the cut is the next step. Music/sfx have no adapter.
- Cost estimates use `pricing.per_1k_characters_usd` when research has recorded it; there is
  no budget table, so "daily/monthly budget" checks are not enforced (none existed before).
- Retries are recorded as `attempts: 1`; the assembler does not retry a vendor call.
- The Inside The Nexus serial is still text episodes (`StoryEpisode`); video production of
  the serial, with `character_ids_json` on scenes, is the path this work prepares.
- UI exposes the policy badge, the default/override switch and the character identity line;
  editing bindings, locks and identity changes is API-only for now.
