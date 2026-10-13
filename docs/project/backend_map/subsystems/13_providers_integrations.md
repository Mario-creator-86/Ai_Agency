# 13 — Providers and integrations (vendor adapters, Settings connections, LLM adapter, vault, discovery, licences)

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (lines): `backend/app/providers/__init__.py` (0), `analytics_base.py` (53), `base.py` (68),
> `comfyui.py` (443), `deterministic_analytics.py` (23), `deterministic_media.py` (316),
> `deterministic_pub.py` (118), `elevenlabs.py` (597), `local_memory.py` (72), `media_base.py` (122),
> `media_http.py` (595), `ollama.py` (233), `openai_media.py` (197), `publishing_base.py` (140),
> `registry.py` (55), `retry.py` (252), `runway.py` (1246), `search.py` (128), `youtube.py` (866),
> `youtube_analytics.py` (417); `backend/app/integrations/__init__.py` (1), `autoconfig.py` (250),
> `catalog.py` (342), `discovery.py` (819), `lifecycle.py` (423), `llm.py` (272), `models.py` (150),
> `plan_licence.py` (145), `probes.py` (84), `router.py` (532), `services.py` (661), `vault.py` (139).
> Total 9,759 lines, 293 functions (inventory). The RunPod package (`backend/app/providers/runpod/`)
> is mapped in its own group and is referenced here only where these files call it.
>
> Mapped 2026-10-12 from commit b00083c plus the working tree. HEAD moved to f4e2bfd during
> mapping; `git diff b00083c HEAD` touches no file in this scope. Verified against the code
> 2026-10-12 at HEAD 3d49e9a (still no change in scope, clean working tree for these files).
> No commit from b00083c to 20abffd touches a file in scope; citations into the media and agents
> files those commits changed (`agents/editorial.py`, `media/assembler.py`) give their 20abffd lines.

## In one paragraph

