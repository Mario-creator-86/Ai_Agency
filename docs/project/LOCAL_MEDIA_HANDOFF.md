# Local media + ElevenLabs acceptance run

Updated 2026-10-05. User authorized a NEW complete film through AI Agency and private YouTube upload. Do not substitute old Nepal benchmark. Do not erase existing Studio.

## Runtime and defaults
Agency http://127.0.0.1:8000 restarted to load revision_notes API. Launcher PID 33680 (verify actual server before stopping). Comfy http://127.0.0.1:8188 restarted with existing E:/Studio/Tools/start_comfy.py; server PID 3816 (verify). Images SDXL_LOCAL; video I2V_HERO_RX9070 (official LTX-2.5 INT8); voice existing ElevenLabs preserved. No paid Runway fallback.

## Film records
Topic 615c7196-054f-429c-b94e-b4c2e0060c36: The Moon turns. Why do we see one face?
Primary source https://science.nasa.gov/moon/facts/ retrieved in Agency source 16745404-5cf2-4dbc-83a5-a88920d9df02. Two real FactChecker-supported claims 29ccc731-4bd4-4f71-8b9e-da2a42e7ba31 and ee3d7434-3bea-4f02-bb56-4889b148c76d.
Original script d4909779-429e-4c83-aeeb-c579c9af2839 Director verdict REVISE. Real writer revision af44291a-d431-454d-8c36-0371829232f8 has seven short scenes; Director review running. Artifacts and exact API command IDs in data/local-media-acceptance/*.json and requests.jsonl. No new still, motion, voice, assembly or upload generated yet.

## Next
Read story-review-v2.json, revise if needed via factual/scripts/write-with-agent revision_notes. Approve passing script, storyboard, real prompt writer, shooting-sheet steps stills/test_shot/motion/assemble, inspect visuals, real QC, private YouTube through publishing service. User authorization covers these manual steps. Keep actual rights status; NEEDS_REVIEW is allowed for private upload by existing QC policy, never fake commercial evidence.
Target channel 23d3ba8b-5f3c-4a99-9ab8-4993fe108f1a / NEXUS CURIOSITY, connected YouTube. Private default, public disabled.

## Verification
Baseline media suites 86 passed before changes and 86 after. Broader provider/cost suites 178 passed. Latest editorial+local suites 66 passed. Ruff changed modules and frontend check passed. Final frontend build, appropriate final tests and project tracking still required. Do not claim end-to-end success before actual film/upload.

## Implementation
Portable config/local_media.json and config/local_workflows contain SHA-pinned tested workflows. providers/comfyui.py loopback-only adapter, providers/local_memory.py RAM guard, media/local_media.py free API pricing + writer duration limits. See git diff, do not revert other pre-existing dirty changes. Backup data/local-media-backup-20261005. Current production integration a4421364-0e77-4d41-9209-a304be1bfebb. FactChecker unavailable model repaired to deepseek-v4-pro:0813. Never print vault secrets or OwnerToken.

## Latest 2026-10-05 evening
Passing script v3 963be848-f367-4015-a2be-d92291f84044, real Director PASS. Approved. Storyboard a4d0a91a-aa7d-4d37-904a-8d54b71dad17 created through Agency. Seven 3-3.2s scenes. Editor Kael glm-5.3-flash twice returned no parseable plan (7000 tokens exhausted); switched only Kael to proven kimi-k3 via settings API. Other agent settings had changed externally since the earlier run; do not restore them from old notes. First valid shot plan revealed earlier failed visual bible had silently fallen back to terrestrial defaults (overcast/haze on Moon). Fixed prompt_agent: regenerate fallback bible on a retry with registry; default motion does not invent haze; explicit physical environment in bible brief. Director now gets writer local duration limits. Latest prompt generation running again, output prompts-v2.json. Agency launcher 37944; no Comfy generation yet.
New regression + compiler/editorial/local suites: 70 passed. Factual/stills/assembly/publishing suites: 102 passed. Frontend: 797 passed, build successful. Docs integrity passed. Secret scan found mostly SHA hashes + existing fixtures and an api_key keyword on discovery.py:101; review and reconcile these false positives explicitly before final.