This part of the backend is the studio's border with the outside world. `app.providers` holds
one adapter per vendor — LLMs (seeded local Ollama), stills (Runway, OpenAI Images, local
ComfyUI), video (Runway, ComfyUI), narration (ElevenLabs), publishing (YouTube Data API v3),
statistics (YouTube Analytics), web search — plus the shared HTTPS plumbing (`media_http`), the
studio-wide retry policy (`retry`), abstract contracts (`base`, `media_base`, `publishing_base`,
`analytics_base`), an in-memory LLM adapter registry and three deterministic offline stand-ins.
`app.integrations` is the Owner's Settings screen behind it: the catalogue of connectable
services and their form fields, validation and encrypted storage of keys (Fernet, key wrapped
with Windows DPAPI), the configured LLM adapter used for every Settings-made LLM connection
(Ollama Cloud, OpenAI, Anthropic, OpenAI-compatible), credential probes, vendor catalogue
discovery (models and voices written to `provider_resource`), the model lifecycle ladder
(DISCOVERED → … → PREFERRED / DEPRECATED) with price provenance, one-click auto-configuration,
the ElevenLabs commercial-licence reader, and the `/api/v1/settings` HTTP routes. Almost
everything here is deterministic code reacting to vendor answers and Owner settings; only one
route calls a language model directly (the Owner's "test this employee" button) and one more
reaches it through `app.media.model_research`.

## Why it exists

- **Providers are replaceable adapters, never assumed capabilities.** ADR-005
  (`docs/project/16_DECISION_LOG.md:735`) and `docs/architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md`
  ("Make providers replaceable and prevent the system from assuming capabilities"; "Do not expose
  a method if underlying provider semantics cannot support it honestly"). The base classes repeat
  that rule (`backend/app/providers/base.py:1-5`, `backend/app/providers/media_base.py:1-5`), and
  every media adapter measures what came back instead of echoing what was asked
  (`backend/app/providers/media_http.py:457-468`, `backend/app/providers/elevenlabs.py:10-14`,
  `backend/app/providers/openai_media.py:3-7`).
- **A retry is a question the studio may ask twice, not a purchase it may make twice.**
  Until 2026-09-17 no adapter retried: one 503 per scene was a failed day
  (`backend/app/providers/retry.py:3-8`). The fix added a second axis — `repeatable` — so a billed
  POST that left and got no answer is never resent (`docs/project/16_DECISION_LOG.md:1844`,
  `backend/app/providers/retry.py:10-16`, spec `docs/architecture/18_AUTOMATION_ORCHESTRATION.md`
  "Retry policy").
- **Keys that cannot be read must not take the page down (REL-06 / TS-03 / SELL-12).** Start-up
  used to decrypt every connection inside the lifespan; one missing key file made the Settings
  page unreachable, so the Owner could not even re-type the keys
  (`backend/app/integrations/services.py:186-192`, `backend/app/integrations/vault.py:1-9`).
- **No fabricated measurements.** The analytics simulator that hashed video ids into 1,500–65,000
  views was deleted, not flagged, because the learning loop would have steered editorial weights
  on invented numbers (D-P7-001, `docs/project/16_DECISION_LOG.md:1306`,
  `backend/app/providers/deterministic_analytics.py:1-19`). The publishing simulator stays only
  for tests, and labels every result `simulated=True` with a `sim:` id
  (`backend/app/providers/deterministic_pub.py:1-8`).
- **Incidents that shaped specific code** (each cited where it lives below): thinking models
  spending the whole Ollama token budget on hidden reasoning — 17 of 18 fact-checks empty
  (`backend/app/integrations/llm.py:7-11`); 391 Ollama Cloud runs with `cost_vr` NULL
  (`backend/app/integrations/llm.py:83-87`); `gen4_image_turbo` chosen as image default although
  it needs reference images, HTTP 400 on every scene of a day (`backend/app/integrations/discovery.py:215-219`);
  a documented 0.08 USD/s overwriting a measured 0.43 USD/s (`backend/app/integrations/lifecycle.py:144-150`);
  Runway refusing a 2K still as an 8.6 MB data URI (`backend/app/providers/runway.py:406-409`);
  a still redo that hung past fifteen minutes (`backend/app/providers/media_http.py:159-164`,
  `backend/app/providers/runway.py:63-67`); Nepal clip bought 4 s for a 4.4 s span
  (`backend/app/providers/runway.py:384-389`); film babcf272 uploaded private because nobody had
  typed «da» for ElevenLabs commercial use (`backend/app/integrations/plan_licence.py:3-13`);
  a refused DNS lookup at 05:00 ending the day through the analytics token refresh
  (`backend/app/providers/youtube_analytics.py:188-192`); an employee failing 492 times with
  only "HTTPError" recorded (`backend/app/providers/ollama.py:12-16`).

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Which Settings LLM connections are live after start | CODE_RULE | `backend/app/integrations/services.py:186-220` | every `integration` row whose catalogue runtime is `llm` and whose keys decrypt is registered as `ConfiguredLLM` with the kind's price table; an unreadable one is skipped and logged |
| The seeded local Ollama endpoint gets an adapter | CODE_RULE | `backend/app/main.py:232-246` | every `ProviderRecord` of type `OLLAMA` without an adapter gets `OllamaProvider(base_url, price_lookup)`; registration asserts nothing about reachability |
| A connection is created / edited | OWNER | `backend/app/integrations/router.py:215`, `backend/app/integrations/services.py:112-183` | versioned save (`expected_version`), kind immutable, empty secret field keeps the stored one |
| A form value is acceptable | CODE_RULE | `backend/app/integrations/services.py:54-109` | only catalogue fields; required present; secret ≤ 8192 chars, other ≤ 500; no CR/LF/NUL; choice in list; port 1-65535; e-mail regex; URL https (http only for localhost/127.0.0.1/::1), no userinfo/query/fragment; IMAP host and port together; RunPod and ComfyUI validated by their own parsers |
| The Owner's RunPod switch and infra answer survive a form save | CODE_RULE | `backend/app/integrations/services.py:153-160` | `allow_infra_actions` and `enabled` copied from the stored config, never from the form |
| An LLM connection is VERIFIED | EXTERNAL | `backend/app/integrations/router.py:276-298` | `sync_provider_models` succeeded (vendor listed models; for Ollama Cloud `/api/me` returned an id, `backend/app/integrations/llm.py:160-169`); `generation_tested: False` is stated in the answer |
| A stored/social/search/`openai_media` connection is ACCESS_VERIFIED | EXTERNAL | `backend/app/integrations/probes.py:26-84`, `backend/app/integrations/router.py:304` | the vendor's identity answer equals the configured account id / model; SMTP (and IMAP) login succeeds; search answer has the configured list shape |
| A discovered-kind connection (RunPod, ComfyUI, ElevenLabs, Runway) is VERIFIED and its catalogue loaded | EXTERNAL | `backend/app/integrations/discovery.py:457-476`, `:495` | `health_check()` HEALTHY then `list_models()` (and `list_voices()` for ElevenLabs) |
| When the catalogue is refreshed | CONFIG + CODE_RULE | `backend/app/integrations/discovery.py:399-423`, `:499-501`; `backend/app/main.py:356-380`; `backend/app/config.py:504-507` | durable 10-minute lease; next refresh after 21,600 s (6 h) on success, 900 s after an error; loop polls every 60 s; manual refresh forces |
| RunPod is left alone by the background refresh | OWNER (switch «RunPod pornit») | `backend/app/integrations/discovery.py:596-622` | only when `RunPodConfig.from_integration(config).enabled`; the Owner's own «Verifică» checks it regardless (`:441-446` forces `enabled: "true"` for that read) |
| Where a newly exposed model starts | CODE_RULE + CONFIG | `backend/app/integrations/discovery.py:549-561`, `backend/app/integrations/lifecycle.py:81-101` | deny-list match → DEPRECATED; no readable `tasks` → QUARANTINE; else DISCOVERED; `STUDIO_AUTO_DISCOVER_MODELS=false` → QUARANTINE; a known model keeps its standing |
| Which purposes a model can serve | EXTERNAL, checked by code | `backend/app/integrations/discovery.py:188-232` | from the vendor's own metadata (`tasks`, `can_do_text_to_speech`, `needs_references`); research `capabilities` may only restrict (or fill Runway `tasks` when the contract was unreadable) |
| A resource is usable for production | CODE_RULE | `backend/app/integrations/discovery.py:255-257`, `:652-682` | `api_available` and `availability_override is not False`, and (MODEL) `usable_purposes` contains the purpose |
| Production default model / voice / image model of a connection | OWNER (the connection's card in Settings, `PUT /integrations/{id}/production`), or CODE_RULE (auto-configure), or LLM_CHECKED_BY_CODE (model research) | `backend/app/integrations/discovery.py:685-756` | connection must be VERIFIED; each id must pass `production_resource` for its purpose; versioned. `production_status` (lifecycle standing) is not checked here, so a QUARANTINE or DEPRECATED model can be a default; the motion router filters standing later (`backend/app/media/production_policy.py:946`, `:1046`) |
| An explicit default on ComfyUI/RunPod admits the model | OWNER + CODE_RULE | `backend/app/integrations/discovery.py:727-741` | a chosen model in DISCOVERED/QUARANTINE becomes CANDIDATE ("not a fabricated quality score"; QC still applies) |
| Which connection serves a purpose (image/video/voice/music/social/email) | OWNER (or CODE_RULE when auto-configure calls it) | `backend/app/integrations/services.py:496-531` | purpose in the fixed list and in the connection's catalogue purposes (or its kind); versioned; the connection's status is not checked here, the media factory ignores a selection whose connection is not VERIFIED/ACCESS_VERIFIED (`backend/app/media/factory.py:202-209`, `:301-303`) |
| Auto-configure picks a service | CODE_RULE | `backend/app/integrations/autoconfig.py:137-169` | only when exactly one VERIFIED/ACCESS_VERIFIED connection declares the purpose and exposes a usable model; ambiguity is reported, never resolved; an existing selection is never touched |
| Auto-configure fills an empty or no-longer-usable default | CODE_RULE (over LLM-written inputs) | `backend/app/integrations/autoconfig.py:96-128`, `:180-243` | top of `rank_candidates` under `STUDIO_PRODUCTION_PRIORITY` (default `premium`), preferring a model whose `tasks` include the purpose's generative task; voice = top-ranked voice (only when the voice is empty). The ranking score is built from the stewards' LLM-written `quality_score` / `reliability_score` / `latency_score` and the stored price (`backend/app/media/production_policy.py:370-378`), so the model research answer weighs on this choice. `allow_production_override` is read only to be preserved (`autoconfig.py:186`, `:231`): an empty or unusable default is filled even when the Owner switched override off. Also runs automatically at the start of every daily run when media readiness is not READY (`backend/app/runbook/services.py:1345-1356`, `:1405`) |
| A model moves up or down the ladder | CODE_RULE + CONFIG | `backend/app/integrations/lifecycle.py:218-292`, `:295-390` | demote to QUARANTINE if judged ≥ min and acceptance < 0.5, or ≥ 3 technical failures and 0 judged; DEPRECATED if cost per accepted second > 3× the cheapest admitted (when `auto_demote_expensive_models`); DISCOVERED → BENCHMARKING only if `auto_benchmark_new_models` (default False); promote one step if acceptance ≥ 0.8 with ≥ min judged (CANDIDATE → PRODUCTION needs ≥ 2×min); min = `min_test_samples_for_promotion` (default 3) |
| A model the Owner refuses is retired | CONFIG (`STUDIO_MODEL_DENY_LIST`) | `backend/app/integrations/lifecycle.py:66-78`, `:348-352` | `fnmatch` shell patterns, case-folded; outranks every result |
| What price is kept when a new one is written | CODE_RULE | `backend/app/integrations/lifecycle.py:132-187` | a DOCUMENTED price never overwrites a BILLED one *for the same unit key* (kept as `documented_<unit>`, returned as a dispute); previous pricing kept; `pricing_version` incremented. The written dict replaces the stored one whole (`:152-153`, `:177`): a BILLED unit the new DOCUMENTED dict does not name, or an empty dict, is dropped (see Oddities) |
| A stored price is stale | CODE_RULE + CONFIG | `backend/app/integrations/lifecycle.py:190-212` (caller `backend/app/media/production_policy.py:507-530`) | observed vs stored drift > `price_stale_tolerance_percent` (default 5 %) |
| Which model an employee thinks with (and its 2nd/3rd slot and strategy) | OWNER (Settings, origin `OWNER`), or CONFIG (the starting allocation file, origin `SEED_ALLOCATION`, `backend/app/agents/ensemble.py:895-905`), or CODE_RULE + EXTERNAL (origin `DIRECTOR_REPAIR`: `switch_model` takes the first ranked candidate whose probe run answers, `backend/app/agents/repairs/agent_health.py:455-528`, `:601-706`) | `backend/app/integrations/services.py:534-661` | origin must be one of the three (`:569`); model exists and available; role's REQUIRED capabilities (`_check_required_capabilities`); agent IDLE/BLOCKED/ERROR and version match; not TERMINATED; tertiary needs secondary; non-SINGLE strategy needs secondary |
| Run one real LLM call to test an employee | OWNER (button) | `backend/app/integrations/router.py:436-460` | see LLM involvement |
| Run the stewards' model research now | OWNER (button) | `backend/app/integrations/router.py:393-399` | see LLM involvement |
| A YouTube channel record is bound to an OAuth connection | OWNER | `backend/app/integrations/router.py:463-494` | connection must be CONNECTED; `remote_channel_id` copied from the connection; event-id concurrency check |
| A connection may be deleted | CODE_RULE | `backend/app/integrations/router.py:497-530` | refused (409) while an agent's primary provider, a service selection or a channel `credentials_ref` names it |
| Whether stored keys are readable and whether that blocks the day | CODE_RULE | `backend/app/integrations/services.py:249-326` | canary round-trip, then each row; `blocking` when an unreadable row is an LLM connection or a selected service, or the key file is broken while rows exist; the preflight reads it (`backend/app/runbook/preflight.py:1256`) |
| Flag NEEDS_RECONNECT and write the Owner one letter per distinct failure | CODE_RULE | `backend/app/integrations/services.py:329-453` | fingerprint `code:ids` deduplicates letters; status restored when keys read again |
| Which YouTube credentials publish | CODE_RULE | `backend/app/integrations/services.py:456-493` | the bound connection id; without one, only when exactly one connection is CONNECTED, else ValueError |
| A voice's commercial licence is recorded | EXTERNAL + CODE_RULE | `backend/app/integrations/plan_licence.py:63-145` | ElevenLabs `GET /v1/user/subscription` tier in `PAID_TIERS`, or a paid tier name followed by `_<suffix>` (e.g. `creator_annual`; any `free*` name never), and status empty/active/trialing → `commercial_use = "da"`; re-read at most hourly while not licensed; never re-read once `da` |
| Whether a failed vendor call is asked again | CODE_RULE + CONFIG | `backend/app/providers/retry.py:136-163`, `:174-252` | 429/502/503/504 and unsent always; other 5xx and silence only if `repeatable`; other 4xx never; attempts 3, cap 30 s (settings 1-10 / 0-600); a Retry-After above the cap is raised at once |
| A billed POST is never resent after silence or a non-safe 5xx | CODE_RULE | `backend/app/providers/media_http.py:313-344`, `backend/app/integrations/llm.py:90-102`, `backend/app/providers/ollama.py:207-215` | `repeatable` defaults to "not POST"; `unanswered` set on any 5xx outside 429/502/503/504 |
| An output URL may be downloaded | CODE_RULE | `backend/app/providers/runway.py:487-512`, `backend/app/providers/media_http.py:114-134` | HTTPS only; IP literal must be global; no single-label or private-suffix name; every resolved address global; socket pinned to the checked address |
| Runway ratio and duration of a purchase | CODE_RULE from EXTERNAL contract | `backend/app/providers/runway.py:265-342`, `:345-403` | read from Runway's published OpenAPI; ratio nearest aspect (largest among equals; `auto_<N>p` max with a first frame); duration rounded UP to the shortest legal one that covers the span |
| Runway purchase refused before any money | CODE_RULE | `backend/app/providers/runway.py:551-560`, `:870-894`, `:992-1013`, `:1173-1181` | no model; task not in contract (only when the contract lists the model's tasks: an unreadable contract does not refuse, `:556-560`); ratio not listed (stills candidates) or ratios unknown (`pick_ratio`, every task); model needs reference images and none given (stills only; video models needing references are kept out by `usable_purposes`); empty prompt |
| Runway price question (dry run) | CODE_RULE | `backend/app/providers/runway.py:633-665`, `:1184-1209` | only when the contract declares `dryRun` for the task; a task id in the answer is cancelled at once |
| Runway purchase that did not finish = open task, not refusal | CODE_RULE | `backend/app/providers/runway.py:801-838`, `:908-956` | poll silence, the 240 s still deadline, the 420 s purchase deadline, or a failed download → `TaskStillOpen(task_id)` (collected later, free); only the vendor's FAILED/CANCELLED is a refusal |
| ElevenLabs optional fields dropped / plain endpoint used | CODE_RULE | `backend/app/providers/elevenlabs.py:431-480` | 400/422 with optional fields → drop them once, remember per adapter; 404/405/422 on timed endpoint → plain endpoint once |
| Narration word timing trusted or dropped | CODE_RULE | `backend/app/providers/elevenlabs.py:165-231`, `:506-531` | alignment shape, finite non-negative monotonic times, end ≤ audio + 0.5 s, words equal to the words sent (NFC); otherwise dropped, audio kept, never a second purchase |
| Local ComfyUI job may start / is interrupted | CODE_RULE | `backend/app/providers/comfyui.py:171-185`, `backend/app/providers/local_memory.py:44-72` | ≥ 8 GiB free RAM and an empty Comfy queue to start; interrupted after 3 consecutive readings under 3 GiB |
| A local workflow may run | CODE_RULE | `backend/app/providers/comfyui.py:102-115` | manifest version 1; workflow inside the manifest folder; SHA-256 equals the manifest's |
| YouTube metadata as sent | CODE_RULE | `backend/app/providers/youtube.py:184-206` | title ≤ 100 chars, no `<`/`>`; description ≤ 5000 UTF-8 bytes with the disclosure block kept whole; tags ≤ 500 budget, deduplicated |
| YouTube upload outcome | EXTERNAL classified by CODE_RULE | `backend/app/providers/youtube.py:419-649` | CONFIRMED (video id), UNKNOWN (bytes may have landed — reconcile first), RETRYABLE (no session/token for a passing reason), FAILED (+`auth_refused` for 400/401/403 at the token endpoint, 401 at session start) |
| A scheduled release is private | CODE_RULE | `backend/app/providers/youtube.py:444-459` | `publish_at` must parse as RFC 3339 and `privacy_status == "private"` |
| Synthetic-media label | CODE_RULE | `backend/app/providers/youtube.py:481-485`, `:706-714` | `containsSyntheticMedia: True` on every insert and every visibility update |
| A video on the channel "is" this publication | CODE_RULE | `backend/app/providers/youtube.py:758-846` | uploads playlist, exact title (`_same_title`), owner channel, published ≥ `created_after` − 2 min; ≤ 4 pages of 50; otherwise `RemoteStateUnavailable` |
| Whose YouTube statistics are read | CODE_RULE | `backend/app/providers/youtube_analytics.py:126-160` | exactly one CONNECTED connection (or the named one), else the environment credentials, else None |
| A refused impressions query is asked smaller | CODE_RULE | `backend/app/providers/youtube_analytics.py:323-335` | only when the query (not the account, not the network) was refused; impressions then reported 0 with `impressions_reported: false` |
| Search results kept | CODE_RULE | `backend/app/providers/search.py:89-115` | addresses and titles only, ≤ 50, URL 10-1000 chars; the allowlist is applied by the caller (`app.research.service.find_pages`) |
| Thinking off on Ollama generation | CODE_RULE | `backend/app/integrations/llm.py:213`, `backend/app/providers/ollama.py:186-198` | `think: False`; `done_reason` and `thinking_chars` returned |

## LLM involvement

### Direct LLM call site in these files

**`create_settings_router.test_agent_llm` — `backend/app/integrations/router.py:436-460`**
(route `POST /api/v1/settings/agents/{agent_id}/test`, Owner bearer token required, `router.py:140`).

| Aspect | Value |
|---|---|
| Speaker | whichever employee the Owner picked (`agent_id` from the path). `run_agent_task` composes that agent's identity as the system prompt (`backend/app/agents/services.py:790-791`) and uses its currently assigned primary model: no `model_id` is passed, so the second and third slots are never tested by this button |
| Gateway | `app.agents.services.run_agent_task` (`backend/app/agents/services.py:733`) |
| Task type / template | `TEST_CONNECTIVITY`, template version `"v1"` (`router.py:448-450`) |
| What it asks | the fixed Romanian sentence «Răspunde într-o singură propoziție scurtă: ești funcțional?» ("answer in one short sentence: are you working?") (`router.py:449`) |
| Generation limits | `max_tokens=2400`, `temperature=0.2` (`router.py:452-453`); for the Director role `run_agent_task` multiplies `max_tokens` by `director_token_multiplier` (default 2, `backend/app/config.py:11`, `:425`, `backend/app/agents/services.py:793-798`) |
| Answer shape | free text, no schema. The route returns the `AgentRunView` dict (status, output_text, tokens, cost_vr, error_detail…) plus `duration_s` (`router.py:459-460`) |
| What the code does with the answer | nothing beyond returning it: **INFORMATIONAL**. Side effects come from the gateway, not from the text: the run is recorded (`agent.run_completed`), a SUCCEEDED run with text emits `agent.message_sent` (speech bubble; `emit_message` defaults to True, `backend/app/agents/services.py:1037-1046`), and `decisions.sources.model_run_finished` withdraws the connection's reconnect card on SUCCEEDED or proposes it on a FAILED run whose HTTP status is one only the Owner fixes, 401/402/403 (`backend/app/decisions/sources.py:64`, `:799-838`; nothing for the seeded Ollama endpoint, which has no `Integration` row) — a code rule on the run status, not on the model's words |
| If the model fails / refuses / returns junk | the gateway records FAILED (provider error, with `http_status`), EMPTY_OUTPUT (no text; explains `done_reason == "length"`), or BLOCKED_* (policy kernel, token ceiling, USD budget, no adapter) and the route returns that record with HTTP 200. `ValueError` (agent not found, model/provider record missing) → 404; `SQLAlchemyError` → 500 (`router.py:455-458`) |
| Can it spend money | yes: one generation on the agent's model (paid tokens on Ollama Cloud / OpenAI / Anthropic / a compatible API). Gated by `run_agent_task`'s daily token ceiling and USD budget (`may_run_agent`, `backend/app/agents/services.py:781`, `:828-830`; a ceiling of 0, the default, means none, `backend/app/economy/accountant.py:1119-1124`; `TEST_CONNECTIVITY` is not budget-exempt, `:1037`); cost from the Owner's price table (`backend/app/integrations/llm.py:229-231`) |

The Director's own probe of a model (`backend/app/agents/repairs/agent_health.py:568-600`) uses
the same task type with `max_tokens=64`, `emit_message=False` and an explicit `model_id`; it is
mapped with the repairs group.

### Functions here that reach the LLM indirectly

**`create_settings_router.post_model_research` — `backend/app/integrations/router.py:393-399`**
(route `POST /api/v1/settings/model-research`, Owner button; inventory hops = 3). It calls
`app.media.model_research.research_all` (`backend/app/media/model_research.py:530-546`), which runs
`research_models` (`:205-513`) for voice, image and video in turn. Each purpose with a selected
discovered-kind connection makes two gateway calls:

| Call site | Speaker | Asks | Answer shape | Checks applied by code |
|---|---|---|---|---|
| `research_models` plan run, `backend/app/media/model_research.py:297-309` | steward: `VideoEditor` (Kael) for video and image, `VoiceArtist` (Lyra) for voice (`:69`); task `research_models`, template `model-research-v1` (`:66-67`); `max_tokens=1500`, `temperature=0.1` | name up to 5 vendor documentation pages to read, given the docs index wrapped as inert text (`:109-117`, `:294-296`) | `UrlPlan{urls: list[str] ≤ 6}` (`:80-82`; a longer list is truncated before validation, `backend/app/agents/identity.py:568-576`) | only `https://` URLs whose host is one of the vendor's own hosts (`vendor_hosts`, `:172-182`) are fetched, at most 5 (`:313-323`); the studio's retriever fetches them, never the model |
| `research_models` judge run, `backend/app/media/model_research.py:337-352` | same steward; `max_tokens=6000`, `temperature=0.1` | score every account model 0..1 for quality, reliability, speed, give a price with unit and evidence URL, recommend one (`:120-142`) | `ModelResearch{models: [ModelNote{remote_id, quality_score, reliability_score, latency_score, price_usd, price_unit, notes, evidence_url}], recommendation{remote_id, reason}}` (`:85-106`) | the schema *rejects* (does not clamp) a score outside 0..1 or a negative price: one such value voids the whole answer, because `fit_to_schema` only cuts long strings and truncates long lists (`backend/app/agents/identity.py:568-576`), so the purpose ends SKIPPED; scores inside 0..1 are taken as given (no check of their content); notes only for models in the account's ranked candidates (`:375-377`); prices written as DOCUMENTED through `update_resource_metadata` → `stamp_price`, which keeps a BILLED price only for a unit key the new reading also names (`backend/app/integrations/lifecycle.py:155-163`); a note with `price_usd: null` is written as an empty pricing dict, which erases the stored price, BILLED included (`:380-392`, `lifecycle.py:152-153`, `:177`; see Oddities); `capabilities` is replaced whole by the three scores, notes and `judged_by` (`:393-399`, `backend/app/integrations/discovery.py:782-790`); the recommendation is used only if it is a known candidate, else the top of `rank_candidates` (`:427-431`), and only if `production_resource` accepts it for the purpose (`:432-436`) and `allow_production_override` is on (`:438`; True when the connection has no production row yet, `:268`) |

Trust: **CHECKED_BY_CODE**. If the plan answer is junk, only the index page is read; if the judge
answer does not parse, `ModelResearchError` is raised and `research_all` reports that purpose as
SKIPPED (`:354-359`, `:544-545`). Within the code's limits the model's judgement is acted on: it
picks which known, usable candidate becomes the default (the code does not compare it with the
ranking or with price), and its `quality_score`, `reliability_score` and `latency_score` are the
main terms of the `rank_candidates` score (`backend/app/media/production_policy.py:320-378`, the
score at `:370-378`), which orders `strategy: auto`, the auto-configure defaults (`_top_resource`) and the
research fallback itself. Money: the six runs spend tokens (gated as above); indirectly the
recommendation can change which model later paid generations use, and DOCUMENTED prices and the
scores feed `rank_candidates`, i.e. the `strategy: auto` order. Price moves past `price_change_alert_percent` (default 10 %) become an Accountant letter
(`:404-415`). The same `research_all` is also run by the weekly worker job
`model_research_weekly` (`backend/app/workflows/worker.py:91`, `:412-417`).

### LLM transport (not call sites)

`ConfiguredLLM.generate` (`backend/app/integrations/llm.py:201-272`) and
`OllamaProvider.generate` (`backend/app/providers/ollama.py:176-233`) are the adapters that
`run_agent_task` calls as `adapter.generate(...)` (`backend/app/agents/services.py:928-936`; the
only `.generate(` call in `backend/app`). Every real language-model call in the studio therefore
leaves through one of these two classes; the one other registered adapter is the sales demo's
deterministic `app.demo.DemoModel` (`backend/app/demo.py:185`, `:204`, `:395-412`), which replaces
every provider's adapter in a demo registry and calls no model.
They decide nothing about content: they shape the request per vendor, ask for thinking off on
Ollama, bound response size, classify errors for the retry policy, and cost the call from the
Owner's per-million-token prices (None, never zero, without a price). Vision calls put their
pictures in `extra={"images": [...]}` (e.g. `backend/app/agents/editorial.py:500`,
`backend/app/media/picture_qc.py:1177`, and since 20abffd the Director's second look at a refused
picture, `backend/app/media/second_look.py:732`); both adapters forward `extra` only to Ollama
(`backend/app/integrations/llm.py:222-223`, `backend/app/providers/ollama.py:205-206`), so on an
OpenAI, Anthropic or compatible connection the pictures are not sent (see Oddities).

### How much of this part is LLM

Of 293 functions, 1 is an LLM call site (`test_agent_llm`) and 1 reaches the LLM through another
module (`post_model_research`); both are Owner-triggered routes. The model lifecycle, discovery,
auto-configure, vault, licence reading, retry, publishing and every media adapter are
deterministic code applying fixed rules to vendor answers and Owner settings. One indirect
dependency on the model remains: `rank_candidates`, which auto-configure uses to fill defaults,
scores models mainly on the `quality_score` / `reliability_score` / `latency_score` the stewards'
model research wrote (`backend/app/media/production_policy.py:370-378`); without research every
model scores a neutral 0.5 and the order falls back to price and remote id. The lifecycle's
"acceptance" is computed from `model_outcome` rows, whose only writer sets `accepted` to whether
the clip's bytes arrived (`backend/app/media/assembler.py:1413-1484`, `:1449`, `:1480`), not to an LLM verdict.

## Hard rules and limits

| Constant / rule | Value | Where |
|---|---|---|
| Retry attempts / backoff cap / base | 3 / 30 s / 1 s; settings `provider_retry_attempts` 1-10, `provider_retry_max_seconds` 0-600 | `backend/app/providers/retry.py:38-40`, `:71-89`; `backend/app/config.py:487-488` |
| Statuses always safe to resend | 429, 502, 503, 504 (from Runway's error page, applied to all vendors) | `backend/app/providers/retry.py:42-48` |
| Backoff shape | wait doubles from base, capped; jitter in the upper half of the window; Retry-After replaces it when ≤ cap, raised at once when > cap | `backend/app/providers/retry.py:217-251` |
| Media / JSON response caps | 96 MiB / 4 MiB | `backend/app/providers/media_http.py:91-92` |
| Default socket timeout; overall deadline guard | 120 s per socket op; `total_seconds` enforced by a timer that shuts the socket | `backend/app/providers/media_http.py:144`, `:166-215`, `:288-310` |
| Vendor text kept | ≤ 500 chars, ≤ 10 issues; data URIs, bearer/basic values, URLs, key-shaped tokens and 32+ char opaque runs redacted | `backend/app/providers/media_http.py:379-404`, `:413-447` |
| PNG/JPEG plausible size | 1..8192 px each side | `backend/app/providers/media_http.py:466`, `:487` |
| MP3 frame walk cap | 200,000 frames, MPEG-1 Layer III only | `backend/app/providers/media_http.py:543-553` |
| Configured LLM timeouts / response cap | 600 s per generation; 20 s for `/api/me`; 4,000,000 bytes | `backend/app/integrations/llm.py:28`, `:111-115`, `:140-144` |
| Anthropic defaults | `anthropic-version: 2023-06-01`; `max_tokens` 1024 when none given | `backend/app/integrations/llm.py:117-118`, `:240` |
| Seeded Ollama defaults | `http://127.0.0.1:11434`; GET 10 s (health 5 s); POST 600 s; refusal body read ≤ 16,384 bytes | `backend/app/providers/ollama.py:40`, `:82`, `:113`, `:118`, `:132` |
| Runway API version and hosts | `2024-11-06`; `api.dev.runwayml.com`; contract `docs.dev.runwayml.com/openapi.json` | `backend/app/providers/runway.py:49-52` |
| Runway deadlines | still poll 240 s every 3 s; still purchase 420 s; read 30 s; submit 90 s; poll 45 s; still download 120 s; clip download 600 s | `backend/app/providers/runway.py:61-75` |
| Runway prompt cap default | 1000 UTF-16 units when the contract states none; cut at a sentence, then a word | `backend/app/providers/runway.py:111`, `:138-172` |
| Runway duration tolerance | 0.001 s; rounded up, clamped to contract bounds | `backend/app/providers/runway.py:114`, `:384-403` |
| Runway inline picture size | sent as is under 4,500,000 data-URI chars; else JPEG at qualities 92→80, scaled 80 % per step, until under 3,500,000 | `backend/app/providers/runway.py:410-461` |
| Runway task states | PENDING/THROTTLED→PENDING, RUNNING→PROCESSING, SUCCEEDED→COMPLETED, FAILED/CANCELLED→FAILED; unknown → error | `backend/app/providers/runway.py:100-107`, `:1213-1216` |
| ElevenLabs output and deadline | `mp3_44100_128`; 180 s per narration request | `backend/app/providers/elevenlabs.py:58`, `:64` |
| ElevenLabs refusal sets | contract 404/405/422; field 400/422 | `backend/app/providers/elevenlabs.py:67`, `:70` |
| ElevenLabs voice defaults and keys | stability 0.5, similarity_boost 0.75; only stability, similarity_boost, style, use_speaker_boost sent | `backend/app/providers/elevenlabs.py:73-75`, `:266-279` |
| ElevenLabs stitching | ≤ 3 request ids, ≤ 3 dictionary locators, ≤ 400 chars context each side | `backend/app/providers/elevenlabs.py:89-93` |
| ElevenLabs alignment slack | 0.5 s past the measured audio | `backend/app/providers/elevenlabs.py:153` |
| ElevenLabs voice discovery | page size 100, 120 s, ≤ 1000 pages, repeated page token refused | `backend/app/providers/elevenlabs.py:344-377` |
| OpenAI Images | default model `gpt-image-1`; 1024x1536 portrait, 1024x1024 otherwise; prompt ≤ 4000 chars; inline b64 only | `backend/app/providers/openai_media.py:27-33`, `:144-171` |
| ComfyUI | localhost only, default port 8188; 60 s per request; poll 2 s; job timeout 21,600 s (manifest may change both); 1-4 stills per call; 9:16 or 16:9 only (±0.01) | `backend/app/providers/comfyui.py:32-45`, `:61-64`, `:76`, `:127-128`, `:355` |
| Local RAM guard | start ≥ 8 GiB free; interrupt after 3 consecutive readings < 3 GiB; checks every 0.5 s, history every 5 s | `backend/app/providers/local_memory.py:14-15`, `:44-72` |
| Search | probe word `encyclopedia`; ≤ 50 results; URL 10-1000 chars; query ≤ 200 chars; 20 s | `backend/app/providers/search.py:36-40`, `:89-115` |
| YouTube limits | title 100 chars; description 5000 bytes; tags 500 budget; category 28 default; chunk 8 MiB | `backend/app/providers/youtube.py:52-65` |
| YouTube auth / quota words | token-endpoint 400/401/403 = account refused; quotaExceeded, rateLimitExceeded, userRateLimitExceeded, uploadLimitExceeded = a moment | `backend/app/providers/youtube.py:211-218` |
| YouTube reconcile | clock skew 2 min; ≤ 4 pages × 50 | `backend/app/providers/youtube.py:222-225` |
| YouTube timeouts | token 15 s; health 10 s; session 30 s; chunk 300 s; status 10 s; update/playlist 15 s | `backend/app/providers/youtube.py:379`, `:403`, `:519`, `:573`, `:666`, `:727`, `:808` |
| YouTube Analytics | report ≤ 4,000,000 bytes; token 15 s, report 20 s; windows 1h/24h → 1 day, 7d, 28d, LIFETIME from 2005-01-01 | `backend/app/providers/youtube_analytics.py:194`, `:231-245`, `:253-259` |
| Probes | 8 s timeout, ≤ 1,000,000 bytes | `backend/app/integrations/probes.py:11-23` |
| Catalogue refresh | 21,600 s success / 900 s error / 60 s poll; settings bounds 60-604,800 / 30-86,400 / 5-3,600; lease 10 min | `backend/app/config.py:504-507`; `backend/app/integrations/discovery.py:415` |
| Lifecycle thresholds | demote acceptance < 0.5; ≥ 3 technical with 0 judged; > 3× cheapest admitted cost; promote ≥ 0.8; CANDIDATE→PRODUCTION at 2× min; min judged default 3 (1-100) | `backend/app/integrations/lifecycle.py:235-292`; `backend/app/config.py:372` |
| Lifecycle switches | `auto_discover_models` True; `auto_benchmark_new_models` False; `max_benchmark_budget_usd` 1.50 (named in a note only); `auto_promote_cheaper_better_models` True; `auto_demote_expensive_models` True | `backend/app/config.py:356-368` |
| Price alert / stale tolerance | 10 % / 5 % | `backend/app/config.py:446-447` |
| Licence | paid tiers starter, creator, pro, scale, business, growing_business, enterprise (+ `_suffix`); active/trialing; re-read hourly | `backend/app/integrations/plan_licence.py:31-39`, `:47-54` |
| Vault codes | MISSING, UNREADABLE, CORRUPT, FOREIGN | `backend/app/integrations/vault.py:18-25` |
| Health probe cache | vault health re-read at most every 30 s | `backend/app/main.py:129`, `:795-803` |
| Selectable purposes | image, video, voice, music, tiktok, instagram, facebook, email | `backend/app/integrations/services.py:503-513` |
| Documented seed prices | ElevenLabs `*` 0.22 USD / 1k chars; `eleven_flash_*`, `eleven_turbo_*` 0.11 | `backend/app/integrations/catalog.py:311-342` |

## Modules

### `app.providers.base` — backend/app/providers/base.py (68 lines)

The abstract LLM adapter and its result types. `ModelInfo.capabilities` is "the provider's own
words, never a guess" (`:21-24`); `HealthResult` statuses follow the spec's common provider state
(`:38`). No logic.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `LLMProvider.health_check` | 50 | abstract: endpoint health | contract (`22_PROVIDER_INTEGRATION_CONTRACTS.md` "LLM adapter") | — |
| `LLMProvider.list_models` | 54 | abstract: available models | same | — |
| `LLMProvider.generate` | 58 | abstract: one text generation, real output only | same | — |

### `app.providers.registry` — backend/app/providers/registry.py (55 lines)

In-memory map provider id → LLM adapter, with a health cache. The application creates its own
instance at start (`backend/app/main.py:694-695`); the module-level singleton `get_registry` is
referenced only by tests (`tests/test_phase4_factual.py`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `ProviderRegistry.register` / `unregister` / `get` | 13 / 17 / 21 | add, remove, look up an adapter; clears its cached health | Settings saves and deletes swap adapters live (`backend/app/integrations/router.py:257`, `:529`) | CODE_RULE |
| `ProviderRegistry.registered_ids` | 24 | sorted ids | "whether any model exists" | — |
| `ProviderRegistry.check_health` | 28 | calls the adapter's health check, caches it; NOT_CONFIGURED when none | provider status | EXTERNAL |
| `ProviderRegistry.cached_status` / `refresh_all` | 37 / 41 | last cached status / check all | — | — |
| `get_registry` | 51 | lazy module singleton | test helper | — |

### `app.providers.retry` — backend/app/providers/retry.py (252 lines)

The studio-wide retry policy used by every adapter in this group (and by RunPod code). Why:
see "Why it exists"; the module docstring (`:1-22`) is the rationale. Nothing here logs error
text, only numbers and class names (`:21`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `_settings` | 57 | cached `Settings()` or None | adapters have no app handle | CONFIG |
| `retry_defaults` | 71 | (attempts, max_seconds) from settings, else 3 and 30 | Owner-tunable policy | CONFIG |
| `parse_retry_after` | 96 | integer seconds or HTTP date → seconds; unreadable → None | honour vendor waits | CODE_RULE |
| `retry_after_seconds` | 127 | the wait carried by an exception | same | — |
| `is_transient` | 136 | the two-axis classification (status / unsent / unanswered / repeatable) | never pay twice for one silence (`16_DECISION_LOG.md:1844`) | CODE_RULE |
| `call_with_retries` | 174 | the loop: backoff with jitter, Retry-After handling, annotates the final error "(after N attempts)" | bounded retries per `18_AUTOMATION_ORCHESTRATION.md` | CODE_RULE |

Helpers: `_now_timestamp`, `_status_of`, `_annotate`. Module attribute `sleep` (`:53`) lets tests
make every retry instant. Data: none. External calls: none itself.

### `app.providers.media_http` — backend/app/providers/media_http.py (595 lines)

Shared HTTPS plumbing for media vendors (Runway, ElevenLabs, OpenAI, search, RunPod, also
`app.office.weather`). "A request that fails raises … nothing invents a plausible substitute"
(`:3-7`). Defines `MediaProviderError` (vendor slug `code`, `http_status`, sanitised `detail`,
`issues`, `retry_after`, `unsent`, `unanswered`), `MediaProviderNotConfigured`, and
`TaskStillOpen` (a paid task accepted but not collected — collected later by id, never re-bought,
`:71-82`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `MediaProviderError.__init__` | 36 | message plus vendor slug `code`, `http_status`, sanitised `detail`, ≤ 10 `issues`, `retry_after`, and the two phase flags `unsent` (never left: always safe to resend) / `unanswered` (left, no answer: never resent when billed) | the retry policy and the Owner's messages read these fields instead of vendor text (`:51-53`: Runway's 400 names the refused field) | — |
| `TaskStillOpen.__init__` | 80 | adds `task_id` to the error | a paid task collected later by id, never re-bought (`:71-78`) | — |
| `PinnedHTTPSConnection.connect` | 105 | opens the socket to a pre-checked IP, TLS still verifies the host | DNS-rebinding protection for vendor-named output hosts | CODE_RULE |
| `public_address` | 114 | resolves a host; every address must be global, else `unsent` error | same rule as the research retriever | CODE_RULE |
| `request` | 137 | one HTTPS request: host from the adapter, size caps, optional pinned public-only host, optional overall deadline, optional explicit connect, allowed statuses; error status → `MediaProviderError` with vendor code, sanitised detail, Retry-After, `unanswered` for non-safe 5xx | single honest transport; 2026-10-03 hang (`:159-164`) | CODE_RULE |
| `_read_until` | 251 | reads the body in 64 KiB pieces until end, cap or deadline | a trickling vendor cannot hold the caller | CODE_RULE |
| `_past_deadline` | 279 | the "unanswered" error at the deadline | possibly billed, never resent | CODE_RULE |
| `_DeadlineGuard` (`__init__` 292, `_fire` 301, `cancel` 309) | — | timer that shuts the socket at the deadline | same | — |
| `possibly_served` | 313 | 5xx not in the safe list | possibly charged | CODE_RULE |
| `retrying` | 319 | `call_with_retries` around a transport; `repeatable` defaults to "not POST" | "a POST to these vendors is a purchase" (`:334-336`) | CODE_RULE |
| `error_code` | 350 | the vendor's slug from known error shapes | Owner-facing code (e.g. `missing_permissions`) | — |
| `sanitise_vendor_text` | 396 | redact secrets, one line, cap | vendor text can echo keys, pictures, signed URLs | CODE_RULE |
| `error_details` | 413 | (sanitised reason, per-field issues) | Runway's 400 names the refused field (`:51-53`) | — |
| `host_of` | 450 | hostname of an https base URL | — (no caller in `backend/app` or `tests`) | — |
| `png_dimensions` / `jpeg_dimensions` / `image_dimensions` | 457 / 471 / 494 | measure the returned picture | never record the requested size as delivered | CODE_RULE |
| `mp3_duration_seconds` | 505 | count MPEG-1 Layer III frames | a narration's length is measured, not estimated | CODE_RULE |
| `wav_duration_seconds` | 574 | duration from RIFF header | same (used by tests only) | — |

Helpers: `_issue_path`. Data read/written: none. External calls: whatever host the adapter names.

### `app.providers.media_base` — backend/app/providers/media_base.py (122 lines)

Abstract `ImageProvider`, `TTSProvider`, `VideoProvider` and their result dataclasses
(`ImageResult`, `TTSResult` with `word_timings`, `VideoGenerationResult` with states
PENDING/PROCESSING/COMPLETED/FAILED). Implements `22_PROVIDER_INTEGRATION_CONTRACTS.md`
"Video/Image/TTS adapter". No logic; every function is abstract.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `ImageProvider.health_check` | 56 | abstract: provider health | spec "Image adapter" | — |
| `ImageProvider.generate_image` | 60 | abstract: one still from a prompt (width, height, style, seed, extra) | same | — |
| `TTSProvider.health_check` | 79 | abstract: provider health | spec "TTS adapter" | — |
| `TTSProvider.list_voices` | 83 | abstract: available voices | same ("list_voices if supported") | — |
| `TTSProvider.synthesize` | 87 | abstract: narration audio with measured duration and word timings | same | — |
| `VideoProvider.health_check` | 105 | abstract: provider health | spec "Video adapter" | — |
| `VideoProvider.create_generation` | 109 | abstract: submit a clip job, return the remote job id | same ("Store remote job ID") | — |
| `VideoProvider.get_generation_status` | 121 | abstract: poll a job | same | — |

### `app.providers.runway` — backend/app/providers/runway.py (1246 lines)

Runway stills and video. No model name, ratio or duration is written in the file: the account's
models come from `GET /v1/organization` (`tier.models`), and what each model accepts comes from
Runway's published OpenAPI contract (`:11-16`). Spends money (Runway credits) on every
`POST /v1/{task}` without `dryRun`.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `estimated_credits` | 119 | credits from `estimatedCost` (`{"credits": n}` or a number); else None, never 0 | "a price nobody stated is not free"; Nepal books showed 0.74 USD for two films (`:620-624`) | CODE_RULE |
| `fit_prompt` | 138 | one line within the UTF-16 cap, cut at a sentence, else a word | a mid-word fragment is read as an instruction | CODE_RULE |
| `parse_model_contract` | 265 | per model: tasks, ratios, durations (list or min/max), `needs_references`, `dry_run`, declared `fields`, `prompt_max` | model capabilities from the vendor's own contract | EXTERNAL → CODE_RULE |
| `_bounds` | 221 | `{"min", "max"}` of a numeric schema, looking inside its oneOf/anyOf alternatives | a model whose contract gives durations as a range rather than a list (read by `parse_model_contract`, used by `pick_duration`) | EXTERNAL → CODE_RULE |
| `pick_ratio` | 345 | nearest-aspect ratio, largest among equals; `auto_<N>p` max when following a first frame | Runway refuses explicit ratios for keyframe image-to-video (2026-10-03, `:350-353`) | CODE_RULE |
| `pick_duration` | 384 | shortest legal duration covering the span, rounded up | a short clip freezes under the dissolve (Nepal, `:387-388`) | CODE_RULE |
| `fit_request_image` | 432 | keep a picture under the 5 MB data-URI limit, re-encoding to JPEG and scaling | 8.6 MB reference refused (`:406-409`) | CODE_RULE |
| `_reference_image` | 469 | reference must be bytes, never a name | Runway would 400 the whole task (`:472-474`) | CODE_RULE |
| `_vet_output_host` | 487 | refuse private/single-label output hosts before any socket | an answer could point inside the Owner's network | CODE_RULE |
| `_RunwayClient.__init__` | 521 | key required (`MediaProviderNotConfigured`), model, contract metadata | — | — |
| `_RunwayClient._require_task` | 551 | refuse when no model chosen or task not in contract | before any purchase | CODE_RULE |
| `_RunwayClient.organization` / `credit_balance` | 581 / 596 | free read of the org; balance None when unstated | asked before every paid step and shot by callers | EXTERNAL |
| `_RunwayClient._submit` | 606 | the paid POST; records `last_estimated_credits` and `last_task_id` | the vendor's own price kept for the books | — (money) |
| `_RunwayClient._quote` | 633 | dry-run price only when the contract declares it; cancels any created task | "a question about a price must never become a purchase" | CODE_RULE |
| `_RunwayClient._cancel` | 667 | DELETE task, failure swallowed | — | — |
| `_RunwayClient._task` | 684 | GET task; may update the last task's price | — | EXTERNAL |
| `_RunwayClient.collect_task` | 706 | free GET of an earlier task; downloads outputs on success | collect an open purchase without buying again | EXTERNAL |
| `_RunwayClient._download` | 740 | vetted, public-only, pinned GET of an output | — | CODE_RULE |
| `RunwayImageAdapter.health_check` | 783 | GET organization | — | EXTERNAL |
| `RunwayImageAdapter._image_outputs` | 801 | poll until SUCCEEDED; FAILED/CANCELLED → error; silence/deadline → `TaskStillOpen` | a paid task is never thrown away | CODE_RULE |
| `RunwayImageAdapter.generate_candidates` | 840 | `count` stills at exactly `ratio` in one purchase (`outputCount` when declared), references as data URIs, `on_submitted(task_id)` before any poll, sums credits | the stills step buys two 2K candidates and keeps the better one | CODE_RULE (money) |
| `RunwayImageAdapter.generate_image` | 982 | one still, nearest ratio, optional single reference | — | CODE_RULE (money) |
| `RunwayVideoAdapter.health_check` | 1054 | GET organization, returns `creditBalance` | — | EXTERNAL |
| `RunwayVideoAdapter.model_contract` | 1067 | fetch and parse the OpenAPI document | — | EXTERNAL |
| `RunwayVideoAdapter.list_models` | 1080 | org models with limits/usage merged with contract; sets `capabilities_warning` if contract unreadable | catalogue discovery | EXTERNAL |
| `RunwayVideoAdapter._video_body` | 1116 | body from the contract; `audio` false where declared, `negativePrompt` and `seed` only where declared | "an undeclared field is a refusal at best" (`:333-335`); generated soundtrack would be paid and thrown away (`:1129-1130`) | CODE_RULE |
| `RunwayVideoAdapter.create_generation` | 1164 | `image_to_video` with a first frame, else `text_to_video`; submit | — | CODE_RULE (money) |
| `RunwayVideoAdapter.estimate_generation` | 1184 | the exact shot's dry-run quote or None | per-shot price, not a per-second guess | CODE_RULE |
| `RunwayVideoAdapter.get_generation_status` | 1211 | poll; downloads on COMPLETED; duration left None (the assembler probes the file) | — | EXTERNAL |

Helpers: `_utf16_units`, `_deref`, `_branches`, `_values`, `_max_length`, `_image_mime`,
`_uri_chars`, `_image_data_uri`, `_RunwayClient._headers`, `_ratio_for`, `_fields`, `_prompt_max`,
`_durations`. Class flags: `ACCEPTS_REFERENCE_IMAGE = True`, `REFERENCE_IMAGE_VERIFIED = False`
(`:780-781`; read by `backend/app/media/shooting_sheet.py:1785-1787`). Data: none directly.
External: `api.dev.runwayml.com`, `docs.dev.runwayml.com`, vendor output hosts.

### `app.providers.elevenlabs` — backend/app/providers/elevenlabs.py (597 lines)

ElevenLabs narration with its own character clock. Spends money (characters) on every
text-to-speech POST. Rationale in the module docstring (`:1-26`): duration is measured from the
MP3 frames; a timing that does not fit is dropped, the audio is kept, nothing is bought twice.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `wants_text_normalisation` | 100 | true for model names containing `flash`/`turbo` | Flash v2.5 reads "$1,000,000" wrongly (`:94-97`) | CODE_RULE |
| `checked_locators` | 133 | keep ≤ 3 well-formed pronunciation dictionary locators | vendor shape only | CODE_RULE |
| `checked_alignment` | 165 | validate the vendor's character alignment | a bad clock would mistime captions | CODE_RULE |
| `words_of` | 202 | characters → words with start/end | caption timing | — |
| `word_timings_for` | 222 | timings only if the words equal the words sent (NFC) | Romanian diacritics may arrive decomposed | CODE_RULE |
| `ElevenLabsTTSAdapter.__init__` | 241 | key required; voice, model, price lookup; `refused_fields` memory | — | — |
| `ElevenLabsTTSAdapter.request_settings` | 266 | voice settings, normalisation, dictionaries, minus refused fields | part of a narration's identity (`assembler.narration_key`) | CODE_RULE |
| `ElevenLabsTTSAdapter.health_check` | 284 | GET `/v1/user` | reachability reported, never assumed | EXTERNAL |
| `ElevenLabsTTSAdapter.subscription` | 307 | GET `/v1/user/subscription` | plan usage (books) and licence tier (`plan_licence`) | EXTERNAL |
| `ElevenLabsTTSAdapter.list_models` / `list_voices` | 322 / 344 | catalogue; voices paginated with safety limits | discovery | EXTERNAL |
| `ElevenLabsTTSAdapter.synthesize` | 379 | requires text, voice and model; timed endpoint; on 400/422 drop optional fields once; on 404/405/422 the plain endpoint once; measures duration; keeps or drops alignment; cost from price table | the narration purchase | CODE_RULE (money) |
| `ElevenLabsTTSAdapter._post_timed` | 556 | one non-repeatable POST under the retry policy, 180 s overall | — | CODE_RULE |
| `ElevenLabsTTSAdapter._timed_answer` | 572 | audio + alignments from the JSON (or bare audio kept) | billed audio is kept even without a clock | CODE_RULE |

Helpers: `_context_text`, `_request_ids`, `_headers`, `_resources`. Cost: `tts_cost_vr(price_lookup,
model, len(narration))` — None without a price (`:543`). External: `api.elevenlabs.io`.

### `app.providers.openai_media` — backend/app/providers/openai_media.py (197 lines)

OpenAI Images: words → `/v1/images/generations`; with a reference picture → `/v1/images/edits`
(multipart). Spends money on every POST. Seed is never reported (the API takes none, `:183-185`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `_multipart` | 43 | multipart body with a random boundary, no dependency | — | — |
| `_reference_bytes` | 75 | reference must be bytes; mime defaults to image/png | a name would be posted as text and the Owner misled (`:78-81`) | CODE_RULE |
| `OpenAIImageAdapter.__init__` | 107 | key required; model default `gpt-image-1` | — | CONFIG |
| `OpenAIImageAdapter.health_check` | 116 | GET `/v1/models/{model}` id must equal | — | EXTERNAL |
| `OpenAIImageAdapter.generate_image` | 127 | chooses endpoint and size, posts, requires inline b64 PNG, measures it | never follow a vendor URL (`:169-171`) | CODE_RULE (money) |

Flags: `ACCEPTS_REFERENCE_IMAGE = True`, `REFERENCE_IMAGE_VERIFIED = False` (`:104-105`).

### `app.providers.comfyui` — backend/app/providers/comfyui.py (443 lines)

Local stills and image-to-video through a ComfyUI server on this PC, from SHA-256-pinned
workflow graphs in `config/local_media.json` (`:28`). "No cloud fallback and no implicit model
downloads" (`:1`). API cost zero (`billing_mode = "local"`, `cost_vr="0"`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `local_url` | 32 | only `http://` on `localhost`, `127.0.0.1` or `::1` (port optional, default 8188), no path/token | pictures and prompts stay on this computer | CODE_RULE |
| `_local_landscape` | 48 | 9:16 → False, 16:9 → True, else None, by aspect | "1530:2720" was refused by string matching (LOCAL_FORMAT 2026-10-05) | CODE_RULE |
| `_request` | 68 | one local HTTP call, no redirects; 4xx → `unsent`, connection failure on POST → `unanswered` | — | CODE_RULE |
| `load_manifest` | 102 | manifest v1; each workflow inside its folder and matching its SHA-256 | a modified workflow is refused | CODE_RULE |
| `ComfyConnection.__init__` | 123 | URL, manifest, model, poll and timeout from the manifest | — | CONFIG |
| `ComfyConnection.profile` | 134 | the manifest entry for the model, else error | — | — |
| `ComfyConnection.health_check` | 140 | GET `/system_stats` | — | EXTERNAL |
| `ComfyConnection.list_models` | 144 | profiles whose node classes and enum inputs the server offers; adds tasks/ratios/durations | catalogue discovery | EXTERNAL |
| `ComfyConnection._submit` | 171 | RAM ≥ 8 GiB and empty queue; client-chosen `prompt_id` so an ambiguous answer can be recovered; starts the RAM watch | never run the same GPU job twice; protect the Owner's PC | CODE_RULE |
| `ComfyConnection.collect_task` | 221 | history → RUNNING / FAILED / SUCCEEDED with images and videos | — | EXTERNAL |
| `ComfyConnection._wait` | 291 | poll until done or timeout → `TaskStillOpen` | — | CODE_RULE |
| `ComfyImageAdapter.generate_image` / `generate_candidates` | 316 / 338 | refuses references; 1-4 stills; swaps sides for landscape; seed + index | the local SDXL profile cannot hold identity | CODE_RULE |
| `ComfyVideoAdapter.create_generation` | 381 | requires first frame; duration ≤ profile `max_seconds`; aspect in a fixed list; uploads frame, submits | tested profile only | CODE_RULE |
| `ComfyVideoAdapter.get_generation_status` | 435 | maps collect result | — | — |

Helpers: `ComfyConnection._json`.

### `app.providers.local_memory` — backend/app/providers/local_memory.py (72 lines)

Windows RAM guard for the studio's own Comfy jobs ("never another client's job", `:1`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `available_memory` | 19 | free physical RAM via `GlobalMemoryStatusEx`; None off Windows | — | EXTERNAL (OS) |
| `watch_job` | 44 | daemon thread; interrupt the job after 3 consecutive readings < 3 GiB; stops when history says done | the Owner's PC must not swap to death | CODE_RULE |

### `app.providers.deterministic_media` — backend/app/providers/deterministic_media.py (316 lines)

Offline stand-ins. `DeterministicVisualAdapter` (SVG card, `format="svg"`) is the assembler's
default image adapter when none is given (`backend/app/media/assembler.py:6418`);
`DeterministicTTSAdapter` (tone WAV with evenly spaced word timings) is the assembler's
`placeholder_voice` (`:6425`) and the demo voice base (`backend/app/demo.py:118`);
`DeterministicPictureAdapter` (`PROVIDER_NAME = "DEMO_LOCAL_PICTURES"`, a 270x480 hash-seeded PNG)
serves the sales demo (SELL-03, `backend/app/demo.py:137-154`). All cost `"0.00"`.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `DeterministicVisualAdapter.generate_image` | 36 | SVG card with the prompt text | pipeline without a paid vendor | CODE_RULE |
| `_png` | 119 | stdlib PNG encoder | — | — |
| `DeterministicPictureAdapter.generate_image` | 157 | gradient + light + grain PNG from a SHA-256 of the prompt and seed | QC needs structure; "shows nothing the prompt describes and says so" (`:142-147`) | CODE_RULE |
| `DeterministicTTSAdapter.list_voices` | 208 | three fixed voices | — | — |
| `DeterministicTTSAdapter.synthesize` | 230 | 150 wpm × speed (0.5-2), harmonic tone, WAV, word timings | — | CODE_RULE |
| `DeterministicVisualAdapter.health_check` | 29 | always HEALTHY | no vendor to ask | — |
| `DeterministicPictureAdapter.health_check` | 154 | always HEALTHY | same | — |
| `DeterministicTTSAdapter.health_check` | 201 | always HEALTHY | same | — |

### `app.providers.deterministic_pub` — backend/app/providers/deterministic_pub.py (118 lines)

Offline publisher for tests only; `IS_SIMULATED = True`, ids `sim:<11 hex>`, no URL (`:1-8`).
No reference in `backend/app` outside the file; used by eight test modules.

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `DeterministicPublishingAdapter.__init__` | 30 | simulated channel | — |
| `health_check` | 35 | status SIMULATED | — |
| `upload_video` | 43 | FAILED for missing/empty file; else CONFIRMED with `simulated=True` | CODE_RULE |
| `get_video_status` | 96 | from its in-memory dict | — |
| `reconcile_upload` | 107 | match by idempotency key | — |

### `app.providers.deterministic_analytics` — backend/app/providers/deterministic_analytics.py (23 lines)

A tombstone: the simulator was removed (D-P7-001); "With no analytics provider configured the
studio answers HTTP 503 and stores nothing" (`:15`). Defines nothing.

### `app.providers.publishing_base` — backend/app/providers/publishing_base.py (140 lines)

Publishing contract: `UploadResult` (status CONFIRMED / UNKNOWN / RETRYABLE / FAILED, `simulated`,
`auth_refused`, platform-reported `privacy_status`/`upload_status`), `RemoteStateUnavailable`
("distinct from an answer of no", `:36-43`), `RemoteVideoStatus`, `PublishingHealthResult`.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `PublishingProvider.health_check` / `upload_video` / `get_video_status` / `reconcile_upload` | 73 / 77 / 90 / 98 | abstract | spec "YouTube adapter" | — |
| `ask_reconcile` | 115 | passes `created_after` / `channel_id` only to adapters whose signature takes them | older adapters and test stand-ins take two arguments; judged on the signature, never on a TypeError | CODE_RULE |

### `app.providers.youtube` — backend/app/providers/youtube.py (866 lines)

The official YouTube Data API v3 publisher. Every way an upload ends is an `UploadResult`
(PUB-01); the platform's own privacy answer is returned (PUB-05); reconciliation reads the
uploads playlist (PUB-03); metadata is fitted to YouTube's limits (PUB-06) (`:1-21`). Publishing
spends API quota, not money.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `register_footer_marker` / `footer_start` | 85 / 92 | known disclosure openings; where the studio's block starts | the footer is kept whole when cutting; `publishing.services` registers other languages | CODE_RULE |
| `fit_bytes` | 129 | fit a UTF-8 byte limit, cut at a word, marked | description limit is bytes | CODE_RULE |
| `tag_budget` | 141 | YouTube's tag count rule | — | CODE_RULE |
| `youtube_safe_metadata` | 184 | safe title/description/tags; idempotent | over a limit YouTube answers 400 after a paid film (audit PUB-06) | CODE_RULE |
| `rfc3339` | 242 | normalise `publishAt` | a bad timestamp is a wrong request, refused locally | CODE_RULE |
| `_google_word` | 257 | Google's one-word reason only | the body may quote the request | CODE_RULE |
| `_same_title` | 289 | title equality as YouTube keeps it (new and pre-2026-10-02 forms) | reconcile | CODE_RULE |
| `_open` | 308 | `urlopen` under the retry policy, repeatable | token refresh, session start and Content-Range chunks are safe to repeat | CODE_RULE |
| `youtube_provider_from_settings` | 323 | adapter from `STUDIO_YOUTUBE_*` settings | legacy path in `backend/app/publishing/router.py:123` | CONFIG |
| `YouTubeProvider.__init__` / `is_configured` | 344 / 363 | client id + secret + refresh token | — | — |
| `YouTubeProvider._get_access_token` | 366 | refresh-token grant | — | EXTERNAL |
| `YouTubeProvider.health_check` | 390 | channels `mine=true` | — | EXTERNAL |
| `YouTubeProvider.upload_video` | 419 | checks file and schedule; token or refusal; safe metadata; `containsSyntheticMedia: True`; category `\d{1,3}` else 28; language tag regex; resumable session; 8 MiB chunks honouring 308 Range; classifies every ending | a refusal after the caller wrote STARTED used to leave the row STARTED for good (`:461-463`) | CODE_RULE + EXTERNAL |
| `YouTubeProvider._token_or_refusal` | 621 | token, or FAILED+`auth_refused` (400/401/403, or no token), or RETRYABLE | SELL-07: Testing-mode refresh tokens expire after 7 days (`:227-234`) | CODE_RULE |
| `YouTubeProvider.get_video_status` | 651 | `videos?part=status`; empty items = "no", failure = `RemoteStateUnavailable` | silence is not "absent" | EXTERNAL |
| `YouTubeProvider.update_visibility` | 684 | `videos.update` status part, re-declaring synthetic media and made-for-kids; 404 → not there | an update reverts what it omits | CODE_RULE + EXTERNAL |
| `YouTubeProvider.reconcile_upload` | 758 | find this publication on the channel's uploads playlist | prevent a second copy of a live video | CODE_RULE |
| `YouTubeProvider._uploads_playlist` | 848 | channels.list contentDetails | — | EXTERNAL |

Helpers: `_safe_text`, `_cut_at_word`, `_safe_title`, `_safe_tags`, `_safe_description`, `_moment`,
`_not_uploaded`. Owner-facing texts: `AUTH_REFUSED_WORDS` (`:229-234`). External:
`oauth2.googleapis.com`, `www.googleapis.com`.

### `app.providers.youtube_analytics` — backend/app/providers/youtube_analytics.py (417 lines)

YouTube Analytics v2 reports. "Every number this adapter returns was reported by YouTube for the
window that was asked for" (`:7-12`). `MetricsUnavailable` carries `during`, `auth_refused`,
`http_status`, `oauth_error` so a statistics read is "no data", never a day-ending fault (`:43-58`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `_oauth_error` | 78 | Google's snake_case refusal word only | — | CODE_RULE |
| `YouTubeAnalyticsProvider.__init__` | 91 | explicit credentials taken whole; environment only when none given | another account's numbers were read as this channel's (`16_DECISION_LOG.md:1956`) | CODE_RULE |
| `YouTubeAnalyticsProvider.from_verified_settings` | 126 | exactly one CONNECTED connection (or the named one), else env, else None | ambiguity must not attribute one channel's numbers to another | CODE_RULE |
| `YouTubeAnalyticsProvider.is_configured` | 162 | access token or full refresh credentials | — | — |
| `YouTubeAnalyticsProvider._refresh_access_token` | 167 | refresh; 4xx except 408/429 → `auth_refused` | a 05:00 DNS failure ended a day (`:188-192`) | CODE_RULE |
| `YouTubeAnalyticsProvider._date_range` | 231 | window → dates | the window used to be ignored (`:234-235`) | CODE_RULE |
| `YouTubeAnalyticsProvider._report` | 247 | one report; 401/403 → account refused; other status → query refused | — | EXTERNAL |
| `YouTubeAnalyticsProvider.fetch_video_metrics` | 294 | base + impression metrics; a refused query is asked without impressions | impressions are never back-computed (`:359`) | CODE_RULE |
| `YouTubeAnalyticsProvider.fetch_channel_metrics` | 371 | channel report; subscribers are a net change, videos 0 (flags say so) | — | CODE_RULE |

External: `oauth2.googleapis.com`, `youtubeanalytics.googleapis.com`. No retry policy here.

### `app.providers.analytics_base` — backend/app/providers/analytics_base.py (53 lines)

Abstract `AnalyticsProvider` and the `VideoMetrics` / `ChannelMetrics` dataclasses. No logic.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `AnalyticsProvider.fetch_video_metrics` | 44 | abstract: real metrics for one remote video id and window | no fabricated measurement (D-P7-001) | — |
| `AnalyticsProvider.fetch_channel_metrics` | 50 | abstract: aggregate channel metrics | same | — |

### `app.providers.search` — backend/app/providers/search.py (128 lines)

A configurable HTTPS JSON web-search API that "may name pages, and nothing else" (`:1-24`):
no snippets or cached copies are read; the allowlist is applied by the caller. Measured reason:
the live run fetched 0 pages from guessed search addresses (`:3-5`). The engine may bill per
query on the Owner's key.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `results_at` | 55 | list at a dotted path | configurable response shape | CONFIG |
| `SearchProvider.__init__` | 68 | https endpoint, header, paths, field names from the connection | one documented contract, configured by the Owner | CONFIG |
| `SearchProvider._headers` | 81 | `Authorization` gets `Bearer`, other headers carry the key as is | — | — |
| `SearchProvider.search` | 89 | one GET; addresses and titles, ≤ limit, ≤ 50 | — | CODE_RULE + EXTERNAL |
| `SearchProvider.probe` | 117 | one neutral query; True when the shape is right | verification must not look like research | CODE_RULE |

### `app.providers.ollama` — backend/app/providers/ollama.py (233 lines)

The adapter of the seeded local Ollama endpoint only; Settings connections use
`app.integrations.llm.ConfiguredLLM` (`backend/app/integrations/llm.py:3-5`). Called by
`run_agent_task` for agents on the seeded provider.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `_vendor_word` | 43 | one-word refusal code from the body | 492 failures recorded as bare "HTTPError" (2026-10-04, `:12-16`) | CODE_RULE |
| `_refused` | 64 | `ProviderHTTPError(status, retry_after, word, keyless)` | lets the Owner's reconnect card be raised | CODE_RULE |
| `OllamaProvider.__init__` | 80 | base URL, optional key, price lookup | — | CONFIG |
| `OllamaProvider._open` / `_get` / `_post` | 99 / 113 / 118 | urllib calls under the retry policy | — | CODE_RULE |
| `OllamaProvider.health_check` | 129 | GET `/api/tags`; OFFLINE / UNKNOWN on error | — | EXTERNAL |
| `OllamaProvider.list_models` | 140 | models; `is_cloud` from the name; capabilities if listed | Ollama Cloud models via local daemon (ADR-PHASE2-002) | EXTERNAL |
| `OllamaProvider.show_model` | 171 | POST `/api/show` (repeatable) | — | EXTERNAL |
| `OllamaProvider.generate` | 176 | `think: False`, `num_predict`, non-repeatable POST; returns text, tokens, cost, `done_reason`, `thinking_chars` | hidden reasoning ate the budget; no chain-of-thought persisted (`:190-197`) | CODE_RULE (money if cloud) |

Helper: `_get_headers`.

### `app.providers.__init__`, `app.integrations.__init__`

Empty package marker / one-line docstring ("Owner-managed service configuration and encrypted
credentials.").

### `app.integrations.catalog` — backend/app/integrations/catalog.py (342 lines)

The Settings catalogue: per service kind its label, group (llm / social / media), form fields
(key, label, required, secret, kind, choices), runtime (`llm`, `stored`, `media`, `search`),
help text, docs URL and purposes. "No example accounts or model names" (`:1`). Kinds: ollama,
openai, compatible, anthropic (runtime llm); tiktok, instagram, facebook, email (stored; TikTok,
Instagram and Facebook say publishing is not integrated yet); elevenlabs, openai_media, comfyui,
runpod, runway (media); replicate (stored, "not connected in the pipeline"); search (search).
Fields that carry Owner decisions: `commercial_use` «da/nu» (AR-15, `:35-43`), `licence_terms`,
Runway `credit_usd` (`:27-33`: "only the Owner can record it"), RunPod `mode`, `model_source`,
`mock` ("only TEST"). `DOCUMENTED_PRICES` (`:311-342`) seeds ElevenLabs' public price as DOCUMENTED
(`16_DECISION_LOG.md:2036`); Ollama Cloud is deliberately absent.

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `field` | 4 | field dict | CONFIG |
| `service` | 49 | service dict | CONFIG |

### `app.integrations.models` — backend/app/integrations/models.py (150 lines)

Tables (no functions): `integration` (kind, name, JSON config, Fernet `encrypted_secrets`,
`secret_fields`, version, status, checked_at, event_id); `service_selection` (purpose →
integration); `provider_resource` (account-scoped MODEL/VOICE inventory with API metadata,
research `pricing`/`capabilities`, `availability_override`, `production_status` default
`PRODUCTION`, price provenance `pricing_version`, `price_verified_at`, `price_verification`,
`previous_pricing_json`, `lifecycle_note`; migration 0031); `provider_discovery` (refresh status
and durable lease); `media_production_config` (default model / voice / image model per
connection and `allow_production_override`); `model_outcome` (what each generation delivered:
run kind TEST_FUNCTIONAL / TEST_BENCHMARK / PRODUCTION, seconds, credits, usd, accepted,
failure_kind).

### `app.integrations.vault` — backend/app/integrations/vault.py (139 lines)

Fernet encryption of each connection's secrets; on Windows the key file is wrapped with
per-user DPAPI. The key file is `<database>.credentials.key` next to the SQLite database
(`backend/app/main.py:691-693`). A key that cannot be read raises `VaultUnreadable(code)` with a
Romanian reason, so the studio starts and says what to do (`:1-9`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `VaultUnreadable.__init__` | 50 | code + `reason_ro` | Owner-facing reason | — |
| `dpapi` | 56 | `CryptProtectData` / `CryptUnprotectData` via ctypes | key bound to the Windows account | EXTERNAL (OS) |
| `CredentialVault._cipher` | 79 | create the key only on encrypt (O_EXCL, 0600, fsync); map missing/unreadable/corrupt | — | CODE_RULE |
| `CredentialVault.encrypt` / `decrypt` | 108 / 111 | JSON dict ↔ token; wrong key → FOREIGN | another studio's key | CODE_RULE |
| `CredentialVault.key_present` | 123 | key file exists | — | — |
| `CredentialVault.self_test` | 126 | canary round-trip; never creates a key | start-up and health probe | CODE_RULE |

### `app.integrations.llm` — backend/app/integrations/llm.py (272 lines)

`ConfiguredLLM`, the adapter behind every LLM connection made in Settings (Ollama incl. Ollama
Cloud, OpenAI, Anthropic, OpenAI-compatible). "Anything that must hold for the studio's real
runs belongs here first" (`:3-5`). `ProviderHTTPError` (a `ValueError`, with `http_status`,
`retry_after`, `word`, `keyless`, `unanswered`) and `ProviderUnreachable` (an `OSError`, `unsent`
/ `unanswered`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `ProviderHTTPError.__init__` | 38 | status, Retry-After, one-word code, keyless, `unanswered` for non-safe 5xx | the retry policy tells "not now" from "never" | CODE_RULE |
| `ProviderUnreachable.__init__` | 64 | phase flags | same | — |
| `ConfiguredLLM.__init__` | 73 | base URL (fixed for openai/anthropic), key, price lookup | 391 runs without cost (`:83-87`) | CONFIG |
| `ConfiguredLLM.request` | 90 | retry wrapper; POST is non-repeatable except `/api/show` and `/api/me` | tokens are billed either way | CODE_RULE |
| `ConfiguredLLM._request_once` | 104 | http.client call, vendor auth header, 600 s, 4 MB cap, two failure phases | long cloud answers took minutes (`:109-110`) | CODE_RULE |
| `ConfiguredLLM.health_check` | 149 | HEALTHY iff `list_models` succeeds | — | EXTERNAL |
| `ConfiguredLLM.is_ollama_cloud` | 157 | kind ollama and host `ollama.com` | — | — |
| `ConfiguredLLM._verify_cloud_access` | 160 | POST `/api/me` must return an id | `/api/tags` is public; only identity proves the key | EXTERNAL |
| `ConfiguredLLM.list_models` | 171 | Ollama `/api/tags` or `/models`; declared capabilities | — | EXTERNAL |
| `ConfiguredLLM._declared_capabilities` | 181 | Ollama `/api/show` per model; failures assume nothing | the editorial gate needs vision; never assumed from a name | EXTERNAL |
| `ConfiguredLLM.generate` | 201 | Ollama `/api/generate` with `think: False`; Anthropic `/messages`; OpenAI/compatible `/chat/completions` (`max_completion_tokens` for OpenAI); cost from price table | thinking ate the budget (`:7-11`) | CODE_RULE (money) |

### `app.integrations.probes` — backend/app/integrations/probes.py (84 lines)

"Explicit credential checks; never publishes, generates media or reads mailbox messages" (`:1`).

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `get_json` | 11 | HTTPS GET, 8 s, 1 MB cap; non-200 → `ValueError` | CODE_RULE |
| `probe` | 26 | per kind: TikTok `open_id`, Instagram `user_id`, Facebook page `id` must equal `account_id`; ElevenLabs `user_id` present; Replicate `username`; OpenAI media model id equal; search probe; SMTP (STARTTLS/TLS) and optional IMAP login; other kinds `NotImplementedError` | EXTERNAL |

### `app.integrations.services` — backend/app/integrations/services.py (661 lines)

Connection save/validation, LLM registry loading, credential-vault health with Owner letters,
YouTube credential selection, purpose selection and employee model assignment.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `public` | 40 | the row without secrets, with its runtime | — | — |
| `validate` | 54 | form rules (see Who decides) | — | CODE_RULE |
| `save` | 112 | versioned save; keeps stored secrets not retyped; unreadable old secrets treated as lost (REL-06); encrypts; preserves RunPod switch and infra answer; resets discovery; LLM kinds get a `ProviderRecord` with models marked unavailable until checked | — | OWNER + CODE_RULE |
| `load_registry` | 186 | register LLM connections whose keys decrypt | REL-06 | CODE_RULE |
| `_settings_tab` | 244 | which Settings tab to point at | — | — |
| `vault_health` | 249 | HEALTHY/DEGRADED, unreadable rows, `blocking`, Owner text, fingerprint | the preflight blocks paid stages on keys the studio cannot open (`:229-231`) | CODE_RULE |
| `_flag_connections` | 329 | NEEDS_RECONNECT once / restore previous status, with events | — | CODE_RULE |
| `_vault_letter` | 387 | one ESCALATE letter to the Owner per fingerprint, signed by the Director's agent; says whether the day is blocked; S4U hint | — | CODE_RULE |
| `check_vault_at_startup` | 434 | the start-up self-test; never raises | the page must come up | CODE_RULE |
| `selected_youtube` | 456 | YouTube provider from a bound connection, or the only connected one; several → refusal | "guessing which channel a publication belongs to is precisely the mistake this subsystem exists to prevent" (`:463-466`) | CODE_RULE |
| `select_service` | 496 | versioned purpose → connection | — | OWNER |
| `assign_agent` | 534 | versioned model assignment with slots, strategy, policy, thresholds and origin; event keeps previous slots | Director repairs must be undoable (`:558-561`) | OWNER (origin OWNER) / CONFIG (SEED_ALLOCATION) / CODE_RULE (DIRECTOR_REPAIR); the checks themselves are CODE_RULE |

Events: `settings.integration_saved`, `settings.integration_needs_reconnect`,
`settings.integration_readable_again`, `settings.service_selected`, `agent.model_assigned`.
Tables written: `integration`, `provider_record`, `model_record` (availability), `service_selection`,
`agent`, `agent_message` (letter).

### `app.integrations.discovery` — backend/app/integrations/discovery.py (819 lines)

One discovery path for every connection whose inventory is read from the vendor
(`DISCOVERED_KINDS`: runpod, comfyui, elevenlabs, runway, `:43-106`). "Authentication, API facts,
and research facts are independent" (`:1`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `explain_key_error` | 137 | Owner text from the vendor's code/status (ElevenLabs permission scopes, Runway 401/403/429) | tell the Owner what to fix; never the vendor's message or the key | CODE_RULE |
| `discovery_adapter` | 180 | ElevenLabs or Runway adapter for discovery (unpriced on purpose, `16_DECISION_LOG.md:2129`) | — | — |
| `usable_purposes` | 188 | purposes from API evidence; research may only restrict | `gen4_image_turbo` incident (`:215-219`) | EXTERNAL + CODE_RULE |
| `model_usable` | 235 | purpose membership | — | CODE_RULE |
| `reset_discovery` | 241 | EMPTY, due now, all resources unavailable | a re-saved key must re-prove its catalogue | CODE_RULE |
| `resource_available` | 255 | API-present and not overridden off | research cannot make an absent resource exist | CODE_RULE |
| `resource_view` / `catalog_view` | 260 / 286 | Settings card data (models, voices, discovery state, production defaults) | — | — |
| `_metadata` | 328 | keep only public catalogue fields per kind | voice samples and account data stay out | CODE_RULE |
| `refresh_catalog` | 378 | lease → health → models (+voices) → write resources, starting standing for new models, prices for ComfyUI (0) and RunPod (backend estimates) → event | — | EXTERNAL + CODE_RULE |
| `_runpod_switched_on` | 596 | the Owner's RunPod switch | background pass leaves RunPod alone when off (2026-10-09) | OWNER |
| `refresh_due_catalogs` | 607 | background pass over due connections; failures logged | — | CODE_RULE |
| `production_resource` | 652 | available resource that serves the purpose, or None | single gate used by factory, autoconfig, research | CODE_RULE |
| `save_production` | 685 | versioned defaults; ComfyUI/RunPod explicit choice → CANDIDATE | — | OWNER |
| `update_resource_metadata` | 771 | research/accounting/Owner writes `capabilities` (replaced whole), `availability_override`, and pricing via `stamp_price` (any field explicitly passed, even empty, is written); event with price moves | "a price is never overwritten in silence" (`:792-794`) | CODE_RULE (content from the caller: OWNER via PATCH, LLM via model research, EXTERNAL via billing) |

Events: `provider.catalog_refreshed` (with `new_models`), `media.production_configured`,
`provider.resource_metadata_updated`. Calls out to vendor APIs (free reads).

### `app.integrations.lifecycle` — backend/app/integrations/lifecycle.py (423 lines)

"A model has a life, and a price has a date" (`:1-24`): standing, price provenance and
judgement from the studio's own results; "Nothing here names a model, a vendor or a price".

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `deny_patterns` / `is_denied` | 66 / 76 | the Owner's deny list as patterns | "the Owner's judgement, not a fact about the vendor's catalogue" | CONFIG |
| `classify_discovered` | 81 | DEPRECATED / QUARANTINE / DISCOVERED for a new model | an unknown model is not tried on a film | CODE_RULE |
| `price_changes` | 107 | per-unit moves with percent; a vanished price is reported | — | CODE_RULE |
| `stamp_price` | 132 | write price with provenance; BILLED beats DOCUMENTED for each unit key both name; the new dict otherwise replaces the stored one whole | 0.08 vs 0.43 USD/s incident (`:144-150`) | CODE_RULE |
| `price_is_stale` | 190 | drift beyond tolerance → fact dict | a page reading outlived four renders measuring 17× more (`:196-198`) | CODE_RULE |
| `_verdict` | 218 | one ladder step from results (thresholds above) | "a single good day cannot carry a model from discovered to preferred" | CODE_RULE + CONFIG |
| `review_models` | 295 | re-judge every model; light (daily worker job `model_review_daily`, `backend/app/workflows/worker.py:98`, `:407-410`) or full (adds a cost frontier) | "the review itself costs nothing" | CODE_RULE |
| `_purpose_of` | 393 | first of video, image, voice the model serves | — | — |
| `_move` | 404 | set standing, note, event `provider.model_lifecycle_changed` | — | — |

`ADMITTED = ("CANDIDATE", "PRODUCTION", "PREFERRED")` (`:55`) is read by
`backend/app/media/assembler.py:1429` and `backend/app/media/production_policy.py`.

### `app.integrations.autoconfig` — backend/app/integrations/autoconfig.py (250 lines)

One Owner action that finishes what verified connections leave unfinished — a verified Runway
and ElevenLabs key still reported "no image provider" and "no default voice" (`:1-22`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `_candidates` | 56 | VERIFIED connections declaring the purpose with at least one usable model | a Runway key with no video model is not a video provider | CODE_RULE |
| `_priority` | 86 | `Settings().production_priority`, default premium | — | CONFIG |
| `_top_resource` | 96 | top of `rank_candidates`, preferring a generative task | same order as `strategy: auto` | CODE_RULE |
| `auto_configure` | 131 | select single-candidate services, fill empty or unusable defaults (and an empty voice), report applied / ambiguous / already; `allow_production_override` is carried over, never consulted (`:186`, `:231`) | "a choice belongs to the Owner" | CODE_RULE (ranking inputs partly LLM-written, see `rank_candidates`) |

Also called before the preflight when readiness reports something empty
(`backend/app/runbook/services.py:1347-1353`).

### `app.integrations.plan_licence` — backend/app/integrations/plan_licence.py (145 lines)

Reads each verified ElevenLabs connection's plan and records the commercial licence when the plan
is paid and active — the Owner's card «Da, citește singur» of 2026-10-10 (`:3-13`). Run by the
watchdog pass `vendor_plan_licence` (`backend/app/workflows/passes/vendor_plan_licence.py:17-25`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `is_paid_tier` | 47 | paid tier name or paid name with suffix; `free*` never | the plan is never inferred from the vendor's name | CODE_RULE |
| `_read_plan` | 57 | `ElevenLabsTTSAdapter(key).subscription()` | a GET that buys nothing | EXTERNAL |
| `record_plan_licences` | 63 | due connections (VERIFIED, not yet «da», last read > 1 h); paid → `commercial_use = "da"`, terms text, `licence_source = "vendor_api"`, version + event; unpaid → only `licence_checked_at`/tier | film babcf272 stayed private | EXTERNAL + CODE_RULE |

Event: `integrations.licence_recorded`. A test-suite `AssertionError` is re-raised (`:103-104`).

### `app.integrations.router` — backend/app/integrations/router.py (532 lines)

The Owner's Settings API, mounted at `/api/v1/settings` (`backend/app/main.py:960`), every route
behind `require_owner` (`:140`). Error strings to the UI are fixed (`check_failure`, `:45-90`):
"no vendor response or credential becomes a UI string".

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `check_failure` | 45 | status → AUTH_REQUIRED / ACCESS_DENIED / RATE_LIMITED / SERVICE_UNAVAILABLE / UNREACHABLE / CHECK_FAILED | — | CODE_RULE |
| `_propose_cards` | 127 | seed the Owner's decision cards right after a save | RunPod cards waited for a restart (2026-10-09) | CODE_RULE |
| `create_settings_router` | 139 | builds the router | — | — |
| `read_settings` (GET `/settings`) | 143 | catalogue, integrations with last check, provider catalogues, selections, agents, roles, models, legacy providers, YouTube channels | legacy Ollama must be verifiable (`:169-172`) | — |
| `save_integration` (PUT `/integrations/{id}`) | 215 | `save`, propose cards; discovered kinds refreshed at once; LLM kinds get a fresh priced adapter registered | a re-saved connection must not report `cost_vr` NULL (`:248-250`) | OWNER |
| `check_integration` (POST `/integrations/{id}/check`) | 263 | discovered → refresh; LLM → model sync; others → `probe`; writes status, maps provider status on failure, event | — | EXTERNAL + CODE_RULE |
| `refresh_resources` (POST `/integrations/{id}/refresh-resources`) | 347 | forced `refresh_catalog` | — | OWNER |
| `configure_production` (PUT `/integrations/{id}/production`) | 362 | `save_production` | — | OWNER |
| `configure_resource_metadata` (PATCH `/resources/{id}/metadata`) | 371 | `update_resource_metadata` | — | OWNER |
| `post_auto_configure` (POST `/auto-configure`) | 380 | `auto_configure` | — | OWNER → CODE_RULE |
| `post_model_research` (POST `/model-research`) | 393 | `research_all` | LLM indirect | OWNER → LLM_CHECKED_BY_CODE |
| `set_selection` (PUT `/selections/{purpose}`) | 402 | `select_service` | — | OWNER |
| `set_agent_model` (PUT `/agents/{agent_id}/model`) | 414 | `assign_agent` with `AssignmentCommand` (strategy SINGLE/FALLBACK/REVIEW/DEBATE/PARALLEL; policy IMPORTANT_ONLY/LOW_CONFIDENCE/ALWAYS/MANUAL; importance ROUTINE/NOTABLE/STRATEGIC; confidence 0..1) | — | OWNER |
| `test_agent_llm` (POST `/agents/{agent_id}/test`) | 436 | one real run on the agent's primary model, `max_tokens=2400`, `temperature=0.2`; returns the run record plus `duration_s` | LLM call site | OWNER (the model's answer is only displayed: INFORMATIONAL) |
| `bind_channel` (PUT `/channels/{channel_id}`) | 463 | bind/unbind a YouTube channel record to a CONNECTED OAuth connection | "a typed channel id is an unverified claim" (`16_DECISION_LOG.md:1815`) | OWNER |
| `delete_integration` (DELETE `/integrations/{id}`) | 497 | refuse when in use; event; delete; unregister adapter | — | OWNER + CODE_RULE |

Events: `settings.integration_checked`, `channel.credentials_bound`, `settings.integration_deleted`
(plus those of the called services).

## Connections

- **Called by**: `backend/app/main.py` (start-up: `check_vault_at_startup` `:299`, `load_registry`
  `:301`, seeded `OllamaProvider` `:232-246`, the catalogue refresher loop `:356-380`, health probe
  `vault_health` `:795-803`, router mount `:960`); `app.agents.services.run_agent_task` (calls
  `adapter.generate` of `ConfiguredLLM` / `OllamaProvider`); `app.media.factory` (builds the
  Runway, OpenAI, ElevenLabs, ComfyUI adapters and gates them with `production_resource`,
  `backend/app/media/factory.py:23-38`, `:250-535`); `app.media.assembler` (deterministic
  placeholders `:6418-6425`, `estimate_generation` `:1394`, `collect_task` `:10505-10510`,
  `ModelOutcome` rows `:1413-1484`); `app.media.stills_stage`, `app.media.shooting_sheet`
  (`credit_balance`, `TaskStillOpen`); `app.media.production_policy` (`stamp_price`,
  `price_is_stale`, `usable_purposes`, `ADMITTED`); `app.media.model_research` (`save_production`,
  `update_resource_metadata`, `production_resource`, `CATALOG`); `app.economy.credits`
  (Runway organization, ElevenLabs subscription); `app.publishing.services` (`ask_reconcile`,
  `youtube_safe_metadata`, `register_footer_marker`, `fit_bytes`, `rfc3339`);
  `app.publishing.router`, `app.runbook.stages:5690`, `app.workflows.watchdog:226-241`
  (`selected_youtube`); `app.publishing.licence_release:374` (`update_visibility`);
  `app.analytics.router:76` (`from_verified_settings`); `app.research.service:41`, `:610-636`
  (`SearchProvider`); `app.runbook.preflight:1256` and `app.backup:696-701` (`vault_health`);
  `app.runbook.services:1347-1353` (`auto_configure`); `app.workflows.worker` (`review_models`,
  `research_all`); `app.workflows.passes.vendor_plan_licence` (`record_plan_licences`);
  `app.agents.ensemble:895-905` (SEED_ALLOCATION) and `app.agents.repairs.agent_health:695-706`
  (DIRECTOR_REPAIR) call `assign_agent`; `app.agents.repairs.agent_health:465-472` uses
  `deny_patterns`; `app.office.weather` uses `media_http.request`; the RunPod package uses
  `media_http`, `retry` and `TaskStillOpen`.
- **Calls out to**: `app.agents.services` (`run_agent_task`, `sync_provider_models`,
  `list_agents`, `list_roles`, `list_provider_models`, `_check_required_capabilities`),
  `app.agents.ensemble` (strategy vocabularies), `app.economy.prices` (`price_lookup`,
  `llm_cost_vr`, `tts_cost_vr`), `app.media.production_policy` (`rank_candidates`,
  `GENERATIVE_TASKS`, `model_record`), `app.media.factory` (`VERIFIED_STATUSES`),
  `app.media.model_research`, `app.decisions.seed.seed_owner_decisions`,
  `app.agents.messages.post_message`, `app.agents.memory.agent_for_role`,
  `app.providers.runpod` (`RunPodConfig`, `RunPodConnection`), `app.youtube.services`
  (`provider_for_connection`), `app.services.append_event`.
- **Events emitted**: `settings.integration_saved`, `settings.integration_checked`,
  `settings.integration_deleted`, `settings.integration_needs_reconnect`,
  `settings.integration_readable_again`, `settings.service_selected`, `agent.model_assigned`,
  `channel.credentials_bound`, `provider.catalog_refreshed`, `media.production_configured`,
  `provider.resource_metadata_updated`, `provider.model_lifecycle_changed`,
  `integrations.licence_recorded`; through `run_agent_task` (test route): `agent.state_changed`,
  `agent.run_completed`, `agent.message_sent`. No events are consumed here.

## Owner touchpoints

- **Settings screen** (`/api/v1/settings`, `backend/app/integrations/router.py:139-532`): add,
  edit, verify, refresh, delete connections; pick each purpose's service; set production defaults
  and whether they may be overridden (`allow_production_override`: when off, model research does
  not change the default, `backend/app/media/model_research.py:438`, and channels may not choose
  differently, `backend/app/integrations/discovery.py:645-648`; auto-configure does not read it and
  still fills an empty or unusable default, `backend/app/integrations/autoconfig.py:186-213`); annotate a resource's price,
  capabilities or availability; run auto-configure; run model research; assign each employee's
  model, second/third slots and multi-model strategy; test an employee's model with one real
  run; bind a YouTube channel to an OAuth connection.
- **Form fields that are Owner statements**: `commercial_use` «da/nu» and `licence_terms`
  (`backend/app/integrations/catalog.py:35-46`), Runway `credit_usd` (`:27-33`), RunPod mode,
  endpoints, bucket, weights source and `mock` (`:190-234`).
- **Switches kept outside the form**: RunPod «RunPod pornit» (`enabled`) and the infra-actions
  answer (`allow_infra_actions`), preserved on save (`backend/app/integrations/services.py:153-160`)
  and read by the background refresh (`backend/app/integrations/discovery.py:596-622`).
- **Settings (.env, `STUDIO_*`)**: `MODEL_DENY_LIST`, `AUTO_DISCOVER_MODELS`,
  `AUTO_BENCHMARK_NEW_MODELS`, `MAX_BENCHMARK_BUDGET_USD`, `AUTO_PROMOTE_CHEAPER_BETTER_MODELS`,
  `AUTO_DEMOTE_EXPENSIVE_MODELS`, `MIN_TEST_SAMPLES_FOR_PROMOTION`, `PRODUCTION_PRIORITY`,
  `PRICE_CHANGE_ALERT_PERCENT`, `PRICE_STALE_TOLERANCE_PERCENT`, `PROVIDER_RETRY_ATTEMPTS`,
  `PROVIDER_RETRY_MAX_SECONDS`, `PROVIDER_CATALOG_REFRESH_*`, `YOUTUBE_*` (legacy publishing),
  `DIRECTOR_TOKEN_MULTIPLIER` (prefix `backend/app/config.py:47`; fields `:80-83`, `:251`,
  `:356-372`, `:425`, `:446-451`, `:487-488`, `:503-507`).
- **Letters and cards produced here**: the vault letter «Cheile salvate nu pot fi citite»
  (ESCALATE, `to_owner=True`, one per fingerprint, `backend/app/integrations/services.py:387-431`);
  decision cards proposed on every save (`backend/app/integrations/router.py:127-136`); a reconnect
  card proposed/withdrawn after the test run (via `decisions.sources.model_run_finished`).
- **Owner-facing refusal texts that ask for an action**: YouTube «Reconectează contul YouTube …
  „In production”» (`backend/app/providers/youtube.py:229-234`); analytics «apasă Reconectează»
  (`backend/app/providers/youtube_analytics.py:205-218`, `:274-285`); ElevenLabs and Runway key
  messages (`backend/app/integrations/discovery.py:110-177`); «Mai multe canale YouTube sunt
  conectate …» (`backend/app/integrations/services.py:484-488`).
- **Licence card answer «Da, citește singur» (2026-10-10)** is implemented by
  `record_plan_licences` (`backend/app/integrations/plan_licence.py:3-13`).

## Oddities and gaps

- `probe()`'s ElevenLabs branch (`backend/app/integrations/probes.py:41-43`) is unreachable from
  the only caller: `check_integration` sends every `DISCOVERED_KINDS` kind (ElevenLabs included) to
  `refresh_resources` first (`backend/app/integrations/router.py:272-273`).
- Probe failures never carry a status: `get_json` raises a bare `ValueError` on any non-200
  (`backend/app/integrations/probes.py:16-17`), so `check_failure`'s 401/403/429/5xx messages apply
  only to LLM connections; a refused social/Replicate/OpenAI-media key reports CHECK_FAILED, and a
  refused search key makes `SearchProvider.probe` return False, reported as a plain FAILED with no
  error code (`backend/app/integrations/probes.py:50-58`, `backend/app/integrations/router.py:304-312`).
- `delete_integration` looks for channels with `credentials_ref == "integration:" + id`
  (`backend/app/integrations/router.py:510-514`), but `bind_channel` writes
  `"youtube_connection:" + id` (`:478`); the check only matches an older reference format. It also
  checks only an agent's primary `provider_id` (`:504`), not `secondary_model_id` /
  `tertiary_model_id` slots on models of that provider.
- `select_service` does not require the connection to be verified (`backend/app/integrations/services.py:496-531`);
  only `auto_configure` filters on `VERIFIED_STATUSES` (`backend/app/integrations/autoconfig.py:66`).
  The selection is saved anyway; at use the media factory ignores a selected connection that is
  not VERIFIED/ACCESS_VERIFIED (`backend/app/media/factory.py:202-209`, `:301-303`).
- **Model research can erase a stored price, BILLED included.** For a judged model with no price
  (`price_usd: null`, which the judge prompt itself asks for when the pages say nothing,
  `backend/app/media/model_research.py:136-137`) research passes `pricing={}`
  (`:380-392`); the field is explicitly set, so `update_resource_metadata` calls `stamp_price`
  (`backend/app/integrations/discovery.py:791-800`), which stores the new dict whole
  (`backend/app/integrations/lifecycle.py:152-153`, `:177`). The BILLED guard only copies a charged
  unit when the documented dict names the same unit (`:157-163`), so an empty or differently-keyed
  reading drops the billed figure; `price_verification` stays BILLED (`:184`) and only
  `previous_pricing_json` keeps the old price. The vanished price is a move with `percent: None`,
  which `research_models` does not turn into a letter (`model_research.py:406-411`).
- **Model research replaces a model's `capabilities` whole** with the three scores, notes and
  `judged_by` (`backend/app/media/model_research.py:393-399`; `update_resource_metadata` sets the
  field, `backend/app/integrations/discovery.py:782-790`). A restriction written there earlier
  through `PATCH /resources/{id}/metadata` (`can_generate_video: false`, `can_do_text_to_speech:
  false`, or Runway `tasks` supplied when the contract was unreadable, read by `usable_purposes`,
  `:204-230`) is erased by the next research run, re-opening or closing a purpose.
- `refresh_catalog` writes ComfyUI and RunPod prices straight onto `resource.pricing` on every
  successful refresh (`backend/app/integrations/discovery.py:535-544`), bypassing `stamp_price`: no
  `previous_pricing_json`, no `pricing_version` bump, `price_verification` left as it was, so a
  RunPod row marked BILLED is reset to the backend's estimate every 6 h.
- `rank_candidates` filters on availability and usable purpose but not on `production_status`
  (`backend/app/media/production_policy.py:359-366`), so the research recommendation, its
  fallback and the auto-configure default can name a QUARANTINE or deny-listed DEPRECATED model;
  only the motion router's own filters keep it out of production scenes (`:946`, `:1046`).
- `ConfiguredLLM.generate` forwards `extra` only to Ollama (`backend/app/integrations/llm.py:222-223`);
  for OpenAI, Anthropic and compatible connections the `images` of a vision call are silently not
  sent. Those kinds also declare no capabilities (`:188-189`), so a caller that checks the declared
  `vision` capability first (`app.agents.editorial.model_can_see`, `backend/app/agents/editorial.py:313-331`;
  likewise `app.agents.vision.seeing_model`, which the Director's second look uses since 20abffd,
  `backend/app/agents/vision.py:145-185`, `backend/app/media/second_look.py:686`)
  never sends them pictures (`seeing_model` then borrows another employee's seeing model; when
  none sees, the second look is UNAVAILABLE and the QC refusal stands,
  `backend/app/media/second_look.py:687-692`); a caller that does not check gets an answer written without them.
- `OpenAIImageAdapter.generate_image` posts with no overall deadline (`total_seconds` not passed,
  `backend/app/providers/openai_media.py:161-163`): only the 120 s per-socket-operation timeout
  bounds it, unlike Runway and ElevenLabs purchases, which carry a whole-request end since the
  2026-10-03 hang (`backend/app/providers/media_http.py:159-164`).
- `review_models(full=True)` (the "weekly" full review with the cost frontier, docstring
  `backend/app/integrations/lifecycle.py:304-307`) has no caller; the worker runs only the light
  review (`backend/app/workflows/worker.py:410`).
- The ladder's `acceptance` is computed from `model_outcome.accepted`, whose only writer sets it to
  "the clip's bytes arrived" (`backend/app/media/assembler.py:1449`, `:1479-1480`) and writes only
  `purpose="video"` (`:1466`). Image and voice models therefore never accumulate judged outcomes
  and cannot be promoted or demoted on results by `_verdict`.
- `max_benchmark_budget_usd` appears only inside the BENCHMARKING note text
  (`backend/app/integrations/lifecycle.py:273-276`); nothing in this scope enforces it.
- `provider_resource.production_status` defaults to `PRODUCTION` (`backend/app/integrations/models.py:61`)
  and `review_models` reads a missing status as PRODUCTION (`backend/app/integrations/lifecycle.py:346`):
  rows created without the discovery path are admitted by default.
- `_move` stamps its event with `metadata_version + 1` without incrementing `metadata_version`
  (`backend/app/integrations/lifecycle.py:410-417`), so repeated moves of one row share a version
  number (no uniqueness constraint on `aggregate_version`, `backend/app/models.py`).
- `stamp_price` protects only BILLED from DOCUMENTED: a DOCUMENTED price (e.g. from model research)
  overwrites an ESTIMATED (dry-run) one (`backend/app/integrations/lifecycle.py:155-163`, `:184`).
- A failed periodic refresh sets the connection to FAILED (`backend/app/integrations/discovery.py:495`)
  until the next attempt (900 s by default), which drops it from `VERIFIED_STATUSES` consumers
  (auto-configure, factory) during a vendor's bad minute; resources keep their previous
  `api_available` because the resource loop runs only on success (`:502-562`).
- `ConfiguredLLM._request_once` raises `ProviderHTTPError(status, retry_after)` without the vendor
  `word` or `keyless` (`backend/app/integrations/llm.py:137-139`), while the seeded `OllamaProvider`
  passes both (`backend/app/providers/ollama.py:70-72`): refusals on Settings connections carry no
  vendor code.
- `ConfiguredLLM._declared_capabilities` sends `{"model": name}` to `/api/show`
  (`backend/app/integrations/llm.py:193`); `OllamaProvider.show_model` sends `{"name": model}`
  (`backend/app/providers/ollama.py:174`).
- `OllamaProvider.list_models` marks a model cloud by substring (`":cloud" in name or "cloud" in
  name.lower()`, `backend/app/providers/ollama.py:148`), a name-based inference.
- `YouTubeAnalyticsProvider.from_verified_settings` falls back to environment credentials even when
  a `connection_id` was named and that connection is not CONNECTED (`backend/app/providers/youtube_analytics.py:144-160`),
  and on the connection path never sets `channel_id` / `connection_id` on the adapter
  (`:153-157`, attributes declared at `:119-123`).
- YouTube Analytics calls `urlopen` directly, outside the studio retry policy
  (`backend/app/providers/youtube_analytics.py:194`, `:253`); `SearchProvider.search` also calls
  `request` without `retrying` (`backend/app/providers/search.py:96`).
- In `YouTubeProvider.upload_video`, if every chunk answers 308, `res_body` is never bound and the
  `NameError` is reported as UNKNOWN (`backend/app/providers/youtube.py:555-619`).
- ElevenLabs 422 is in both `CONTRACT_REFUSALS` and `FIELD_REFUSALS`
  (`backend/app/providers/elevenlabs.py:67-70`): a 422 with optional fields can produce three POSTs
  (timed, timed without options, plain). Each refused one made no audio.
- `record_plan_licences` never re-reads a connection once `commercial_use == "da"`
  (`backend/app/integrations/plan_licence.py:82`): a later downgrade to a free plan is not detected.
  The keys it writes outside the catalogue fields (`licence_checked_at`, `licence_plan_tier`,
  `licence_source`) are dropped by the next Settings save, which stores only the form's fields
  (`backend/app/integrations/services.py:152-161`; the form sends catalogue fields only,
  `frontend/src/settings.js:343-347`).
- `media_http.host_of` (`backend/app/providers/media_http.py:450-454`) has no caller in
  `backend/app` or `tests`; `wav_duration_seconds` and `get_registry` are used only by tests;
  `DeterministicPublishingAdapter` is referenced only by tests.
- `catalog.py` keeps services whose pipeline is absent: TikTok, Instagram, Facebook ("Publicarea
  … nu este încă integrată") and Replicate ("Generarea nu este încă conectată")
  (`backend/app/integrations/catalog.py:105-154`, `:246-254`); they can be verified and selected
  for a purpose.
- `22_PROVIDER_INTEGRATION_CONTRACTS.md` lists `generate_structured` and `estimate_cost` for the LLM
  adapter and `cancel_generation` / `estimate_cost` for video; `LLMProvider` has neither
  (`backend/app/providers/base.py:44-68`), and only Runway video offers an estimate
  (`estimate_generation`, `backend/app/providers/runway.py:1184`). The spec says "potential
  methods", so this is a gap, not a contradiction.
- `OUTPUT_HOST_SUFFIXES` is empty by design (`backend/app/providers/runway.py:77-84`): Runway
  outputs are accepted from any public host.
- `REFERENCE_IMAGE_VERIFIED = False` on Runway and OpenAI images
  (`backend/app/providers/runway.py:781`, `backend/app/providers/openai_media.py:105`): reference
  pictures are coded but never confirmed by a real run.
